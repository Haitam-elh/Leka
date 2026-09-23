"""Database access for the connectors module.

The only place in this module where a query is written (architecture rule 4).
Every repository here is built with a workspace and filters on it — serving
a customer never needs "all sources". The one exception is
SourceCredentialSweeper, below: a key rotation spans every workspace by
definition, and says so.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Result, Select, select, update

from leka.connectors.models import (
    Source,
    SourceCredential,
    SourceEvent,
    SourceEventType,
    SourceStatus,
)
from leka.db import WorkspaceScopedRepository


def _affected_rows(result: Result[Any]) -> int:
    """How many rows an UPDATE touched. Same shape as leka.ingestion's."""
    return int(cast("CursorResult[Any]", result).rowcount or 0)


class SourceRepository(WorkspaceScopedRepository):
    """Rows in `sources`, for one workspace."""

    def list_statement(self) -> Select[tuple[Source]]:
        return self.select(Source)

    async def find(self, source_id: uuid.UUID) -> Source | None:
        """None for another workspace's source, too: the caller answers 404."""
        return await self.get(Source, source_id)

    def stage(self, source: Source) -> None:
        self.add(source)

    async def flush(self) -> None:
        await self._session.flush()

    async def refresh(self, source: Source) -> None:
        """Read back what PostgreSQL computed on the last write (updated_at)."""
        await self._session.refresh(source)

    async def remove(self, source: Source) -> None:
        # Its credential goes with it: ON DELETE CASCADE, in the database.
        await self.delete(source)
        await self._session.flush()


class SourceCredentialRepository(WorkspaceScopedRepository):
    """Rows in `source_credentials`. Used by the SecretStore and nothing else."""

    async def find(self, source_id: uuid.UUID) -> SourceCredential | None:
        result = await self._session.execute(
            self.select(SourceCredential).where(SourceCredential.source_id == source_id)
        )
        return result.scalar_one_or_none()

    async def put(
        self,
        source_id: uuid.UUID,
        *,
        ciphertext: bytes,
        key_version: str,
        hint: str,
        rotated_at: datetime,
    ) -> SourceCredential:
        row = await self.find(source_id)
        if row is None:
            row = SourceCredential(source_id=source_id)
            self.add(row)
        row.ciphertext = ciphertext
        row.key_version = key_version
        row.hint = hint
        row.rotated_at = rotated_at
        await self._session.flush()
        return row


class SourceEventRepository(WorkspaceScopedRepository):
    """Rows in `source_events`: appended, listed, never changed."""

    def append(
        self,
        source_id: uuid.UUID,
        type_: SourceEventType,
        *,
        actor_user_id: uuid.UUID | None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.add(
            SourceEvent(
                source_id=source_id,
                type=type_,
                actor_user_id=actor_user_id,
                payload=payload or {},
            )
        )

    def list_statement(self, source_id: uuid.UUID) -> Select[tuple[SourceEvent]]:
        return self.select(SourceEvent).where(SourceEvent.source_id == source_id)


# The statuses a scheduled health check looks at: the sources that were
# activated. A draft has nothing to be healthy for.
CHECKED_STATUSES = (SourceStatus.ACTIVE, SourceStatus.DEGRADED, SourceStatus.ERROR)


async def activated_sources(session: Any) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(workspace_id, source_id) of every activated source. Inside system_scope()."""
    result = await session.execute(
        select(Source.workspace_id, Source.id).where(Source.status.in_(CHECKED_STATUSES))
    )
    return [(workspace_id, source_id) for workspace_id, source_id in result.tuples()]


class SourceCredentialSweeper:
    """Every stored credential, across every workspace — for key rotation only.

    Not workspace-scoped, for the reason RawPayloadSweeper gives: a rotation
    that stopped at one tenant would leave the others readable only with the
    old key, which is the key about to be removed. It must run inside
    system_scope(), which says so in one reviewable line.

    It moves ciphertext and nothing else. Nothing here can decrypt.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    async def encrypted_after(
        self, after: uuid.UUID | None, *, limit: int
    ) -> list[tuple[uuid.UUID, bytes]]:
        """The next batch of stored credentials, in source order, after `after`.

        Keyset, not OFFSET: rows rewritten by the previous batch do not move
        the position, so nothing is skipped or read twice.
        """
        statement = select(SourceCredential.source_id, SourceCredential.ciphertext)
        if after is not None:
            statement = statement.where(SourceCredential.source_id > after)
        result = await self._session.execute(
            statement.order_by(SourceCredential.source_id).limit(limit)
        )
        return list(result.tuples())

    async def replace(
        self, source_id: uuid.UUID, *, expected: bytes, new: bytes, key_version: str
    ) -> bool:
        """Swap one ciphertext for another, unless the row changed since it was read.

        A plain UPDATE would overwrite a credential somebody saved while the
        rotation ran — encrypted under the new key already — with the rotated
        old one, silently reverting their change. False means that happened,
        and the row was left alone.
        """
        result = await self._session.execute(
            update(SourceCredential)
            .where(
                SourceCredential.source_id == source_id,
                SourceCredential.ciphertext == expected,
            )
            .values(ciphertext=new, key_version=key_version)
        )
        return _affected_rows(result) == 1
