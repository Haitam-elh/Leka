"""Where an unhandled error goes when nobody is watching the logs.

With nothing configured, nothing is sent anywhere — which is the right
default on a laptop and in CI, and it is what keeps the test suite from
reporting its own deliberate failures to a third party.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator

from leka.core.settings._blank import blank_is_none
from leka.core.settings._rotation import RotateEvery


class MonitoringSettings:
    """Sentry, and nothing else.

    No metrics backend and no dashboard, deliberately: docs/background.md
    already says the SQL queries in it are the dashboard, and a second
    vendor to configure, pay and audit buys nothing on a product with no
    traffic yet.

    THE DSN IS TREATED AS A SECRET even though Sentry's own documentation
    calls it safe to expose. It identifies the project and lets anyone who
    holds it write events into it, which is enough to poison the one signal
    we would rely on during an incident. Declaring it SecretStr also puts it
    in `secret_values`, so it can never appear in a log line.
    """

    sentry_dsn: Annotated[SecretStr | None, RotateEvery(days=365)] = None

    # Errors only. Tracing samples requests and bills per span; on a staging
    # environment with no users it would price a feature nobody reads.
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    # Sent with every event so two environments cannot be confused for each
    # other in the same project. Read from `environment` by the platform
    # module rather than duplicated here.
    sentry_send_default_pii: Literal[False] = False

    # The commit this container was built from. Set by the deployment
    # pipeline; it is what makes "releases are traceable" true rather than
    # stated — an error in Sentry names the commit that introduced it.
    release: str | None = None

    @field_validator("sentry_dsn", "release", mode="before")
    @classmethod
    def _blank_dsn_is_not_configured(cls, value: object) -> object:
        """An empty LEKA_SENTRY_DSN means "off", not a DSN of length zero.

        A deployment template that always sets the variable would otherwise
        make the SDK raise at startup on every environment that has no
        project yet. See core/settings/_blank.py.
        """
        return blank_is_none(value)

    @property
    def monitoring_enabled(self) -> bool:
        return self.sentry_dsn is not None


__all__ = ["MonitoringSettings"]
