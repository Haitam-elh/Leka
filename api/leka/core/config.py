"""Application settings, read from the environment once, at import time.

A missing required variable must stop the process on startup. A None
discovered in production three weeks later costs far more than a container
that refuses to boot.

THE FIELDS THEMSELVES LIVE IN leka/core/settings/, one file per domain. This
module assembles them and owns three things they cannot own individually:

  * the model configuration — the LEKA_ prefix, the .env file, frozen
  * the checks that SPAN domains, which is every production guard: they
    combine `environment` from one domain with a field from another
  * loading, and the single `settings` instance

ADDING SETTINGS FOR A NEW DOMAIN. Write `core/settings/<domain>.py`, then
add two lines here: the import, and the class name in the base list. Nothing
else in this file changes, and nobody editing another domain touches your
fields. That is the point of the split — the settings file is where two
people working at once collide, every time, because it grows with every
feature and belongs to no feature.

The import path is unchanged: `from leka.core.config import settings`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple, Self

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from leka.core.settings._rotation import RotateEvery
from leka.core.settings.background import BackgroundSettings
from leka.core.settings.database import DatabaseSettings
from leka.core.settings.email import EmailSettings
from leka.core.settings.model_access import ModelAccessSettings
from leka.core.settings.monitoring import MonitoringSettings
from leka.core.settings.paths import REPO_ROOT
from leka.core.settings.runtime import RuntimeSettings
from leka.core.settings.security import SecuritySettings
from leka.core.settings.storage import StorageSettings

__all__ = ["REPO_ROOT", "ConfigurationError", "OverdueSecret", "Settings", "settings"]


class ConfigurationError(RuntimeError):
    """Raised on startup when the environment is incomplete or malformed."""


class OverdueSecret(NamedTuple):
    """A secret past its lifetime, or of unknown age. Names and numbers only."""

    setting: str
    # None: nobody recorded when it was last rotated.
    age_days: int | None
    rotate_every_days: int


class Settings(
    RuntimeSettings,
    DatabaseSettings,
    SecuritySettings,
    EmailSettings,
    ModelAccessSettings,
    MonitoringSettings,
    StorageSettings,
    BackgroundSettings,
    BaseSettings,
):
    """Every knob the backend reads from its environment.

    Variables are prefixed with ``LEKA_`` so they never collide with the
    ``POSTGRES_*`` variables docker-compose hands to the database container.

    The domain classes are plain mixins, not nested models, and that is
    deliberate: nested models would make pydantic-settings expect
    ``LEKA_QUEUE__MAX_ATTEMPTS``, with a double underscore. The flat names
    are a contract — they are what .env.example documents, what CI sets, and
    what an operator types.
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

    # ── Checks that span domains ────────────────────────────────────────────
    #
    # These live here rather than in a domain file because each combines
    # `environment` with a field from somewhere else. Putting one in either
    # domain would make that domain depend on the other, which is the thing
    # the split exists to avoid.

    @model_validator(mode="after")
    def _refuse_unsafe_cookies_in_production(self) -> Self:
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
    def _refuse_local_object_store_in_production(self) -> Self:
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

    @model_validator(mode="after")
    def _rotation_dates_name_real_secrets(self) -> Self:
        """A typo in LEKA_SECRETS_ROTATED_ON must not quietly switch the age check off.

        An unknown name records the age of nothing, and a date in the future
        makes a secret look fresh for years. Both stop the process, like any
        invalid configuration — which is not the same as stopping because a
        secret is old. A day of slack, for whoever typed the date ahead of UTC.
        """
        lifetimes = _lifetimes()
        unknown = sorted(set(self.secrets_rotated_on) - set(lifetimes))
        if unknown:
            msg = (
                f"LEKA_SECRETS_ROTATED_ON names {unknown}, which are not secrets. "
                f"Known: {sorted(lifetimes)}."
            )
            raise ValueError(msg)

        tomorrow = datetime.now(UTC).date() + timedelta(days=1)
        future = sorted(name for name, day in self.secrets_rotated_on.items() if day > tomorrow)
        if future:
            msg = f"LEKA_SECRETS_ROTATED_ON dates {future} in the future."
            raise ValueError(msg)
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def overdue_secrets(self, today: date) -> list[OverdueSecret]:
        """Secrets past their declared lifetime, or of unknown age.

        Staging and production only: local and CI keys are throwaway, and a
        warning on every laptop is a warning nobody reads. A secret that is
        not configured has nothing to rotate, and is not reported.
        """
        if self.environment not in {"staging", "production"}:
            return []

        overdue: list[OverdueSecret] = []
        for name, lifetime in _lifetimes().items():
            if not _holds_a_secret(getattr(self, name)):
                continue
            rotated = self.secrets_rotated_on.get(name)
            age = None if rotated is None else (today - rotated).days
            if age is None or age > lifetime:
                overdue.append(OverdueSecret(name, age, lifetime))
        return overdue

    @property
    def secret_values(self) -> tuple[SecretStr, ...]:
        """Every secret actually configured, for the log masking to recognise.

        Found from the fields themselves rather than listed, so a secret added
        to any domain later is masked without anybody remembering to add it
        here. A connection URL counts through its password.

        Only leka.core.logging reads this: holding every value is exactly its
        job, and nobody else's. tests/test_secret_access.py enforces it.
        """
        found: list[SecretStr] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            for item in value if isinstance(value, tuple) else (value,):
                if isinstance(item, SecretStr):
                    found.append(item)
                else:
                    found.extend(SecretStr(password) for password in _url_passwords(item))
        return tuple(found)


def _lifetimes() -> dict[str, int]:
    """Every field's declared lifetime, read from its RotateEvery marker."""
    return {
        name: marker.days
        for name, field in Settings.model_fields.items()
        for marker in field.metadata
        if isinstance(marker, RotateEvery)
    }


def _holds_a_secret(value: object) -> bool:
    """Whether a field's value actually carries a secret: a URL may have no password."""
    items = value if isinstance(value, tuple) else (value,)
    return any(isinstance(item, SecretStr) or _url_passwords(item) for item in items)


def _url_passwords(value: object) -> list[str]:
    """The passwords a connection URL carries, if the value is one."""
    hosts = getattr(value, "hosts", None)
    if callable(hosts):
        # PostgresDsn can name several hosts, each with its own credentials.
        return [host["password"] for host in hosts() if host.get("password")]
    password = getattr(value, "password", None)
    return [password] if isinstance(password, str) and password else []


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
