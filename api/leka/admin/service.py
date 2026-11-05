"""Signing LEKA's team in, and doing a sensitive operation once (LEKA-544).

No FastAPI here: the rules, over repositories, testable as they are.

SIGNING IN follows the customers' rules (leka/identity/service.py) and adds
a lock, because an admin account opens every customer:
- one answer for every failure — unknown address, wrong password, disabled
  or locked account — and the same work spent on each, so nothing tells an
  outsider which address is an admin's;
- five wrong passwords in a row lock the account for fifteen minutes
  (settings: admin_sign_in_attempts, admin_lockout_minutes), counted apart
  from the request so a refusal cannot roll the count back;
- a new session at each sign-in, its token hashed at rest, ending after a
  working day or two idle hours.

RENEWING (LEKA-546) gives the device a new token and ends the old one; the
session keeps its end, so renewing never makes it last longer than the
working day it was opened for. The old token still works for thirty seconds,
for the calls that left with it. Shown again after that, it is someone
else's copy, or a device that lost the new one: every session of that
device ends, and the trail says so (`admin.session_reused`).

ONCE: a sensitive operation (suspending an organisation, adding credits)
carries an `Idempotency-Key`. Its answer is kept under that key: the same
request sent again — a retry on a bad network — gets the same answer and
does nothing; the same key with another request is refused.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin import audit, codes
from leka.admin.access import AdminPermission, AdminRole, granted
from leka.admin.models import AdminAccount, AdminCode, AdminSession
from leka.admin.repository import AdminRepository
from leka.admin.schemas import AdminPrincipal
from leka.core.config import settings
from leka.core.security import (
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    tokens_match,
    verify_password,
    waste_time_like_a_real_verification,
)
from leka.db import session_factory
from leka.identity import EmailSender, password_is_breached

MIN_PASSWORD_LENGTH = 14


class AdminAuthError(Exception):
    """Not signed in. The reason is for the trail, never for the answer."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AdminAccountError(Exception):
    """An account that cannot be made as asked, said so an operator can act."""


class CodeError(Exception):
    """A code that is not one, or no longer: one answer, whatever the cause."""


