"""LEKA ADMIN's own rows: its accounts, their sessions, their idempotency keys.

None of these tables is workspace-scoped, so no scope is needed to read
them. What LEKA ADMIN reads of the customers is leka/admin/reads.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.models import (
    AdminAccount,
    AdminCode,
    AdminIdempotencyKey,
    AdminRolePermission,
    AdminSession,
)


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def account_by_email(self, email: str) -> AdminAccount | None:
        found: AdminAccount | None = await self._session.scalar(
            select(AdminAccount).where(AdminAccount.email == email.strip().lower())
        )
        return found

    async def accounts(self) -> list[AdminAccount]:
        return list(
            (await self._session.scalars(select(AdminAccount).order_by(AdminAccount.email))).all()
        )

    def add(self, row: AdminAccount | AdminSession | AdminCode | AdminRolePermission) -> None:
        self._session.add(row)

    async def flush(self) -> None:
        await self._session.flush()

    async def live_session(
        self, token_hash: str, now: datetime
    ) -> tuple[AdminSession, AdminAccount] | None:
        """The session a token opens, and its admin — when both still may."""
        row = (
            await self._session.execute(
                select(AdminSession, AdminAccount)
                .join(AdminAccount, AdminAccount.id == AdminSession.admin_id)
                .where(
                    AdminSession.token_hash == token_hash,
                    AdminSession.revoked_at.is_(None),
                    AdminSession.expires_at > now,
                    AdminAccount.status == "active",
                )
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def revoke(self, session_id: uuid.UUID, now: datetime, reason: str) -> bool:
        """End a session now. False: it had ended already."""
        ended = await self._session.scalar(
            update(AdminSession)
            .where(AdminSession.id == session_id, AdminSession.revoked_at.is_(None))
            .values(revoked_at=now, ended_reason=reason)
            .returning(AdminSession.id)
        )
        return ended is not None

    async def revoke_all(self, admin_id: uuid.UUID, now: datetime, reason: str) -> int:
        result = await self._session.execute(
            update(AdminSession)
            .where(AdminSession.admin_id == admin_id, AdminSession.revoked_at.is_(None))
            .values(revoked_at=now, ended_reason=reason)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    # ── Renewal and a device's sessions (LEKA-546) ──────────────────────────

    async def session_by_token(self, token_hash: str) -> tuple[AdminSession, AdminAccount] | None:
        """The session a token was given for, whatever became of it."""
        row = (
            await self._session.execute(
                select(AdminSession, AdminAccount)
                .join(AdminAccount, AdminAccount.id == AdminSession.admin_id)
                .where(AdminSession.token_hash == token_hash)
            )
        ).first()
        return (row[0], row[1]) if row else None

    async def revoke_family(self, family_id: uuid.UUID, now: datetime, reason: str) -> int:
        result = await self._session.execute(
            update(AdminSession)
            .where(AdminSession.family_id == family_id, AdminSession.revoked_at.is_(None))
            .values(revoked_at=now, ended_reason=reason)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def open_sessions(
        self, admin_id: uuid.UUID, now: datetime, used_since: datetime
    ) -> list[AdminSession]:
        """An admin's sessions that still open LEKA ADMIN: not ended, not
        past their end, used since `used_since`. The last used first."""
        return list(
            (
                await self._session.scalars(
                    select(AdminSession)
                    .where(
                        AdminSession.admin_id == admin_id,
                        AdminSession.revoked_at.is_(None),
                        AdminSession.expires_at > now,
                        AdminSession.last_seen_at > used_since,
                    )
                    .order_by(AdminSession.last_seen_at.desc())
                )
            ).all()
        )

    async def claim_key(self, admin_id: uuid.UUID, key: str, route: str, fingerprint: str) -> bool:
        """Take an idempotency key for this request. False: it was taken.

        A placeholder (status 0) inserted at once: a second request with the
        same key waits on the unique index until the first commits, then
        finds its answer instead of running the operation again.
        """
        inserted = await self._session.scalar(
            insert(AdminIdempotencyKey)
            .values(
                id=uuid.uuid4(),
                admin_id=admin_id,
                key=key,
                route=route,
                fingerprint=fingerprint,
                status_code=0,
                response={},
            )
            .on_conflict_do_nothing(constraint="uq_admin_idempotency_keys_key")
            .returning(AdminIdempotencyKey.id)
        )
        return inserted is not None

    async def key(self, admin_id: uuid.UUID, key: str) -> AdminIdempotencyKey | None:
        found: AdminIdempotencyKey | None = await self._session.scalar(
            select(AdminIdempotencyKey).where(
                AdminIdempotencyKey.admin_id == admin_id, AdminIdempotencyKey.key == key
            )
        )
        return found

    async def answer_key(
        self, admin_id: uuid.UUID, key: str, status_code: int, response: dict[str, object]
    ) -> None:
        await self._session.execute(
            update(AdminIdempotencyKey)
            .where(AdminIdempotencyKey.admin_id == admin_id, AdminIdempotencyKey.key == key)
            .values(status_code=status_code, response=response)
        )

    # ── Accounts, as the Super Admin sees them (LEKA-545) ────────────────────

    async def account(self, admin_id: uuid.UUID) -> AdminAccount | None:
        return await self._session.get(AdminAccount, admin_id)

    async def live_sessions(self, now: datetime) -> dict[uuid.UUID, int]:
        rows = await self._session.execute(
            select(AdminSession.admin_id, func.count())
            .where(AdminSession.revoked_at.is_(None), AdminSession.expires_at > now)
            .group_by(AdminSession.admin_id)
        )
        return {admin_id: int(count) for admin_id, count in rows.all()}

    async def active_super_admins(self) -> int:
        return int(
            await self._session.scalar(
                select(func.count()).where(
                    AdminAccount.role == "super_admin", AdminAccount.status == "active"
                )
            )
            or 0
        )

    async def revoke_others(
        self, admin_id: uuid.UUID, keep: uuid.UUID, now: datetime, reason: str
    ) -> int:
        result = await self._session.execute(
            update(AdminSession)
            .where(
                AdminSession.admin_id == admin_id,
                AdminSession.revoked_at.is_(None),
                AdminSession.id != keep,
            )
            .values(revoked_at=now, ended_reason=reason)
        )
        return int(getattr(result, "rowcount", 0) or 0)

    # ── What each role grants ───────────────────────────────────────────────

    async def role_permissions(self, role: str) -> frozenset[str]:
        return frozenset(
            (
                await self._session.scalars(
                    select(AdminRolePermission.permission).where(AdminRolePermission.role == role)
                )
            ).all()
        )

    async def set_role_permissions(self, role: str, permissions: frozenset[str], by: str) -> None:
        await self._session.execute(
            delete(AdminRolePermission).where(AdminRolePermission.role == role)
        )
        for permission in sorted(permissions):
            self._session.add(
                AdminRolePermission(
                    id=uuid.uuid4(), role=role, permission=permission, granted_by=by
                )
            )
        await self._session.flush()

    # ── Single-use codes ─────────────────────────────────────────────────────

    async def drop_codes(self, admin_id: uuid.UUID, purpose: str) -> None:
        """The codes not used yet of this purpose: a new one replaces them."""
        await self._session.execute(
            delete(AdminCode).where(
                AdminCode.admin_id == admin_id,
                AdminCode.purpose == purpose,
                AdminCode.consumed_at.is_(None),
            )
        )

    async def live_code(self, admin_id: uuid.UUID, now: datetime) -> AdminCode | None:
        found: AdminCode | None = await self._session.scalar(
            select(AdminCode)
            .where(
                AdminCode.admin_id == admin_id,
                AdminCode.consumed_at.is_(None),
                AdminCode.expires_at > now,
            )
            .order_by(AdminCode.created_at.desc())
            .limit(1)
        )
        return found

    async def consume_code(self, code_id: uuid.UUID, now: datetime) -> bool:
        """Use a code, once: False if it was used in the meantime."""
        used = await self._session.scalar(
            update(AdminCode)
            .where(AdminCode.id == code_id, AdminCode.consumed_at.is_(None))
            .values(consumed_at=now)
            .returning(AdminCode.id)
        )
        return used is not None
