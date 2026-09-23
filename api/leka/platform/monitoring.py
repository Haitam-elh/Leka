"""Unhandled errors, sent somewhere a person will see them.

WHY THIS MODULE EXISTS AT ALL. Logs are the record; they are useless as an
alarm. Nobody reads a staging log file, and the first sign of a broken
deployment should not be a customer. Sentry is the smallest thing that
turns an exception into a message.

WHY IT SCRUBS. Sentry does not send the message — it sends the exception,
its stack, and the local variables of every frame in it. `settings` is a
local variable in more places than anyone can enumerate, and it holds the
database password, the Fernet keys and the session signing key. LEKA-335
built a masker so that a secret can never reach a log line; a monitoring
integration that bypasses it would hand a third party exactly what that
ticket was written to protect.

The scrubbing is not done here. `tests/test_secret_access.py` allows one
module to read `settings.secret_values`, and it is `leka.core.logging`.
This module hands events to `scrub_secrets` and never sees a secret itself,
which is why that guard test still passes with this file in the tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import structlog

from leka.core.config import Settings
from leka.core.logging import scrub_secrets

if TYPE_CHECKING:  # pragma: no cover
    # Only for the annotation: the SDK is imported lazily below so that an
    # environment without a DSN never loads it.
    from sentry_sdk.types import Event

logger = structlog.get_logger(__name__)


def _scrub_event(event: Event, _hint: dict[str, Any]) -> Event | None:
    """Sentry's last chance to change an event, and ours.

    Returns the event with every known secret replaced, at any depth. If
    scrubbing itself fails, the event is dropped and the failure logged,
    never sent unscrubbed: a lost error report can be reproduced, a secret
    on a third party's servers cannot be taken back.
    """
    try:
        scrubbed = scrub_secrets(event)
    except Exception as error:  # pragma: no cover - defensive
        logger.error("sentry_scrub_failed", error=str(error))
        return None
    if not isinstance(scrubbed, dict):  # pragma: no cover - scrub keeps the shape
        return None
    return cast("Event", scrubbed)


def configure_monitoring(settings: Settings) -> bool:
    """Start reporting errors, if a project is configured.

    Returns whether it did, so a caller can say so at startup instead of
    leaving "is Sentry on?" to be answered by causing an error.

    Never raises. A monitoring integration that prevents the application
    from booting has inverted its own purpose.
    """
    if settings.sentry_dsn is None:
        return False

    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - the dependency is declared
        logger.warning("sentry_sdk_missing")
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        # Two environments in one project are indistinguishable without
        # this, and the first question about any error is "where".
        environment=settings.environment,
        release=settings.release,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # Off, and typed as unchangeable in the settings: PII here would mean
        # a customer's e-mail address on a third party's servers, which is a
        # data-protection decision and not a monitoring one.
        send_default_pii=settings.sentry_send_default_pii,
        before_send=_scrub_event,
    )
    logger.info("monitoring_configured", environment=settings.environment, release=settings.release)
    return True


__all__ = ["configure_monitoring"]
