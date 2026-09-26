"""The sync, against a connector whose every answer is scripted (LEKA-352).

A fake connector — registered for these tests only, as in
test_sources_api.py — streams what each test tells it to, and remembers the
`since` it was asked for. The object store is a temporary directory. What is
asserted is what the sync promises in leka/ingestion/sync.py: what it
stores, how far it records having read, and what it does when a vendor
fails in each of the three ways a vendor can.
"""

from __future__ import annotations

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
    SourceSync,
    SyncRun,
    SyncRunOutcome,
    SyncRunStatus,
    SyncTrigger,
)
from leka.ingestion import sync as sync_module
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


SCRIPT = Script()
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
            yield RawRecord(
                kind=capability,
                external_id=f"{capability.value}-{index}",
                payload={"n": index},
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
    assert rows["commits"].records_total == 2
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
