"""Application settings, read from the environment once, at import time.

A missing required variable must stop the process on startup. A None
discovered in production three weeks later costs far more than a container
that refuses to boot.

This file is shared: it belongs to LEKA-329. Changes to it are requested,
not made in passing — see docs/conventions.md.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: api/leka/core/config.py -> api/leka/core -> api/leka -> api -> .
REPO_ROOT = Path(__file__).resolve().parents[3]


class ConfigurationError(RuntimeError):
    """Raised on startup when the environment is incomplete or malformed."""


class Settings(BaseSettings):
    """Every knob the backend reads from its environment.

    Variables are prefixed with ``LEKA_`` so they never collide with the
    ``POSTGRES_*`` variables docker-compose hands to the database container.
    """

    model_config = SettingsConfigDict(
        env_prefix="LEKA_",
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    # ── Required. No defaults on purpose: the app must not invent them. ──────
    database_url: PostgresDsn = Field(
        description="postgresql+asyncpg://user:password@host:port/database",
    )
    redis_url: RedisDsn = Field(
        description="redis://host:port/db — queue backend for the background loop",
    )
    secret_key: SecretStr = Field(
        description=(
            "Signing key for anything the server hands to a client. "
            "Consumed by leka.identity (LEKA-330); defined here because "
            "configuration lives in one place."
        ),
    )

    # ── Optional, with defaults that are safe in every environment. ──────────
    environment: Literal["local", "ci", "staging", "production"] = "local"
    debug: bool = False

    api_v1_prefix: str = "/api/v1"
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"

    # Database pool. Small by default: two part-time developers on laptops.
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_echo: bool = False

    # Where the agent markdown files live. Content, not code — see agents/README.md.
    agents_dir: Path = REPO_ROOT / "agents"

    # The only consumer of this is leka.capabilities (architecture rule 7).
    # Optional: the platform boots and serves without a model configured.
    anthropic_api_key: SecretStr | None = None

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

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def _load_settings() -> Settings:
    """Build Settings, turning a pydantic error into an actionable message."""
    try:
        return Settings()
    except ValidationError as exc:
        lines = [
            "LEKA cannot start: its environment is incomplete or invalid.",
            "",
        ]
        for error in exc.errors():
            variable = "LEKA_" + ".".join(str(part) for part in error["loc"]).upper()
            lines.append(f"  {variable}: {error['msg']}")
        lines += [
            "",
            "Copy .env.example to .env and fill it in — see docs/setup.md.",
        ]
        raise ConfigurationError("\n".join(lines)) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """FastAPI dependency and general accessor.

    Cached: the environment is read once per process.
    """
    return _load_settings()


# Imported at module level so that an incomplete environment stops the process
# on startup rather than on the first request that happens to need a setting.
settings: Settings = _load_settings()
