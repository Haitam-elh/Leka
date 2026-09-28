"""The sync, against a connector whose every answer is scripted (LEKA-352).

A fake connector — registered for these tests only, as in
test_sources_api.py — streams what each test tells it to, and remembers the
`since` it was asked for. The object store is a temporary directory. What is
asserted is what the sync promises in leka/ingestion/sync.py: what it
stores, how far it records having read, and what it does when a vendor
fails in each of the three ways a vendor can.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import select, text

from leka.connectors import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    DiagnosticCode,
    HealthResult,
    HealthStatus,
    RawRecord,
    Source,
    SourceEvent,
    SourceKind,
    SourceService,
    SourceStatus,
    SyncStatus,
    diagnose,
    register_connector,
    unregister_connector,
)
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import (
    RawPayload,
    SourceRecord,
    SourceRecordRepository,
    SourceSync,
    SyncRun,
    SyncRunOutcome,
    SyncRunStatus,
    SyncTrigger,
)
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion import sync as sync_module
from leka.ingestion.checksum import checksum
from leka.ingestion.purge import PURGE_JOB, purge_deleted
from leka.ingestion.sync import RetryableSyncError, sync_source
from leka.platform import LocalObjectStore

pytestmark = pytest.mark.integration


class FakeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FakeCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr


class Script:
    """What the fake vendor answers, per capability, and what it was asked."""

    def __init__(self) -> None:
        self.records: dict[Capability, int] = {}
        # Fail after this many records: (capability, after, code, retry_after).
        self.failure: tuple[Capability, int, DiagnosticCode, int | None] | None = None
        self.asked: list[tuple[Capability, datetime | None]] = []
        # Records whose payload the vendor has changed since the last read.
        self.edited: set[int] = set()
        # Records the vendor no longer returns (deleted, or out of reach).
        self.gone: set[int] = set()
        # Where each record lives, when it matters (scope rules, LEKA-351).
        self.containers: dict[int, str] = {}


SCRIPT = Script()
queued_purges: list[tuple[str, tuple[object, ...]]] = []
OFFERED = frozenset({Capability.REPOSITORIES, Capability.COMMITS, Capability.ISSUES})


class FakeConnector(Connector[FakeConfig, FakeCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.SLACK,
        display_name="Fake",
        category=ConnectorCategory.CHAT,
        auth_type="token",
        config_schema=FakeConfig,
        credentials_schema=FakeCredentials,
        capabilities=OFFERED,
    )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(account="fake", capabilities=sorted(OFFERED))

    async def check_health(self) -> HealthResult:
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        SCRIPT.asked.append((capability, since))
        for index in range(SCRIPT.records.get(capability, 0)):
            failure = SCRIPT.failure
            if failure and failure[0] is capability and index == failure[1]:
                raise diagnose(failure[2], retry_after=failure[3])
            if index in SCRIPT.gone:
                continue
            yield RawRecord(
                kind=capability,
                external_id=f"{capability.value}-{index}",
                container=SCRIPT.containers.get(index),
                payload={"n": index, "edited": index in SCRIPT.edited},
                fetched_at=datetime.now(UTC),
            )


@pytest.fixture(autouse=True)
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[LocalObjectStore]:
    global SCRIPT
    SCRIPT = Script()
    register_connector(FakeConnector)
    monkeypatch.setattr(sync_module, "BATCH_SIZE", 2)
    from leka.platform import storage

    store = LocalObjectStore(tmp_path)
    monkeypatch.setattr(storage, "_store", store)
    # The jobs a pass queues — the purge, the processing — are captured,
    # not put on a queue.
    queued_purges.clear()

    async def capture(job: str, *args: object, **kwargs: object) -> object:
        queued_purges.append((job, args))
        return object()

    monkeypatch.setattr(sync_module, "enqueue_job", capture)
    # And the processing stages the pipeline queues (LEKA-360).
    monkeypatch.setattr(pipeline_module, "enqueue_job", capture)
    yield store
    unregister_connector(SourceKind.SLACK)


@pytest.fixture
async def source() -> AsyncIterator[Source]:
    """An activated fake source, in a workspace of its own, deleted afterwards."""
    with system_scope():
        async with session_factory() as session:
            workspace_id: uuid.UUID = (
                await session.execute(
                    text("INSERT INTO workspaces (name, slug) VALUES ('Sync', :s) RETURNING id"),
                    {"s": f"sync-{uuid.uuid4().hex[:10]}"},
                )
            ).scalar_one()
            await session.commit()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = SourceService(session, workspace_id, actor_user_id=None)
            created = await service.create(SourceKind.SLACK, "Fake", {}, {"token": "t" * 24})
            await service.test(created)
            await service.activate(created)
            await session.commit()
            yield created
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace_id})
            await session.commit()


async def _read(
    source: Source,
) -> tuple[Source, dict[str, SourceSync], list[RawPayload], list[str]]:
    """The source, its sync rows by capability, its payloads, its history."""
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            fresh = await session.get(Source, source.id)
            assert fresh is not None
            rows = (
                await session.execute(select(SourceSync).where(SourceSync.source_id == source.id))
            ).scalars()
            payloads = (
                await session.execute(select(RawPayload).where(RawPayload.source_id == source.id))
            ).scalars()
            history = (
                await session.execute(
                    select(SourceEvent.type)
                    .where(SourceEvent.source_id == source.id)
                    .order_by(SourceEvent.created_at)
                )
            ).scalars()
            return (
                fresh,
                {r.capability: r for r in rows},
                list(payloads),
                [e.value for e in history],
            )


async def _sync(source: Source, *, full: bool = False) -> sync_module.SyncReport:
    return await sync_source(source.workspace_id, source.id, full=full)


# ── what a pass stores ───────────────────────────────────────────────────────


async def test_a_first_pass_reads_everything_and_stores_it_in_batches(
    source: Source, fake: LocalObjectStore
) -> None:
    SCRIPT.records = {Capability.REPOSITORIES: 3, Capability.COMMITS: 4}

    report = await _sync(source)

    assert report.status == "succeeded"
    assert report.records == {"repositories": 3, "commits": 4, "issues": 0}
    # Repositories first: what the rest hangs from. Nothing asked "since" yet.
    assert SCRIPT.asked[0] == (Capability.REPOSITORIES, None)
    assert all(since is None for _, since in SCRIPT.asked)

    fresh, rows, payloads, _ = await _read(source)
    assert fresh.sync_status is SyncStatus.IDLE
    assert fresh.last_synced_at is not None
    # 3 → 2+1, 4 → 2+2: four payloads, each a JSON line per record.
    assert len(payloads) == 4
    lines = []
    for payload in payloads:
        body = b"".join([chunk async for chunk in fake.get(payload.object_key)])
        lines += [json.loads(line) for line in body.decode().splitlines()]
    assert sorted(line["external_id"] for line in lines if line["kind"] == "commits") == [
        f"commits-{n}" for n in range(4)
    ]
    commits = rows["commits"]
    assert (commits.status, commits.records_last_run, commits.records_total) == (
        SyncRunStatus.IDLE,
        4,
        4,
    )
    assert commits.since is not None
    assert commits.last_full_at == commits.since


async def test_the_next_pass_asks_for_what_changed_since_the_last_one_started(
    source: Source,
) -> None:
    SCRIPT.records = {Capability.COMMITS: 1}
    await _sync(source)
    _, rows, _, _ = await _read(source)
    first_start = rows["commits"].since
    assert first_start is not None
    SCRIPT.asked.clear()

    await _sync(source)

    assert (Capability.COMMITS, first_start) in SCRIPT.asked
    _, rows, _, _ = await _read(source)
    # Read twice, written once: the same commit is not stored again (LEKA-353).
    assert rows["commits"].records_total == 1
    assert rows["commits"].since is not None and rows["commits"].since > first_start


async def test_a_week_on_or_when_asked_it_reads_everything_again(source: Source) -> None:
    SCRIPT.records = {Capability.COMMITS: 1}
    await _sync(source)
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE source_syncs SET last_full_at = :old WHERE source_id = :s"),
                {"old": datetime.now(UTC) - timedelta(days=8), "s": source.id},
            )
            await session.commit()
    SCRIPT.asked.clear()

    await _sync(source)
    assert (Capability.COMMITS, None) in SCRIPT.asked

    SCRIPT.asked.clear()
    await _sync(source, full=True)
    assert all(since is None for _, since in SCRIPT.asked)


async def test_only_what_the_test_found_readable_is_read(source: Source) -> None:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE sources SET capabilities = '[\"commits\"]' WHERE id = :s"),
                {"s": source.id},
            )
            await session.commit()

    await _sync(source)

    assert [capability for capability, _ in SCRIPT.asked] == [Capability.COMMITS]


# ── failures ─────────────────────────────────────────────────────────────────


async def test_a_passing_failure_keeps_what_was_stored_and_is_retried(source: Source) -> None:
    SCRIPT.records = {Capability.REPOSITORIES: 1, Capability.COMMITS: 5}
    SCRIPT.failure = (Capability.COMMITS, 3, DiagnosticCode.PROVIDER_ERROR, None)

    with pytest.raises(RetryableSyncError):
        await _sync(source)

    fresh, rows, payloads, history = await _read(source)
    commits = rows["commits"]
    # Two of the three read before the failure were a full batch, stored.
    assert commits.records_total == 2
    assert (commits.status, commits.consecutive_failures) == (SyncRunStatus.FAILED, 1)
    assert commits.since is None  # a failed pass does not move the cursor
    assert commits.last_error is not None and commits.last_error["code"] == "PROVIDER_ERROR"
    assert "issues" not in rows  # stopped at the first failure
    assert fresh.sync_status is SyncStatus.FAILED
    assert fresh.status is SourceStatus.ACTIVE  # it may pass: no person needed yet
    assert history.count("sync_failed") == 1
    assert len(payloads) == 2  # repositories, and the first commits batch

    # Failing again says nothing new; recovering says so, once.
    with pytest.raises(RetryableSyncError):
        await _sync(source)
    SCRIPT.failure = None
    await _sync(source)

    fresh, rows, _, history = await _read(source)
    assert history.count("sync_failed") == 1
    assert history.count("sync_recovered") == 1
    assert fresh.sync_status is SyncStatus.IDLE and fresh.last_error is None
    assert rows["commits"].consecutive_failures == 0 and rows["commits"].since is not None


async def test_a_refused_token_needs_a_person_not_a_retry(source: Source) -> None:
    SCRIPT.records = {Capability.REPOSITORIES: 1}
    SCRIPT.failure = (Capability.REPOSITORIES, 0, DiagnosticCode.AUTH_INVALID, None)

    report = await _sync(source)  # not raised: retrying fails the same way

    assert report.status == "failed" and report.error == "AUTH_INVALID"
    fresh, _, _, history = await _read(source)
    assert fresh.status is SourceStatus.ERROR
    assert fresh.last_error is not None and fresh.last_error["remediation"]
    assert history[-1] == "sync_failed"


async def test_a_quota_reset_far_away_is_left_to_the_next_scheduled_pass(source: Source) -> None:
    SCRIPT.records = {Capability.REPOSITORIES: 1}
    SCRIPT.failure = (Capability.REPOSITORIES, 0, DiagnosticCode.RATE_LIMITED, 3600)

    report = await _sync(source)

    assert report.status == "failed" and report.error == "RATE_LIMITED"
    fresh, _, _, _ = await _read(source)
    assert fresh.status is SourceStatus.ACTIVE


# ── what is not read ─────────────────────────────────────────────────────────


async def test_a_source_switched_off_is_not_read(source: Source) -> None:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            service = SourceService(session, source.workspace_id, actor_user_id=None)
            await service.disable(await service.get(source.id))
            await session.commit()

    report = await _sync(source)

    assert report.status == "skipped"
    assert SCRIPT.asked == []


async def test_a_source_deleted_since_it_was_scheduled_is_skipped(source: Source) -> None:
    report = await sync_source(source.workspace_id, uuid.uuid4())

    assert report.status == "skipped"
    assert SCRIPT.asked == []


# ── what a pass finds from the one before ───────────────────────────────────


async def test_a_pass_left_running_by_a_dead_worker_counts_as_a_failure(source: Source) -> None:
    SCRIPT.records = {Capability.COMMITS: 1}
    await _sync(source)
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE source_syncs SET status = 'running' WHERE source_id = :s"),
                {"s": source.id},
            )
            await session.commit()
    SCRIPT.failure = (Capability.COMMITS, 0, DiagnosticCode.PROVIDER_ERROR, None)

    with pytest.raises(RetryableSyncError):
        await _sync(source)

    _, rows, _, _ = await _read(source)
    # The abandoned pass, then this one: two failures in a row, and not "running".
    assert (rows["commits"].status, rows["commits"].consecutive_failures) == (
        SyncRunStatus.FAILED,
        2,
    )


async def test_a_full_pass_that_fails_leaves_the_next_one_full(source: Source) -> None:
    SCRIPT.records = {Capability.COMMITS: 3}
    await _sync(source)
    SCRIPT.failure = (Capability.COMMITS, 1, DiagnosticCode.PROVIDER_ERROR, None)

    with pytest.raises(RetryableSyncError):
        await _sync(source, full=True)

    _, rows, _, _ = await _read(source)
    assert rows["commits"].since is None
    SCRIPT.failure, SCRIPT.asked = None, []
    await _sync(source)
    assert (Capability.COMMITS, None) in SCRIPT.asked


# ── the weekly slot ──────────────────────────────────────────────────────────


def test_each_source_has_its_night_and_they_are_spread() -> None:
    slots = [sync_module.full_slot(uuid.uuid4()) for _ in range(2000)]

    assert {weekday for weekday, _ in slots} == set(range(7))
    assert {hour for _, hour in slots} == set(sync_module.FULL_SLOT_HOURS)


def test_the_last_slot_is_the_latest_one_not_in_the_future() -> None:
    source_id = uuid.uuid4()
    weekday, hour = sync_module.full_slot(source_id)
    now = datetime(2026, 9, 27, 15, 30, tzinfo=UTC)

    slot = sync_module.last_slot(source_id, now)

    assert (slot.weekday(), slot.hour, slot.minute) == (weekday, hour, 0)
    assert now - timedelta(days=7) < slot <= now


async def test_a_full_pass_waits_for_the_source_slot(source: Source) -> None:
    SCRIPT.records = {Capability.COMMITS: 1}
    await _sync(source)  # the first pass is full
    _, rows, _, _ = await _read(source)
    first_full = rows["commits"].last_full_at
    assert first_full is not None
    SCRIPT.asked.clear()

    await _sync(source)  # an hour later, same week: incremental

    assert all(since is not None for _, since in SCRIPT.asked)
    _, rows, _, _ = await _read(source)
    assert rows["commits"].last_full_at == first_full


# ── what each pass leaves behind (LEKA-353) ─────────────────────────────────


async def _runs(source: Source) -> list[SyncRun]:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(SyncRun).where(SyncRun.source_id == source.id).order_by(SyncRun.started_at)
            )
            return list(rows.scalars())


async def test_each_pass_is_a_run_with_what_it_read(source: Source) -> None:
    SCRIPT.records = {Capability.REPOSITORIES: 3, Capability.COMMITS: 2}

    await _sync(source)
    await sync_source(source.workspace_id, source.id, trigger=SyncTrigger.MANUAL)

    first, second = await _runs(source)
    assert (first.trigger, first.full_read, first.status) == (
        SyncTrigger.SCHEDULE,
        True,  # the first pass reads everything, asked or not
        SyncRunOutcome.SUCCEEDED,
    )
    assert (first.records, first.payloads) == (5, 3)  # 3 → 2+1, 2 → 2
    assert first.bytes > 0
    assert first.finished_at is not None and first.finished_at >= first.started_at
    assert first.capability is None and first.error is None
    assert (second.trigger, second.full_read) == (SyncTrigger.MANUAL, False)


async def test_a_failed_pass_keeps_how_far_it_got_and_why(source: Source) -> None:
    SCRIPT.records = {Capability.REPOSITORIES: 1, Capability.COMMITS: 5}
    SCRIPT.failure = (Capability.COMMITS, 3, DiagnosticCode.PROVIDER_ERROR, None)

    with pytest.raises(RetryableSyncError):
        await _sync(source)

    (run,) = await _runs(source)
    assert run.status is SyncRunOutcome.FAILED
    assert run.records == 3  # the repository, and the first full batch of commits
    assert run.error is not None and run.error["code"] == "PROVIDER_ERROR"
    assert run.finished_at is not None


async def test_a_run_left_running_by_a_dead_worker_is_closed_as_abandoned(source: Source) -> None:
    SCRIPT.records = {Capability.COMMITS: 1}
    await _sync(source)
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE sync_runs SET status = 'running', finished_at = NULL "
                    "WHERE source_id = :s"
                ),
                {"s": source.id},
            )
            await session.commit()

    await _sync(source)

    dead, alive = await _runs(source)
    assert dead.status is SyncRunOutcome.ABANDONED
    assert dead.finished_at is not None and dead.finished_at <= alive.started_at
    assert alive.status is SyncRunOutcome.SUCCEEDED


async def test_a_skipped_pass_leaves_no_run(source: Source) -> None:
    await sync_source(source.workspace_id, uuid.uuid4())

    assert await _runs(source) == []


# ── the per-record index (LEKA-353) ──────────────────────────────────────────


async def _index(source: Source, kind: str = "commits") -> dict[str, SourceRecord]:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(SourceRecord).where(
                    SourceRecord.source_id == source.id, SourceRecord.kind == kind
                )
            )
            return {row.external_id: row for row in rows.scalars()}


async def test_a_record_read_again_unchanged_is_not_written_again(source: Source) -> None:
    SCRIPT.records = {Capability.COMMITS: 3}
    await _sync(source)
    _, _, payloads_before, _ = await _read(source)

    await _sync(source)  # the fake vendor returns the same three

    _, _, payloads_after, _ = await _read(source)
    assert len(payloads_after) == len(payloads_before)
    *_, second = await _runs(source)
    assert (second.records, second.payloads, second.bytes) == (3, 0, 0)
    index = await _index(source)
    assert len(index) == 3
    assert all(row.last_seen_run_id == second.id for row in index.values())


async def test_only_what_changed_is_written(source: Source) -> None:
    SCRIPT.records = {Capability.COMMITS: 3}
    await _sync(source, full=True)
    first_keys = {row.external_id: row.payload_key for row in (await _index(source)).values()}
    SCRIPT.edited = {1}

    await _sync(source)

    index = await _index(source)
    assert index["commits-1"].payload_key != first_keys["commits-1"]
    assert index["commits-0"].payload_key == first_keys["commits-0"]
    *_, second = await _runs(source)
    assert second.payloads == 1


async def test_a_full_pass_marks_gone_what_it_did_not_see_and_a_return_revives_it(
    source: Source,
) -> None:
    SCRIPT.records = {Capability.REPOSITORIES: 2, Capability.COMMITS: 4}
    await _sync(source)
    SCRIPT.gone = {2, 3}

    report = await _sync(source, full=True)

    assert report.deleted["commits"] == 2
    index = await _index(source)
    assert {key for key, row in index.items() if row.deleted_at} == {"commits-2", "commits-3"}
    # Another capability's records are its own sweep's business.
    assert all(row.deleted_at is None for row in (await _index(source, "repositories")).values())

    SCRIPT.gone = set()
    await _sync(source, full=True)
    assert all(row.deleted_at is None for row in (await _index(source)).values())


async def test_nothing_is_marked_gone_by_a_pass_that_did_not_read_everything(
    source: Source,
) -> None:
    SCRIPT.records = {Capability.COMMITS: 4}
    await _sync(source)
    SCRIPT.gone = {3}

    await _sync(source)  # incremental: not seeing it proves nothing
    assert all(row.deleted_at is None for row in (await _index(source)).values())

    SCRIPT.failure = (Capability.COMMITS, 1, DiagnosticCode.PROVIDER_ERROR, None)
    with pytest.raises(RetryableSyncError):
        await _sync(source, full=True)  # cut short: neither
    assert all(row.deleted_at is None for row in (await _index(source)).values())


async def test_a_capability_stored_before_the_index_is_read_in_full_once(source: Source) -> None:
    SCRIPT.records = {Capability.COMMITS: 2}
    await _sync(source)
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM source_records WHERE source_id = :s"), {"s": source.id}
            )
            await session.commit()
    SCRIPT.asked.clear()

    await _sync(source)

    assert (Capability.COMMITS, None) in SCRIPT.asked
    assert len(await _index(source)) == 2
    SCRIPT.asked.clear()
    await _sync(source)
    assert all(
        since is not None for capability, since in SCRIPT.asked if capability.value == "commits"
    )


def test_the_checksum_does_not_depend_on_key_order() -> None:
    one = RawRecord(
        kind=Capability.COMMITS,
        external_id="c",
        payload={"a": 1, "b": [2]},
        fetched_at=datetime.now(UTC),
    )
    two = RawRecord(
        kind=Capability.COMMITS,
        external_id="c",
        payload={"b": [2], "a": 1},
        fetched_at=datetime.now(UTC),
    )

    assert checksum(one) == checksum(two)
    assert len(checksum(one)) == 64


# ── purging deleted records from the store (LEKA-353) ───────────────────────


async def _lines(store: LocalObjectStore, key: str) -> list[str]:
    body = b"".join([chunk async for chunk in store.get(key)])
    return [json.loads(line)["external_id"] for line in body.splitlines()]


async def _live_payloads(source: Source) -> list[RawPayload]:
    _, _, payloads, _ = await _read(source)
    return sorted((p for p in payloads if p.deleted_at is None), key=lambda p: p.fetched_at)


async def test_a_pass_that_marks_records_gone_queues_their_purge(source: Source) -> None:
    SCRIPT.records = {Capability.COMMITS: 2}
    await _sync(source)
    assert [job for job, _ in queued_purges if job == PURGE_JOB] == []
    SCRIPT.gone = {1}

    await _sync(source, full=True)

    assert [q for q in queued_purges if q[0] == PURGE_JOB] == [
        (PURGE_JOB, (str(source.workspace_id), str(source.id)))
    ]


async def test_the_purge_rewrites_mixed_batches_and_withdraws_empty_ones(
    source: Source, fake: LocalObjectStore
) -> None:
    SCRIPT.records = {Capability.COMMITS: 4}  # batches [0, 1] and [2, 3]
    await _sync(source)
    first, _ = await _live_payloads(source)
    SCRIPT.gone = {1, 2, 3}
    await _sync(source, full=True)

    result = await purge_deleted(source.workspace_id, source.id)

    assert (result["rewritten"], result["withdrawn"], result["records_removed"]) == (1, 1, 3)
    (left,) = await _live_payloads(source)
    assert left.id == first.id and left.object_key != first.object_key
    assert await _lines(fake, left.object_key) == ["commits-0"]
    assert not await fake.exists(first.object_key)  # the old object is gone
    index = await _index(source)
    assert index["commits-0"].payload_key == left.object_key
    assert all(index[f"commits-{n}"].payload_key is None for n in (1, 2, 3))


async def test_the_purge_removes_every_version_not_only_the_latest(
    source: Source, fake: LocalObjectStore
) -> None:
    SCRIPT.records = {Capability.COMMITS: 1}
    await _sync(source)  # version 1
    SCRIPT.edited = {0}
    await _sync(source)  # version 2, in another batch
    assert len(await _live_payloads(source)) == 2
    SCRIPT.gone = {0}
    await _sync(source, full=True)

    await purge_deleted(source.workspace_id, source.id)

    assert await _live_payloads(source) == []


async def test_the_purge_is_idempotent(source: Source) -> None:
    SCRIPT.records = {Capability.COMMITS: 3}
    await _sync(source)
    SCRIPT.gone = {0}
    await _sync(source, full=True)
    await purge_deleted(source.workspace_id, source.id)

    again = await purge_deleted(source.workspace_id, source.id)

    assert again == {"examined": 0, "rewritten": 0, "withdrawn": 0, "records_removed": 0}


async def test_a_record_seen_again_while_a_purge_runs_keeps_its_copy(
    source: Source, fake: LocalObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Haitam's review of #89: a pass and a purge can run side by side on a
    source. A record deleted, then seen again — same checksum — while a purge
    that listed it as deleted is under way, must keep its line."""
    SCRIPT.records = {Capability.COMMITS: 2}
    await _sync(source)
    SCRIPT.gone = {1}
    await _sync(source, full=True)
    listed_before_it_came_back = {("commits", "commits-1")}

    SCRIPT.gone = set()
    await _sync(source)  # seen again, unchanged

    revived = (await _index(source))["commits-1"]
    assert revived.deleted_at is None
    # Written again although its checksum did not change: it was not live.
    assert "commits-1" in await _lines(fake, str(revived.payload_key))

    async def stale(self: SourceRecordRepository, source_id: uuid.UUID) -> set[tuple[str, str]]:
        return listed_before_it_came_back

    monkeypatch.setattr(SourceRecordRepository, "pending_purge", stale)
    await purge_deleted(source.workspace_id, source.id)

    after = (await _index(source))["commits-1"]
    assert after.deleted_at is None
    # Its batch is still live — not withdrawn, not rewritten without it —
    # and it is the batch the index names.
    live = {payload.object_key: payload for payload in await _live_payloads(source)}
    assert after.payload_key in live
    assert "commits-1" in await _lines(fake, str(after.payload_key))
    holding = [key for key in live if "commits-1" in await _lines(fake, key)]
    assert holding


