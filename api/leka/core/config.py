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

from pydantic import (
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
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

    # ── Authentication (LEKA-330) ───────────────────────────────────────────

    # Two limits, not one. A session dies at the absolute maximum whatever
    # happens, and at the idle timeout if unused. Both matter: the first
    # bounds a stolen cookie's usefulness, the second closes the laptop
    # someone left in a cafe.
    session_absolute_lifetime_days: int = Field(default=30, ge=1, le=365)
    session_idle_lifetime_days: int = Field(default=7, ge=1, le=90)

    verification_token_lifetime_hours: int = Field(default=24, ge=1, le=168)
    # Deliberately short. A reset link sits in an inbox, which is the least
    # trustworthy place a credential can wait.
    reset_token_lifetime_hours: int = Field(default=1, ge=1, le=24)

    session_cookie_name: str = "leka_session"
    # Sent over HTTPS only. False is for local development and nothing else —
    # the startup check below refuses it in production.
    session_cookie_secure: bool = True
    # "lax" gives CSRF protection for free, because every mutation we serve
    # is POST, PATCH or DELETE. "none" gives that up and is only needed when
    # the frontend and the API do not share a parent domain. See
    # docs/adr/009-cookie-strategy.md.
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # ── Email delivery ──────────────────────────────────────────────────────
    # With no API key the console sender is used: messages go to the log.
    # That is what makes the verification and recovery flows testable without
    # an account anywhere.
    email_from: str = "LEKA <no-reply@leka.example>"

    # SMTP, for a mailbox we already pay for. Preferred over an API provider
    # when both are configured: one fewer account, one fewer bill.
    #
    # OVH: ssl0.ovh.net, port 465, SSL/TLS, username = the full address.
    smtp_host: str | None = None
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    # True for port 465 (implicit TLS), False for 587 (STARTTLS).
    smtp_use_ssl: bool = True

    resend_api_key: SecretStr | None = None

    # Check new passwords against known breaches via HaveIBeenPwned, using
    # k-anonymity — only the first five characters of the hash are sent, and
    # the password never leaves this process. Off by default: it is a network
    # call, and tests must not depend on one.
    check_passwords_against_breaches: bool = False

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

    # ── Object storage (LEKA-332) ───────────────────────────────────────────
    # Raw payloads — a GitHub API response, a Datadog log export, a Confluence
    # page — do not belong in PostgreSQL. They are the largest volume in the
    # product and the shortest-lived; in the database they would swell every
    # backup and slow every restore. The rows hold metadata and a key, the
    # bytes live here. See docs/adr/010-object-storage.md.
    #
    # "local" is the default so the whole platform is testable with no account
    # anywhere, exactly as ConsoleEmailSender did for LEKA-330. Production
    # refuses to start with it — see _refuse_local_object_store_in_production.
    object_store: Literal["local", "s3"] = "local"

    # Where LocalObjectStore writes. Relative paths resolve against the repo
    # root, so one developer's working directory is not part of the contract.
    object_store_path: Path = Path("var/objects")

    # S3-compatible. Cloudflare R2 today, Amazon S3 in phase 3, same protocol
    # and the same code either way: only the endpoint changes.
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    # R2 ignores the region and wants "auto"; S3 wants a real one.
    s3_region: str = "auto"
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None

    # ── Retention ───────────────────────────────────────────────────────────
    # How long a raw payload is ours to keep, in days, per source kind. The
    # policy itself lives in leka.ingestion.retention, which is where the
    # source vocabulary belongs; this is only the override, so that a
    # customer contract or a regulator can move a number without a deploy.
    #
    # A dict keyed by source kind, as JSON:
    #   LEKA_RAW_PAYLOAD_RETENTION_DAYS={"datadog": 14, "github": 180}
    # Kinds left out keep the default written in that module.
    raw_payload_retention_days: dict[str, int] = Field(default_factory=dict)

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

    @field_validator("raw_payload_retention_days")
    @classmethod
    def _retention_is_within_reason(cls, value: dict[str, int]) -> dict[str, int]:
        """Refuse a retention that is obviously wrong, at startup.

        0 deletes a payload the moment it lands, which reads as "disabled"
        to whoever typed it and means "delete everything" to the sweep. A
        number in the thousands is a typo that nobody notices until the
        storage bill does. Both must stop the process, not the sweep.
        """
        for kind, days in value.items():
            if not 1 <= days <= 3650:
                msg = (
                    f"LEKA_RAW_PAYLOAD_RETENTION_DAYS[{kind!r}] is {days}. "
                    "Retention is in DAYS and must be between 1 and 3650."
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

    @field_validator(
        "anthropic_api_key",
        "mistral_api_key",
        "resend_api_key",
        "smtp_password",
        "smtp_host",
        "smtp_username",
        mode="before",
    )
    @classmethod
    def _empty_key_is_no_key(cls, value: object) -> object:
        """An empty string is not a value.

        Applies to credentials and to the SMTP connection details alike: a
        blank LEKA_SMTP_HOST must read as "no SMTP configured", not as a host
        called "". Otherwise the sender selection picks SMTP and every email
        fails against an empty address.

        .env.example ships these present but blank, so a copied .env yields
        "" rather than an absent variable. Without this, a setting nobody
        filled in reads as configured, and the failure moves from startup to
        the first time it is used — the failure mode this whole file exists
        to prevent.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _refuse_unsafe_cookies_in_production(self) -> Settings:
        """A cookie misconfiguration does not fail loudly on its own.

        It works perfectly in every test and quietly stops protecting anyone
        in production, which is why this is checked at startup rather than
        left to a code review.
        """
        if self.environment != "production":
            return self

        if not self.session_cookie_secure:
            msg = (
                "LEKA_SESSION_COOKIE_SECURE=false in production: the session "
                "cookie would travel over plain HTTP."
            )
            raise ValueError(msg)

        if self.session_cookie_samesite == "none":
            msg = (
                "LEKA_SESSION_COOKIE_SAMESITE=none in production. This gives up "
                "the CSRF protection SameSite=Lax provides for free, and is only "
                "needed when the frontend and the API do not share a parent "
                "domain. Put them under one (app.leka.xx and api.leka.xx) and "
                "use lax. If you genuinely must use none, remove this check "
                "deliberately and read docs/adr/009-cookie-strategy.md first."
            )
            raise ValueError(msg)

        return self

    @model_validator(mode="after")
    def _refuse_local_object_store_in_production(self) -> Settings:
        """A local disk is not durable storage.

        LocalObjectStore writes under a directory. On a container that is an
        ephemeral filesystem: the payloads survive exactly as long as the
        container does, and a redeploy loses every one of them silently —
        the rows keep pointing at keys whose bytes are gone. Like the cookie
        check above, this is verified at startup rather than left to a review.
        """
        if self.environment != "production":
            return self

        if self.object_store == "local":
            msg = (
                "LEKA_OBJECT_STORE=local in production: raw payloads would be "
                "written to a container filesystem and lost on the next "
                "deploy, leaving rows that point at nothing. Configure the S3 "
                "store (LEKA_S3_BUCKET, LEKA_S3_ENDPOINT_URL and credentials)."
            )
            raise ValueError(msg)

        missing = [
            name
            for name, value in (
                ("LEKA_S3_BUCKET", self.s3_bucket),
                ("LEKA_S3_ACCESS_KEY_ID", self.s3_access_key_id),
                ("LEKA_S3_SECRET_ACCESS_KEY", self.s3_secret_access_key),
            )
            if value is None
        ]
        if missing:
            msg = f"LEKA_OBJECT_STORE=s3 but {', '.join(missing)} is not set."
            raise ValueError(msg)

        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def object_store_root(self) -> Path:
        """Where LocalObjectStore writes, as an absolute path.

        A relative setting resolves against the repository root rather than
        the process working directory: the API, the worker and a test runner
        start from different places and must agree on one directory.
        """
        configured = self.object_store_path
        return configured if configured.is_absolute() else REPO_ROOT / configured

    @property
    def smtp_configured(self) -> bool:
        return self.smtp_host is not None and self.smtp_password is not None

    @property
    def sends_real_email(self) -> bool:
        return self.smtp_configured or self.resend_api_key is not None

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
