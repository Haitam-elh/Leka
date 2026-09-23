"""Async engine, session factory, and the FastAPI session dependency.

Every database session in the process comes from here. Repositories receive
an AsyncSession; they never build their own engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from leka.core.config import settings

engine: AsyncEngine = create_async_engine(
    str(settings.database_url),
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    # Recycle before a cloud load balancer silently drops an idle connection.
    pool_recycle=1800,
    pool_pre_ping=True,
)

session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,  # objects stay usable after commit, inside a request
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request.

    The session commits when the handler returns, and rolls back on any
    exception — including an HTTPException. A request refused with 403 must
    not leave behind the rows it had written before deciding to refuse.

    This is why routes contain no commit(): a route validates, calls one
    service and returns (architecture rule 6). Scattering commits through
    forty handlers means the one that forgets writes nothing and reports
    success, which is the worst of both.

    Work that must be durable regardless of what happens afterwards — an
    audit entry for a refused action, say — commits explicitly inside its own
    service and does not rely on this.
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# How every route asks for a database session. Use this, never
# Depends(get_session) on its own — and that is not a style rule.
#
# scope="function" makes the commit above happen when the handler returns,
# BEFORE the response is sent. FastAPI's default for a dependency with
# `yield` is the opposite: it runs the code after `yield` once the response
# has gone. The client then holds a 200 for a transaction that has not
# committed yet, and its next request can arrive first. Signing in did
# exactly that: the browser received its cookie, asked /auth/me, and was
# refused a session that did not exist yet — "back on /login" in CI, one
# sign-in in twenty, on a machine busy enough to lose the race. And a commit
# that FAILED after the response had already said 200 was data silently
# lost.
#
# One definition because the scope is part of FastAPI's dependency cache
# key: a route that mixed the two spellings would get two sessions in one
# request, each blind to what the other wrote.
DatabaseSession = Annotated[AsyncSession, Depends(get_session, scope="function")]


async def check_database() -> bool:
    """Liveness probe for /api/v1/health.

    Deliberately not in a repository: this asks whether the connection pool
    can reach PostgreSQL at all, it reads no business data. Rule 4 governs
    business queries.
    """
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True
