"""Credential encryption at rest.

A customer's GitHub token is the keys to their source code. These tests are
the contract for how it is stored — see docs/adr/005-credential-storage.md,
including an honest account of what this does and does not protect against.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from leka.platform import DecryptionError, SecretBox

TOKEN = "ghp_a_customers_real_looking_github_token_1234"


@pytest.fixture
def key() -> str:
    return Fernet.generate_key().decode()


def test_a_credential_round_trips(key: str) -> None:
    box = SecretBox((key,))

    assert box.decrypt(box.encrypt(TOKEN)) == TOKEN


def test_the_stored_bytes_do_not_contain_the_token(key: str) -> None:
    """The point of the exercise: a dump or a replica yields ciphertext."""
    stored = SecretBox((key,)).encrypt(TOKEN)

    assert TOKEN.encode() not in stored
    assert b"ghp_" not in stored


def test_encrypting_twice_gives_different_bytes(key: str) -> None:
    """Fernet includes a random IV. Identical tokens must not produce
    identical rows, or the database leaks which sources share a credential."""
    box = SecretBox((key,))

    assert box.encrypt(TOKEN) != box.encrypt(TOKEN)


def test_a_foreign_key_cannot_decrypt(key: str) -> None:
    stored = SecretBox((key,)).encrypt(TOKEN)
    someone_else = SecretBox((Fernet.generate_key().decode(),))

    with pytest.raises(DecryptionError):
        someone_else.decrypt(stored)


def test_corrupted_bytes_raise_rather_than_return_nothing(key: str) -> None:
    """A silently empty token becomes a confusing 401 from a vendor's API,
    hours later, in a worker log."""
    box = SecretBox((key,))

    with pytest.raises(DecryptionError):
        box.decrypt(b"not a fernet token at all")


def test_no_key_at_all_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one key"):
        SecretBox(())


# ── Rotation: the known weakness of this design, hence these tests ───────────


def test_an_old_key_still_decrypts_while_it_is_configured(key: str) -> None:
    old_box = SecretBox((key,))
    stored = old_box.encrypt(TOKEN)
    new_key = Fernet.generate_key().decode()

    # During rotation both keys are configured, new one first.
    rotating = SecretBox((new_key, key))

    assert rotating.decrypt(stored) == TOKEN


def test_the_new_key_alone_cannot_read_old_rows(key: str) -> None:
    """Why step 2 of the rotation exists. Dropping the old key before
    re-encrypting leaves rows nobody can read."""
    stored = SecretBox((key,)).encrypt(TOKEN)
    new_only = SecretBox((Fernet.generate_key().decode(),))

    with pytest.raises(DecryptionError):
        new_only.decrypt(stored)


def test_rotate_re_encrypts_with_the_primary_key(key: str) -> None:
    stored = SecretBox((key,)).encrypt(TOKEN)
    new_key = Fernet.generate_key().decode()
    rotating = SecretBox((new_key, key))

    rotated = rotating.rotate(stored)

    # The old key is now unnecessary: step 3 can drop it.
    assert SecretBox((new_key,)).decrypt(rotated) == TOKEN


def test_new_writes_use_the_first_key(key: str) -> None:
    new_key = Fernet.generate_key().decode()
    rotating = SecretBox((new_key, key))

    fresh = rotating.encrypt(TOKEN)

    assert SecretBox((new_key,)).decrypt(fresh) == TOKEN


def test_only_what_the_first_key_wrote_is_current(key: str) -> None:
    """What lets an interrupted rotation resume instead of starting over."""
    rotating = SecretBox((Fernet.generate_key().decode(), key))

    assert rotating.needs_rotation(SecretBox((key,)).encrypt(TOKEN)) is True
    assert rotating.needs_rotation(rotating.encrypt(TOKEN)) is False
    assert rotating.needs_rotation(b"not a fernet token at all") is True
