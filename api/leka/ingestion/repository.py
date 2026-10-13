"""Database access for the ingestion module.

The only place in this module where a query is written (architecture rule 4).
Records what each pipeline run did; it does not write entities. Writing to
the graph goes through leka.knowledge.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import (
    CursorResult,
    Float,
    Result,
    Select,
    Text,
    and_,
    column,
    delete,
    func,
    literal,
    literal_column,
    or_,
    select,
    text,
    true,
    update,
)
from sqlalchemy import cast as as_type
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import ACTIVE_JOB_STATUSES, JobRun, JobStatus
from leka.connectors import Source
from leka.db import WorkspaceScopedRepository
from leka.ingestion.models import (
    CONTENT_WORDS,
    DeliveryStatus,
    EnrichedRelationship,
    EnrichmentRun,
    EntityEnrichment,
    ExtractedRecordRow,
    ExtractionStatus,
    NormalisationStatus,
    NormalisedRecordRow,
    ParsedRecordRow,
    ParseStatus,
    ProcessingRun,
    ProcessingRunStatus,
    ProcessingStage,
    RawPayload,
    ResolutionDecision,
    ResolutionRun,
    ResolvedEntity,
    ResolvedKey,
    SourceRecord,
    SourceSync,
    SyncRun,
    SyncRunOutcome,
    SyncTrigger,
    ValidatedRecordRow,
    ValidationStatus,
    WebhookDelivery,
)

if TYPE_CHECKING:
    from leka.ingestion.enrichment.engine import Enrichment


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

    async def gone(
        self, source_id: uuid.UUID, kind: str, external_ids: Sequence[str], *, at: datetime
    ) -> int:
        """What the system itself says was deleted — a webhook's deletion
        (LEKA-350): marked as a sweep marks it, and so purged the same way.
        One seen again later comes back, as from a sweep."""
        if not external_ids:
            return 0
        result = await self._session.execute(
            update(SourceRecord)
            .where(
                SourceRecord.workspace_id == self.workspace_id,
                SourceRecord.source_id == source_id,
                SourceRecord.kind == kind,
                SourceRecord.external_id.in_(list(external_ids)),
                SourceRecord.deleted_at.is_(None),
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


class ExtractionRepository(WorkspaceScopedRepository):
    """What extraction made of a source's records (LEKA-354).

    `versions` is, per capability, the version of the strategy that extracts
    it now — None for a capability no strategy knows. A record needs
    extracting when it has no row yet, when its checksum moved, or when that
    version is not the one its row was made by.
    """

    model = ExtractedRecordRow

    def _stale(self, source_id: uuid.UUID, versions: dict[str, int | None]) -> Select[Any]:
        row = ExtractedRecordRow
        known = [k for k, v in versions.items() if v is not None]
        version_moved = or_(
            *(
                and_(SourceRecord.kind == kind, row.extractor_version.is_distinct_from(version))
                for kind, version in versions.items()
            ),
            # A strategy withdrawn: what it made is no longer vouched for.
            and_(SourceRecord.kind.not_in(known), row.extractor_version.is_not(None)),
        )
        return (
            select(SourceRecord)
            .outerjoin(row, row.source_record_id == SourceRecord.id)
            .where(
                SourceRecord.workspace_id == self.workspace_id,
                SourceRecord.source_id == source_id,
                SourceRecord.deleted_at.is_(None),
                SourceRecord.payload_key.is_not(None),
                or_(row.id.is_(None), row.checksum != SourceRecord.checksum, version_moved),
            )
        )

    async def stale(
        self,
        source_id: uuid.UUID,
        versions: dict[str, int | None],
        *,
        after: uuid.UUID | None,
        limit: int,
    ) -> Sequence[SourceRecord]:
        """The next `limit` records to extract, by id — a cursor, so a record
        whose batch could not be read is passed over, not read forever."""
        statement = self._stale(source_id, versions).order_by(SourceRecord.id).limit(limit)
        if after is not None:
            statement = statement.where(SourceRecord.id > after)
        return (await self._session.execute(statement)).scalars().all()

    async def has_stale(self, source_id: uuid.UUID, versions: dict[str, int | None]) -> bool:
        found = await self._session.execute(
            self._stale(source_id, versions).with_only_columns(SourceRecord.id).limit(1)
        )
        return found.first() is not None

    async def save(self, rows: list[dict[str, object]]) -> None:
        """One row per source record: made, or made again."""
        if not rows:
            return
        # `taken_out` is the job's, not a column (LEKA-405).
        statement = insert(ExtractedRecordRow).values(
            [
                {
                    "workspace_id": self.workspace_id,
                    **{k: v for k, v in row.items() if k != "taken_out"},
                }
                for row in rows
            ]
        )
        excluded = statement.excluded
        await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_extracted_records_source_record",
                set_={
                    column: getattr(excluded, column)
                    for column in (
                        "status",
                        "extractor",
                        "extractor_version",
                        "checksum",
                        "result",
                        "sensitivity",
                        "failure_code",
                        "message",
                        "extracted_at",
                    )
                }
                | {"updated_at": func.now()},
            )
        )

    async def forget_deleted(self, source_id: uuid.UUID) -> int:
        """Records marked deleted lose what was extracted from them."""
        deleted = select(SourceRecord.id).where(
            SourceRecord.workspace_id == self.workspace_id,
            SourceRecord.source_id == source_id,
            SourceRecord.deleted_at.is_not(None),
        )
        result = await self._session.execute(
            delete(ExtractedRecordRow).where(
                ExtractedRecordRow.workspace_id == self.workspace_id,
                ExtractedRecordRow.source_record_id.in_(deleted),
            )
        )
        return _affected_rows(result)

    async def counts(self, source_id: uuid.UUID) -> list[tuple[str, str | None, str | None, int]]:
        """(status, failure code, extractor, how many) for the source."""
        row = ExtractedRecordRow
        rows = await self._session.execute(
            select(row.status, row.failure_code, row.extractor, func.count())
            .where(row.workspace_id == self.workspace_id, row.source_id == source_id)
            .group_by(row.status, row.failure_code, row.extractor)
        )
        return [(str(s), code, extractor, int(n)) for s, code, extractor, n in rows.all()]

    async def latest(self, source_id: uuid.UUID) -> datetime | None:
        found = await self._session.execute(
            select(func.max(ExtractedRecordRow.extracted_at)).where(
                ExtractedRecordRow.workspace_id == self.workspace_id,
                ExtractedRecordRow.source_id == source_id,
            )
        )
        return found.scalar_one()

    async def failures(
        self, source_id: uuid.UUID, *, limit: int
    ) -> Sequence[tuple[ExtractedRecordRow, str]]:
        """The latest failures, with the vendor id of their record."""
        rows = await self._session.execute(
            select(ExtractedRecordRow, SourceRecord.external_id)
            .join(SourceRecord, SourceRecord.id == ExtractedRecordRow.source_record_id)
            .where(
                ExtractedRecordRow.workspace_id == self.workspace_id,
                ExtractedRecordRow.source_id == source_id,
                ExtractedRecordRow.status == ExtractionStatus.FAILED,
            )
            .order_by(ExtractedRecordRow.extracted_at.desc(), ExtractedRecordRow.id)
            .limit(limit)
        )
        return [(extraction, str(external_id)) for extraction, external_id in rows.all()]


class ParsingRepository(WorkspaceScopedRepository):
    """What parsing read in a source's extractions (LEKA-355).

    An extraction needs parsing when it was extracted and has no row yet,
    or its row was parsed from another checksum, extractor version or
    parser version.
    """

    model = ParsedRecordRow

    def _stale(self, source_id: uuid.UUID, version: int) -> Select[Any]:
        extracted, parsed = ExtractedRecordRow, ParsedRecordRow
        return (
            select(extracted)
            .outerjoin(parsed, parsed.extracted_record_id == extracted.id)
            .where(
                extracted.workspace_id == self.workspace_id,
                extracted.source_id == source_id,
                extracted.status == ExtractionStatus.EXTRACTED,
                or_(
                    parsed.id.is_(None),
                    parsed.checksum != extracted.checksum,
                    parsed.extractor_version.is_distinct_from(extracted.extractor_version),
                    parsed.parser_version != version,
                ),
            )
        )

    async def stale(
        self, source_id: uuid.UUID, version: int, *, after: uuid.UUID | None, limit: int
    ) -> Sequence[ExtractedRecordRow]:
        statement = self._stale(source_id, version).order_by(ExtractedRecordRow.id).limit(limit)
        if after is not None:
            statement = statement.where(ExtractedRecordRow.id > after)
        return (await self._session.execute(statement)).scalars().all()

    async def has_stale(self, source_id: uuid.UUID, version: int) -> bool:
        found = await self._session.execute(
            self._stale(source_id, version).with_only_columns(ExtractedRecordRow.id).limit(1)
        )
        return found.first() is not None

    async def forget_unparseable(self, source_id: uuid.UUID) -> int:
        """Extractions that failed since they were parsed lose their parse."""
        failed = select(ExtractedRecordRow.id).where(
            ExtractedRecordRow.workspace_id == self.workspace_id,
            ExtractedRecordRow.source_id == source_id,
            ExtractedRecordRow.status == ExtractionStatus.FAILED,
        )
        result = await self._session.execute(
            delete(ParsedRecordRow).where(
                ParsedRecordRow.workspace_id == self.workspace_id,
                ParsedRecordRow.extracted_record_id.in_(failed),
            )
        )
        return _affected_rows(result)

    async def save(self, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        statement = insert(ParsedRecordRow).values(
            [{"workspace_id": self.workspace_id, **row} for row in rows]
        )
        excluded = statement.excluded
        columns = (
            "status",
            "checksum",
            "extractor_version",
            "parser_version",
            "result",
            "failure_code",
            "message",
            "parsed_at",
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_parsed_records_extracted_record",
                set_={c: getattr(excluded, c) for c in columns} | {"updated_at": func.now()},
            )
        )

    def _of(self, source_id: uuid.UUID) -> Any:
        return and_(
            ParsedRecordRow.workspace_id == self.workspace_id,
            ParsedRecordRow.source_id == source_id,
        )

    async def counts(self, source_id: uuid.UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(ParsedRecordRow.status, func.count())
            .where(self._of(source_id))
            .group_by(ParsedRecordRow.status)
        )
        return {str(status): int(n) for status, n in rows.all()}

    async def facts(self, source_id: uuid.UUID) -> dict[str, int]:
        """How many facts of each type the source's records gave."""
        facts = (
            func.jsonb_array_elements(ParsedRecordRow.result["facts"])
            .table_valued(column("value", JSONB))
            .lateral()
        )
        kind = facts.c.value["type"].astext
        rows = await self._session.execute(
            select(kind, func.count())
            .select_from(ParsedRecordRow)
            .join(facts, true())
            .where(self._of(source_id), ParsedRecordRow.status == ParseStatus.PARSED)
            .group_by(kind)
        )
        return {str(kind): int(n) for kind, n in rows.all()}

    async def quality(self, source_id: uuid.UUID) -> float | None:
        score = ParsedRecordRow.result["quality"]["score"].astext.cast(Float)
        found = await self._session.execute(
            select(func.avg(score)).where(
                self._of(source_id), ParsedRecordRow.status == ParseStatus.PARSED
            )
        )
        average = found.scalar_one()
        return round(float(average), 2) if average is not None else None

    async def latest(self, source_id: uuid.UUID) -> datetime | None:
        found = await self._session.execute(
            select(func.max(ParsedRecordRow.parsed_at)).where(self._of(source_id))
        )
        return found.scalar_one()

    async def failures(
        self, source_id: uuid.UUID, *, limit: int
    ) -> Sequence[tuple[ParsedRecordRow, str]]:
        rows = await self._session.execute(
            select(ParsedRecordRow, SourceRecord.external_id)
            .join(ExtractedRecordRow, ExtractedRecordRow.id == ParsedRecordRow.extracted_record_id)
            .join(SourceRecord, SourceRecord.id == ExtractedRecordRow.source_record_id)
            .where(self._of(source_id), ParsedRecordRow.status == ParseStatus.FAILED)
            .order_by(ParsedRecordRow.parsed_at.desc(), ParsedRecordRow.id)
            .limit(limit)
        )
        return [(row, str(external_id)) for row, external_id in rows.all()]


