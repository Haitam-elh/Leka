"""Database access for the ingestion module.

The only place in this module where a query is written (architecture rule 4).
Records what each pipeline run did; it does not write entities. Writing to
the graph goes through leka.knowledge.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Result, Select, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import ACTIVE_JOB_STATUSES, JobRun, JobStatus
from leka.connectors import Source
from leka.db import WorkspaceScopedRepository
from leka.ingestion.models import (
    RawPayload,
    SourceRecord,
    SourceSync,
    SyncRun,
    SyncRunOutcome,
    SyncTrigger,
)


def _affected_rows(result: Result[Any]) -> int:
    """How many rows a DELETE touched.

    SQLAlchemy returns a CursorResult, which carries rowcount, but the
    declared return type of execute() is the narrower Result. One cast beats
    a scattered type: ignore — the same shape leka.identity.repository uses.
    """
    return int(cast("CursorResult[Any]", result).rowcount or 0)


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

    async def all_for_source(self, source_id: uuid.UUID) -> Sequence[RawPayload]:
        """Every live payload of one source, oldest first."""
        return await self.list(
            self.live().where(RawPayload.source_id == source_id).order_by(RawPayload.fetched_at)
        )

    def mark_deleted(self, payload: RawPayload, *, now: datetime | None = None) -> RawPayload:
        """Withdraw a payload without removing it yet.

        The row stops being read immediately; the retention sweep removes the
        object and then the row. Splitting it this way means a withdrawal
        takes effect at once even though deleting bytes is slow and can fail.
        """
        payload.deleted_at = now or datetime.now(UTC)
        return payload


class SourceSyncRepository(WorkspaceScopedRepository):
    """Where each capability of each source stands, within one workspace.

    Reads and the one write that must not race: the row of a (source,
    capability) is made by whichever pass gets there first, with INSERT ...
    ON CONFLICT DO NOTHING, and read back — two passes started together
    (the scheduler and a "sync now") both find the same row rather than one
    failing on the unique constraint. The transitions themselves belong to
    the sync (leka/ingestion/sync.py), which owns their order.
    """

    async def for_source(self, source_id: uuid.UUID) -> Sequence[SourceSync]:
        return await self.list(
            self.select(SourceSync)
            .where(SourceSync.source_id == source_id)
            .order_by(SourceSync.capability)
        )

    async def passes(self, source_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Which of these sources have a pass under way, and whether it is
        `running` — a worker executing it — or `queued` — waiting, or waiting
        for a retry. Read from the job runs, which know whether a worker holds
        it; `source_syncs` only knows a pass started, not that it is alive.

        job_runs belongs to no workspace, so the filter on for_workspace_id is
        written out here, as leka.background asks of whatever reads it.
        """
        keys = {f"sync:{source_id}": source_id for source_id in source_ids}
        if not keys:
            return {}
        rows = await self._session.execute(
            select(JobRun.concurrency_key, JobRun.status).where(
                JobRun.for_workspace_id == self.workspace_id,
                JobRun.concurrency_key.in_(list(keys)),
                JobRun.status.in_(ACTIVE_JOB_STATUSES),
            )
        )
        return {
            keys[str(key)]: "running" if status is JobStatus.RUNNING else "queued"
            for key, status in rows.all()
        }

    async def summaries(self) -> Sequence[tuple[uuid.UUID, int, datetime | None]]:
        """Per source of this workspace: records brought so far, and the last
        success of any of its capabilities. One query for a whole list."""
        rows = await self._session.execute(
            select(
                SourceSync.source_id,
                func.sum(SourceSync.records_total),
                func.max(SourceSync.last_succeeded_at),
            )
            .where(SourceSync.workspace_id == self.workspace_id)
            .group_by(SourceSync.source_id)
        )
        return [(source_id, int(total), last) for source_id, total, last in rows.all()]

    async def get_or_create(self, source_id: uuid.UUID, capability: str) -> SourceSync:
        await self._session.execute(
            insert(SourceSync)
            .values(workspace_id=self.workspace_id, source_id=source_id, capability=capability)
            .on_conflict_do_nothing(constraint="uq_source_syncs_source_capability")
        )
        found = await self._session.execute(
            self.select(SourceSync).where(
                SourceSync.source_id == source_id, SourceSync.capability == capability
            )
        )
        return found.scalar_one()


