"""LEKA's team, managed by its Super Admins (LEKA-545).

Who may open LEKA ADMIN and with which role, and what each role may do:
the Super Admin's, from the app, instead of the server's shell.

  invite       an account for an address, with a role: an email carries a
               code to choose the password (leka/admin/codes.py)
  change       a name, a role, active or disabled; disabling ends every
               session at once
  sign out     every session of an admin, now
  roles        what each role grants; a Super Admin's own never changes

Three things no Super Admin can do, so nobody locks LEKA's team out:
change their own role or status (another Super Admin does it), leave the
team without an active Super Admin, or give a role what only a Super Admin
may do (leka/admin/access.py SUPER_ADMIN_ONLY).

Every change is kept in the admin trail, before and after.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin import audit, codes
from leka.admin.access import (
    GRANTABLE,
    PERMISSION_INFO,
    SUPER_ADMIN_ONLY,
    AdminPermission,
    AdminRole,
    granted,
)
from leka.admin.models import AdminAccount
from leka.admin.repository import AdminRepository
from leka.admin.schemas import (
    AdminPermissionRead,
    AdminPrincipal,
    AdminRead,
    AdminRoleRead,
    AdminRolesRead,
)
from leka.admin.service import issue_code
from leka.identity import EmailSender


class TeamError(Exception):
    """Refused, with the HTTP status that says why."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _read(account: AdminAccount, sessions: dict[uuid.UUID, int]) -> AdminRead:
    return AdminRead(
        id=account.id,
        email=account.email,
        name=account.name,
        role=AdminRole(account.role),
        status=cast(Literal["invited", "active", "disabled"], account.status),
        last_sign_in_at=account.last_sign_in_at,
        locked_until=account.locked_until,
        created_at=account.created_at,
        created_by=account.created_by,
        sessions=sessions.get(account.id, 0),
    )


async def members(session: AsyncSession, *, now: datetime | None = None) -> list[AdminRead]:
    accounts = AdminRepository(session)
    sessions = await accounts.live_sessions(now or datetime.now(UTC))
    return [_read(a, sessions) for a in await accounts.accounts()]


async def _one(session: AsyncSession, admin_id: uuid.UUID) -> AdminAccount:
    account = await AdminRepository(session).account(admin_id)
    if account is None:
        raise TeamError(404, "No admin with this id.")
    return account


async def invite(
    session: AsyncSession,
    principal: AdminPrincipal,
    *,
    email: str,
    name: str,
    role: AdminRole,
    sender: EmailSender,
    route: str,
    now: datetime | None = None,
) -> AdminRead:
    moment = now or datetime.now(UTC)
    accounts = AdminRepository(session)
    if await accounts.account_by_email(email) is not None:
        raise TeamError(409, f"{email} already has a LEKA ADMIN account.")
    account = AdminAccount(
        id=uuid.uuid4(),
        email=email,
        name=name.strip(),
        password_hash=None,
        role=role.value,
        status="invited",
        failed_sign_ins=0,
        created_by=principal.email,
    )
    accounts.add(account)
    await accounts.flush()
    code = await issue_code(session, account, "invite", moment)
    await sender.send(
        codes.invitation(account.email, account.name, role.value, principal.name, code)
    )
    audit.record(
        session,
        "admin.invited",
        admin_id=principal.admin_id,
        target_type="admin",
        target_id=account.id,
        route=route,
        ip_prefix=principal.ip_prefix,
        detail={"email": account.email, "role": role.value},
    )
    await session.refresh(account)
    return _read(account, {})


async def resend(
    session: AsyncSession,
    principal: AdminPrincipal,
    admin_id: uuid.UUID,
    *,
    sender: EmailSender,
    route: str,
    now: datetime | None = None,
) -> AdminRead:
    account = await _one(session, admin_id)
    if account.status != "invited":
        raise TeamError(409, "Only an invited admin is sent an invitation again.")
    code = await issue_code(session, account, "invite", now or datetime.now(UTC))
    await sender.send(
        codes.invitation(account.email, account.name, account.role, principal.name, code)
    )
    audit.record(
        session,
        "admin.invitation_sent",
        admin_id=principal.admin_id,
        target_type="admin",
        target_id=account.id,
        route=route,
        ip_prefix=principal.ip_prefix,
        detail={"email": account.email},
    )
    return _read(account, {})


