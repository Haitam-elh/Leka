"""Async engine, session factory, and the FastAPI session dependency.

Every database session in the process comes from here. Repositories receive
an AsyncSession; they never build their own engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

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
    """FastAPI dependency yielding one session per request.

    The session is rolled back and closed whatever happens, so a failed
    request never leaves a transaction open holding locks.
    """
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database() -> bool:
    """Liveness probe for /api/v1/health.

    Deliberately not in a repository: this asks whether the connection pool
    can reach PostgreSQL at all, it reads no business data. Rule 4 governs
    business queries.
    """
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True