class PasswordRefusedError(Exception):
    """A new password LEKA will not take; the reason is safe to show."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class IdempotencyConflictError(Exception):
    """The key was used for another request, or that request is still running."""


class RenewalError(Exception):
    """This session was renewed already: the new token is the one to use."""


# How long a renewed token still opens LEKA ADMIN: the calls that left with
# it come back, and only after that is it a copy.
RENEWAL_GRACE = timedelta(seconds=30)


@dataclass(frozen=True)
class SignedIn:
    account: AdminAccount
    session: AdminSession
    token: str


def _lifetime() -> timedelta:
    return timedelta(hours=settings.admin_session_lifetime_hours)


def _idle() -> timedelta:
    return timedelta(minutes=settings.admin_session_idle_minutes)


async def _count_failure(account_id: uuid.UUID, now: datetime) -> bool:
    """One more wrong password, committed apart. True: the account is locked now."""
    async with session_factory() as session:
        account = await session.get(AdminAccount, account_id, with_for_update=True)
        if account is None:
            return False
        account.failed_sign_ins += 1
        locked = account.failed_sign_ins >= settings.admin_sign_in_attempts
        if locked:
            account.locked_until = now + timedelta(minutes=settings.admin_lockout_minutes)
            account.failed_sign_ins = 0
        await session.commit()
        return locked


class AdminAuth:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._accounts = AdminRepository(session)

    async def sign_in(
        self,
        email: str,
        password: str,
        *,
        user_agent: str | None = None,
        ip_prefix: str | None = None,
        now: datetime | None = None,
    ) -> SignedIn:
        moment = now or datetime.now(UTC)
        account = await self._accounts.account_by_email(email)
        if account is None or account.status != "active":
            waste_time_like_a_real_verification()
            raise AdminAuthError("no_account" if account is None else account.status)
        if account.locked_until is not None and account.locked_until > moment:
            waste_time_like_a_real_verification()
            raise AdminAuthError("locked")
        if account.password_hash is None or not verify_password(password, account.password_hash):
            locked = await _count_failure(account.id, moment)
            raise AdminAuthError("locked_now" if locked else "wrong_password")

        if password_needs_rehash(account.password_hash):
            account.password_hash = hash_password(password)
        account.failed_sign_ins = 0
        account.locked_until = None
        account.last_sign_in_at = moment

        token = generate_token()
        first = uuid.uuid4()
        row = AdminSession(
            id=first,
            admin_id=account.id,
            token_hash=hash_token(token),
            family_id=first,
            signed_in_at=moment,
            last_seen_at=moment,
            expires_at=moment + _lifetime(),
            user_agent=(user_agent or "")[:400] or None,
            ip_prefix=ip_prefix,
        )
        self._accounts.add(row)
        await self._accounts.flush()
        return SignedIn(account=account, session=row, token=token)

    async def _principal(
        self,
        row: AdminSession,
        account: AdminAccount,
        ip_prefix: str | None,
        *,
        renewable: bool = True,
    ) -> AdminPrincipal:
        return AdminPrincipal(
            admin_id=account.id,
            email=account.email,
            name=account.name,
            role=AdminRole(account.role),
            # Read now: a role the Super Admin changes is changed at the
            # next request, not at the next sign-in (LEKA-545).
            permissions=granted(account.role, await self._accounts.role_permissions(account.role)),
            session_id=row.id,
            ip_prefix=ip_prefix,
            renewable=renewable,
        )

    async def _renewed_token(
        self, token_hash: str, ip_prefix: str | None, moment: datetime
    ) -> AdminPrincipal | None:
        """A token that is no longer live: within its grace after a renewal,
        still its session; a renewed token after that, a copy, and its
        device's sessions end."""
        found = await self._accounts.session_by_token(token_hash)
        if found is None:
            return None
        row, account = found
        if row.ended_reason != "renewed" or row.revoked_at is None:
            return None
        if moment - row.revoked_at <= RENEWAL_GRACE:
            if (
                account.status != "active"
                or row.expires_at <= moment
                or row.last_seen_at + _idle() <= moment
            ):
                return None
            return await self._principal(row, account, ip_prefix, renewable=False)
        ended = await _end_family(row.family_id, moment)
        await audit.apart(
            "admin.session_reused",
            admin_id=account.id,
            admin_email=account.email,
            target_type="admin_session",
            target_id=str(row.id),
            ip_prefix=ip_prefix,
            session_id=row.id,
            detail={"family": str(row.family_id), "sessions_ended": ended},
        )
        return None

    async def resolve(
        self, token: str, *, ip_prefix: str | None = None, now: datetime | None = None
    ) -> AdminPrincipal | None:
        """Who a bearer token is, or None: unknown, revoked, expired, idle too
        long, or its admin disabled."""
        moment = now or datetime.now(UTC)
        found = await self._accounts.live_session(hash_token(token), moment)
        if found is None:
            return await self._renewed_token(hash_token(token), ip_prefix, moment)
        row, account = found
        if row.last_seen_at + _idle() <= moment:
            return None
        # Written at most once a minute: a screen polling would otherwise
        # write a row on every call.
        if moment - row.last_seen_at > timedelta(minutes=1):
            await self._session.execute(
                update(AdminSession).where(AdminSession.id == row.id).values(last_seen_at=moment)
            )
        return await self._principal(row, account, ip_prefix)

    async def sign_out(self, principal: AdminPrincipal, *, now: datetime | None = None) -> None:
        await self._accounts.revoke(principal.session_id, now or datetime.now(UTC), "signed_out")

    async def renew(
        self,
        principal: AdminPrincipal,
        *,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> SignedIn:
        """A new token for this device's session, the old one ended; the
        same end. Once per token: a second renewal of it is refused."""
        moment = now or datetime.now(UTC)
        if not principal.renewable:
            raise RenewalError
        if not await self._accounts.revoke(principal.session_id, moment, "renewed"):
            raise RenewalError
        current = await self._session.get(AdminSession, principal.session_id)
        account = await self._accounts.account(principal.admin_id)
        if current is None or account is None:
            raise RenewalError
        token = generate_token()
        row = AdminSession(
            id=uuid.uuid4(),
            admin_id=account.id,
            token_hash=hash_token(token),
            family_id=current.family_id,
            signed_in_at=current.signed_in_at,
            last_seen_at=moment,
            expires_at=current.expires_at,
            user_agent=(user_agent or "")[:400] or current.user_agent,
            ip_prefix=principal.ip_prefix,
        )
        self._accounts.add(row)
        await self._accounts.flush()
        return SignedIn(account=account, session=row, token=token)

    async def sessions(
        self, principal: AdminPrincipal, *, now: datetime | None = None
    ) -> list[AdminSession]:
        """The admin's devices signed in now, the last used first."""
        moment = now or datetime.now(UTC)
        return await self._accounts.open_sessions(principal.admin_id, moment, moment - _idle())

    async def end_session(
        self, principal: AdminPrincipal, session_id: uuid.UUID, *, now: datetime | None = None
    ) -> bool:
        """Close one of the admin's own sessions — another device, or this
        one. False: no open session of theirs has this id."""
        row = await self._session.get(AdminSession, session_id)
        if row is None or row.admin_id != principal.admin_id:
            return False
        reason = "signed_out" if session_id == principal.session_id else "ended_by_self"
        return await self._accounts.revoke(session_id, now or datetime.now(UTC), reason)


async def _end_family(family_id: uuid.UUID, now: datetime) -> int:
    """A device's sessions, ended apart from the request: it is refused and
    rolled back, and they must end all the same."""
    async with session_factory() as session:
        ended = await AdminRepository(session).revoke_family(family_id, now, "reused")
        await session.commit()
        return ended


async def permissions_now(session: AsyncSession, role: str) -> frozenset[AdminPermission]:
    """What a role grants now, as the Super Admin left it (LEKA-545)."""
    return granted(role, await AdminRepository(session).role_permissions(role))


async def create_account(
    session: AsyncSession,
    *,
    email: str,
    name: str,
    role: str,
    password: str,
    by: str,
) -> AdminAccount:
    """An admin account, from the server (python -m leka.admin.cli create)."""
    address = email.strip().lower()
    if "@" not in address:
        raise AdminAccountError(f"{email!r} is not an email address.")
    if role not in {r.value for r in AdminRole}:
        raise AdminAccountError(
            f"Unknown role {role!r}: one of {', '.join(r.value for r in AdminRole)}."
        )
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AdminAccountError(f"A password of {MIN_PASSWORD_LENGTH} characters at least.")
    accounts = AdminRepository(session)
    if await accounts.account_by_email(address) is not None:
        raise AdminAccountError(f"{address} is already an admin.")
    account = AdminAccount(
        id=uuid.uuid4(),
        email=address,
        name=name.strip()[:120] or address,
        password_hash=hash_password(password),
        role=role,
        status="active",
        failed_sign_ins=0,
        created_by=by[:320],
    )
    accounts.add(account)
    await accounts.flush()
    audit.record(
        session,
        "admin.account_created",
        admin_id=None,
        admin_email=by[:320],
        target_type="admin",
        target_id=account.id,
        detail={"email": address, "role": role},
    )
    return account


def fingerprint(route: str, body: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps({"route": route, "body": body}, sort_keys=True, default=str).encode()
    ).hexdigest()


async def once(
    session: AsyncSession,
    principal: AdminPrincipal,
    key: str,
    route: str,
    body: dict[str, object],
    run: Callable[[], Awaitable[tuple[int, dict[str, object]]]],
) -> tuple[int, dict[str, object], bool]:
    """Run a sensitive operation once per key. Returns its status, its answer,
    and whether it was replayed rather than run."""
    keys = AdminRepository(session)
    print_ = fingerprint(route, body)
    if not await keys.claim_key(principal.admin_id, key, route, print_):
        kept = await keys.key(principal.admin_id, key)
        if kept is None or kept.fingerprint != print_:
            raise IdempotencyConflictError("This Idempotency-Key was used for another request.")
        if kept.status_code == 0:
            raise IdempotencyConflictError("A request with this Idempotency-Key is still running.")
        return kept.status_code, dict(kept.response), True
    status_code, answer = await run()
    await keys.answer_key(principal.admin_id, key, status_code, answer)
    return status_code, answer, False


# ── Passwords: forgotten, chosen with a code, changed (LEKA-545) ─────────────


async def issue_code(
    session: AsyncSession, account: AdminAccount, purpose: str, now: datetime
) -> str:
    """A new code for this purpose; the one sent before stops working."""
    accounts = AdminRepository(session)
    await accounts.drop_codes(account.id, purpose)
    code = codes.new_code()
    accounts.add(
        AdminCode(
            id=uuid.uuid4(),
            admin_id=account.id,
            purpose=purpose,
            code_hash=hash_token(code),
            expires_at=now + codes.LIFETIME[purpose],
            attempts=0,
        )
    )
    await accounts.flush()
    return code


async def forgot_password(
    session: AsyncSession, email: str, sender: EmailSender, *, now: datetime | None = None
) -> bool:
    """A reset code to an active admin's address. True if one was sent —
    for the trail only: the caller answers the same either way."""
    moment = now or datetime.now(UTC)
    account = await AdminRepository(session).account_by_email(email)
    if account is None or account.status != "active":
        return False
    code = await issue_code(session, account, "reset", moment)
    await sender.send(codes.reset(account.email, account.name, code))
    return True


async def _count_wrong_code(code_id: uuid.UUID, now: datetime) -> None:
    """One more wrong try, committed apart (the request is refused and rolled
    back); the fifth burns the code. One atomic update each: no lock held
    while the request waits."""
    async with session_factory() as session:
        tries = await session.scalar(
            update(AdminCode)
            .where(AdminCode.id == code_id)
            .values(attempts=AdminCode.attempts + 1)
            .returning(AdminCode.attempts)
        )
        if tries is not None and tries >= codes.MAX_ATTEMPTS:
            await session.execute(
                update(AdminCode)
                .where(AdminCode.id == code_id, AdminCode.consumed_at.is_(None))
                .values(consumed_at=now)
            )
        await session.commit()


async def _acceptable(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordRefusedError(f"A password of {MIN_PASSWORD_LENGTH} characters at least.")
    if await password_is_breached(password):
        raise PasswordRefusedError("This password appears in known breaches: choose another one.")


async def redeem_code(
    session: AsyncSession, email: str, typed: str, password: str, *, now: datetime | None = None
) -> AdminAccount:
    """The code sent to this address, and the password chosen with it: an
    invited admin becomes active, a forgotten password is replaced, and every
    session of the account ends."""
    moment = now or datetime.now(UTC)
    accounts = AdminRepository(session)
    account = await accounts.account_by_email(email)
    if account is None or account.status == "disabled":
        raise CodeError
    row = await accounts.live_code(account.id, moment)
    if row is None:
        raise CodeError
    if not tokens_match(codes.normalised(typed), row.code_hash):
        await _count_wrong_code(row.id, moment)
        raise CodeError
    await _acceptable(password)
    if not await accounts.consume_code(row.id, moment):
        raise CodeError
    account.password_hash = hash_password(password)
    account.status = "active"
    account.failed_sign_ins = 0
    account.locked_until = None
    await accounts.revoke_all(account.id, moment, "password")
    await accounts.flush()
    return account


async def change_password(
    session: AsyncSession,
    principal: AdminPrincipal,
    current: str,
    password: str,
    *,
    now: datetime | None = None,
) -> int:
    """A signed-in admin's new password; their other sessions end. Returns
    how many ended."""
    moment = now or datetime.now(UTC)
    accounts = AdminRepository(session)
    account = await accounts.account(principal.admin_id)
    if account is None or account.password_hash is None:
        raise AdminAuthError("no_account")
    if not verify_password(current, account.password_hash):
        await _count_failure(account.id, moment)
        raise AdminAuthError("wrong_password")
    await _acceptable(password)
    account.password_hash = hash_password(password)
    return await accounts.revoke_others(account.id, principal.session_id, moment, "password")
