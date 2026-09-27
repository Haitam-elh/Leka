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
answer. Once a week a pass ignores the cursor and reads everything:
incremental reads trust every vendor's dates, and this is the net under
that trust. Each source has its own slot (full_slot), at night UTC, so a
workspace's sources and a thousand workspaces do not all read in full at
once; a source never read in full, or whose cursor was forgotten, is read
in full at its next pass whatever the day.

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

from leka.background import Event, JobQueue, enqueue_job
from leka.connectors import (
    Capability,
    Connector,
    ConnectorError,
    Diagnostic,
    DiagnosticCode,
    LifecycleEvent,
    RawRecord,
    ScopeRules,
    Source,
    SourceEventType,
    SourceNotFoundError,
    SourceService,
    SourceStatus,
    SyncStatus,
    in_scope,
    next_status,
)
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion.checksum import checksum
from leka.ingestion.models import (
    SourceSync,
    SyncRun,
    SyncRunOutcome,
    SyncRunStatus,
    SyncTrigger,
)
from leka.ingestion.pipeline import advance
from leka.ingestion.purge import PURGE_JOB
from leka.ingestion.purge import concurrency_key as purge_key
from leka.ingestion.repository import (
    RawPayloadRepository,
    Seen,
    SourceRecordRepository,
    SourceSyncRepository,
    SyncRunRepository,
    SyncScheduleRepository,
)
from leka.ingestion.retention import expires_at
from leka.platform import from_bytes, object_key, object_store

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500
# The weekly full pass lands in a slot between these hours, UTC: the night
# of the product's customers, who are in Europe. One constant to move.
FULL_SLOT_HOURS = (1, 2, 3, 4)
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
    deleted: dict[str, int] = field(default_factory=dict)
    # Read, then left out by the source's scope rules (LEKA-351).
    excluded: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source_id": str(self.source_id),
            "status": self.status,
            "records": self.records,
            "deleted": self.deleted,
            "excluded": self.excluded,
            "error": self.error,
        }


def run_sync(
    workspace_id: str, source_id: str, full: bool = False, trigger: str = "schedule"
) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    report = asyncio.run(
        sync_source(
            uuid.UUID(workspace_id),
            uuid.UUID(source_id),
            full=full,
            trigger=SyncTrigger(trigger),
        )
    )
    return report.as_dict()


# ── Starting a pass ─────────────────────────────────────────────────────────

SYNC_JOB = "leka.ingestion.sync.run_sync"
# How long after a pass was last tried the scheduler starts another.
SYNC_INTERVAL = timedelta(hours=1)
# Sources offered per scheduler pass: the rest are next tick's.
SCHEDULE_BATCH = 200
# BACKPRESSURE (LEKA-353). The schedule offers no more passes than these
# leave room for, across the platform and per workspace: the workers and
# the database take what the queue holds, and one customer with forty
# sources must not hold every worker while the others wait. What does not
# fit is offered at the next tick, oldest first. "Synchroniser maintenant"
# and an activation are not held back: a person is waiting for them.
MAX_ACTIVE_PASSES = 20
MAX_ACTIVE_PASSES_PER_WORKSPACE = 3


def concurrency_key(source_id: uuid.UUID) -> str:
    """One pass per source at a time, whoever asked for it."""
    return f"sync:{source_id}"


async def enqueue_sync(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    full: bool = False,
    queue: JobQueue = JobQueue.DEFAULT,
    trigger: SyncTrigger = SyncTrigger.SCHEDULE,
) -> bool:
    """Put a pass on the queue. False if one is already queued or running for
    this source — someone clicking while the schedule runs it is not an error."""
    run = await enqueue_job(
        SYNC_JOB,
        str(workspace_id),
        str(source_id),
        job_kwargs={"full": full, "trigger": trigger.value},
        for_workspace_id=workspace_id,
        queue=queue,
        concurrency_key=concurrency_key(source_id),
    )
    return run is not None


def run_sync_for_event(event_id: str) -> str:
    """`source.activated`, `source.scope_changed` (leka/background/routes.py):
    a FULL pass — the scope rules changed: what came in is read from the
    start, what went out is swept.

    Published in the activation's own transaction, so it exists only if the
    activation does — a pass enqueued from the request could start before
    the request committed and find the source not yet active. It does not
    read here: it enqueues, so the pass holds the source's key like any other.

    Full, not only the first time: changing a source's settings or
    credentials sends it back to draft, so every widened scope — a project,
    a repository, a space added — comes back through an activation. An
    incremental pass from the old cursor would never read its history.
    """
    return asyncio.run(_on_activated(uuid.UUID(event_id)))


async def _on_activated(event_id: uuid.UUID) -> str:
    with system_scope():
        async with session_factory() as session:
            event = await session.get(Event, event_id)
    if event is None:
        return "gone"
    source_id = uuid.UUID(str(event.payload["source_id"]))
    trigger = (
        SyncTrigger.SETTINGS if event.type == "source.scope_changed" else SyncTrigger.ACTIVATION
    )
    queued = await enqueue_sync(event.workspace_id, source_id, full=True, trigger=trigger)
    return "queued" if queued else "already_active"