class SyncRunRepository(WorkspaceScopedRepository):
    """The passes over a workspace's sources: one row each (LEKA-353)."""

    async def start(
        self, source_id: uuid.UUID, *, trigger: SyncTrigger, full: bool, at: datetime
    ) -> SyncRun:
        """A new pass. A run of this source still `running` is one whose worker
        died — only one pass holds sync:<source_id> — so it is closed first,
        as abandoned, at the moment it is found."""
        await self._session.execute(
            update(SyncRun)
            .where(
                SyncRun.workspace_id == self.workspace_id,
                SyncRun.source_id == source_id,
                SyncRun.status == SyncRunOutcome.RUNNING,
            )
            .values(status=SyncRunOutcome.ABANDONED, finished_at=at)
        )
        run = SyncRun(source_id=source_id, trigger=trigger, full_read=full, started_at=at)
        self.add(run)
        await self.flush()
        return run

    def history(self, source_id: uuid.UUID) -> Select[tuple[SyncRun]]:
        """A source's passes, for pagination; newest first by default."""
        return self.select(SyncRun).where(SyncRun.source_id == source_id)


@dataclass(frozen=True)
class Seen:
    """One record a pass saw: what the index needs of it."""

    external_id: str
    container: str | None
    checksum: str
    # The batch it was written to; None when it was unchanged and not written.
    payload_key: str | None


@dataclass(frozen=True)
class Known:
    checksum: str
    live: bool
    # A batch still holds its latest version (the purge job clears this).
    stored: bool


