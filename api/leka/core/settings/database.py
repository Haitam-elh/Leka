"""PostgreSQL and Redis: how to reach them, and how many connections to hold."""

from __future__ import annotations

from pydantic import Field, PostgresDsn, RedisDsn, field_validator


class DatabaseSettings:
    """Connection details. No defaults on the URLs, on purpose.

    A default database URL is a URL somebody eventually runs against by
    accident. The process must refuse to start rather than invent one.
    """

    database_url: PostgresDsn = Field(
        description="postgresql+asyncpg://user:password@host:port/database",
    )
    redis_url: RedisDsn = Field(
        description="redis://host:port/db — queue backend for the background loop",
    )

    # Small by default: two part-time developers on laptops.
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_echo: bool = False

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: PostgresDsn) -> PostgresDsn:
        """Reject a sync DSN early.

        SQLAlchemy accepts ``postgresql://`` and then fails much later, deep
        inside the first query, with an error that names neither this setting
        nor the fix.
        """
        if value.scheme != "postgresql+asyncpg":
            msg = (
                f"LEKA_DATABASE_URL must use the asyncpg driver "
                f"(postgresql+asyncpg://...), got scheme {value.scheme!r}."
            )
            raise ValueError(msg)
        return value


__all__ = ["DatabaseSettings"]
