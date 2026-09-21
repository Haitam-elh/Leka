"""Authentication flows.

The rules that decide whether someone gets in. Everything here is pure
business logic over repositories — no FastAPI, no cookies, no HTTP status
codes — so each rule can be tested directly.

Three things run through the whole file and are worth stating once:

**No account enumeration.** Registering an address that is taken, asking to
reset a password for an address that does not exist, and signing in with an
unknown email all return exactly what the successful case returns. A
difference of any kind — message, status, or response time — turns a public
form into a way to ask "does this person have an account here?".

**Timing counts as a difference.** The unknown-email path of login runs a
real argon2 verification against a dummy hash. Without it, "no such user"
answers in microseconds and "wrong password" in fifty milliseconds, which is
trivially measurable from anywhere in the world.

**Tokens are hashed at rest.** Sessions, verification links and reset links
all. A leaked backup is not a set of usable credentials.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import structlog

from leka.core.config import settings
from leka.core.security import (
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
    waste_time_like_a_real_verification,
)
from leka.identity.email import EmailMessage, EmailSender
from leka.identity.models import EmailToken, Session, TokenPurpose, User
from leka.identity.repository import (
    EmailTokenRepository,
    SessionRepository,
    UserRepository,
)

logger = structlog.get_logger(__name__)

HIBP_RANGE_ENDPOINT = "https://api.pwnedpasswords.com/range"


class AuthenticationError(Exception):
    """Sign-in refused. The reason is for us; the caller gets one message."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AccountUnverifiedError(Exception):
    """Correct password, unproven address.

    Distinguishable from a wrong password on purpose: the person has already
    demonstrated they own the account, so telling them to check their inbox
    reveals nothing they do not know, and not telling them is a dead end.
    """


