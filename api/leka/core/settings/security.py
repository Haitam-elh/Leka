"""Keys, sessions and cookies: what protects a person's account.

Two secrets live here and they do different jobs. `secret_key` is the root
of every signature the server hands a client and expects back — today, a
pagination cursor. Sessions are not signed: they are random tokens, stored
hashed. `encryption_keys` encrypt customers' credentials at rest, and are a
tuple because rotation needs the old key readable while the new one writes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, field_validator


class SecuritySettings:
    """Signing, encryption, session lifetimes, cookie flags."""

    secret_key: SecretStr = Field(
        description=(
            "Root of every signature the server hands to a client. Read by "
            "leka.core.signing alone, which derives a key per purpose from it."
        ),
    )
    encryption_keys: tuple[SecretStr, ...] = Field(
        min_length=1,
        description=(
            "Fernet keys for credentials at rest. The FIRST encrypts; all of "
            "them are tried when decrypting, which is what makes rotation "
            "possible without a flag day. Generate one with: python -c "
            '"from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        ),
    )

    # Two limits, not one. A session dies at the absolute maximum whatever
    # happens, and at the idle timeout if unused. Both matter: the first
    # bounds a stolen cookie's usefulness, the second closes the laptop
    # someone left in a cafe.
    session_absolute_lifetime_days: int = Field(default=30, ge=1, le=365)
    session_idle_lifetime_days: int = Field(default=7, ge=1, le=90)

    verification_token_lifetime_hours: int = Field(default=24, ge=1, le=168)
    # Deliberately short. A reset link sits in an inbox, which is the least
    # trustworthy place a credential can wait.
    reset_token_lifetime_hours: int = Field(default=1, ge=1, le=24)

    session_cookie_name: str = "leka_session"
    # Sent over HTTPS only. False is for local development and nothing else —
    # a startup check in core/config.py refuses it in production.
    session_cookie_secure: bool = True
    # "lax" gives CSRF protection for free, because every mutation we serve
    # is POST, PATCH or DELETE. "none" gives that up and is only needed when
    # the frontend and the API do not share a parent domain. See
    # docs/adr/009-cookie-strategy.md.
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # Check new passwords against known breaches via HaveIBeenPwned, using
    # k-anonymity — only the first five characters of the hash are sent, and
    # the password never leaves this process. Off by default: it is a network
    # call, and tests must not depend on one.
    check_passwords_against_breaches: bool = False

    @field_validator("encryption_keys")
    @classmethod
    def _keys_are_usable(cls, value: tuple[SecretStr, ...]) -> tuple[SecretStr, ...]:
        """Reject a malformed Fernet key at startup.

        Fernet only complains when it is first used, which would be the first
        sync of the first connector — long after deploy, and in a worker log
        nobody is watching.
        """
        from cryptography.fernet import Fernet

        for index, key in enumerate(value):
            try:
                Fernet(key.get_secret_value().encode())
            except (ValueError, TypeError) as exc:
                msg = (
                    f"LEKA_ENCRYPTION_KEYS[{index}] is not a valid Fernet key "
                    "(32 url-safe base64-encoded bytes)"
                )
                raise ValueError(msg) from exc
        return value


__all__ = ["SecuritySettings"]
