"""Database access for the ingestion module.

The only place in this module where a query is written (architecture rule 4).
Records what each pipeline run did; it does not write entities. Writing to
the graph goes through leka.knowledge.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.db import WorkspaceScopedRepository
from leka.ingestion.models import RawPayload


class IngestionRunRepository:
    """Reads and writes the history of pipeline runs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session


class RawPayloadRepository(WorkspaceScopedRepository):
    """Rows in `raw_payloads`, always within one workspace.

    Inherits the scoped base, so the workspace is a constructor argument
    rather than something a caller can forget, every read is pre-filtered,
    and a row bearing another workspace is refused rather than written.

    Nothing here touches the object store. The row and the bytes are written
    and deleted by a service that owns both and can order the two operations
    — a repository that quietly deleted objects would make that order an
    accident of where you happened to call it from.
    """

    def record(
        self,
        *,
        source_id: uuid.UUID,
        object_key: str,
        content_type: str,
        size_bytes: int,
        checksum_sha256: str,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> RawPayload:
        """Stage the metadata of a payload already written to the store.

        Keyword-only, deliberately. Seven arguments of which three are
        strings and two are timestamps is exactly the call whose positions
        get swapped in a hurry, and a checksum landing in the content_type
        column would fail nowhere — it would simply be wrong for ever.

        size_bytes and checksum_sha256 come from what the store MEASURED
        while writing (StoredObject), never from what a caller believed it
        was sending. That is what makes them usable later as proof.
        """
        payload = RawPayload(
            workspace_id=self.workspace_id,
            source_id=source_id,
            object_key=object_key,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
            fetched_at=fetched_at,
            expires_at=expires_at,
        )
        self.add(payload)
        return payload

    def live(self) -> Select[tuple[RawPayload]]:
        """This workspace's payloads that have not been withdrawn."""
        return self.select(RawPayload).where(RawPayload.deleted_at.is_(None))

    async def get_payload(self, payload_id: uuid.UUID) -> RawPayload | None:
        """One payload of this workspace, by id, if it is still live."""
        result = await self._session.execute(self.live().where(RawPayload.id == payload_id))
        return result.scalar_one_or_none()

    async def get_by_object_key(self, object_key: str) -> RawPayload | None:
        """Find the row that speaks for one stored object.

        Scoped like everything else, so a key belonging to another workspace
        is simply not found — which is also what stops this becoming a way
        to probe someone else's store.
        """
        result = await self._session.execute(
            self.select(RawPayload).where(RawPayload.object_key == object_key)
        )
        return result.scalar_one_or_none()

    async def list_for_source(
        self, source_id: uuid.UUID, *, limit: int = 100
    ) -> Sequence[RawPayload]:
        """The most recent payloads collected from one source."""
        statement = (
            self.live()
            .where(RawPayload.source_id == source_id)
            .order_by(RawPayload.fetched_at.desc())
            .limit(limit)
        )
        return await self.list(statement)

    async def list_with_checksum(self, checksum_sha256: str) -> Sequence[RawPayload]:
        """Every payload of this workspace with the same fingerprint.

        The same content collected twice, which is what re-syncing a
        repository every night produces. Today this answers "have we seen
        this before?"; it is also the measurement any future deduplication
        decision would be argued from. See docs/adr/010-object-storage.md.
        """
        return await self.list(self.live().where(RawPayload.checksum_sha256 == checksum_sha256))

    def mark_deleted(self, payload: RawPayload, *, now: datetime | None = None) -> RawPayload:
        """Withdraw a payload without removing it yet.

        The row stops being read immediately; the retention sweep removes the
        object and then the row. Splitting it this way means a withdrawal
        takes effect at once even though deleting bytes is slow and can fail.
        """
        payload.deleted_at = now or datetime.now(UTC)
        return payload
