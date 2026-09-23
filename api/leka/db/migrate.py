"""Bring the schema up to this release, or leave it alone if it is already past it.

    python -m leka.db.migrate

What a deployment runs instead of `alembic upgrade head`. The two differ in
one case, and it is the case that matters during an incident: a database
already migrated by a NEWER release. That is what every rollback looks like —
the image goes back, the schema deliberately does not (docs/deployment.md) —
and `alembic upgrade head` answers it with "Can't locate revision", exit 255.
The API and the worker wait for this step to succeed, so a rollback after any
release that carried a migration failed on this line, and left the broken
release running.

So: a database at a revision this release has never heard of is reported and
left untouched. Everything else goes to alembic, unchanged.

Run from the directory holding alembic.ini, as alembic itself is: /app in the
image, api/ on a laptop.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterable

import structlog
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from alembic import command
from leka.core.config import settings
from leka.core.logging import configure_logging
from leka.db.session import engine

logger = structlog.get_logger(__name__)

ALEMBIC_INI = "alembic.ini"


async def applied_revisions() -> set[str]:
    """What alembic_version says, or nothing on a database never migrated.

    Through leka.db.session's engine rather than one of its own: that module
    owns database_url (tests/test_secret_access.py).
    """
    try:
        async with engine.connect() as connection:
            table = await connection.execute(text("SELECT to_regclass('alembic_version')"))
            if table.scalar() is None:
                return set()
            rows = await connection.execute(text("SELECT version_num FROM alembic_version"))
            return {row[0] for row in rows}
    finally:
        await engine.dispose()


def unknown_to(script: ScriptDirectory, applied: Iterable[str]) -> set[str]:
    """The applied revisions this release has no migration file for."""
    known = {revision.revision for revision in script.walk_revisions()}
    return set(applied) - known


def main() -> int:
    configure_logging(settings)
    config = Config(ALEMBIC_INI)
    script = ScriptDirectory.from_config(config)

    ahead = unknown_to(script, asyncio.run(applied_revisions()))
    if ahead:
        # A warning, not an error: this is the expected state of a rollback.
        # Whether the older code can run against the newer schema is a
        # question for whoever rolled back, and docs/deployment.md asks it.
        logger.warning(
            "schema_ahead_of_release",
            database_at=sorted(ahead),
            release_head=script.get_current_head(),
        )
        return 0

    command.upgrade(config, "head")
    return 0


if __name__ == "__main__":  # pragma: no cover - the process itself
    sys.exit(main())
