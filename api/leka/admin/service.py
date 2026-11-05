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

from leka.admin import audit
from leka.admin.access import AdminRole, permissions_of
from leka.admin.models import AdminAccount, AdminSession
from leka.admin.repository import AdminRepository
from leka.admin.schemas import AdminPrincipal
from leka.core.config import settings
from leka.core.security import (
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
    waste_time_like_a_real_verification,
)
from leka.db import session_factory

MIN_PASSWORD_LENGTH = 14


class AdminAuthError(Exception):
    """Not signed in. The reason is for the trail, never for the answer."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AdminAccountError(Exception):
    """An account that cannot be made as asked, said so an operator can act."""


class IdempotencyConflictError(Exception):
    """The key was used for another request, or that request is still running."""


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
            raise AdminAuthError("no_account" if account is None else "disabled")
        if account.locked_until is not None and account.locked_until > moment:
            waste_time_like_a_real_verification()
            raise AdminAuthError("locked")
        if not verify_password(password, account.password_hash):
            locked = await _count_failure(account.id, moment)
            raise AdminAuthError("locked_now" if locked else "wrong_password")

        if password_needs_rehash(account.password_hash):
            account.password_hash = hash_password(password)
        account.failed_sign_ins = 0
        account.locked_until = None
        account.last_sign_in_at = moment

        token = generate_token()
        row = AdminSession(
            id=uuid.uuid4(),
            admin_id=account.id,
            token_hash=hash_token(token),
            last_seen_at=moment,
            expires_at=moment + _lifetime(),
            user_agent=(user_agent or "")[:400] or None,
            ip_prefix=ip_prefix,
        )
        self._accounts.add(row)
        await self._accounts.flush()
        return SignedIn(account=account, session=row, token=token)

    async def resolve(
        self, token: str, *, ip_prefix: str | None = None, now: datetime | None = None
    ) -> AdminPrincipal | None:
        """Who a bearer token is, or None: unknown, revoked, expired, idle too
        long, or its admin disabled."""
        moment = now or datetime.now(UTC)
        found = await self._accounts.live_session(hash_token(token), moment)
        if found is None:
            return None
        row, account = found
        if row.last_seen_at + _idle() <= moment:
            return None
        # Written at most once a minute: a screen polling would otherwise
        # write a row on every call.
        if moment - row.last_seen_at > timedelta(minutes=1):
            await self._session.execute(
                update(AdminSession).where(AdminSession.id == row.id).values(last_seen_at=moment)
            )
        return AdminPrincipal(
            admin_id=account.id,
            email=account.email,
            name=account.name,
            role=AdminRole(account.role),
            permissions=permissions_of(account.role),
            session_id=row.id,
            ip_prefix=ip_prefix,
        )

    async def sign_out(self, principal: AdminPrincipal, *, now: datetime | None = None) -> None:
        await self._accounts.revoke(principal.session_id, now or datetime.now(UTC))


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
