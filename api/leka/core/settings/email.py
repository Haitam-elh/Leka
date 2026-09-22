"""How verification and recovery messages leave the building.

With nothing configured the console sender is used and messages go to the
log, which is what makes those flows testable without an account anywhere.
"""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator

from leka.core.settings._blank import blank_is_none


class EmailSettings:
    """SMTP for a mailbox we already pay for, or an API provider."""

    email_from: str = "LEKA <no-reply@leka.example>"

    # SMTP is preferred over an API provider when both are configured: one
    # fewer account, one fewer bill.
    #
    # OVH: ssl0.ovh.net, port 465, SSL/TLS, username = the full address.
    smtp_host: str | None = None
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    # True for port 465 (implicit TLS), False for 587 (STARTTLS).
    smtp_use_ssl: bool = True

    resend_api_key: SecretStr | None = None

    @field_validator("smtp_host", "smtp_username", "smtp_password", "resend_api_key", mode="before")
    @classmethod
    def _blank_email_field_is_not_configured(cls, value: object) -> object:
        """A blank LEKA_SMTP_HOST means "no SMTP", not a host called "".

        Otherwise the sender selection picks SMTP and every message fails
        against an empty address. See core/settings/_blank.py.
        """
        return blank_is_none(value)

    @property
    def smtp_configured(self) -> bool:
        return self.smtp_host is not None and self.smtp_password is not None

    @property
    def sends_real_email(self) -> bool:
        return self.smtp_configured or self.resend_api_key is not None


__all__ = ["EmailSettings"]
