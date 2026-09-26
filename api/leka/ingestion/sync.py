"""The sync: reading a source into LEKA (LEKA-352).

One pass over one source. For each capability the source was found to offer
at its last test — repositories, commits, pull requests… — ask the connector
for what changed since the last successful pass, write what comes back to
the object store in batches, and record how far it got.

    source (active)  ──▶ connector.iter_resources(capability, since)
                            │  RawRecords, page by page
                            ▼
                     batches of BATCH_SIZE ──▶ object store + raw_payloads
                            │  committed batch by batch
                            ▼
                     source_syncs (cursor, counts, diagnostic)
                     sources.sync_status / last_synced_at (the summary)

THE CURSOR IS WHEN THE LAST SUCCESSFUL PASS STARTED (see SourceSync). A
failed pass does not move it; the next one reads from the same place, and
what the failed one already stored is stored again — a write, not a wrong
answer. Every FULL_RESYNC_EVERY a pass ignores the cursor and reads
everything: incremental reads trust every vendor's dates, and this is the
net under that trust.

FAILURES, AND WHO DEALS WITH THEM:

    retryable, soon    (network, 5xx, a short quota wait)
                       -> the state is recorded, then RetryableSyncError is
                          raised so the job runner retries with its backoff
    retryable, later   (a quota reset an hour away)
                       -> recorded, not raised: the schedule's next pass is
                          sooner than the runner's retries would be useful
    not retryable      (a revoked token, a permission taken away)
                       -> recorded, the source goes to `error`, and its
                          history says so once — it needs a person, not a
                          retry

The first failure is a `sync_failed` event and the first success after it
`sync_recovered`: a history an admin reads, not one line an hour.

Runs as a job (`run_sync`), one at a time per source — the caller holds the
concurrency key `sync:<source_id>` (leka.background.enqueue_job). Safe to
run twice: a second pass reads again from the same cursor.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import (
    Capability,
    Connector,
    ConnectorError,
    Diagnostic,
    DiagnosticCode,
    LifecycleEvent,
    RawRecord,
    Source,
    SourceEventType,
    SourceNotFoundError,
    SourceService,
    SourceStatus,
    SyncStatus,
    next_status,
)
from leka.db import session_factory, workspace_scope
from leka.ingestion.models import SourceSync, SyncRunStatus
from leka.ingestion.repository import RawPayloadRepository, SourceSyncRepository
from leka.ingestion.retention import expires_at
from leka.platform import from_bytes, object_key, object_store

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500
FULL_RESYNC_EVERY = timedelta(days=7)
# A retryable failure asked to wait longer than this is left to the next
# scheduled pass rather than to the runner's retries, which would all land
# inside the wait and fail again.
RETRY_SOON_SECONDS = 300
# Which sources are read: switched on. `error` is not — it is waiting for a
# person, and the health check or a test brings it back.
SYNCABLE = (SourceStatus.ACTIVE, SourceStatus.DEGRADED)
CONTENT_TYPE = "application/x-ndjson"


# What a pass records for the one before it that never finished.
ABANDONED = Diagnostic(
    code=DiagnosticCode.UNKNOWN,
    retryable=True,
    message="La synchronisation précédente s'est interrompue avant de finir.",
    remediation="Rien à faire : la suivante reprend depuis la dernière réussite.",
)


class RetryableSyncError(RuntimeError):
    """The pass failed for a reason that may pass: the runner retries it."""


@dataclass
class SyncReport:
    source_id: uuid.UUID
    status: str  # "succeeded", "failed", "skipped"
    records: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source_id": str(self.source_id),
            "status": self.status,
            "records": self.records,
            "error": self.error,
        }


def run_sync(workspace_id: str, source_id: str, full: bool = False) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    report = asyncio.run(sync_source(uuid.UUID(workspace_id), uuid.UUID(source_id), full=full))
    return report.as_dict()


async def sync_source(
    workspace_id: uuid.UUID, source_id: uuid.UUID, *, full: bool = False
) -> SyncReport:
    """One pass over one source. See the module docstring."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            return await _Pass(session, workspace_id, full=full).run(source_id)


