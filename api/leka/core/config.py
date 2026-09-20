"""Application settings, read from the environment once, at import time.

A missing required variable must stop the process on startup. A None
discovered in production three weeks later costs far more than a container
that refuses to boot.

This file is shared: it belongs to LEKA-329. Changes to it are requested,
not made in passing — see docs/conventions.md.
"""

from __future__ import annotations

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
        # extra="ignore", not "forbid": .env is shared with docker-compose,
        # which reads POSTGRES_* and REDIS_PORT from the same file, and with
        # the web app, which reads NEXT_PUBLIC_API_URL. Forbidding extras
        # means `cp .env.example .env` produces an API that refuses to start —
        # which is exactly what it did before this line was written.
        extra="ignore",
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
    encryption_keys: tuple[SecretStr, ...] = Field(
        min_length=1,
        description=(
            "Fernet keys for credentials at rest. The FIRST encrypts; all of "
            "them are tried when decrypting, which is what makes rotation "
            "possible without a flag day. Generate one with: python -c "
            '"from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
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

    # ── Model access. Consumed by leka.capabilities and nowhere else
    # (architecture rule 7). Both keys are optional: the platform boots and
    # serves without a model configured.
    #
    # Two providers from the start, on purpose. An abstraction validated
    # against a single implementation is an abstraction that fits one
    # implementation; the second provider is what proves the gateway holds.
    # Mistral also answers the question a customer's security officer asks
    # first: where does our data go.
    # Mistral is the default, not Anthropic. The architecture puts Mistral
    # first with Claude as the fallback, and the commercial argument is "your
    # data stays in Europe" — which only holds if the European path is the
    # one exercised every day, rather than an option discovered broken in
    # front of a customer's security officer.
    llm_provider: Literal["mistral", "anthropic"] = "mistral"
    anthropic_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None

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

    @field_validator("encryption_keys")
    @classmethod
    def _keys_are_usable(cls, value: tuple[SecretStr, ...]) -> tuple[SecretStr, ...]:
        """Reject a malformed Fernet key at startup.

        Fernet only complains when it is first used, which would be the first
        sync of the first connector — long after deploy, and in a worker log
        nobody is watching.
        """
        from cryptography.fernet import Fernet

        for index, key in enumerate(value):
            try:
                Fernet(key.get_secret_value().encode())
            except (ValueError, TypeError) as exc:
                msg = (
                    f"LEKA_ENCRYPTION_KEYS[{index}] is not a valid Fernet key "
                    "(32 url-safe base64-encoded bytes)"
                )
                raise ValueError(msg) from exc
        return value

    @field_validator("anthropic_api_key", "mistral_api_key", mode="before")
    @classmethod
    def _empty_key_is_no_key(cls, value: object) -> object:
        """An empty string is not a credential.

        .env.example ships these commented-in but blank, so a copied .env
        yields "" rather than an absent variable. Without this, a key nobody
        filled in reads as configured, and the failure moves from startup to
        the first model call — which is the failure mode this whole file
        exists to prevent.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def llm_api_key(self) -> SecretStr | None:
        """The key for the selected provider, if it is configured.

        None means no model is reachable. leka.capabilities is the only
        module that reads this, and the only one entitled to fail on it —
        the rest of the platform works without a model.
        """
        keys: dict[str, SecretStr | None] = {
            "anthropic": self.anthropic_api_key,
            "mistral": self.mistral_api_key,
        }
        return keys[self.llm_provider]

    @property
    def has_model_access(self) -> bool:
        return self.llm_api_key is not None


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


# ONE way to reach the settings: this module-level instance.
#
# There was also a cached get_settings() accessor. Two paths to the same
# object is one too many — the second one drifts. The environment is read
# here, at import, so an incomplete environment stops the process on startup
# rather than on the first request that happens to need a setting.
#
# The consequence is deliberate and worth stating: importing ANY leka module
# without a valid environment fails, including from a one-off script. That is
# the same guarantee, applied consistently.
settings: Settings = _load_settings()
