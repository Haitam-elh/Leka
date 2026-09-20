"""Password hashing, token generation, constant-time comparison.

Pure functions over bytes and strings. No FastAPI, no database, no request —
so every rule here can be tested directly, which matters more in this module
than anywhere else in the codebase: a mistake in authentication does not show
up at runtime. Nothing crashes. It just quietly lets the wrong person in.

See docs/security.md for the threat model these choices answer.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# ─────────────────────────────────────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────────────────────────────────────
#
# argon2id: the hybrid variant, resistant both to GPU cracking (like argon2d)
# and to side-channel attacks (like argon2i). It is what OWASP and RFC 9106
# recommend, and it is the default of this library — stated explicitly below
# anyway, because a security parameter taken from a default is a security
# parameter nobody chose.
#
# Not bcrypt: it silently truncates at 72 bytes, so a long passphrase is
# weaker than it looks. Not any bare SHA: those are designed to be fast, which
# is exactly wrong for a password.
#
# Parameters follow the RFC 9106 second recommended configuration, which trades
# less memory for more passes and suits a shared application server:

# 64 MiB. Enough that a GPU cannot hold thousands of hashes in parallel;
# little enough that a few concurrent logins do not evict the connection pool.
ARGON2_MEMORY_COST_KIB = 64 * 1024
# Three passes over that memory.
ARGON2_TIME_COST = 3
# Two lanes: our API is async and IO-bound, and more parallelism here mostly
# takes CPU away from serving other requests.
ARGON2_PARALLELISM = 2
ARGON2_HASH_LENGTH = 32
ARGON2_SALT_LENGTH = 16

_hasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST_KIB,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LENGTH,
    salt_len=ARGON2_SALT_LENGTH,
    type=Type.ID,
)

# NIST SP 800-63B: length is what matters. No composition rules — requiring an
# uppercase and a digit produces Password1! and nothing more secure. No forced
# expiry either; it produces password2, password3.
PASSWORD_MIN_LENGTH = 12
# A maximum exists only to bound the work an attacker can make us do by
# posting a megabyte. It is far above any real passphrase, and we never
# truncate below it.
PASSWORD_MAX_LENGTH = 256

# A real argon2id hash of a value nobody knows, verified against when the
# email does not exist. Without it, "unknown email" returns in microseconds
# and "wrong password" in ~50ms, and the difference is trivially measurable —
# which turns the login form into an account enumeration oracle.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))
_WRONG_ON_PURPOSE = "this never matches the dummy hash"


def hash_password(password: str) -> str:
    """Hash a password for storage. The salt is generated and embedded."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising on a mismatch: a wrong password is an
    expected event, not an error condition.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def waste_time_like_a_real_verification() -> None:
    """Spend the same work as a real verification, for an account that does
    not exist.

    Called on the no-such-email path of login. It computes nothing anyone
    needs; its only output is the time it takes. See
    test_identity_security.py, which asserts this runs rather than timing it —
    a wall-clock assertion on a shared CI runner fails at random, and a test
    that fails at random gets ignored, which removes the protection it was
    written to provide.
    """
    # The verification necessarily fails — that is the point, and the whole
    # cost is paid before it does. Swallowing the exception is not laziness:
    # letting it escape would turn the no-such-email path into a 500, which
    # is a louder account oracle than the timing this exists to hide.
    try:
        _hasher.verify(_DUMMY_HASH, _WRONG_ON_PURPOSE)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return


def password_needs_rehash(password_hash: str) -> bool:
    """True when a stored hash used weaker parameters than we now require.

    Called after a successful login: that is the one moment we hold the clear
    password and can upgrade the hash without asking anyone to do anything.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Tokens
# ─────────────────────────────────────────────────────────────────────────────

# 32 bytes = 256 bits of entropy. Guessing one is not a threat model, it is a
# thermodynamics problem.
TOKEN_BYTES = 32


def generate_token() -> str:
    """A session, verification or reset token.

    secrets, never random: the latter is a Mersenne twister, and observing a
    few of its outputs predicts the rest.
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """What we store for a token.

    SHA-256, not argon2, and deliberately so. Argon2 is slow on purpose to
    make guessing a low-entropy secret expensive; a 256-bit random token has
    nothing to guess. Slowing it down would only add latency to every single
    authenticated request, since this runs on each one.

    What this does buy is the same thing password hashing buys: a leaked
    database is not a set of usable sessions.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(presented: str, stored_hash: str) -> bool:
    """Compare a presented token to a stored hash, in constant time.

    compare_digest, not ==: string comparison returns as soon as two bytes
    differ, and the timing of that leaks the token prefix byte by byte.
    """
    return hmac.compare_digest(hash_token(presented), stored_hash)
