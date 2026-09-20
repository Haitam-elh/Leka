"""structlog setup, called once on startup.

Console renderer for a developer's terminal, JSON for anything a log
collector will read. Configured in one place so the API and the worker
produce the same shape of log line.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from leka.core.config import Settings

# Keys whose value must never reach a log line, in any module.
#
# This is the leak nobody notices until the day a log aggregator is plugged
# in and six months of passwords are suddenly searchable. Masking at the
# logging layer rather than at every call site means a new route cannot
# forget: the author of a future `logger.info("x", token=...)` does not have
# to know this list exists.
REDACTED_KEYS = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "password_hash",
        "token",
        "session_token",
        "reset_token",
        "verification_token",
        "token_hash",
        "cookie",
        "set-cookie",
        "authorization",
        "secret",
        "secret_key",
        "api_key",
        "credentials",
    }
)

MASK = "[redacted]"


def redact_secrets(
    logger: object, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Replace the value of any sensitive key with a marker.

    Matches case-insensitively and on suffixes, so `user_password` and
    `X-Api-Key` are caught too. The key itself is kept: knowing that a token
    was involved is useful, and the value never is.
    """
    for key in list(event_dict):
        lowered = key.lower().replace("-", "_")
        if lowered in REDACTED_KEYS or any(
            lowered.endswith(f"_{sensitive}") for sensitive in REDACTED_KEYS
        ):
            event_dict[key] = MASK
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Point stdlib logging and structlog at the same pipeline."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            # First in the chain, before anything can render or ship a line.
            redact_secrets,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
        cache_logger_on_first_use=True,
    )