class SourceRecordRepository(WorkspaceScopedRepository):
    """The per-record index of a workspace's sources (LEKA-353)."""

    async def known(
        self, source_id: uuid.UUID, kind: str, external_ids: Sequence[str]
    ) -> dict[str, Known]:
        if not external_ids:
            return {}
        rows = await self._session.execute(
            select(
                SourceRecord.external_id,
                SourceRecord.checksum,
                SourceRecord.deleted_at,
                SourceRecord.payload_key,
            ).where(
                SourceRecord.workspace_id == self.workspace_id,
                SourceRecord.source_id == source_id,
                SourceRecord.kind == kind,
                SourceRecord.external_id.in_(list(external_ids)),
            )
        )
        return {
            external_id: Known(checksum, deleted_at is None, payload_key is not None)
            for external_id, checksum, deleted_at, payload_key in rows.all()
        }

    async def seen(
        self,
        source_id: uuid.UUID,
        kind: str,
        records: Sequence[Seen],
        *,
        run_id: uuid.UUID,
        at: datetime,
    ) -> None:
        """Record that `run_id` saw these. One statement for a batch.

        A record seen again comes back (`deleted_at` NULL) — a page shared
        again, a repository back in scope. An unchanged one keeps the batch
        that already holds it.
        """
        if not records:
            return
        statement = insert(SourceRecord).values(
            [
                {
                    "workspace_id": self.workspace_id,
                    "source_id": source_id,
                    "kind": kind,
                    "external_id": record.external_id,
                    "container": record.container,
                    "checksum": record.checksum,
                    "first_seen_at": at,
                    "last_seen_at": at,
                    "last_seen_run_id": run_id,
                    "payload_key": record.payload_key,
                }
                for record in records
            ]
        )
        excluded = statement.excluded
        await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_source_records_source_kind_external",
                set_={
                    "container": excluded.container,
                    "checksum": excluded.checksum,
                    "last_seen_at": excluded.last_seen_at,
                    "last_seen_run_id": excluded.last_seen_run_id,
                    "payload_key": func.coalesce(excluded.payload_key, SourceRecord.payload_key),
                    "deleted_at": None,
                    "updated_at": func.now(),
                },
            )
        )

    async def sweep(
        self, source_id: uuid.UUID, kind: str, *, run_id: uuid.UUID, at: datetime
    ) -> int:
        """After a FULL pass of `kind` succeeded: what `run_id` did not see is
        gone at the vendor, or out of the credentials' reach or the scope."""
        result = await self._session.execute(
            update(SourceRecord)
            .where(
                SourceRecord.workspace_id == self.workspace_id,
                SourceRecord.source_id == source_id,
                SourceRecord.kind == kind,
                SourceRecord.deleted_at.is_(None),
                SourceRecord.last_seen_run_id.is_distinct_from(run_id),
            )
            .values(deleted_at=at, updated_at=func.now())
        )
        return _affected_rows(result)

    async def indexed(self, source_id: uuid.UUID, kind: str) -> bool:
        """Whether this capability of the source has any record in the index."""
        found = await self._session.execute(
            select(SourceRecord.id)
            .where(
                SourceRecord.workspace_id == self.workspace_id,
                SourceRecord.source_id == source_id,
                SourceRecord.kind == kind,
            )
            .limit(1)
        )
        return found.first() is not None

    async def has_pending_purge(self, source_id: uuid.UUID) -> bool:
        found = await self._session.execute(
            select(SourceRecord.id)
            .where(
                SourceRecord.workspace_id == self.workspace_id,
                SourceRecord.source_id == source_id,
                SourceRecord.deleted_at.is_not(None),
                SourceRecord.payload_key.is_not(None),
            )
            .limit(1)
        )
        return found.first() is not None

    async def pending_purge(self, source_id: uuid.UUID) -> set[tuple[str, str]]:
        """(kind, external_id) of the deleted records a batch may still hold."""
        rows = await self._session.execute(
            select(SourceRecord.kind, SourceRecord.external_id).where(
                SourceRecord.workspace_id == self.workspace_id,
                SourceRecord.source_id == source_id,
                SourceRecord.deleted_at.is_not(None),
                SourceRecord.payload_key.is_not(None),
            )
        )
        return {(kind, external_id) for kind, external_id in rows.all()}

    async def still_deleted(
        self, source_id: uuid.UUID, identities: set[tuple[str, str]]
    ) -> set[tuple[str, str]]:
        """Which of these are STILL deleted, their index rows locked until the
        caller commits. A pass that sees one again waits for that commit
        rather than reviving it while its lines are being removed."""
        still: set[tuple[str, str]] = set()
        for kind in {kind for kind, _ in identities}:
            rows = await self._session.execute(
                select(SourceRecord.kind, SourceRecord.external_id)
                .where(
                    SourceRecord.workspace_id == self.workspace_id,
                    SourceRecord.source_id == source_id,
                    SourceRecord.kind == kind,
                    SourceRecord.external_id.in_([e for k, e in identities if k == kind]),
                    SourceRecord.deleted_at.is_not(None),
                )
                .with_for_update()
            )
            still.update((k, e) for k, e in rows.all())
        return still

    async def move_payload(self, source_id: uuid.UUID, old_key: str, new_key: str) -> None:
        """Records whose latest version was in a rewritten batch now point at
        its new object."""
        await self._session.execute(
            update(SourceRecord)
            .where(
                SourceRecord.workspace_id == self.workspace_id,
                SourceRecord.source_id == source_id,
                SourceRecord.payload_key == old_key,
            )
            .values(payload_key=new_key, updated_at=func.now())
        )

    async def purged(self, source_id: uuid.UUID, gone: set[tuple[str, str]]) -> None:
        """No batch holds these any more. Only those still deleted: one seen
        again during the purge was written again and keeps its batch."""
        for kind in {kind for kind, _ in gone}:
            await self._session.execute(
                update(SourceRecord)
                .where(
                    SourceRecord.workspace_id == self.workspace_id,
                    SourceRecord.source_id == source_id,
                    SourceRecord.kind == kind,
                    SourceRecord.external_id.in_([e for k, e in gone if k == kind]),
                    SourceRecord.deleted_at.is_not(None),
                )
                .values(payload_key=None, updated_at=func.now())
            )

    async def live_counts(self) -> dict[tuple[uuid.UUID, str], int]:
        """Records not deleted, per (source, kind), for the whole workspace."""
        rows = await self._session.execute(
            select(SourceRecord.source_id, SourceRecord.kind, func.count())
            .where(
                SourceRecord.workspace_id == self.workspace_id,
                SourceRecord.deleted_at.is_(None),
            )
            .group_by(SourceRecord.source_id, SourceRecord.kind)
        )
        return {(source_id, kind): int(count) for source_id, kind, count in rows.all()}