async def test_what_a_connector_lists_whole_is_swept_at_every_pass(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cloud inventory has no "changed since": every pass reads it whole,
    so an instance deleted is gone at the next pass, not a week later."""
    whole = FakeConnector.manifest.model_copy(
        update={"listed_whole": frozenset({Capability.ISSUES})}
    )
    monkeypatch.setattr(FakeConnector, "manifest", whole)
    SCRIPT.records = {Capability.ISSUES: 3, Capability.COMMITS: 3}
    await _sync(source)
    SCRIPT.gone = {2}

    report = await _sync(source)  # an ordinary pass, not asked to be full

    assert report.deleted == {"issues": 1}
    assert (await _index(source, "issues"))["issues-2"].deleted_at is not None
    assert (await _index(source))["commits-2"].deleted_at is None  # commits wait for the full pass


@pytest.mark.parametrize(
    "code",
    [DiagnosticCode.PERMISSION_DENIED, DiagnosticCode.RATE_LIMITED, DiagnosticCode.PROVIDER_ERROR],
    ids=["a-region-refuses", "throttled-halfway", "provider-down"],
)
async def test_what_is_listed_whole_is_not_swept_when_the_listing_is_cut_short(
    source: Source, monkeypatch: pytest.MonkeyPatch, code: DiagnosticCode
) -> None:
    """A region that refuses, a 429 halfway: what was not reached is not
    gone. Never a sweep on a partial read — listed whole or not."""
    whole = FakeConnector.manifest.model_copy(
        update={"listed_whole": frozenset({Capability.ISSUES})}
    )
    monkeypatch.setattr(FakeConnector, "manifest", whole)
    SCRIPT.records = {Capability.ISSUES: 3}
    await _sync(source)
    SCRIPT.failure = (Capability.ISSUES, 1, code, 3600)

    with contextlib.suppress(RetryableSyncError):
        await _sync(source)

    assert all(row.deleted_at is None for row in (await _index(source, "issues")).values())


@pytest.mark.parametrize(
    ("offered", "expected"),
    [
        # Jira, Linear: projects before the issues that name them.
        ({"projects", "issues"}, ["projects", "issues"]),
        # Confluence: spaces before their pages.
        ({"spaces", "pages"}, ["spaces", "pages"]),
        # Notion: databases before the pages that are their rows.
        ({"pages", "databases"}, ["databases", "pages"]),
        # Google Workspace, Microsoft 365: drives before their files.
        ({"files", "drives"}, ["drives", "files"]),
    ],
)
def test_what_the_others_hang_from_is_read_first(offered: set[str], expected: list[str]) -> None:
    from types import SimpleNamespace
    from typing import Any, cast

    source = cast(Any, SimpleNamespace(capabilities=sorted(offered)))
    order = sync_module._capabilities(source, frozenset(Capability(c) for c in offered))

    assert [c.value for c in order] == expected