def run_enqueue_due_syncs() -> dict[str, int]:
    """Entry point for the schedule (leka/background/schedule.py)."""
    return asyncio.run(enqueue_due_syncs())


async def enqueue_due_syncs(*, now: datetime | None = None) -> dict[str, int]:
    """Offer a pass to every switched-on source not tried for SYNC_INTERVAL,
    within the room MAX_ACTIVE_PASSES and its per-workspace share leave."""
    before = (now or datetime.now(UTC)) - SYNC_INTERVAL
    with system_scope():
        async with session_factory() as session:
            schedule = SyncScheduleRepository(session)
            due = await schedule.due(
                before=before, statuses=[s.value for s in SYNCABLE], limit=SCHEDULE_BATCH
            )
            active = await schedule.active_passes(SYNC_JOB)
    total = sum(active.values())
    result = {"queued": 0, "already_active": 0, "deferred": 0}
    for workspace_id, source_id in due:
        if total >= MAX_ACTIVE_PASSES or active.get(workspace_id, 0) >= (
            MAX_ACTIVE_PASSES_PER_WORKSPACE
        ):
            result["deferred"] += 1
            continue
        queued = await enqueue_sync(workspace_id, source_id)
        result["queued" if queued else "already_active"] += 1
        if queued:
            total += 1
            active[workspace_id] = active.get(workspace_id, 0) + 1
    logger.info("syncs_scheduled", **result)
    return result