class SyncScheduleRepository:
    """Which sources are due a pass, across every workspace. For the scheduler.

    Not workspace-scoped, like RawPayloadSweeper: it answers a question about
    all of them, and runs under system_scope, declared by its caller.

    DUE MEANS NOT TRIED FOR `interval`, not "not succeeded for": a source
    failing for a reason that needs a person would otherwise be tried at
    every scheduler tick. The last attempt is the newest `last_started_at`
    of its capabilities; a source never tried has none, and is due at once.
    A pass whose worker died leaves a `running` behind but an old start, so
    it is due again too.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def active_passes(self, job: str) -> dict[uuid.UUID, int]:
        """Passes queued, running or waiting for a retry, per workspace."""
        rows = await self._session.execute(
            select(JobRun.for_workspace_id, func.count())
            .where(JobRun.job == job, JobRun.status.in_(ACTIVE_JOB_STATUSES))
            .group_by(JobRun.for_workspace_id)
        )
        return {workspace_id: int(count) for workspace_id, count in rows.all() if workspace_id}

    async def due(
        self, *, before: datetime, statuses: Sequence[str], limit: int
    ) -> Sequence[tuple[uuid.UUID, uuid.UUID]]:
        """(workspace_id, source_id) of the switched-on sources last tried before `before`."""
        last_tried = (
            select(SourceSync.source_id, func.max(SourceSync.last_started_at).label("at"))
            .group_by(SourceSync.source_id)
            .subquery()
        )
        statement = (
            select(Source.workspace_id, Source.id)
            .outerjoin(last_tried, last_tried.c.source_id == Source.id)
            .where(
                Source.status.in_(statuses),
                or_(last_tried.c.at.is_(None), last_tried.c.at < before),
            )
            .order_by(last_tried.c.at.asc().nulls_first())
            .limit(limit)
        )
        rows = await self._session.execute(statement)
        return [(workspace_id, source_id) for workspace_id, source_id in rows.all()]


class RawPayloadSweeper:
    """Retention work, across every workspace at once.

    Separate from RawPayloadRepository, and deliberately NOT workspace-scoped.
    That is what it is for: a sweep that stopped at one tenant would need a
    caller looping over every workspace, and a workspace created between two
    iterations would be skipped. It must run inside system_scope(), which
    says out loud in one reviewable line that this crosses tenants on
    purpose.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def due_for_deletion(
        self, *, now: datetime | None = None, limit: int = 500
    ) -> Sequence[RawPayload]:
        """Payloads past their expiry, or withdrawn. Oldest first.

        Batched, and that is not premature. The first sweep after a retention
        change can match millions of rows; loading them all would take the
        worker out of memory instead of letting it make steady progress. The
        caller runs again until this returns nothing.
        """
        moment = now or datetime.now(UTC)
        result = await self._session.execute(
            select(RawPayload)
            .where((RawPayload.expires_at <= moment) | (RawPayload.deleted_at.is_not(None)))
            .order_by(RawPayload.expires_at)
            .limit(limit)
        )
        return result.scalars().all()

    async def delete_rows(self, payload_ids: Sequence[uuid.UUID]) -> int:
        """Remove rows whose objects the caller has already dealt with."""
        if not payload_ids:
            return 0
        result = await self._session.execute(
            delete(RawPayload).where(RawPayload.id.in_(payload_ids))
        )
        return _affected_rows(result)

    async def every_object_key(self) -> set[str]:
        """Every key any row still claims, across every workspace.

        What reconciliation compares the store against: a key in the store
        and not in this set belongs to nobody.

        Held in memory, which is a choice with a limit. One key is roughly
        120 bytes, so a million payloads is around 120 MB and the point at
        which this becomes a streaming comparison per workspace prefix
        instead. That threshold is written down in
        docs/adr/010-object-storage.md rather than left to be discovered.
        """
        result = await self._session.execute(select(RawPayload.object_key))
        return set(result.scalars().all())
