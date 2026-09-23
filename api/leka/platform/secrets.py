"""Encryption of credentials at rest.

A customer's GitHub token is the keys to their source code. It is encrypted
before it reaches the database, so a leaked backup, a stray pg_dump or a
misconfigured read replica yields ciphertext.

This is defence in depth, not a substitute for the rest: the key lives in the
environment, so anyone who can read the process environment can decrypt. What
it buys is that the database and the key are never in the same place — and a
database is copied far more often than an environment is.

See docs/adr/005-credential-storage.md.
"""

from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from leka.core.config import settings


class DecryptionError(RuntimeError):
    """A stored credential could not be decrypted with any configured key.

    Almost always one of two things: the key was rotated without keeping the
    old one, or the row was written by a different environment. Both are
    operational problems that must be loud, never a silently empty token.
    """


class SecretBox:
    """Encrypts and decrypts credentials.

    Takes several keys on purpose. The first encrypts; all of them are tried
    when decrypting. That is what makes key rotation possible without a
    flag day: add the new key at the front, deploy, re-encrypt existing rows
    with scripts/rotate_encryption_key.py, then drop the old key in a later
    deploy.

    A single key is the degenerate case and works the same way.
    """

    def __init__(self, keys: tuple[str, ...]) -> None:
        if not keys:
            msg = "SecretBox needs at least one key"
            raise ValueError(msg)
        fernets = [Fernet(key.encode()) for key in keys]
        self._primary = fernets[0]
        self._fernet = MultiFernet(fernets)
        self.key_count = len(keys)
        # Which key encrypts now, as something safe to store beside the
        # ciphertext: a truncated hash of a 256-bit random key says which
        # key it was and nothing about it. What a rotation, and an operator
        # checking one, compare against.
        self.key_version = hashlib.sha256(keys[0].encode()).hexdigest()[:12]

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt with the primary key."""
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, token: bytes) -> str:
        """Decrypt with whichever configured key wrote it."""
        try:
            return self._fernet.decrypt(token).decode()
        except InvalidToken as exc:
            msg = (
                "stored credential could not be decrypted with any configured "
                "key — was LEKA_ENCRYPTION_KEYS rotated without keeping the "
                "previous key?"
            )
            raise DecryptionError(msg) from exc

    def needs_rotation(self, token: bytes) -> bool:
        """Whether a stored value was written by anything but the primary key.

        Answered from the token's signature alone. Nothing is decrypted, so
        asking the question never puts a plaintext in memory. A token no
        configured key wrote needs rotation too, and rotate() says so loudly.
        """
        try:
            self._primary.extract_timestamp(token)
        except InvalidToken:
            return True
        return False

    def rotate(self, token: bytes) -> bytes:
        """Re-encrypt an existing value with the primary key.

        Used by scripts/rotate_encryption_key.py during a key rotation.
        Decrypting and re-encrypting would work too; this does it without the
        plaintext ever existing as a Python string.
        """
        try:
            return self._fernet.rotate(token)
        except InvalidToken as exc:
            msg = "stored credential could not be rotated: no configured key decrypts it"
            raise DecryptionError(msg) from exc


# Built at import, like the settings it reads: a malformed key must stop the
# process on startup, not on the first sync that needs a token.
secret_box: SecretBox = SecretBox(tuple(key.get_secret_value() for key in settings.encryption_keys))
