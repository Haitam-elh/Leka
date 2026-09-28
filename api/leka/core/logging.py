"""structlog setup, called once on startup.

Console renderer for a developer's terminal, JSON for anything a log
collector will read. Configured in one place so the API and the worker
produce the same shape of log line.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable, MutableMapping
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

# A value shorter than this is never masked by value. The local database
# password is "leka": masked by value, the product's own name would vanish
# from every line, and a marker everywhere is a marker nobody reads. A real
# secret is longer than this anyway.
MIN_MASKED_LENGTH = 8

# How deep `scrub` walks a nested structure. Sentry nests an exception's
# frames and their local variables about six levels down; ten leaves room
# and still bounds a structure that refers to itself.
MAX_SCRUB_DEPTH = 10


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


class SecretValueMasker:
    """Replace every configured secret, wherever it appears in a line.

    The net under REDACTED_KEYS, which only knows key names. A secret logged
    under `value=`, inside a sentence, inside a URL or inside a traceback
    passes every check on keys there is; this one looks at the values.

    Cheap on purpose, because it runs on every line. The secrets are known
    once, at startup. A line is searched with `in`, which runs in C, and
    rewritten only when a secret is actually in it.

    Lines from libraries that log through the standard library — uvicorn,
    SQLAlchemy — do not pass through structlog's processors, and so not
    through this one.
    """

    def __init__(self, secrets: Iterable[str]) -> None:
        # Longest first: when one secret contains another, the longer one
        # must go whole, or its remainder is left in the line.
        kept = {secret for secret in secrets if len(secret) >= MIN_MASKED_LENGTH}
        self._secrets = tuple(sorted(kept, key=len, reverse=True))

    def __call__(
        self, logger: object, method_name: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        if self._secrets:
            for key in list(event_dict):
                event_dict[key] = self._mask(event_dict[key])
        return event_dict

    def scrub(self, value: object) -> object:
        """Mask every secret anywhere inside a nested structure.

        The processor above only walks one level, because a log line is
        flat. A Sentry event is not: the value that gets someone fired sits
        in `exception.values[0].stacktrace.frames[3].vars["settings"]`, four
        levels down. This walks the whole thing.

        Depth is bounded. An event with a cycle in it would otherwise take
        the process down while reporting the error that caused it, which is
        the worst possible time.
        """
        return self._scrub(value, depth=0)

    def _scrub(self, value: object, *, depth: int) -> object:
        if not self._secrets or depth > MAX_SCRUB_DEPTH:
            return value
        if isinstance(value, dict):
            return {key: self._scrub(item, depth=depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [self._scrub(item, depth=depth + 1) for item in value]
        if isinstance(value, tuple):
            return tuple(self._scrub(item, depth=depth + 1) for item in value)
        return self._mask(value)

    def _mask(self, value: object) -> object:
        if value is None or isinstance(value, bool | int | float):
            return value
        # Anything else becomes text somewhere down the line — a URL object,
        # a dict, an exception — so it is searched as the text it will be.
        text = value if isinstance(value, str) else str(value)
        if not any(secret in text for secret in self._secrets):
            return value
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        return text


_masker: SecretValueMasker = SecretValueMasker(())


def scrub_secrets(value: object) -> object:
    """Remove every configured secret from anything, at any depth.

    The public way for another module to get a value cleaned without
    reading the secrets itself. `tests/test_secret_access.py` allows exactly
    one reader of `settings.secret_values`, which is this module — so
    leka.platform.monitoring hands its Sentry events here rather than
    building a second copy of the list and a second place to forget one.

    Returns the value unchanged until `configure_logging` has run. That is
    the honest answer at import time and during a test that never configures
    logging: nothing is configured, so nothing is known to be secret.
    """
    return _masker.scrub(value)


def configure_logging(settings: Settings) -> None:
    """Point stdlib logging and structlog at the same pipeline."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )
    # httpx writes every URL it calls, at INFO. A connector's URLs are the
    # customer's, and some carry a credential for as long as they live — a
    # pre-authenticated download link, Microsoft Graph's for a file's
    # content. A connector's failures reach the logs as diagnostics, cleaned
    # of secrets; its requests do not reach them at all.
    for chatty in ("httpx", "httpcore"):
        logging.getLogger(chatty).setLevel(logging.WARNING)

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
            # Last before rendering: it must see the traceback as text, which
            # format_exc_info has only just produced.
            _remember_masker(
                SecretValueMasker(value.get_secret_value() for value in settings.secret_values)
            ),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
        cache_logger_on_first_use=True,
    )


def _remember_masker(masker: SecretValueMasker) -> SecretValueMasker:
    """Keep the processor's masker reachable, and hand it straight back.

    Written as one expression inside the processor list so the masker used
    for logs and the masker used for Sentry cannot become two objects built
    from two readings of the settings.
    """
    global _masker
    _masker = masker
    return masker