async def change(
    session: AsyncSession,
    principal: AdminPrincipal,
    admin_id: uuid.UUID,
    *,
    name: str | None,
    role: AdminRole | None,
    status: str | None,
    route: str,
    now: datetime | None = None,
) -> AdminRead:
    moment = now or datetime.now(UTC)
    accounts = AdminRepository(session)
    account = await _one(session, admin_id)
    before = {"name": account.name, "role": account.role, "status": account.status}
    new_role = role.value if role is not None else account.role
    new_status = status or account.status

    if admin_id == principal.admin_id and (
        new_role != account.role or new_status != account.status
    ):
        raise TeamError(409, "Your own role and access are changed by another Super Admin.")
    if new_status == "active" and account.password_hash is None:
        raise TeamError(409, "This admin has not chosen a password yet: send the invitation again.")
    was_super = account.role == AdminRole.SUPER_ADMIN.value and account.status == "active"
    stays_super = new_role == AdminRole.SUPER_ADMIN.value and new_status == "active"
    if was_super and not stays_super and await accounts.active_super_admins() <= 1:
        raise TeamError(409, "LEKA ADMIN keeps at least one active Super Admin.")

    if name is not None:
        account.name = name.strip()
    account.role = new_role
    account.status = new_status
    ended = 0
    if new_status == "disabled" and before["status"] != "disabled":
        ended = await accounts.revoke_all(account.id, moment, "disabled")
    if new_status == "active" and before["status"] == "disabled":
        account.failed_sign_ins = 0
        account.locked_until = None
    await accounts.flush()
    audit.record(
        session,
        "admin.account_changed",
        admin_id=principal.admin_id,
        target_type="admin",
        target_id=account.id,
        route=route,
        ip_prefix=principal.ip_prefix,
        detail={
            "before": before,
            "after": {"name": account.name, "role": account.role, "status": account.status},
            "sessions_ended": ended,
        },
    )
    return _read(account, await accounts.live_sessions(moment))


async def sign_out_everywhere(
    session: AsyncSession,
    principal: AdminPrincipal,
    admin_id: uuid.UUID,
    *,
    route: str,
    now: datetime | None = None,
) -> int:
    account = await _one(session, admin_id)
    ended = await AdminRepository(session).revoke_all(
        account.id, now or datetime.now(UTC), "ended_by_admin"
    )
    audit.record(
        session,
        "admin.signed_out_everywhere",
        admin_id=principal.admin_id,
        target_type="admin",
        target_id=account.id,
        route=route,
        ip_prefix=principal.ip_prefix,
        detail={"sessions_ended": ended},
    )
    return ended


def catalogue() -> list[AdminPermissionRead]:
    return [
        AdminPermissionRead(
            permission=permission,
            module=PERMISSION_INFO[permission][0],
            level=cast(Literal["read", "write", "sensitive"], PERMISSION_INFO[permission][1]),
            grantable=permission in GRANTABLE,
        )
        for permission in AdminPermission
    ]


async def _role(session: AsyncSession, role: AdminRole) -> AdminRoleRead:
    stored = await AdminRepository(session).role_permissions(role.value)
    return AdminRoleRead(
        role=role,
        editable=role is not AdminRole.SUPER_ADMIN,
        permissions=sorted(granted(role.value, stored)),
    )


async def roles(session: AsyncSession) -> AdminRolesRead:
    return AdminRolesRead(
        roles=[await _role(session, role) for role in AdminRole], permissions=catalogue()
    )


async def set_permissions(
    session: AsyncSession,
    principal: AdminPrincipal,
    role: AdminRole,
    permissions: list[AdminPermission],
    *,
    route: str,
) -> AdminRoleRead:
    if role is AdminRole.SUPER_ADMIN:
        raise TeamError(409, "A Super Admin may do everything; that is not changed.")
    reserved = sorted(p.value for p in set(permissions) & SUPER_ADMIN_ONLY)
    if reserved:
        raise TeamError(409, f"Only a Super Admin may: {', '.join(reserved)}.")
    accounts = AdminRepository(session)
    before = sorted(await accounts.role_permissions(role.value))
    wanted = frozenset(p.value for p in permissions)
    await accounts.set_role_permissions(role.value, wanted, by=principal.email)
    audit.record(
        session,
        "admin.role_changed",
        admin_id=principal.admin_id,
        target_type="role",
        target_id=role.value,
        route=route,
        ip_prefix=principal.ip_prefix,
        detail={"before": before, "after": sorted(wanted)},
    )
    return await _role(session, role)
