"""The application signing key, and the one module that reads it.

LEKA_SECRET_KEY signs what the server hands a client and expects back
unchanged. Only this module reads it. Everything else asks for a signature
under a PURPOSE, and every purpose signs with a key of its own, derived from
the root one:

    key(purpose) = HMAC-SHA256(LEKA_SECRET_KEY, "leka:" + purpose)

Two reasons, both about the day something goes wrong.

SEPARATION. With a single key, a signature produced for one use is valid
for every other use: a place that signs bytes an attacker chooses would
forge all the others at once. A key per purpose makes a signature mean
"valid for this purpose", and nothing more.

CONTAINMENT. A module holding the root key holds every key that can be
derived from it, and can leak them all through one log line. A module
holding a signing function holds nothing it can leak. HMAC is a
pseudo-random function: seeing one derived key teaches nothing about the
root, or about any other purpose's key.

A purpose carries a version. Changing what is signed under a purpose
without changing its name would let old signatures vouch for new payloads.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import StrEnum, unique

from leka.core.config import settings


@unique
class Purpose(StrEnum):
    """Everything the root key signs, one member per kind of signed thing.

    `@unique` is not decoration. Two members with the same value would not be
    an error in an Enum: the second silently becomes an alias of the first,
    and the two purposes share a key.
    """

    PAGINATION_CURSOR = "pagination-cursor:v1"


def _key(purpose: Purpose) -> bytes:
    """Derived on every call, deliberately.

    One HMAC costs microseconds, and nothing cached means nothing to go
    stale when a test or a rotation changes the root.
    """
    root = settings.secret_key.get_secret_value().encode()
    return hmac.new(root, f"leka:{purpose.value}".encode(), hashlib.sha256).digest()


def sign(purpose: Purpose, payload: bytes) -> bytes:
    """An HMAC-SHA256 of `payload`, valid for `purpose` and no other.

    Compare a presented signature with hmac.compare_digest, never with `==`:
    an ordinary comparison stops at the first differing byte, and the time
    it takes tells an attacker how many bytes they have right.
    """
    return hmac.new(_key(purpose), payload, hashlib.sha256).digest()


__all__ = ["Purpose", "sign"]
