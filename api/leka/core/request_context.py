"""The identifier of the request being served, readable from anywhere.

Split out of the middleware that sets it, and deliberately: leka.api sits at
the top of the dependency order, so anything below it — the CSRF middleware
in leka.identity, a repository, a service — could not import from there to
ask what request it is serving. This module is in leka.core, which everyone
may import.

Nothing here knows about HTTP. It is a context variable and a generator; the
middleware that fills it lives in leka.api.request_id.
"""

from __future__ import annotations

import os
import time
from contextvars import ContextVar

# Crockford's base32: no I, L, O or U, so an identifier read aloud or copied
# out of a terminal cannot be misheard or mistyped into a different one.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_request_id: ContextVar[str | None] = ContextVar("leka_request_id", default=None)


def new_request_id() -> str:
    """A 26-character identifier that sorts by time.

    A ULID rather than a UUID4: 48 bits of millisecond timestamp then 80 of
    randomness, so sorting a day of log lines returns them in the order they
    happened. That is worth more than it sounds when you are reading a
    failure and want to know what came immediately before it.

    Nine lines rather than a dependency.
    """
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    encoded = ""
    for _ in range(26):
        value, remainder = divmod(value, 32)
        encoded = _ALPHABET[remainder] + encoded
    return encoded


def current_request_id() -> str | None:
    """The id of the request being served, or None outside one.

    None is a real answer, not a failure: a worker job, a migration and a
    unit test all run without a request. An error built there simply has no
    id to quote.
    """
    return _request_id.get()


def set_request_id(request_id: str) -> object:
    """Bind an id for this context. Returns a token for reset_request_id."""
    return _request_id.set(request_id)


def reset_request_id(token: object) -> None:
    """Undo a set_request_id, so a context cannot leak into the next one."""
    _request_id.reset(token)  # type: ignore[arg-type]


# Where the request came from, as the audit trail keeps it (LEKA-407): the
# caller's address as given — reduced to a network prefix before it is
# stored — and what it said it was.
_origin: ContextVar[tuple[str | None, str | None]] = ContextVar(
    "leka_request_origin", default=(None, None)
)


def set_request_origin(ip: str | None, user_agent: str | None) -> object:
    return _origin.set((ip, user_agent))


def current_request_origin() -> tuple[str | None, str | None]:
    """(address, user agent) of the request being served; (None, None)
    outside one."""
    return _origin.get()


def reset_request_origin(token: object) -> None:
    _origin.reset(token)  # type: ignore[arg-type]


__all__ = [
    "current_request_id",
    "current_request_origin",
    "new_request_id",
    "reset_request_id",
    "reset_request_origin",
    "set_request_id",
    "set_request_origin",
]
