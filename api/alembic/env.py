"""Alembic environment.

Reads the database URL from leka.core.config, so migrations, the API and the
worker can never disagree about which database they are talking to.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine

# Importing a module registers its tables on Base.metadata. Modules are
# imported through their __init__.py, never through their internals
# (architecture rule 1).
import leka.connectors
import leka.knowledge
import leka.platform  # noqa: F401
from alembic import context
from leka.core.config import settings
from leka.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Tables that exist in the database but have no SQLAlchemy model yet.
#
# Migration 001 creates users and memberships with the bare minimum, because
# other tables must be able to reference them. Their models belong to
# leka.identity (LEKA-330). Until that lands, autogenerate would compare an
# empty metadata against real tables and cheerfully propose dropping them.
#
# LEKA-330: delete these two entries in the same commit that adds the models.
UNMODELLED_TABLES = frozenset({"users", "memberships"})


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Keep autogenerate away from tables no model describes yet."""
    if type_ == "table" and name in UNMODELLED_TABLES:
        return False
    return not (type_ == "column" and getattr(obj.table, "name", None) in UNMODELLED_TABLES)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting — `alembic upgrade head --sql`."""
    context.configure(
        url=str(settings.database_url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Any) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live database."""
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
