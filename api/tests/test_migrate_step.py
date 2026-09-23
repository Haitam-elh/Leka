"""The deployment's migration step, and the rollback it used to break.

LEKA-336. Staging ran `alembic upgrade head` before starting the API. Rolled
back to an image older than the schema, alembic cannot find the revision the
database is at, exits 255, and the API — which waits for this step — is never
started on the release being rolled back to. Every rollback after a release
that carried a migration failed there.
"""

from __future__ import annotations

from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from leka.core.settings.paths import REPO_ROOT
from leka.db import migrate


@pytest.fixture
def script() -> ScriptDirectory:
    config = Config(str(REPO_ROOT / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "api" / "alembic"))
    return ScriptDirectory.from_config(config)


def test_a_revision_from_a_newer_release_is_recognised(script: ScriptDirectory) -> None:
    head = script.get_current_head()
    assert head is not None

    assert migrate.unknown_to(script, {head}) == set()
    assert migrate.unknown_to(script, {"f00dfeedbeef"}) == {"f00dfeedbeef"}
    assert migrate.unknown_to(script, set()) == set()


@pytest.mark.parametrize(
    ("database_at", "upgraded"),
    [
        (set(), True),  # a new database
        ({"KNOWN"}, True),  # an older release's schema: migrate it
        ({"f00dfeedbeef"}, False),  # a newer release's schema: a rollback
    ],
)
def test_only_a_schema_ahead_of_the_release_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
    script: ScriptDirectory,
    database_at: set[str],
    upgraded: bool,
) -> None:
    head = script.get_current_head()
    assert head is not None
    applied = {head if revision == "KNOWN" else revision for revision in database_at}

    calls: list[tuple[Any, str]] = []

    async def fake_applied() -> set[str]:
        return applied

    monkeypatch.chdir(REPO_ROOT / "api")
    monkeypatch.setattr(migrate, "applied_revisions", fake_applied)
    monkeypatch.setattr(command, "upgrade", lambda config, target: calls.append((config, target)))

    # Zero either way: a rollback is the expected state, not a failure.
    assert migrate.main() == 0
    assert [target for _, target in calls] == (["head"] if upgraded else [])


@pytest.mark.integration
async def test_it_reads_the_revision_the_database_is_at(script: ScriptDirectory) -> None:
    """The test database is migrated to head by conftest, so this is what a
    database in step with its release reads as."""
    assert await migrate.applied_revisions() == {script.get_current_head()}