class _Pass:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID, *, full: bool) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._full = full
        self._sources = SourceService(session, workspace_id, actor_user_id=None)
        self._syncs = SourceSyncRepository(session, workspace_id)
        self._payloads = RawPayloadRepository(session, workspace_id)

    async def run(self, source_id: uuid.UUID) -> SyncReport:
        report = SyncReport(source_id=source_id, status="skipped")
        try:
            source = await self._sources.get(source_id)
        except SourceNotFoundError:
            # Deleted since it was scheduled, or its workspace was.
            return report
        if source.status not in SYNCABLE:
            return report

        was_failing = source.sync_status is SyncStatus.FAILED
        source.sync_status = SyncStatus.RUNNING
        await self._session.commit()

        failure: Diagnostic | None = None
        try:
            connector = await self._sources.open_connector(source)
            for capability in _capabilities(source, connector.manifest.capabilities):
                count, failure = await self._capability(source, connector, capability)
                report.records[capability.value] = count
                if failure is not None:
                    break
        except ConnectorError as error:
            failure = error.diagnostic

        self._conclude(source, failure, was_failing=was_failing)
        await self._session.commit()

        report.status = "failed" if failure else "succeeded"
        report.error = failure.code.value if failure else None
        logger.info("source_synced", **report.as_dict())
        if failure and failure.retryable and (failure.retry_after or 0) <= RETRY_SOON_SECONDS:
            raise RetryableSyncError(f"{failure.code.value}: {failure.message}")
        return report

    async def _capability(
        self, source: Source, connector: Connector[Any, Any], capability: Capability
    ) -> tuple[int, Diagnostic | None]:
        """Read one capability. Returns what was stored, and why it stopped if it did."""
        row = await self._syncs.get_or_create(source.id, capability.value)
        if row.status is SyncRunStatus.RUNNING:
            # Only one pass at a time holds sync:<source_id>, so a `running`
            # found here is a pass whose worker died: the runner gave up on
            # its job, nothing else will ever touch this row. Counted as the
            # failure it was, then read as usual.
            _failed(row, ABANDONED, row.records_last_run)
        started = datetime.now(UTC)
        read_all = self._full or _due_for_full(row, started)
        if read_all:
            # Forgotten from the start, not the end: a full pass that fails
            # half-way leaves the next one full too, rather than an
            # incremental that would never read what this one did not reach.
            row.since = None
        row.status = SyncRunStatus.RUNNING
        row.last_started_at = started
        await self._session.commit()

        count = 0
        batch: list[RawRecord] = []
        try:
            stream = connector.iter_resources(capability, since=None if read_all else row.since)
            async for record in stream:
                batch.append(record)
                if len(batch) >= BATCH_SIZE:
                    count += await self._store(source, row, batch)
                    batch = []
            if batch:
                count += await self._store(source, row, batch)
        except ConnectorError as error:
            _failed(row, error.diagnostic, count)
            await self._session.commit()
            return count, error.diagnostic
        except NotImplementedError:
            # A connector that cannot synchronise yet: nothing to read, not a failure.
            row.status = SyncRunStatus.IDLE
            await self._session.commit()
            return 0, None

        _succeeded(row, started, count, full=read_all)
        await self._session.commit()
        return count, None

    async def _store(self, source: Source, row: SourceSync, records: list[RawRecord]) -> int:
        """One batch: the bytes to the store, then the row, then commit.

        Object first, row second — the order leka.ingestion.tasks relies on:
        an object whose row never committed is found by reconciliation; a
        row whose object never arrived could not be repaired.
        """
        fetched_at = datetime.now(UTC)
        key = object_key(self._workspace_id, source.id, fetched_at, extension="jsonl")
        body = "\n".join(record.model_dump_json() for record in records).encode()
        stored = await object_store().put(key, from_bytes(body), content_type=CONTENT_TYPE)
        self._payloads.record(
            source_id=source.id,
            object_key=key,
            content_type=CONTENT_TYPE,
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            fetched_at=fetched_at,
            expires_at=expires_at(source.kind, fetched_at),
        )
        # Counted as it is committed: a pass that fails later has still stored this.
        row.records_total += len(records)
        await self._session.commit()
        return len(records)

    def _conclude(self, source: Source, failure: Diagnostic | None, *, was_failing: bool) -> None:
        """The source's summary, and its history when that summary changes."""
        if failure is None:
            source.sync_status = SyncStatus.IDLE
            source.last_synced_at = datetime.now(UTC)
            if was_failing:
                source.last_error = None
                self._sources.record(source, SourceEventType.SYNC_RECOVERED)
            return
        source.sync_status = SyncStatus.FAILED
        source.last_error = failure.model_dump(mode="json")
        if not failure.retryable:
            # A person has to act: the token, the permissions. Retrying would
            # only fail the same way every hour.
            source.status = next_status(source.status, LifecycleEvent.UNHEALTHY)
        if not was_failing:
            self._sources.record(source, SourceEventType.SYNC_FAILED, code=failure.code.value)


def _capabilities(source: Source, offered: frozenset[Capability]) -> list[Capability]:
    """What the source's last test found readable and its connector can read,
    repositories first — what the others hang from."""
    found = {c for c in Capability if c.value in source.capabilities and c in offered}
    return sorted(found, key=lambda c: (c is not Capability.REPOSITORIES, c.value))


def _due_for_full(row: SourceSync, now: datetime) -> bool:
    if row.since is None or row.last_full_at is None:
        return True
    return now - row.last_full_at >= FULL_RESYNC_EVERY


def _succeeded(row: SourceSync, started: datetime, count: int, *, full: bool) -> None:
    row.status = SyncRunStatus.IDLE
    row.since = started
    row.last_succeeded_at = datetime.now(UTC)
    if full:
        row.last_full_at = started
    row.records_last_run = count
    row.consecutive_failures = 0
    row.last_error = None


def _failed(row: SourceSync, diagnostic: Diagnostic, count: int) -> None:
    row.status = SyncRunStatus.FAILED
    row.records_last_run = count
    row.consecutive_failures += 1
    row.last_error = diagnostic.model_dump(mode="json")
