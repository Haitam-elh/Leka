"""Types the identity module exposes over its boundary.

Two things to notice, both security rather than style:

No response model anywhere carries a password, a hash, or a token. The
session token exists in exactly one place outside this process — the cookie
— and nothing serialises it.

Error codes are machine-readable so the interface can react, while the
messages stay deliberately uninformative to anyone probing. "Invalid email or
password" is the same sentence whether the address exists or not.
"""

from __future__ import annotations

import enum
import unicodedata
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from leka.core import languages
from leka.core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from leka.identity.models import CompanySize


class AuthErrorCode(enum.StrEnum):
    """What the interface needs to tell apart.

    A human-readable sentence is not enough for a UI that must show a
    "resend verification" button in one case and a countdown in another.
    These codes carry no information an attacker lacks: they are returned
    only for states the caller can already observe.
    """

    # The noqa markers below silence bandit's S105: it sees "TOKEN" and
    # "PASSWORD" in a name assigned a string literal and assumes a hardcoded
    # secret. These are error codes the API returns to a browser.
    INVALID_CREDENTIALS = "invalid_credentials"
    ACCOUNT_UNVERIFIED = "account_unverified"
    RATE_LIMITED = "rate_limited"
    TOKEN_INVALID = "token_invalid"  # noqa: S105
    TOKEN_EXPIRED = "token_expired"  # noqa: S105
    PASSWORD_TOO_SHORT = "password_too_short"  # noqa: S105
    PASSWORD_BREACHED = "password_breached"  # noqa: S105
    # Closing an account that is the last owner of a workspace others use.
    LAST_OWNER = "last_owner"
    NOT_AUTHENTICATED = "not_authenticated"
    SESSION_EXPIRED = "session_expired"


class AuthErrorResponse(BaseModel):
    """The body of every 4xx this module returns.

    A superset of FastAPI's default {"detail": ...}, so it does not change
    the shape LEKA-331's routes already return.
    """

    model_config = ConfigDict(frozen=True)

    detail: str
    code: AuthErrorCode


def _normalise_email(value: str) -> str:
    """Lower-case and trim.

    Without this, Nora@acme.com and nora@acme.com become two accounts, and
    the second person to register finds the address mysteriously taken.
    """
    candidate = value.strip().lower()
    local, separator, domain = candidate.partition("@")
    if not separator or not local or "." not in domain or domain.startswith("."):
        msg = f"{value!r} is not an email address"
        raise ValueError(msg)
    return candidate


