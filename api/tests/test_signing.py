"""leka.core.signing: one root key, and a key of its own for every purpose."""

from __future__ import annotations

import hashlib
import hmac

import pytest
from pydantic import SecretStr

from leka.core import signing
from leka.core.config import settings
from leka.core.signing import Purpose, sign

PAYLOAD = b'{"d":"desc","i":"0","k":"x","s":"created_at"}'


def _root() -> bytes:
    return settings.secret_key.get_secret_value().encode()


def test_the_root_key_never_signs_anything_directly() -> None:
    """A signature made with the root key would be valid for every purpose."""
    with_root = hmac.new(_root(), PAYLOAD, hashlib.sha256).digest()
    assert sign(Purpose.PAGINATION_CURSOR, PAYLOAD) != with_root


def test_the_derivation_is_the_documented_one() -> None:
    """Pinned, because changing it invalidates every signature in flight.

    Today that is a cursor, which lives for seconds. The day a signed thing
    lives longer — a link in an e-mail — the change must be deliberate.
    """
    key = hmac.new(_root(), b"leka:pagination-cursor:v1", hashlib.sha256).digest()
    expected = hmac.new(key, PAYLOAD, hashlib.sha256).digest()
    assert sign(Purpose.PAGINATION_CURSOR, PAYLOAD) == expected


def test_rotating_the_root_key_changes_every_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    before = sign(Purpose.PAGINATION_CURSOR, PAYLOAD)
    rotated = settings.model_copy(update={"secret_key": SecretStr("another-root-key")})
    monkeypatch.setattr(signing, "settings", rotated)

    assert sign(Purpose.PAGINATION_CURSOR, PAYLOAD) != before