async def sync_source(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    full: bool = False,
    trigger: SyncTrigger = SyncTrigger.SCHEDULE,
) -> SyncReport:
    """One pass over one source. See the module docstring."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            return await _Pass(session, workspace_id, full=full, trigger=trigger).run(source_id)


class _Pass:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: uuid.UUID,
        *,
        full: bool,
        trigger: SyncTrigger,
    ) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._full = full
        self._trigger = trigger
        self._runs = SyncRunRepository(session, workspace_id)
        self._run: SyncRun | None = None
        self._records = SourceRecordRepository(session, workspace_id)
        # What each full capability's sweep found gone, for the report.
        self.deleted: dict[str, int] = {}
        # What the scope rules left out, per capability, for the report.
        self.excluded: dict[str, int] = {}
        self._scope = ScopeRules()
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
        self._run = await self._runs.start(
            source.id, trigger=self._trigger, full=self._full, at=datetime.now(UTC)
        )
        await self._session.commit()

        failure: Diagnostic | None = None
        try:
            connector = await self._sources.open_connector(source)
            # The scope rules of this pass: read once, applied to every record.
            _version, settings = await self._sources.settings(source)
            self._scope = settings.scope
            for capability in _capabilities(source, connector.manifest.capabilities):
                count, failure = await self._capability(source, connector, capability)
                report.records[capability.value] = count
                if failure is not None:
                    break
        except ConnectorError as error:
            failure = error.diagnostic

        self._conclude(source, failure, was_failing=was_failing)
        self._run.status = SyncRunOutcome.FAILED if failure else SyncRunOutcome.SUCCEEDED
        self._run.finished_at = datetime.now(UTC)
        self._run.capability = None
        self._run.error = failure.model_dump(mode="json") if failure else None
        await self._session.commit()

        # Deleted records still in a batch — found now, or left by a purge that
        # never ran: the purge job takes them out of the store (purge.py).
        if await self._records.has_pending_purge(source.id):
            await enqueue_job(
                PURGE_JOB,
                str(self._workspace_id),
                str(source.id),
                for_workspace_id=self._workspace_id,
                concurrency_key=purge_key(source.id),
            )
        # What was stored is processed next: the first stage with work
        # (leka/ingestion/pipeline.py) — the extraction, or a later stage
        # alone when only its version changed.
        await advance(self._session, self._workspace_id, source, after=None)
        report.deleted = self.deleted
        report.excluded = self.excluded
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
        # A capability that stored records before the index existed (LEKA-352)
        # is read in full once, so the index knows all of it — not only what
        # changes. One that never had any has nothing to catch up on.
        read_all = (
            self._full
            or capability in connector.manifest.listed_whole
            or _due_for_full(row, started)
            or (
                row.records_total > 0
                and not await self._records.indexed(source.id, capability.value)
            )
        )
        if read_all:
            # Forgotten from the start, not the end: a full pass that fails
            # half-way leaves the next one full too, rather than an
            # incremental that would never read what this one did not reach.
            row.since = None
        row.status = SyncRunStatus.RUNNING
        row.last_started_at = started
        if self._run is not None:
            self._run.capability = capability.value
            # A pass is full if it read a capability whole, asked or not: the
            # first pass, a weekly slot, a forgotten cursor.
            self._run.full_read = self._run.full_read or read_all
        await self._session.commit()

        count = 0
        batch: list[RawRecord] = []
        try:
            stream = connector.iter_resources(capability, since=None if read_all else row.since)
            async for record in stream:
                # Out of scope: not stored, not indexed — so not seen, and what
                # was stored of it goes at the next full read (the sweep).
                if not in_scope(record.container, self._scope):
                    self.excluded[capability.value] = self.excluded.get(capability.value, 0) + 1
                    continue
                batch.append(record)
                if len(batch) >= BATCH_SIZE:
                    count += await self._store(source, row, capability, batch)
                    batch = []
            if batch:
                count += await self._store(source, row, capability, batch)
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
        if read_all and self._run is not None:
            # Only after a FULL read of this capability SUCCEEDED: one cut
            # short by a quota must not call "gone" what it did not reach.
            gone = await self._records.sweep(
                source.id, capability.value, run_id=self._run.id, at=datetime.now(UTC)
            )
            self.deleted[capability.value] = gone
        await self._session.commit()
        return count, None

    async def _store(
        self, source: Source, row: SourceSync, capability: Capability, records: list[RawRecord]
    ) -> int:
        """One batch: what changed to the store, then its row, the index, commit.

        DEDUPLICATED (LEKA-353): a record whose checksum is the one the index
        holds, still live and still in a batch, is not written again — the
        pass only notes it saw it. What is new or changed is written.

        Object first, row second — the order leka.ingestion.tasks relies on:
        an object whose row never committed is found by reconciliation; a
        row whose object never arrived could not be repaired.
        """
        # A listing can shift under pagination and repeat a record: keep the
        # last one, so the index is written once per record.
        latest = {record.external_id: record for record in records}
        sums = {external_id: checksum(record) for external_id, record in latest.items()}
        known = await self._records.known(source.id, capability.value, list(latest))
        changed = [
            record
            for external_id, record in latest.items()
            if not (
                (entry := known.get(external_id))
                and entry.checksum == sums[external_id]
                and entry.live
                and entry.stored
            )
        ]

        key: str | None = None
        size = 0
        if changed:
            fetched_at = datetime.now(UTC)
            key = object_key(self._workspace_id, source.id, fetched_at, extension="jsonl")
            body = "\n".join(record.model_dump_json() for record in changed).encode()
            stored = await object_store().put(key, from_bytes(body), content_type=CONTENT_TYPE)
            size = stored.size_bytes
            self._payloads.record(
                source_id=source.id,
                object_key=key,
                content_type=CONTENT_TYPE,
                size_bytes=stored.size_bytes,
                checksum_sha256=stored.checksum_sha256,
                fetched_at=fetched_at,
                expires_at=expires_at(source.kind, fetched_at),
            )
        written = {record.external_id for record in changed}
        if self._run is not None:
            await self._records.seen(
                source.id,
                capability.value,
                [
                    Seen(
                        external_id=external_id,
                        container=record.container,
                        checksum=sums[external_id],
                        payload_key=key if external_id in written else None,
                    )
                    for external_id, record in latest.items()
                ],
                run_id=self._run.id,
                at=datetime.now(UTC),
            )
        # Counted as it is committed: a pass that fails later has still stored
        # this — and a pass in progress shows how far it has got.
        row.records_total += len(changed)
        if self._run is not None:
            self._run.records += len(records)
            self._run.payloads += 1 if changed else 0
            self._run.bytes += size
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
    what the others hang from first — repositories, projects, and the spaces
    and databases a documentation tool's pages sit in (LEKA-346)."""
    found = {c for c in Capability if c.value in source.capabilities and c in offered}
    roots = (Capability.REPOSITORIES, Capability.PROJECTS, Capability.SPACES, Capability.DATABASES)
    return sorted(found, key=lambda c: (c not in roots, c.value))


def full_slot(source_id: uuid.UUID) -> tuple[int, int]:
    """(weekday, hour UTC) of a source's weekly full pass, from its id.

    Derived rather than stored: the same every week, spread evenly across
    the week's nights, and nothing to keep in step.
    """
    number = source_id.int
    return number % 7, FULL_SLOT_HOURS[(number // 7) % len(FULL_SLOT_HOURS)]


def last_slot(source_id: uuid.UUID, now: datetime) -> datetime:
    """The most recent occurrence of the source's slot, at or before `now`."""
    weekday, hour = full_slot(source_id)
    slot = now.astimezone(UTC).replace(hour=hour, minute=0, second=0, microsecond=0)
    slot -= timedelta(days=(slot.weekday() - weekday) % 7)
    return slot if slot <= now else slot - timedelta(days=7)


def _due_for_full(row: SourceSync, now: datetime) -> bool:
    """Never read in full, cursor forgotten, or its weekly slot has come since."""
    if row.since is None or row.last_full_at is None:
        return True
    return row.last_full_at < last_slot(row.source_id, now)


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
