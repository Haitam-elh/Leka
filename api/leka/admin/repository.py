"""LEKA ADMIN's own rows: its accounts, their sessions, their idempotency keys.

None of these tables is workspace-scoped, so no scope is needed to read
them. What LEKA ADMIN reads of the customers is leka/admin/reads.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.models import AdminAccount, AdminIdempotencyKey, AdminSession


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

    def add(self, row: AdminAccount | AdminSession) -> None:
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

    async def revoke(self, session_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(AdminSession)
            .where(AdminSession.id == session_id, AdminSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def revoke_all(self, admin_id: uuid.UUID, now: datetime) -> int:
        result = await self._session.execute(
            update(AdminSession)
            .where(AdminSession.admin_id == admin_id, AdminSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return int(getattr(result, "rowcount", 0) or 0)

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
