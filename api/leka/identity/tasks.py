"""Background work for identity.

Sweeping expired sessions and spent tokens. Enqueued on RQ by the scheduler;
runnable by hand with `python -m leka.identity.tasks`.

An expired session is DELETED rather than left in place and ignored. A row
nobody will ever use again is still a row that appears in a backup, and the
smallest set of credentials we can hold is the right one.
"""

from __future__ import annotations

import asyncio

import structlog

from leka.db import session_factory, system_scope
from leka.identity.repository import EmailTokenRepository, SessionRepository

logger = structlog.get_logger(__name__)


async def purge_expired() -> dict[str, int]:
    """Delete expired sessions and tokens across every account.

    system_scope because this is exactly what it is for: work that spans
    every tenant, said out loud in one line a reviewer can see. These tables
    are not workspace-scoped anyway, but declaring the scope keeps the
    convention uniform — and the day one of them gains a workspace_id,
    nothing silently starts leaking.
    """
    with system_scope():
        async with session_factory() as session:
            sessions_removed = await SessionRepository(session).delete_expired()
            tokens_removed = await EmailTokenRepository(session).delete_expired()
            await session.commit()

    result = {"sessions": sessions_removed, "tokens": tokens_removed}
    logger.info("identity_purge_completed", **result)
    return result


def run_purge() -> dict[str, int]:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(purge_expired())


if __name__ == "__main__":  # pragma: no cover
    run_purge()