class NormalisationRepository(WorkspaceScopedRepository):
    """The candidates normalisation made of a source's parses (LEKA-356).

    A parse needs normalising when it was parsed and has no row yet, or its
    row was made from another checksum, extractor, parser or normaliser
    version. Normalising needs the extraction too: `stale` returns both.
    """

    model = NormalisedRecordRow

    def _stale(self, source_id: uuid.UUID, version: int, settings_version: int = 0) -> Select[Any]:
        parsed, extracted, row = ParsedRecordRow, ExtractedRecordRow, NormalisedRecordRow
        return (
            select(parsed, extracted)
            .join(extracted, extracted.id == parsed.extracted_record_id)
            .outerjoin(row, row.parsed_record_id == parsed.id)
            .where(
                parsed.workspace_id == self.workspace_id,
                parsed.source_id == source_id,
                parsed.status == ParseStatus.PARSED,
                or_(
                    row.id.is_(None),
                    row.checksum != parsed.checksum,
                    row.extractor_version.is_distinct_from(parsed.extractor_version),
                    row.parser_version != parsed.parser_version,
                    row.normaliser_version != version,
                    row.settings_version != settings_version,
                ),
            )
        )

    async def stale(
        self,
        source_id: uuid.UUID,
        version: int,
        *,
        after: uuid.UUID | None,
        limit: int,
        settings_version: int = 0,
    ) -> list[tuple[ParsedRecordRow, ExtractedRecordRow]]:
        statement = (
            self._stale(source_id, version, settings_version)
            .order_by(ParsedRecordRow.id)
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(ParsedRecordRow.id > after)
        rows = await self._session.execute(statement)
        return [(parsed, extracted) for parsed, extracted in rows.all()]

    async def has_stale(
        self, source_id: uuid.UUID, version: int, settings_version: int = 0
    ) -> bool:
        found = await self._session.execute(
            self._stale(source_id, version, settings_version)
            .with_only_columns(ParsedRecordRow.id)
            .limit(1)
        )
        return found.first() is not None

    async def forget_unnormalisable(self, source_id: uuid.UUID) -> int:
        """Parses that failed since they were normalised lose their candidates."""
        failed = select(ParsedRecordRow.id).where(
            ParsedRecordRow.workspace_id == self.workspace_id,
            ParsedRecordRow.source_id == source_id,
            ParsedRecordRow.status == ParseStatus.FAILED,
        )
        result = await self._session.execute(
            delete(NormalisedRecordRow).where(
                NormalisedRecordRow.workspace_id == self.workspace_id,
                NormalisedRecordRow.parsed_record_id.in_(failed),
            )
        )
        return _affected_rows(result)

    async def save(self, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        statement = insert(NormalisedRecordRow).values(
            [{"workspace_id": self.workspace_id, **row} for row in rows]
        )
        excluded = statement.excluded
        columns = (
            "status",
            "checksum",
            "extractor_version",
            "parser_version",
            "normaliser_version",
            "settings_version",
            "entity_type",
            "entity_key",
            "result",
            "failure_code",
            "message",
            "normalised_at",
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_normalised_records_parsed_record",
                set_={c: getattr(excluded, c) for c in columns} | {"updated_at": func.now()},
            )
        )

    def _of(self, source_id: uuid.UUID) -> Any:
        return and_(
            NormalisedRecordRow.workspace_id == self.workspace_id,
            NormalisedRecordRow.source_id == source_id,
        )

    def _normalised(self, source_id: uuid.UUID) -> Any:
        return and_(
            self._of(source_id), NormalisedRecordRow.status == NormalisationStatus.NORMALISED
        )

    async def counts(self, source_id: uuid.UUID) -> list[tuple[str, str | None, int]]:
        """(status, failure code, how many)."""
        row = NormalisedRecordRow
        rows = await self._session.execute(
            select(row.status, row.failure_code, func.count())
            .where(self._of(source_id))
            .group_by(row.status, row.failure_code)
        )
        return [(str(status), code, int(n)) for status, code, n in rows.all()]

    async def entity_types(self, source_id: uuid.UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(NormalisedRecordRow.entity_type, func.count())
            .where(
                self._of(source_id), NormalisedRecordRow.status == NormalisationStatus.NORMALISED
            )
            .group_by(NormalisedRecordRow.entity_type)
        )
        return {str(kind): int(n) for kind, n in rows.all()}

    async def relationship_types(self, source_id: uuid.UUID) -> dict[str, int]:
        edges = (
            func.jsonb_array_elements(NormalisedRecordRow.result["relationships"])
            .table_valued(column("value", JSONB))
            .lateral()
        )
        kind = edges.c.value["type"].astext
        rows = await self._session.execute(
            select(kind, func.count())
            .select_from(NormalisedRecordRow)
            .join(edges, true())
            .where(
                self._of(source_id), NormalisedRecordRow.status == NormalisationStatus.NORMALISED
            )
            .group_by(kind)
        )
        return {str(k): int(n) for k, n in rows.all()}

    async def with_diagnostics(self, source_id: uuid.UUID) -> int:
        found = await self._session.execute(
            select(func.count()).where(
                self._of(source_id),
                NormalisedRecordRow.status == NormalisationStatus.NORMALISED,
                func.jsonb_array_length(NormalisedRecordRow.result["diagnostics"]) > 0,
            )
        )
        return int(found.scalar_one())

    async def latest(self, source_id: uuid.UUID) -> datetime | None:
        found = await self._session.execute(
            select(func.max(NormalisedRecordRow.normalised_at)).where(self._of(source_id))
        )
        return found.scalar_one()

    async def failures(
        self, source_id: uuid.UUID, *, limit: int
    ) -> Sequence[tuple[NormalisedRecordRow, str]]:
        rows = await self._session.execute(
            select(NormalisedRecordRow, SourceRecord.external_id)
            .join(ParsedRecordRow, ParsedRecordRow.id == NormalisedRecordRow.parsed_record_id)
            .join(ExtractedRecordRow, ExtractedRecordRow.id == ParsedRecordRow.extracted_record_id)
            .join(SourceRecord, SourceRecord.id == ExtractedRecordRow.source_record_id)
            .where(self._of(source_id), NormalisedRecordRow.status == NormalisationStatus.FAILED)
            .order_by(NormalisedRecordRow.normalised_at.desc(), NormalisedRecordRow.id)
            .limit(limit)
        )
        return [(row, str(external_id)) for row, external_id in rows.all()]


class ProcessingRunRepository(WorkspaceScopedRepository):
    """Each run of a processing stage over a source (LEKA-360)."""

    model = ProcessingRun

    def start(
        self,
        source_id: uuid.UUID,
        stage: ProcessingStage,
        *,
        versions: dict[str, object],
        at: datetime,
    ) -> ProcessingRun:
        run = ProcessingRun(
            workspace_id=self.workspace_id,
            source_id=source_id,
            stage=stage,
            status=ProcessingRunStatus.RUNNING,
            started_at=at,
            versions=versions,
            counts={},
        )
        self._session.add(run)
        return run

    async def abandon_running(
        self, source_id: uuid.UUID, stage: ProcessingStage, *, at: datetime
    ) -> int:
        """Runs of this stage still `running` when another starts: one run of
        a stage at a time per source, so their worker died."""
        result = await self._session.execute(
            update(ProcessingRun)
            .where(
                ProcessingRun.workspace_id == self.workspace_id,
                ProcessingRun.source_id == source_id,
                ProcessingRun.stage == stage,
                ProcessingRun.status == ProcessingRunStatus.RUNNING,
            )
            .values(status=ProcessingRunStatus.ABANDONED, finished_at=at, updated_at=func.now())
        )
        return _affected_rows(result)

    async def latest(self, source_id: uuid.UUID) -> dict[ProcessingStage, ProcessingRun]:
        """The last run of each stage of the source."""
        newest = (
            select(ProcessingRun)
            .where(
                ProcessingRun.workspace_id == self.workspace_id,
                ProcessingRun.source_id == source_id,
            )
            .distinct(ProcessingRun.stage)
            .order_by(ProcessingRun.stage, ProcessingRun.started_at.desc())
        )
        rows = (await self._session.execute(newest)).scalars().all()
        return {row.stage: row for row in rows}

    def history(self, source_id: uuid.UUID) -> Select[tuple[ProcessingRun]]:
        """The source's runs, every stage, newest first: for serve_page."""
        return select(ProcessingRun).where(
            ProcessingRun.workspace_id == self.workspace_id,
            ProcessingRun.source_id == source_id,
        )

    async def job_states(self, keys: dict[str, ProcessingStage]) -> dict[ProcessingStage, str]:
        """Which stages have a job under way — `running` on a worker, or
        `queued` — read from the job runs by their concurrency keys, like
        a pass's (SourceSyncRepository.passes)."""
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

    async def delete_rows(self, source_id: uuid.UUID, stage: ProcessingStage) -> int:
        """Every row the stage made for the source — and, by cascade, what
        the later stages made from them. For a reprocess, on request."""
        statement: Any
        if stage is ProcessingStage.EXTRACTION:
            statement = delete(ExtractedRecordRow).where(
                ExtractedRecordRow.workspace_id == self.workspace_id,
                ExtractedRecordRow.source_id == source_id,
            )
        elif stage is ProcessingStage.PARSING:
            statement = delete(ParsedRecordRow).where(
                ParsedRecordRow.workspace_id == self.workspace_id,
                ParsedRecordRow.source_id == source_id,
            )
        elif stage is ProcessingStage.VALIDATION:
            statement = delete(ValidatedRecordRow).where(
                ValidatedRecordRow.workspace_id == self.workspace_id,
                ValidatedRecordRow.source_id == source_id,
            )
        else:
            statement = delete(NormalisedRecordRow).where(
                NormalisedRecordRow.workspace_id == self.workspace_id,
                NormalisedRecordRow.source_id == source_id,
            )
        result = await self._session.execute(statement)
        return _affected_rows(result)


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


class WebhookDeliveryRepository(WorkspaceScopedRepository):
    """What a workspace's webhook sources received (LEKA-350): their inbox,
    then their log."""

    def keep(
        self,
        *,
        source_id: uuid.UUID,
        received_at: datetime,
        status: DeliveryStatus,
        size_bytes: int,
        delivery_id: str | None = None,
        resource: str | None = None,
        records: int = 0,
        gone: int = 0,
        body: bytes | None = None,
        error: dict[str, object] | None = None,
    ) -> WebhookDelivery:
        """Stage one delivery. Only a pending one keeps its body."""
        row = WebhookDelivery(
            source_id=source_id,
            received_at=received_at,
            status=status,
            size_bytes=size_bytes,
            delivery_id=delivery_id,
            resource=resource,
            records=records,
            gone=gone,
            body=body if status is DeliveryStatus.PENDING else None,
            error=error,
            processed_at=None if status is DeliveryStatus.PENDING else received_at,
        )
        self.add(row)
        return row

    async def backlog(self, source_id: uuid.UUID) -> tuple[int, int]:
        """How many deliveries wait for a pass, and how many bytes they hold."""
        row = (
            await self._session.execute(
                select(func.count(), func.coalesce(func.sum(WebhookDelivery.size_bytes), 0)).where(
                    WebhookDelivery.workspace_id == self.workspace_id,
                    WebhookDelivery.source_id == source_id,
                    WebhookDelivery.status == DeliveryStatus.PENDING,
                )
            )
        ).one()
        return int(row[0]), int(row[1])

    async def pending(self, source_id: uuid.UUID, *, limit: int) -> Sequence[WebhookDelivery]:
        """The next deliveries to store, in the order they came."""
        return await self.list(
            self.select(WebhookDelivery)
            .where(
                WebhookDelivery.source_id == source_id,
                WebhookDelivery.status == DeliveryStatus.PENDING,
            )
            .order_by(WebhookDelivery.received_at, WebhookDelivery.id)
            .limit(limit)
        )

    def log(self, source_id: uuid.UUID) -> Select[tuple[WebhookDelivery]]:
        """A source's deliveries, for pagination; newest first by default."""
        return self.select(WebhookDelivery).where(WebhookDelivery.source_id == source_id)


PLURAL = {"merge": "merges", "link": "links", "ambiguous": "ambiguous"}


class ValidationRepository(WorkspaceScopedRepository):
    """What validation found of a source's normalised records (LEKA-358).

    A normalised record needs validating when it was normalised and has no
    row yet, when it was normalised again since (`normalised_at`), or when
    the rules changed (`validator_version`). Validating needs when a pass
    last saw its record: `stale` returns that too.
    """

    model = ValidatedRecordRow

    def _stale(self, source_id: uuid.UUID, version: int) -> Select[Any]:
        normalised, row = NormalisedRecordRow, ValidatedRecordRow
        return (
            select(normalised, SourceRecord.last_seen_at)
            .join(ParsedRecordRow, ParsedRecordRow.id == normalised.parsed_record_id)
            .join(ExtractedRecordRow, ExtractedRecordRow.id == ParsedRecordRow.extracted_record_id)
            .join(SourceRecord, SourceRecord.id == ExtractedRecordRow.source_record_id)
            .outerjoin(row, row.normalised_record_id == normalised.id)
            .where(
                normalised.workspace_id == self.workspace_id,
                normalised.source_id == source_id,
                normalised.status == NormalisationStatus.NORMALISED,
                or_(
                    row.id.is_(None),
                    row.normalised_at != normalised.normalised_at,
                    row.validator_version != version,
                ),
            )
        )

    async def stale(
        self, source_id: uuid.UUID, version: int, *, after: uuid.UUID | None, limit: int
    ) -> list[tuple[NormalisedRecordRow, datetime | None]]:
        statement = self._stale(source_id, version).order_by(NormalisedRecordRow.id).limit(limit)
        if after is not None:
            statement = statement.where(NormalisedRecordRow.id > after)
        rows = await self._session.execute(statement)
        return [(normalised, seen_at) for normalised, seen_at in rows.all()]

    async def has_stale(self, source_id: uuid.UUID, version: int) -> bool:
        found = await self._session.execute(
            self._stale(source_id, version).with_only_columns(NormalisedRecordRow.id).limit(1)
        )
        return found.first() is not None

    async def duplicate_keys(self, source_id: uuid.UUID) -> set[str]:
        """The entity keys two or more of the source's records make."""
        rows = await self._session.execute(
            select(NormalisedRecordRow.entity_key)
            .where(
                NormalisedRecordRow.workspace_id == self.workspace_id,
                NormalisedRecordRow.source_id == source_id,
                NormalisedRecordRow.status == NormalisationStatus.NORMALISED,
            )
            .group_by(NormalisedRecordRow.entity_key)
            .having(func.count() > 1)
        )
        return {key for (key,) in rows.all() if key}

    async def forget_unvalidatable(self, source_id: uuid.UUID) -> int:
        """Records that failed normalisation since lose their validation."""
        failed = select(NormalisedRecordRow.id).where(
            NormalisedRecordRow.workspace_id == self.workspace_id,
            NormalisedRecordRow.source_id == source_id,
            NormalisedRecordRow.status == NormalisationStatus.FAILED,
        )
        result = await self._session.execute(
            delete(ValidatedRecordRow).where(
                ValidatedRecordRow.workspace_id == self.workspace_id,
                ValidatedRecordRow.normalised_record_id.in_(failed),
            )
        )
        return _affected_rows(result)

    async def save(self, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        statement = insert(ValidatedRecordRow).values(
            [{"workspace_id": self.workspace_id, **row} for row in rows]
        )
        excluded = statement.excluded
        columns = (
            "kind",
            "entity_type",
            "entity_key",
            "status",
            "issues",
            "quality",
            "completeness",
            "consistency",
            "freshness",
            "confidence",
            "seen_at",
            "normalised_at",
            "validator_version",
            "run_id",
            "validated_at",
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_validated_records_normalised_record",
                set_={c: getattr(excluded, c) for c in columns} | {"updated_at": func.now()},
            )
        )

    def _of(self, source_id: uuid.UUID) -> Any:
        return and_(
            ValidatedRecordRow.workspace_id == self.workspace_id,
            ValidatedRecordRow.source_id == source_id,
        )

    async def statuses(self, source_id: uuid.UUID | None = None) -> dict[uuid.UUID, dict[str, int]]:
        """How many valid, warning, quarantined — per source of the workspace."""
        statement = (
            select(ValidatedRecordRow.source_id, ValidatedRecordRow.status, func.count())
            .where(ValidatedRecordRow.workspace_id == self.workspace_id)
            .group_by(ValidatedRecordRow.source_id, ValidatedRecordRow.status)
        )
        if source_id is not None:
            statement = statement.where(ValidatedRecordRow.source_id == source_id)
        found: dict[uuid.UUID, dict[str, int]] = {}
        for source, status, count in (await self._session.execute(statement)).all():
            found.setdefault(source, {s.value: 0 for s in ValidationStatus})[str(status)] = int(
                count
            )
        return found

    async def averages(
        self, source_id: uuid.UUID | None = None
    ) -> dict[uuid.UUID, dict[str, float]]:
        """The mean of each score, per source — quarantined records left out
        of quality, which is 0 for them by rule."""
        row = ValidatedRecordRow
        statement = (
            select(
                row.source_id,
                func.avg(row.quality).filter(row.status != ValidationStatus.QUARANTINED),
                func.avg(row.completeness),
                func.avg(row.consistency),
                func.avg(row.freshness),
                func.avg(row.confidence),
                func.max(row.validated_at),
            )
            .where(row.workspace_id == self.workspace_id)
            .group_by(row.source_id)
        )
        if source_id is not None:
            statement = statement.where(row.source_id == source_id)
        found: dict[uuid.UUID, dict[str, Any]] = {}
        for source, *values, last in (await self._session.execute(statement)).all():
            names = ("quality", "completeness", "consistency", "freshness", "confidence")
            found[source] = {
                name: round(float(value), 2) if value is not None else None
                for name, value in zip(names, values, strict=True)
            } | {"validated_at": last}
        return found

    async def issue_counts(self, source_id: uuid.UUID) -> list[tuple[str, str, str, int]]:
        """(code, severity, remediation, how many records) for the source, the
        most frequent first."""
        issue = (
            func.jsonb_array_elements(ValidatedRecordRow.issues).table_valued("value").alias("i")
        )
        code = issue.c.value.op("->>")("code")
        severity = issue.c.value.op("->>")("severity")
        remedy = issue.c.value.op("->>")("remediation")
        rows = await self._session.execute(
            select(code, severity, remedy, func.count(func.distinct(ValidatedRecordRow.id)))
            .select_from(ValidatedRecordRow)
            .join(issue, true())
            .where(self._of(source_id))
            .group_by(code, severity, remedy)
            .order_by(func.count(func.distinct(ValidatedRecordRow.id)).desc(), code)
        )
        return [(str(c), str(s), str(r), int(n)) for c, s, r, n in rows.all()]

    async def quarantined(self, source_id: uuid.UUID, limit: int) -> Sequence[ValidatedRecordRow]:
        """The latest quarantined records of the source."""
        return await self.list(
            self.select(ValidatedRecordRow)
            .where(
                ValidatedRecordRow.source_id == source_id,
                ValidatedRecordRow.status == ValidationStatus.QUARANTINED,
            )
            .order_by(ValidatedRecordRow.validated_at.desc(), ValidatedRecordRow.id)
            .limit(limit)
        )


class ResolutionRepository(WorkspaceScopedRepository):
    """Entity resolution's rows (LEKA-357): what it reads of normalisation,
    and what it made — replaced whole at each run, the ids kept."""

    async def fingerprint(self) -> str:
        """What normalisation and validation (LEKA-358) have made so far: how
        many rows of each, and the latest. A row replaced moves the latest;
        one removed, the count."""
        found = []
        for model, stamp in (
            (NormalisedRecordRow, NormalisedRecordRow.normalised_at),
            (ValidatedRecordRow, ValidatedRecordRow.validated_at),
        ):
            count, latest = (
                await self._session.execute(
                    select(func.count(), func.max(stamp)).where(
                        model.workspace_id == self.workspace_id
                    )
                )
            ).one()
            found.append(f"{int(count)}:{latest.isoformat() if latest else '-'}")
        return "|".join(found)

    async def latest_run(self, *, succeeded: bool = False) -> ResolutionRun | None:
        statement = self.select(ResolutionRun)
        if succeeded:
            statement = statement.where(ResolutionRun.status == "succeeded")
        found = await self._session.execute(
            statement.order_by(ResolutionRun.started_at.desc()).limit(1)
        )
        return found.scalar_one_or_none()

    async def pending(self, fingerprint: str, version: int) -> bool:
        """Whether resolving now would read anything the last success did not:
        normalisation moved since, or the rules did."""
        last = await self.latest_run(succeeded=True)
        return last is None or last.fingerprint != fingerprint or last.resolver_version != version

    async def start(self, fingerprint: str, version: int, *, at: datetime) -> ResolutionRun:
        """A new run. One still `running` is one whose worker died — one run
        at a time per workspace (resolve:<workspace>) — and is closed first."""
        await self._session.execute(
            update(ResolutionRun)
            .where(
                ResolutionRun.workspace_id == self.workspace_id,
                ResolutionRun.status == "running",
            )
            .values(status="abandoned", finished_at=at, updated_at=func.now())
        )
        run = ResolutionRun(
            status="running", started_at=at, fingerprint=fingerprint, resolver_version=version
        )
        self.add(run)
        await self.flush()
        return run

    async def normalised(
        self, *, after: uuid.UUID | None, limit: int
    ) -> Sequence[tuple[uuid.UUID, uuid.UUID, dict[str, object], float | None]]:
        """The next `limit` candidates' rows, by id: (row id, source, result,
        the quality validation gave it). A QUARANTINED record is not among
        them (LEKA-358); one not validated yet is — validation catches up,
        and resolution runs again."""
        validated = ValidatedRecordRow
        statement = (
            select(
                NormalisedRecordRow.id,
                NormalisedRecordRow.source_id,
                NormalisedRecordRow.result,
                validated.quality,
            )
            .outerjoin(validated, validated.normalised_record_id == NormalisedRecordRow.id)
            .where(
                NormalisedRecordRow.workspace_id == self.workspace_id,
                NormalisedRecordRow.status == NormalisationStatus.NORMALISED,
                or_(validated.id.is_(None), validated.status != ValidationStatus.QUARANTINED),
            )
            .order_by(NormalisedRecordRow.id)
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(NormalisedRecordRow.id > after)
        rows = await self._session.execute(statement)
        return [
            (row_id, source_id, result or {}, quality)
            for row_id, source_id, result, quality in rows.all()
        ]

    async def previous_ids(self) -> dict[str, set[uuid.UUID]]:
        """Which entity each key belonged to at the last run."""
        rows = await self._session.execute(
            select(ResolvedKey.key, ResolvedKey.entity_id).where(
                ResolvedKey.workspace_id == self.workspace_id
            )
        )
        found: dict[str, set[uuid.UUID]] = {}
        for key, entity_id in rows.all():
            found.setdefault(key, set()).add(entity_id)
        return found

    async def clear(self) -> None:
        """Everything the last run made; the keys and decisions go with their
        entities."""
        await self._session.execute(
            delete(ResolvedEntity).where(ResolvedEntity.workspace_id == self.workspace_id)
        )

    async def write(self, model: type[Any], rows: list[dict[str, object]]) -> None:
        for start in range(0, len(rows), 1_000):
            chunk = rows[start : start + 1_000]
            await self._session.execute(
                insert(model).values([{"workspace_id": self.workspace_id, **row} for row in chunk])
            )

    def entities(self) -> Select[tuple[ResolvedEntity]]:
        """The workspace's resolved entities, for pagination."""
        return self.select(ResolvedEntity)

    async def keys_of(self, entity_ids: Sequence[uuid.UUID]) -> Sequence[ResolvedKey]:
        return await self.list(
            self.select(ResolvedKey)
            .where(ResolvedKey.entity_id.in_(list(entity_ids)))
            .order_by(ResolvedKey.kind, ResolvedKey.key)
        )

    async def decisions_of(self, entity_id: uuid.UUID) -> Sequence[ResolutionDecision]:
        return await self.list(
            self.select(ResolutionDecision)
            .where(
                or_(
                    ResolutionDecision.entity_id == entity_id,
                    ResolutionDecision.other_entity_id == entity_id,
                )
            )
            .order_by(ResolutionDecision.kind, ResolutionDecision.confidence.desc())
        )

    async def links_among(
        self, entity_ids: Sequence[uuid.UUID]
    ) -> list[tuple[uuid.UUID, uuid.UUID, str, float, str]]:
        """The links between these entities: two things resolution found
        probably the same and kept apart — each pair once, with its rule,
        confidence and evidence (LEKA-372: a context folds them)."""
        ids = list(set(entity_ids))
        if len(ids) < 2:
            return []
        rows = await self.list(
            self.select(ResolutionDecision)
            .where(
                ResolutionDecision.kind == "link",
                ResolutionDecision.entity_id.in_(ids),
                ResolutionDecision.other_entity_id.in_(ids),
            )
            .order_by(ResolutionDecision.confidence.desc(), ResolutionDecision.entity_id)
        )
        seen: set[frozenset[uuid.UUID]] = set()
        links: list[tuple[uuid.UUID, uuid.UUID, str, float, str]] = []
        for row in rows:
            if row.other_entity_id is None:
                continue
            pair = frozenset({row.entity_id, row.other_entity_id})
            if pair in seen:
                continue
            seen.add(pair)
            links.append(
                (row.entity_id, row.other_entity_id, row.rule, row.confidence, row.evidence)
            )
        return links

    async def holding(self, key: str) -> Sequence[ResolvedEntity]:
        """The entities a key names: one — or several, when it is ambiguous."""
        held = select(ResolvedKey.entity_id).where(
            ResolvedKey.workspace_id == self.workspace_id, ResolvedKey.key == key
        )
        return await self.list(
            self.select(ResolvedEntity)
            .where(ResolvedEntity.id.in_(held))
            .order_by(ResolvedEntity.confidence.desc(), ResolvedEntity.key)
        )

    async def counts(self) -> dict[str, int]:
        """What the workspace resolves to now."""
        entities = await self._session.scalar(
            select(func.count()).where(ResolvedEntity.workspace_id == self.workspace_id)
        )
        by_kind = await self._session.execute(
            select(ResolutionDecision.kind, func.count())
            .where(ResolutionDecision.workspace_id == self.workspace_id)
            .group_by(ResolutionDecision.kind)
        )
        conflicted = await self._session.scalar(
            select(func.count()).where(
                ResolvedEntity.workspace_id == self.workspace_id,
                func.jsonb_array_length(ResolvedEntity.conflicts) > 0,
            )
        )
        return {
            "entities": int(entities or 0),
            "conflicted": int(conflicted or 0),
            **{PLURAL.get(kind, kind): int(n) for kind, n in by_kind.all()},
        }


class EnrichmentRepository(WorkspaceScopedRepository):
    """Enrichment's rows (LEKA-359): what it reads of resolution and of what
    the sources stated, and what it made — replaced whole at each run."""

    async def basis(self) -> uuid.UUID | None:
        """The resolution run enrichment reads: the latest that succeeded."""
        found = await self._session.scalar(
            select(ResolutionRun.id)
            .where(
                ResolutionRun.workspace_id == self.workspace_id,
                ResolutionRun.status == "succeeded",
            )
            .order_by(ResolutionRun.started_at.desc())
            .limit(1)
        )
        return found

    async def latest_run(self, *, succeeded: bool = False) -> EnrichmentRun | None:
        statement = self.select(EnrichmentRun)
        if succeeded:
            statement = statement.where(EnrichmentRun.status == "succeeded")
        found = await self._session.execute(
            statement.order_by(EnrichmentRun.started_at.desc()).limit(1)
        )
        return found.scalar_one_or_none()

    async def pending(self, basis: uuid.UUID | None, version: int) -> bool:
        """Whether enriching now would read anything the last success did
        not: a newer resolution run, or new rules. Nothing resolved yet:
        nothing to enrich."""
        if basis is None:
            return False
        last = await self.latest_run(succeeded=True)
        return last is None or last.resolution_run_id != basis or last.enricher_version != version

    async def start(self, basis: uuid.UUID | None, version: int, *, at: datetime) -> EnrichmentRun:
        """A new run. One still `running` is one whose worker died — one run
        at a time per workspace (enrich:<workspace>) — and is closed first."""
        await self._session.execute(
            update(EnrichmentRun)
            .where(
                EnrichmentRun.workspace_id == self.workspace_id,
                EnrichmentRun.status == "running",
            )
            .values(status="abandoned", finished_at=at, updated_at=func.now())
        )
        run = EnrichmentRun(
            status="running", started_at=at, resolution_run_id=basis, enricher_version=version
        )
        self.add(run)
        await self.flush()
        return run

    async def entities(self) -> Sequence[tuple[uuid.UUID, str, str, str, dict[str, object]]]:
        """Every resolved entity: (id, type, key, name, attributes)."""
        rows = await self._session.execute(
            select(
                ResolvedEntity.id,
                ResolvedEntity.type,
                ResolvedEntity.key,
                ResolvedEntity.name,
                ResolvedEntity.attributes,
            ).where(ResolvedEntity.workspace_id == self.workspace_id)
        )
        return [tuple(row) for row in rows.all()]

    async def keys(self) -> Sequence[tuple[uuid.UUID, str, uuid.UUID]]:
        """Every key an entity goes by, per source: (entity, key, source)."""
        rows = await self._session.execute(
            select(ResolvedKey.entity_id, ResolvedKey.key, ResolvedKey.source_id).where(
                ResolvedKey.workspace_id == self.workspace_id
            )
        )
        return [tuple(row) for row in rows.all()]

    async def records(
        self, *, after: uuid.UUID | None, limit: int
    ) -> Sequence[tuple[uuid.UUID, uuid.UUID, str | None, object, object]]:
        """The next `limit` normalised rows, by id: (row id, source, its
        entity's key, that entity's attributes, the relationships it
        states) — as normalisation wrote them. A QUARANTINED record is not
        among them (LEKA-358), as resolution does not read its entity."""
        validated = ValidatedRecordRow
        statement = (
            select(
                NormalisedRecordRow.id,
                NormalisedRecordRow.source_id,
                NormalisedRecordRow.entity_key,
                NormalisedRecordRow.result["entity"]["attributes"],
                NormalisedRecordRow.result["relationships"],
            )
            .outerjoin(validated, validated.normalised_record_id == NormalisedRecordRow.id)
            .where(
                NormalisedRecordRow.workspace_id == self.workspace_id,
                NormalisedRecordRow.status == NormalisationStatus.NORMALISED,
                or_(validated.id.is_(None), validated.status != ValidationStatus.QUARANTINED),
            )
            .order_by(NormalisedRecordRow.id)
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(NormalisedRecordRow.id > after)
        rows = await self._session.execute(statement)
        return [tuple(row) for row in rows.all()]

    async def replace(self, enrichment: Enrichment, *, run_id: uuid.UUID, at: datetime) -> None:
        """What the last run made, replaced by this one's — in the caller's
        transaction: all of it, or nothing."""
        for model in (EnrichedRelationship, EntityEnrichment):
            await self._session.execute(
                delete(model).where(model.workspace_id == self.workspace_id)
            )
        await self._insert(
            EnrichedRelationship,
            [
                {
                    "from_entity_id": edge.from_id,
                    "to_entity_id": edge.to_id,
                    "type": edge.type,
                    "origin": edge.origin,
                    "rule": edge.rule,
                    "confidence": edge.confidence,
                    "cross_source": edge.cross_source,
                    "sources": len(edge.sources),
                    "evidence": edge.evidence[:1000],
                    "provenance": edge.provenance,
                    "run_id": run_id,
                    "enriched_at": at,
                }
                for edge in enrichment.edges
            ],
        )
        await self._insert(
            EntityEnrichment,
            [
                {
                    "entity_id": fact.entity_id,
                    "attribute": fact.attribute,
                    "value": fact.value,
                    "confidence": fact.confidence,
                    "rule": fact.rule,
                    "evidence": fact.evidence[:1000],
                    "inputs": list(fact.inputs),
                    "run_id": run_id,
                    "enriched_at": at,
                }
                for fact in enrichment.facts
            ],
        )

    async def _insert(self, model: type[Any], rows: list[dict[str, object]]) -> None:
        for start in range(0, len(rows), 1_000):
            chunk = rows[start : start + 1_000]
            await self._session.execute(
                insert(model).values([{"workspace_id": self.workspace_id, **row} for row in chunk])
            )

    # ── reads ────────────────────────────────────────────────────────────────

    def _resolved(self) -> Select[tuple[uuid.UUID]]:
        return select(ResolvedEntity.id).where(ResolvedEntity.workspace_id == self.workspace_id)

    def relationships_page(self) -> Select[tuple[EnrichedRelationship]]:
        """The workspace's enriched relationships whose two ends resolution
        still has, for pagination."""
        return self.select(EnrichedRelationship).where(
            EnrichedRelationship.from_entity_id.in_(self._resolved()),
            EnrichedRelationship.to_entity_id.in_(self._resolved()),
        )

    async def enrichments_of(self, entity_id: uuid.UUID) -> Sequence[EntityEnrichment]:
        return await self.list(
            self.select(EntityEnrichment)
            .where(EntityEnrichment.entity_id == entity_id)
            .order_by(EntityEnrichment.attribute)
        )

    async def edges_of(
        self, entity_id: uuid.UUID, *, outgoing: bool, limit: int
    ) -> tuple[Sequence[EnrichedRelationship], int]:
        """An entity's relationships one way — the surest first, by type —
        whose other end resolution still has; and how many there are."""
        this, other = (
            (EnrichedRelationship.from_entity_id, EnrichedRelationship.to_entity_id)
            if outgoing
            else (EnrichedRelationship.to_entity_id, EnrichedRelationship.from_entity_id)
        )
        where = (
            EnrichedRelationship.workspace_id == self.workspace_id,
            this == entity_id,
            other.in_(self._resolved()),
        )
        total = await self._session.scalar(
            select(func.count()).select_from(EnrichedRelationship).where(*where)
        )
        edges = await self.list(
            select(EnrichedRelationship)
            .where(*where)
            .order_by(
                EnrichedRelationship.type,
                EnrichedRelationship.confidence.desc(),
                EnrichedRelationship.id,
            )
            .limit(limit)
        )
        return edges, int(total or 0)

    async def entities_by_id(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, ResolvedEntity]:
        if not ids:
            return {}
        found = await self.list(self.select(ResolvedEntity).where(ResolvedEntity.id.in_(set(ids))))
        return {entity.id: entity for entity in found}

    async def counts(self) -> dict[str, int]:
        """What the workspace's enrichment holds now."""
        edges = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count().filter(EnrichedRelationship.origin == "stated"),
                    func.count().filter(EnrichedRelationship.origin == "inferred"),
                    func.count().filter(EnrichedRelationship.cross_source.is_(True)),
                ).where(EnrichedRelationship.workspace_id == self.workspace_id)
            )
        ).one()
        attributes = await self._session.scalar(
            select(func.count()).where(EntityEnrichment.workspace_id == self.workspace_id)
        )
        return {
            "relationships": int(edges[0]),
            "stated": int(edges[1]),
            "inferred": int(edges[2]),
            "cross_source": int(edges[3]),
            "attributes": int(attributes or 0),
        }

    async def by_rule(self) -> dict[str, dict[str, int]]:
        """How many relationships each rule made, per type; how many of each
        attribute."""
        edges = await self._session.execute(
            select(EnrichedRelationship.type, EnrichedRelationship.rule, func.count())
            .where(EnrichedRelationship.workspace_id == self.workspace_id)
            .group_by(EnrichedRelationship.type, EnrichedRelationship.rule)
        )
        attributes = await self._session.execute(
            select(EntityEnrichment.attribute, func.count())
            .where(EntityEnrichment.workspace_id == self.workspace_id)
            .group_by(EntityEnrichment.attribute)
        )
        relationships: dict[str, int] = {}
        for kind, rule, n in edges.all():
            relationships[f"{kind}:{rule}"] = int(n)
        return {
            "relationships": relationships,
            "attributes": {name: int(n) for name, n in attributes.all()},
        }

    # ── the environment screens (LEKA-359, mockups 10 and 11) ───────────────

    def _as_text(self) -> Any:
        """An enriched value, as text: a date compares as one."""
        return EntityEnrichment.value.op("#>>")(literal_column("'{}'"))

    async def things(
        self, *, types: Sequence[str] | None = None, ids: Sequence[uuid.UUID] | None = None
    ) -> Sequence[tuple[uuid.UUID, str, str, str, dict[str, object]]]:
        """Resolved entities of some types, or by id: (id, type, key, name,
        attributes)."""
        statement = select(
            ResolvedEntity.id,
            ResolvedEntity.type,
            ResolvedEntity.key,
            ResolvedEntity.name,
            ResolvedEntity.attributes,
        ).where(ResolvedEntity.workspace_id == self.workspace_id)
        if types is not None:
            statement = statement.where(ResolvedEntity.type.in_(list(types)))
        if ids is not None:
            statement = statement.where(ResolvedEntity.id.in_(list(set(ids))))
        rows = await self._session.execute(statement)
        return [tuple(row) for row in rows.all()]

    async def mentioning(
        self, name: str, *, types: Sequence[str], limit: int = 20
    ) -> Sequence[tuple[uuid.UUID, str, str, str, dict[str, object]]]:
        """Entities of these types whose name or what their source said of
        them names `name` — case aside: (id, type, key, name, attributes)."""
        pattern = f"%{name.replace('%', r'\%').replace('_', r'\_')}%"
        rows = await self._session.execute(
            select(
                ResolvedEntity.id,
                ResolvedEntity.type,
                ResolvedEntity.key,
                ResolvedEntity.name,
                ResolvedEntity.attributes,
            )
            .where(
                ResolvedEntity.workspace_id == self.workspace_id,
                ResolvedEntity.type.in_(list(types)),
                ResolvedEntity.name.ilike(pattern)
                | as_type(ResolvedEntity.attributes, Text).ilike(pattern),
            )
            .order_by(ResolvedEntity.name)
            .limit(limit)
        )
        return [tuple(row) for row in rows.all()]

    async def facts_of(
        self, entity_ids: Sequence[uuid.UUID], attributes: Sequence[str]
    ) -> dict[uuid.UUID, dict[str, object]]:
        """Some enriched attributes of some entities."""
        if not entity_ids:
            return {}
        rows = await self._session.execute(
            select(
                EntityEnrichment.entity_id, EntityEnrichment.attribute, EntityEnrichment.value
            ).where(
                EntityEnrichment.workspace_id == self.workspace_id,
                EntityEnrichment.entity_id.in_(list(set(entity_ids))),
                EntityEnrichment.attribute.in_(list(attributes)),
            )
        )
        found: dict[uuid.UUID, dict[str, object]] = defaultdict(dict)
        for entity_id, attribute, value in rows.all():
            found[entity_id][attribute] = value
        return dict(found)

    async def connected_kinds(self) -> set[str]:
        """The kinds of the workspace's sources LEKA reads from: active, or
        degraded but still answering."""
        rows = await self._session.scalars(
            select(Source.kind).where(
                Source.workspace_id == self.workspace_id,
                Source.status.in_(["active", "degraded"]),
            )
        )
        return {str(kind.value if hasattr(kind, "value") else kind) for kind in rows}

    async def kinds_of(self, entity_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
        """The kinds of the sources that show each entity: github, jira…"""
        if not entity_ids:
            return {}
        rows = await self._session.execute(
            select(ResolvedKey.entity_id, Source.kind)
            .join(Source, Source.id == ResolvedKey.source_id)
            .where(
                ResolvedKey.workspace_id == self.workspace_id,
                ResolvedKey.entity_id.in_(list(set(entity_ids))),
            )
            .distinct()
        )
        found: dict[uuid.UUID, set[str]] = defaultdict(set)
        for entity_id, kind in rows.all():
            found[entity_id].add(str(kind.value if hasattr(kind, "value") else kind))
        return dict(found)

    async def sources_of(self, entity_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, set[uuid.UUID]]:
        """The sources that show each entity (LEKA-442): what its state rests on."""
        if not entity_ids:
            return {}
        rows = await self._session.execute(
            select(ResolvedKey.entity_id, ResolvedKey.source_id)
            .where(
                ResolvedKey.workspace_id == self.workspace_id,
                ResolvedKey.entity_id.in_(list(set(entity_ids))),
            )
            .distinct()
        )
        found: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for entity_id, source_id in rows.all():
            found[entity_id].add(source_id)
        return dict(found)

    async def workspace_sources(self) -> Sequence[Source]:
        """The workspace's sources, as the connectors hold them now."""
        rows = await self._session.scalars(
            select(Source).where(Source.workspace_id == self.workspace_id).order_by(Source.name)
        )
        return list(rows.all())

    async def links_among(
        self, types: Sequence[str], edge_types: Sequence[str]
    ) -> Sequence[tuple[uuid.UUID, uuid.UUID, str]]:
        """The relationships of some types between entities of some types."""
        among = select(ResolvedEntity.id).where(
            ResolvedEntity.workspace_id == self.workspace_id,
            ResolvedEntity.type.in_(list(types)),
        )
        rows = await self._session.execute(
            select(
                EnrichedRelationship.from_entity_id,
                EnrichedRelationship.to_entity_id,
                EnrichedRelationship.type,
            ).where(
                EnrichedRelationship.workspace_id == self.workspace_id,
                EnrichedRelationship.type.in_(list(edge_types)),
                EnrichedRelationship.from_entity_id.in_(among),
                EnrichedRelationship.to_entity_id.in_(among),
            )
        )
        return [tuple(row) for row in rows.all()]

    async def links_of(
        self, entity_ids: Sequence[uuid.UUID], edge_types: Sequence[str]
    ) -> Sequence[tuple[uuid.UUID, uuid.UUID, str]]:
        """The relationships of some types from or to some entities."""
        if not entity_ids:
            return []
        ids = list(set(entity_ids))
        rows = await self._session.execute(
            select(
                EnrichedRelationship.from_entity_id,
                EnrichedRelationship.to_entity_id,
                EnrichedRelationship.type,
            ).where(
                EnrichedRelationship.workspace_id == self.workspace_id,
                EnrichedRelationship.type.in_(list(edge_types)),
                or_(
                    EnrichedRelationship.from_entity_id.in_(ids),
                    EnrichedRelationship.to_entity_id.in_(ids),
                ),
            )
        )
        return [tuple(row) for row in rows.all()]

    async def open_incidents(self) -> Sequence[uuid.UUID]:
        """The incidents not resolved: open, in progress."""
        rows = await self._session.execute(
            select(ResolvedEntity.id).where(
                ResolvedEntity.workspace_id == self.workspace_id,
                ResolvedEntity.type == "incident",
                ResolvedEntity.attributes["state"].astext.in_(["open", "in_progress"]),
            )
        )
        return list(rows.scalars().all())

    async def moved_since(
        self,
        since: str,
        *,
        types: Sequence[str] | None = None,
        exclude: Sequence[str] = (),
        limit: int | None = None,
        among: Sequence[uuid.UUID] | None = None,
    ) -> Sequence[tuple[uuid.UUID, str]]:
        """The entities whose last activity is `since` or later — an ISO
        date — the latest first: (id, when)."""
        when = self._as_text()
        statement = (
            select(EntityEnrichment.entity_id, when)
            .join(ResolvedEntity, ResolvedEntity.id == EntityEnrichment.entity_id)
            .where(
                EntityEnrichment.workspace_id == self.workspace_id,
                EntityEnrichment.attribute == "last_activity_at",
                when >= since,
            )
            .order_by(when.desc(), EntityEnrichment.entity_id)
        )
        if types is not None:
            statement = statement.where(ResolvedEntity.type.in_(list(types)))
        if exclude:
            statement = statement.where(ResolvedEntity.type.not_in(list(exclude)))
        if among is not None:
            statement = statement.where(EntityEnrichment.entity_id.in_(list(set(among))))
        if limit is not None:
            statement = statement.limit(limit)
        rows = await self._session.execute(statement)
        return [(entity_id, str(at)) for entity_id, at in rows.all()]

    async def count_where(self, attribute: str, value: object) -> int:
        """How many entities have an enriched attribute of this value."""
        found = await self._session.scalar(
            select(func.count()).where(
                EntityEnrichment.workspace_id == self.workspace_id,
                EntityEnrichment.attribute == attribute,
                EntityEnrichment.value == literal(value, JSONB),
            )
        )
        return int(found or 0)

    async def finished_at(self) -> datetime | None:
        """When the last enrichment that succeeded finished."""
        last = await self.latest_run(succeeded=True)
        return last.finished_at if last else None

    # ── what the company model is built from (LEKA-361) ─────────────────────

    async def latest_enrichment(self) -> uuid.UUID | None:
        """The last enrichment run that succeeded: what the model reads."""
        last = await self.latest_run(succeeded=True)
        return last.id if last else None

    async def resolved(
        self,
    ) -> Sequence[
        tuple[
            uuid.UUID,
            str,
            str,
            str,
            dict[str, object],
            float,
            float | None,
            list[dict[str, object]],
        ]
    ]:
        """Every resolved entity: (id, type, key, name, attributes,
        confidence, quality, conflicts — every value its sources disagree
        on)."""
        rows = await self._session.execute(
            select(
                ResolvedEntity.id,
                ResolvedEntity.type,
                ResolvedEntity.key,
                ResolvedEntity.name,
                ResolvedEntity.attributes,
                ResolvedEntity.confidence,
                ResolvedEntity.quality,
                ResolvedEntity.conflicts,
            ).where(ResolvedEntity.workspace_id == self.workspace_id)
        )
        return [tuple(row) for row in rows.all()]

    async def seen_keys(
        self,
    ) -> Sequence[tuple[uuid.UUID, str, uuid.UUID, str, datetime | None, datetime | None]]:
        """Every key a resolved entity goes by, per source: (entity, key,
        source, kind, first seen, last seen)."""
        rows = await self._session.execute(
            select(
                ResolvedKey.entity_id,
                ResolvedKey.key,
                ResolvedKey.source_id,
                ResolvedKey.kind,
                ResolvedKey.first_seen_at,
                ResolvedKey.last_seen_at,
            ).where(ResolvedKey.workspace_id == self.workspace_id)
        )
        return [tuple(row) for row in rows.all()]

    async def enrichments(self) -> Sequence[tuple[uuid.UUID, str, object, str, float, str]]:
        """Every enriched attribute: (entity, attribute, value, rule,
        confidence, evidence)."""
        rows = await self._session.execute(
            select(
                EntityEnrichment.entity_id,
                EntityEnrichment.attribute,
                EntityEnrichment.value,
                EntityEnrichment.rule,
                EntityEnrichment.confidence,
                EntityEnrichment.evidence,
            ).where(EntityEnrichment.workspace_id == self.workspace_id)
        )
        return [tuple(row) for row in rows.all()]

    async def enriched_edges(self) -> Sequence[EnrichedRelationship]:
        """Every relationship enrichment made."""
        return await self.list(self.select(EnrichedRelationship))


class EnrichedWorkspaces:
    """Each workspace's last successful enrichment run, across every
    workspace: what the company model's sweep (LEKA-361) compares its builds
    with. Not workspace-scoped, like SyncScheduleRepository: it runs under
    system_scope, declared by its caller."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest(self) -> dict[uuid.UUID, uuid.UUID]:
        """workspace → its last enrichment run that succeeded."""
        rows = await self._session.execute(
            select(EnrichmentRun.workspace_id, EnrichmentRun.id)
            .where(EnrichmentRun.status == "succeeded")
            .distinct(EnrichmentRun.workspace_id)
            .order_by(EnrichmentRun.workspace_id, EnrichmentRun.started_at.desc())
        )
        return dict(rows.tuples().all())


@dataclass(frozen=True)
class EvidenceRow:
    """A record a thing of the company model was read from (LEKA-376): which
    source, its id there, what extraction said of it — its title, link,
    state, dates, the start of its text — when the source last showed it,
    and whether it is gone."""

    source_id: uuid.UUID
    kind: str
    external_id: str
    title: str | None
    url: str | None
    state: str | None
    created_at: str | None
    updated_at: str | None
    excerpt: str | None
    seen_at: datetime
    deleted_at: datetime | None


# The records' fields evidence reads, from source_records s and the
# extracted record x made of it.
_EVIDENCE = """
    SELECT DISTINCT ON (s.id)
           s.source_id, s.kind, s.external_id,
           x.result ->> 'title', x.result ->> 'url', x.result ->> 'state',
           x.result ->> 'created_at', x.result ->> 'updated_at',
           left(jsonb_path_query_first(x.result, '$.content[0].text') #>> '{}', :chars),
           s.last_seen_at, s.deleted_at
"""
_EVIDENCE_FROM = """
      JOIN parsed_records p ON p.id = n.parsed_record_id
      JOIN extracted_records x ON x.id = p.extracted_record_id AND x.status = 'extracted'
      JOIN source_records s ON s.id = x.source_record_id
"""


class ContentRepository(WorkspaceScopedRepository):
    """The records' own text, searched (LEKA-371): what a page, a ticket, a
    pull request says — not only what it is called — read back to the
    company model's things it is about. And the records behind a thing:
    its evidence (LEKA-376)."""

    async def evidence_of(
        self, entity_id: uuid.UUID, *, limit: int, chars: int
    ) -> list[EvidenceRow]:
        """The records an entity of the model was read from: every record
        whose key, from its source, entity resolution made this entity —
        the ones its sources still show first, the latest seen first."""
        return await self._evidence(
            """
            FROM resolved_keys k
            JOIN normalised_records n
              ON n.workspace_id = k.workspace_id
             AND n.source_id = k.source_id
             AND n.entity_key = k.key
            """
            + _EVIDENCE_FROM
            + "WHERE k.workspace_id = :workspace AND k.entity_id = :entity",
            {"entity": entity_id},
            limit=limit,
            chars=chars,
        )

    async def evidence_in(
        self, records: Sequence[uuid.UUID], *, limit: int, chars: int
    ) -> list[EvidenceRow]:
        """The records behind these normalised records — what stated a
        relationship (its provenance's `record_id`)."""
        if not records:
            return []
        return await self._evidence(
            "FROM normalised_records n"
            + _EVIDENCE_FROM
            + "WHERE n.workspace_id = :workspace AND n.id = ANY(CAST(:records AS uuid[]))",
            {"records": list(dict.fromkeys(records))},
            limit=limit,
            chars=chars,
        )

    async def _evidence(
        self, source: str, params: dict[str, object], *, limit: int, chars: int
    ) -> list[EvidenceRow]:
        rows = await self._session.execute(
            text(
                f"""
                SELECT * FROM ({_EVIDENCE} {source} ORDER BY s.id) AS found
                ORDER BY found.deleted_at IS NOT NULL, found.last_seen_at DESC, found.external_id
                LIMIT :limit
                """  # noqa: S608 — the fragments are this module's constants, the rest bound
            ),
            {**params, "workspace": self.workspace_id, "limit": limit, "chars": chars},
        )
        return [EvidenceRow(*row) for row in rows.tuples().all()]

    async def matching(self, tsquery: str, *, limit: int) -> list[tuple[uuid.UUID, float]]:
        """The entities whose records' text holds the words of `tsquery` — the
        best first, by how well the words match (ts_rank_cd) — each once,
        with its best record's rank. A record gone at its source is left out.

        A record is read back to its entity by the key normalisation gave it
        and the entity resolution made of that key, from that source: the
        resolved entity's id is the company model's (a build keeps it)."""
        words = CONTENT_WORDS.replace("result", "x.result")
        rows = await self._session.execute(
            text(
                f"""
                SELECT k.entity_id, max(ts_rank_cd({words}, q)) AS rank
                FROM extracted_records x
                JOIN source_records s ON s.id = x.source_record_id AND s.deleted_at IS NULL
                JOIN parsed_records p ON p.extracted_record_id = x.id
                JOIN normalised_records n
                  ON n.parsed_record_id = p.id AND n.entity_key IS NOT NULL
                JOIN resolved_keys k
                  ON k.workspace_id = x.workspace_id
                 AND k.source_id = n.source_id
                 AND k.key = n.entity_key,
                     to_tsquery('simple'::regconfig, :tsquery) AS q
                WHERE x.workspace_id = :workspace
                  AND x.status = 'extracted'
                  AND {words} @@ q
                GROUP BY k.entity_id
                ORDER BY rank DESC, k.entity_id
                LIMIT :limit
                """  # noqa: S608 — CONTENT_WORDS is this module's constant, the rest bound
            ),
            {"tsquery": tsquery, "workspace": self.workspace_id, "limit": limit},
        )
        return [(entity_id, float(rank)) for entity_id, rank in rows.tuples().all()]
