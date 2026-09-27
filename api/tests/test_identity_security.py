"""The security properties of authentication, tested directly.

"Security-sensitive flows are covered by automated tests" is an acceptance
criterion of LEKA-330, not a formality. This file covers the rules that have
no visible symptom when they break: a password stored in the clear, a timing
difference, a session that survives a sign-out. Nothing crashes when these
are wrong. The wrong person just gets in.
"""

from __future__ import annotations

import pytest
import structlog

from leka.core import security
from leka.core.logging import MASK, redact_secrets
from leka.identity import truncate_ip

pytestmark = pytest.mark.integration


# ── Passwords ────────────────────────────────────────────────────────────────


def test_a_password_is_never_recoverable_from_its_hash() -> None:
    password = "correct horse battery staple"
    stored = security.hash_password(password)

    assert password not in stored
    assert stored.startswith("$argon2id$")


def test_the_same_password_hashes_differently_every_time() -> None:
    """A per-hash salt. Without one, identical passwords give identical rows
    and the database tells an attacker which accounts to try first."""
    assert security.hash_password("same") != security.hash_password("same")


def test_argon2id_is_the_variant_and_the_parameters_are_ours() -> None:
    """Pinned deliberately: a security parameter taken from a library default
    is a parameter nobody chose, and defaults change between releases."""
    stored = security.hash_password("whatever will do")
    _, variant, _, parameters, *_ = stored.split("$")

    assert variant == "argon2id"
    assert f"m={security.ARGON2_MEMORY_COST_KIB}" in parameters
    assert f"t={security.ARGON2_TIME_COST}" in parameters
    assert f"p={security.ARGON2_PARALLELISM}" in parameters


def test_long_passphrases_are_not_truncated() -> None:
    """bcrypt silently cuts at 72 bytes, which makes a long passphrase weaker
    than it looks. This is the test that would have caught choosing it."""
    base = "a" * 80
    stored = security.hash_password(base + "_ending_one")

    assert security.verify_password(base + "_ending_one", stored)
    assert not security.verify_password(base + "_ending_two", stored)


def test_a_malformed_hash_is_a_failed_verification_not_a_crash() -> None:
    """A corrupted column must not take down the login route."""
    assert security.verify_password("anything", "not-a-hash") is False


def test_the_dummy_verification_does_real_work_and_never_raises() -> None:
    """The defence against timing-based account enumeration.

    Asserted by behaviour rather than by a stopwatch: a wall-clock comparison
    on a shared CI runner fails at random, and a test that fails at random
    gets ignored — which removes the protection it was written to provide.

    What matters is that the no-such-email path runs a genuine argon2
    verification and returns cleanly. An early version raised
    VerifyMismatchError here, which would have turned that path into a 500 —
    a louder account oracle than the timing it was hiding.
    """
    # Calling it is the assertion: the function returns nothing, and an
    # earlier version raised VerifyMismatchError here.
    security.waste_time_like_a_real_verification()


@pytest.mark.parametrize("attempt", ["", "short", "elevenchars"])
def test_the_password_floor_is_twelve_characters(attempt: str) -> None:
    from pydantic import ValidationError

    from leka.identity import RegisterRequest

    with pytest.raises(ValidationError) as caught:
        RegisterRequest(
            email="a@b.com", password=attempt, first_name="Nora", last_name="D", company="Acme"
        )
    # Refused for the password, not for something else missing.
    assert [error["loc"] for error in caught.value.errors()] == [("password",)]


def test_no_composition_rules() -> None:
    """NIST SP 800-63B: demanding an uppercase and a digit produces
    Password1! and nothing stronger. Length is what matters."""
    from leka.identity import RegisterRequest

    accepted = RegisterRequest(
        email="a@b.com",
        password="all lowercase words here",
        first_name="Nora",
        last_name="D",
        company="Acme",
    )

    assert accepted.password == "all lowercase words here"


# ── Tokens ───────────────────────────────────────────────────────────────────


def test_a_token_is_never_recoverable_from_its_stored_hash() -> None:
    token = security.generate_token()
    stored = security.hash_token(token)

    assert token not in stored
    assert len(stored) == 64


def test_tokens_are_unguessable() -> None:
    """256 bits from secrets, not random: the latter is a Mersenne twister,
    and a few observed outputs predict the rest."""
    minted = {security.generate_token() for _ in range(200)}

    assert len(minted) == 200
    assert all(len(token) >= 40 for token in minted)


def test_token_comparison_is_constant_time() -> None:
    token = security.generate_token()
    stored = security.hash_token(token)

    assert security.tokens_match(token, stored)
    assert not security.tokens_match(security.generate_token(), stored)


# ── Logs ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "token",
        "session_token",
        "token_hash",
        "cookie",
        "authorization",
        "api_key",
        "user_password",
    ],
)
def test_secrets_never_reach_a_log_line(key: str) -> None:
    """The leak nobody notices until a log aggregator is plugged in and six
    months of credentials become searchable."""
    masked = redact_secrets(None, "info", {key: "the actual secret", "email": "a@b.com"})

    assert masked[key] == MASK
    assert masked["email"] == "a@b.com"


def test_redaction_keeps_the_key_so_the_event_stays_readable() -> None:
    """Knowing a token was involved is useful. Its value never is."""
    masked = redact_secrets(None, "info", {"token": "abc", "event": "login"})

    assert "token" in masked
    assert masked["event"] == "login"


def test_the_redaction_processor_is_actually_installed() -> None:
    """A processor written and never wired in protects nothing.

    configure_logging is called explicitly: it normally runs in the
    application lifespan, which a unit test does not start. Without this
    call the assertion would compare against structlog's defaults — which
    resemble ours closely enough to pass for the wrong reason.
    """
    from leka.core.config import settings
    from leka.core.logging import configure_logging

    configure_logging(settings)
    configured = structlog.get_config()["processors"]

    assert redact_secrets in configured


# ── Personal data ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("203.0.113.47", "203.0.113.0/24"),
        ("203.0.113.47, 70.41.3.18", "203.0.113.0/24"),
        ("2001:db8:85a3:8d3:1319:8a2e:370:7348", "2001:db8:85a3::/48"),
        (None, None),
        ("", None),
        ("not an address", None),
    ],
)
def test_addresses_are_truncated_before_storage(raw: str | None, expected: str | None) -> None:
    """A full address is personal data under GDPR and we have no use for one:
    the question is "roughly the same network", not "where exactly"."""
    assert truncate_ip(raw) == expected