class _EmailField(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return _normalise_email(value)


class _PasswordField(BaseModel):
    """Length only, per NIST SP 800-63B.

    No composition rules: demanding an uppercase and a digit produces
    Password1! and nothing stronger. The maximum exists only so that nobody
    can make us hash a megabyte, and we never truncate below it.
    """

    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


def _plain_text(value: str | None) -> str | None:
    """Trimmed, one line, no control character — or None when empty.

    A name travels into e-mails, the interface and an operator's terminal
    (`python -m leka.identity.admin accounts`): an escape sequence in it
    would be one typed by a stranger into someone else's screen.
    """
    if value is None:
        return None
    text = " ".join(value.split())
    if any(unicodedata.category(char) in ("Cc", "Cf") for char in text):
        msg = "control characters are not allowed"
        raise ValueError(msg)
    return text or None


class AccountProfile(BaseModel):
    """Who is registering, as the site's forms have always asked: first and
    last name and the company, required; the role and the company's size,
    if they want to say."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    company: str = Field(min_length=1, max_length=200)
    job_title: str | None = Field(default=None, max_length=100)
    company_size: CompanySize | None = None

    @field_validator("first_name", "last_name", "company", "job_title", mode="before")
    @classmethod
    def _text(cls, value: object) -> object:
        return _plain_text(value) if isinstance(value, str) else value


class _LanguageField(BaseModel):
    """The language the page was shown in, when the person is not known yet:
    the e-mail sent next is written in it, as far as e-mails are translated."""

    language: str | None = Field(default=None, max_length=35)

    @field_validator("language")
    @classmethod
    def _listed(cls, value: str | None) -> str | None:
        return languages.listed(value) if value is not None else None


class RegisterRequest(_EmailField, _PasswordField, AccountProfile, _LanguageField):
    """Registering keeps the language the form was shown in as the account's:
    the person saw it, and could change it, on that page."""


class ProfileUpdate(BaseModel):
    """What someone changes about themselves. Only the fields sent change.

    The three the form requires can be changed, never emptied; the role and
    the company size can be cleared with null. Accounts made before
    registration asked start with none, and this is how they get a name.
    """

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    company: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=100)
    company_size: CompanySize | None = None
    # A language LEKA offers, and a region; null clears the choice.
    language: str | None = Field(default=None, max_length=35)
    region: str | None = Field(default=None, max_length=2)

    @field_validator("first_name", "last_name", "company", "job_title", mode="before")
    @classmethod
    def _text(cls, value: object) -> object:
        return _plain_text(value) if isinstance(value, str) else value

    @field_validator("language")
    @classmethod
    def _language(cls, value: str | None) -> str | None:
        return languages.listed(value) if value is not None else None

    @field_validator("region")
    @classmethod
    def _region(cls, value: str | None) -> str | None:
        return languages.listed_region(value) if value is not None else None

    @model_validator(mode="after")
    def _required_stay_filled(self) -> ProfileUpdate:
        for name in ("first_name", "last_name", "company"):
            if name in self.model_fields_set and getattr(self, name) is None:
                msg = f"{name} can be changed, not emptied"
                raise ValueError(msg)
        return self


class LoginRequest(_EmailField):
    # Not length-validated: a wrong password of any length must be rejected
    # by the same path with the same message, never by a 422 that tells the
    # caller their guess was the wrong shape.
    password: str = Field(max_length=PASSWORD_MAX_LENGTH)
    # "Se souvenir de cet appareil". Unticked, the session ends when the
    # browser closes, and the server forgets it within hours; ticked, it
    # lasts as long as sessions do. See AuthService.open_session.
    remember: bool = False


class ForgotPasswordRequest(_EmailField, _LanguageField):
    """An address, and the language the page was shown in — for the e-mail
    of someone who never chose one."""


class ResetPasswordRequest(_PasswordField):
    token: str = Field(min_length=20, max_length=256)


class AccountDeletion(BaseModel):
    """Closing one's own account: the password again, as for any act that
    cannot be undone by the person who did it."""

    password: str = Field(max_length=PASSWORD_MAX_LENGTH)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class UserRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    email: str
    email_verified_at: datetime | None
    last_login_at: datetime | None
    # None for an account made before registration asked.
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    job_title: str | None = None
    company_size: CompanySize | None = None
    # None until chosen.
    language: str | None = None
    region: str | None = None


class SessionRead(BaseModel):
    """A session as its owner sees it, on the "your devices" screen.

    No token, not even hashed. Enough to recognise a device and revoke it,
    nothing that helps anyone impersonate it.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip_prefix: str | None
    is_current: bool = False


class WorkspaceMembershipRead(BaseModel):
    """A workspace this person may enter, and as what."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    slug: str
    role: str


class MeResponse(BaseModel):
    """Everything the interface needs after signing in.

    One call: who I am, where I may go, and where I currently am. Three
    round-trips for that would show as a flicker on every page load.
    """

    model_config = ConfigDict(frozen=True)

    user: UserRead
    workspaces: list[WorkspaceMembershipRead]
    active_workspace_id: uuid.UUID | None
    # The CSRF token of this session, for the interface to send back in the
    # X-CSRF-Token header. It is also in a cookie, but a host-only cookie of
    # the API's host: the page, served from leka-core.com, cannot read it.
    # Only the page's origin can read this body (CORS), which is what makes
    # the double submit hold — see leka/identity/csrf.py.
    csrf_token: str | None = None


class RegistrationAccepted(BaseModel):
    """The answer to registering, whether or not the address was free.

    Identical in both cases on purpose: a different response would turn the
    registration form into a way to ask "does this person have an account?".
    """

    model_config = ConfigDict(frozen=True)

    detail: str = "If that address can be registered, a verification email is on its way."


class RecoveryAccepted(BaseModel):
    """The answer to a forgotten-password request. Always the same."""

    model_config = ConfigDict(frozen=True)

    detail: str = "If an account exists for that address, a reset link is on its way."