class PasswordRejectedError(Exception):
    """The proposed password cannot be used."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LoginResult:
    user: User
    session: Session
    # Returned once, to be put in a cookie. Never stored, never logged.
    token: str


def truncate_ip(raw: str | None) -> str | None:
    """Reduce an address to a network prefix before storing it.

    /24 for IPv4, /48 for IPv6. A full address is personal data under GDPR
    and we have no use for one: the question this answers is "was this
    roughly the same network", not "where exactly were you".
    """
    if not raw:
        return None
    address = raw.split(",")[0].strip()
    if ":" in address:
        parts = address.split(":")
        return ":".join(parts[:3]) + "::/48"
    parts = address.split(".")
    if len(parts) != 4:
        return None
    return ".".join([*parts[:3], "0"]) + "/24"


async def password_is_breached(password: str) -> bool:
    """Ask HaveIBeenPwned whether this password appears in a known breach.

    k-anonymity: only the first five characters of the SHA-1 hash are sent,
    and the service answers with every suffix it knows for that prefix. The
    password itself never leaves this process, and the provider cannot tell
    which of the returned hashes we were asking about.

    Off by default — it is a network call, and a test suite that depends on
    one is a test suite that fails when someone else's service is down.
    """
    if not settings.check_passwords_against_breaches:
        return False

    digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{HIBP_RANGE_ENDPOINT}/{prefix}")
            response.raise_for_status()
    except httpx.HTTPError as error:
        # Fail open, deliberately. Refusing every registration because a
        # third-party service is unreachable is a worse outcome than
        # accepting a password that might be in a list.
        logger.warning("breach_check_unavailable", error=str(error))
        return False

    return any(line.split(":")[0] == suffix for line in response.text.splitlines())


class AuthService:
    """Registration, sign-in, sessions, verification and recovery."""

    def __init__(
        self,
        users: UserRepository,
        sessions: SessionRepository,
        tokens: EmailTokenRepository,
        email: EmailSender,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._tokens = tokens
        self._email = email

    # ── Registration and verification ────────────────────────────────────────

    async def register(self, email: str, password: str) -> None:
        """Create an account, or pretend to.

        Returns nothing in both cases, and the route answers identically.
        When the address is already registered we email its owner instead —
        which is both the safe response and the useful one: if it was them,
        they learn they already have an account; if it was not, they learn
        someone is poking at their address.
        """
        await self._reject_unusable_password(password)

        existing = await self._users.get_by_email(email)
        if existing is not None:
            await self._email.send(
                EmailMessage(
                    to=email,
                    subject="Someone tried to create a LEKA account with your address",
                    body=(
                        "If this was you, you already have an account — sign in, "
                        "or use the forgotten-password link. If it was not, you "
                        "do not need to do anything: no account was created and "
                        "nothing changed."
                    ),
                )
            )
            return

        user = User(email=email, password_hash=hash_password(password))
        self._users.add(user)
        await self._users.flush()
        await self._issue_verification(user)

    async def resend_verification(self, email: str) -> None:
        """Send another verification link, or do nothing. Same answer either way."""
        user = await self._users.get_by_email(email)
        if user is None or user.is_verified:
            return
        await self._issue_verification(user)

    async def _issue_verification(self, user: User) -> None:
        # Any outstanding link dies: two live links means the older one,
        # possibly forwarded, still works.
        await self._tokens.invalidate_outstanding(user.id, TokenPurpose.VERIFICATION)
        token = generate_token()
        self._tokens.add(
            EmailToken(
                user_id=user.id,
                token_hash=hash_token(token),
                purpose=TokenPurpose.VERIFICATION,
                expires_at=datetime.now(UTC)
                + timedelta(hours=settings.verification_token_lifetime_hours),
            )
        )
        await self._tokens.flush()
        await self._email.send(
            EmailMessage(
                to=user.email,
                subject="Confirm your LEKA address",
                body=(
                    "Confirm your address to finish setting up your account:\n\n"
                    f"  /auth/verify/{token}\n\n"
                    f"The link works for {settings.verification_token_lifetime_hours} "
                    "hours and once only."
                ),
            )
        )

    async def verify_email(self, token: str) -> User:
        """Consume a verification token."""
        stored = await self._consume(token, TokenPurpose.VERIFICATION)
        user = await self._users.get(stored.user_id)
        if user is None:  # pragma: no cover - cascade makes this unreachable
            msg = "token belongs to no account"
            raise AuthenticationError(msg)
        if not user.is_verified:
            user.email_verified_at = datetime.now(UTC)
        return user

    # ── Signing in ───────────────────────────────────────────────────────────

    async def login(
        self,
        email: str,
        password: str,
        *,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> LoginResult:
        """Verify credentials and open a new session.

        A NEW session, always. Reusing an identifier that existed before
        authentication is session fixation: an attacker who can set a cookie
        before you sign in then holds one that is valid after.
        """
        user = await self._users.get_by_email(email)

        if user is None or not user.can_sign_in_with_password:
            # Spend the same work as a real verification. This is the whole
            # defence against timing-based account enumeration.
            waste_time_like_a_real_verification()
            msg = "no account, or no password set"
            raise AuthenticationError(msg)

        assert user.password_hash is not None
        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            msg = "wrong password"
            raise AuthenticationError(msg)

        if not user.is_verified:
            raise AccountUnverifiedError

        # The one moment we hold the clear password and can silently upgrade
        # a hash made with older parameters.
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        user.failed_login_count = 0
        user.last_login_at = datetime.now(UTC)
        return await self.open_session(user, user_agent=user_agent, ip=ip)

    async def open_session(
        self, user: User, *, user_agent: str | None = None, ip: str | None = None
    ) -> LoginResult:
        token = generate_token()
        now = datetime.now(UTC)
        session = Session(
            user_id=user.id,
            token_hash=hash_token(token),
            last_seen_at=now,
            expires_at=now + timedelta(days=settings.session_absolute_lifetime_days),
            user_agent=(user_agent or "")[:400] or None,
            ip_prefix=truncate_ip(ip),
        )
        self._sessions.add(session)
        await self._sessions.flush()
        return LoginResult(user=user, session=session, token=token)

    async def logout(self, session: Session) -> None:
        await self._sessions.revoke(session)

    async def logout_everywhere(self, user: User, *, keep: uuid.UUID | None = None) -> int:
        return await self._sessions.revoke_all_for_user(user.id, except_session_id=keep)

    # ── Passwords ────────────────────────────────────────────────────────────

    async def request_password_reset(self, email: str) -> None:
        """Send a reset link, or do nothing. The caller cannot tell which."""
        user = await self._users.get_by_email(email)
        if user is None:
            return

        await self._tokens.invalidate_outstanding(user.id, TokenPurpose.RESET)
        token = generate_token()
        self._tokens.add(
            EmailToken(
                user_id=user.id,
                token_hash=hash_token(token),
                purpose=TokenPurpose.RESET,
                expires_at=datetime.now(UTC) + timedelta(hours=settings.reset_token_lifetime_hours),
            )
        )
        await self._tokens.flush()
        await self._email.send(
            EmailMessage(
                to=user.email,
                subject="Reset your LEKA password",
                body=(
                    "Someone asked to reset the password for this address.\n\n"
                    f"  /auth/password/reset?token={token}\n\n"
                    f"The link works for {settings.reset_token_lifetime_hours} hour(s) "
                    "and once only. If it was not you, nothing has changed and you "
                    "can ignore this message."
                ),
            )
        )

    async def reset_password(self, token: str, new_password: str) -> User:
        """Set a new password from a reset link.

        Every other session is revoked. If the reason for the reset was that
        someone else had the old password, leaving their sessions alive would
        make the reset pointless.
        """
        await self._reject_unusable_password(new_password)
        stored = await self._consume(token, TokenPurpose.RESET)
        user = await self._users.get(stored.user_id)
        if user is None:  # pragma: no cover
            msg = "token belongs to no account"
            raise AuthenticationError(msg)

        await self._apply_new_password(user, new_password)
        await self._sessions.revoke_all_for_user(user.id)
        return user

    async def change_password(
        self, user: User, current_password: str, new_password: str, *, keep: uuid.UUID
    ) -> None:
        """Change a password while signed in.

        Revokes every OTHER session and keeps this one: signing someone out
        of the browser they are currently using, as a reward for improving
        their security, teaches them not to.
        """
        if not user.can_sign_in_with_password or not verify_password(
            current_password, user.password_hash or ""
        ):
            msg = "current password does not match"
            raise AuthenticationError(msg)

        await self._reject_unusable_password(new_password)
        await self._apply_new_password(user, new_password)
        await self._sessions.revoke_all_for_user(user.id, except_session_id=keep)

    async def _apply_new_password(self, user: User, password: str) -> None:
        user.password_hash = hash_password(password)
        user.password_changed_at = datetime.now(UTC)
        user.failed_login_count = 0
        # Any pending reset link dies with the change: a link still sitting in
        # an inbox must not undo what just happened.
        await self._tokens.invalidate_outstanding(user.id, TokenPurpose.RESET)

    async def _reject_unusable_password(self, password: str) -> None:
        if await password_is_breached(password):
            msg = (
                "This password appears in a known data breach. Choose one you "
                "have not used elsewhere."
            )
            raise PasswordRejectedError(msg)

    # ── Tokens ───────────────────────────────────────────────────────────────

    async def _consume(self, token: str, purpose: TokenPurpose) -> EmailToken:
        """Spend a one-time token, or refuse.

        One exception for "never existed", "already used", "expired" and
        "wrong kind": telling them apart lets someone probe for live tokens.
        The distinction is logged, where only we can read it.

        The decision comes from a conditional UPDATE, not from a read
        followed by a check. Two concurrent requests carrying the same token
        can no longer both succeed: the database serialises them on the row
        and only one of them finds anything left to spend.
        """
        token_hash = hash_token(token)
        stored = await self._tokens.consume(token_hash, purpose)
        if stored is not None:
            return stored

        # The refusal is already settled. This second read only decides what
        # to write in the log, so it can no longer open a window.
        await self._log_rejection(token_hash, purpose)
        msg = "invalid token"
        raise AuthenticationError(msg)

    async def _log_rejection(self, token_hash: str, purpose: TokenPurpose) -> None:
        """Say in the log why a token was refused.

        The caller was told nothing beyond "invalid", which is deliberate.
        We still want the four reasons apart when reading our own logs: a
        burst of "expired" is a link people click too late, a burst of
        "unknown" is someone guessing.
        """
        stored = await self._tokens.get_by_token_hash(token_hash)
        if stored is None:
            reason = "unknown"
        elif stored.purpose is not purpose:
            reason = "wrong_purpose"
        elif stored.consumed_at is not None:
            reason = "already_used"
        elif stored.expires_at <= datetime.now(UTC):
            reason = "expired"
        else:
            # The UPDATE matched nothing, yet the row now looks spendable.
            # Only a concurrent request can produce that, and naming it is
            # more useful than pretending it was one of the four above.
            reason = "lost_race"
        logger.info("token_rejected", purpose=purpose.value, reason=reason)
