"""Retention, erasure, and the objects a cascade cannot reach.

The promise being tested is not "rows go away". It is that when a customer
leaves, their DATA leaves — including the bytes in a bucket that no foreign
key has ever heard of. Every test here exists because one of the mechanisms
that makes that true can fail on its own:

    the retention sweep     deletes what we said we would not keep
    the deletion purge      deletes a customer's objects when they go
    the reconciliation      deletes what the other two missed

The last one is why the first two are allowed to be imperfect.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from leka.connectors import Source, SourceKind
from leka.core.config import settings
from leka.db import session_factory, system_scope
from leka.ingestion import RawPayloadRepository
from leka.ingestion.retention import (
    DEFAULT_RETENTION_DAYS,
    FALLBACK_RETENTION_DAYS,
    expires_at,
    retention_days,
)
from leka.ingestion.tasks import (
    ORPHAN_GRACE,
    reconcile_orphaned_objects,
    sweep_expired_payloads,
)
from leka.platform import Workspace, WorkspaceStatus
from leka.platform.service import DELETION_GRACE_PERIOD
from leka.platform.storage import LocalObjectStore, from_bytes, object_key, workspace_prefix
from leka.platform.tasks import erase_workspaces_past_grace, purge_workspace_objects

pytestmark = pytest.mark.integration


# ── A store the tasks will actually use ──────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalObjectStore:
    """Point the process-wide object store at a temporary directory.

    The tasks call object_store() rather than taking one, because RQ hands a
    worker arguments as JSON and an adapter is not JSON. Substituting it here
    is what lets them be tested at all.
    """
    from leka.platform import storage

    replacement = LocalObjectStore(tmp_path)
    monkeypatch.setattr(storage, "_store", replacement)
    return replacement


class Tenant:
    def __init__(self, workspace_id: uuid.UUID, source_id: uuid.UUID) -> None:
        self.workspace_id = workspace_id
        self.source_id = source_id


async def _make_tenant(label: str, *, kind: SourceKind = SourceKind.GITHUB) -> Tenant:
    marker = f"{label}-{uuid.uuid4().hex[:10]}"
    with system_scope():
        async with session_factory() as session:
            workspace = Workspace(name=label, slug=marker)
            session.add(workspace)
            await session.flush()
            source = Source(workspace_id=workspace.id, kind=kind, name=marker)
            session.add(source)
            await session.flush()
            await session.commit()
            return Tenant(workspace.id, source.id)


async def _remove(workspace_id: uuid.UUID) -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM workspaces WHERE id = :wid"), {"wid": workspace_id}
            )
            await session.commit()


@pytest.fixture
async def tenants() -> AsyncIterator[tuple[Tenant, Tenant]]:
    first, second = await _make_tenant("alpha"), await _make_tenant("beta")
    yield first, second
    await _remove(first.workspace_id)
    await _remove(second.workspace_id)


async def _store_payload(
    store: LocalObjectStore,
    tenant: Tenant,
    *,
    body: bytes = b'{"payload": true}',
    fetched_at: datetime | None = None,
    expires: datetime | None = None,
) -> str:
    """Write an object AND the row that speaks for it, as production does."""
    when = fetched_at or datetime.now(UTC)
    key = object_key(tenant.workspace_id, tenant.source_id, when)
    written = await store.put(key, from_bytes(body), content_type="application/json")

    with system_scope():
        async with session_factory() as session:
            RawPayloadRepository(session, tenant.workspace_id).record(
                source_id=tenant.source_id,
                object_key=written.key,
                content_type=written.content_type,
                size_bytes=written.size_bytes,
                checksum_sha256=written.checksum_sha256,
                fetched_at=when,
                expires_at=expires or when + timedelta(days=30),
            )
            await session.commit()
    return written.key


async def _rows_for(workspace_id: uuid.UUID) -> int:
    with system_scope():
        async with session_factory() as session:
            found = await session.execute(
                text("SELECT count(*) FROM raw_payloads WHERE workspace_id = :wid"),
                {"wid": workspace_id},
            )
            return int(found.scalar_one())


# ── The policy ───────────────────────────────────────────────────────────────


def test_every_source_kind_has_a_declared_retention() -> None:
    """A kind nobody thought about must not silently mean "keep for ever".

    This fails the day a connector is added without a decision being made
    about how long its payloads are ours — which is the moment to make it,
    not a year later when someone asks why we still hold something.
    """
    missing = [kind for kind in SourceKind if kind not in DEFAULT_RETENTION_DAYS]
    assert not missing, (
        f"source kinds with no declared retention: {missing}. "
        "Add them to DEFAULT_RETENTION_DAYS with a reason, in "
        "leka/ingestion/retention.py."
    )


def test_observability_is_kept_for_less_time_than_structure() -> None:
    """The reason the numbers differ, asserted rather than left in a comment.

    Code and tickets describe structure: small, slow-moving, worth
    re-reading. Log exports are enormous and worthless within days.
    """
    assert retention_days(SourceKind.DATADOG) < retention_days(SourceKind.GITHUB)


def test_the_expiry_is_computed_from_the_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """And configuration wins, so a contract can move a number without a deploy."""
    from leka.ingestion import retention

    fetched = datetime(2026, 1, 1, tzinfo=UTC)

    assert expires_at(SourceKind.GITHUB, fetched) == fetched + timedelta(
        days=retention_days(SourceKind.GITHUB)
    )

    # Settings is frozen on purpose — the environment is read once, at
    # startup. A copy is the honest way to ask "what would this do with a
    # different configuration?".
    monkeypatch.setattr(
        retention,
        "settings",
        settings.model_copy(update={"raw_payload_retention_days": {"github": 7}}),
    )
    assert expires_at(SourceKind.GITHUB, fetched) == fetched + timedelta(days=7)


def test_a_source_may_keep_less_than_its_kind_never_more() -> None:
    """A source's own retention (its settings, LEKA-348) shortens the
    policy; asking for more than the policy gets the policy."""
    fetched = datetime(2026, 1, 1, tzinfo=UTC)
    policy = retention_days(SourceKind.DATADOG)

    assert expires_at(SourceKind.DATADOG, fetched, days=7) == fetched + timedelta(days=7)
    assert expires_at(SourceKind.DATADOG, fetched, days=policy + 60) == fetched + timedelta(
        days=policy
    )
    assert expires_at(SourceKind.DATADOG, fetched, days=None) == fetched + timedelta(days=policy)


def test_an_unknown_kind_falls_back_to_the_shortest_policy() -> None:
    """Keeping too little is a resync. Keeping too much is a broken promise."""
    assert min(DEFAULT_RETENTION_DAYS.values()) == FALLBACK_RETENTION_DAYS


# ── The retention sweep ──────────────────────────────────────────────────────


async def test_the_sweep_removes_what_expired_and_leaves_what_did_not(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant]
) -> None:
    """The whole point, in one test: both halves, and only the right ones."""
    alpha, _ = tenants
    now = datetime.now(UTC)
    expired = await _store_payload(store, alpha, expires=now - timedelta(days=1))
    alive = await _store_payload(store, alpha, expires=now + timedelta(days=30))

    result = await sweep_expired_payloads(now=now)

    assert result["rows"] == 1
    assert result["objects"] == 1
    assert not await store.exists(expired), "the expired object is still in the store"
    assert await store.exists(alive), "a live payload was deleted"
    assert await _rows_for(alpha.workspace_id) == 1


async def test_the_sweep_takes_withdrawn_payloads_too(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant]
) -> None:
    """A withdrawal leaves every read at once; the bytes go on the next sweep."""
    alpha, _ = tenants
    key = await _store_payload(store, alpha, expires=datetime.now(UTC) + timedelta(days=365))

    with system_scope():
        async with session_factory() as session:
            repository = RawPayloadRepository(session, alpha.workspace_id)
            payload = await repository.get_by_object_key(key)
            assert payload is not None
            repository.mark_deleted(payload)
            await session.commit()

    await sweep_expired_payloads()

    assert not await store.exists(key)
    assert await _rows_for(alpha.workspace_id) == 0


async def test_the_sweep_does_not_reach_into_another_tenant(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant]
) -> None:
    """It crosses tenants on purpose, which is exactly why it has to be
    checked: a sweep with a wrong predicate deletes everyone's data at once."""
    alpha, beta = tenants
    now = datetime.now(UTC)
    doomed = await _store_payload(store, alpha, expires=now - timedelta(days=1))
    kept = await _store_payload(store, beta, expires=now + timedelta(days=30))

    await sweep_expired_payloads(now=now)

    assert not await store.exists(doomed)
    assert await store.exists(kept)
    assert await _rows_for(beta.workspace_id) == 1


async def test_a_sweep_with_nothing_to_do_is_not_an_error(store: LocalObjectStore) -> None:
    assert await sweep_expired_payloads() == {"rows": 0, "objects": 0, "objects_failed": 0}


async def test_a_failing_object_delete_does_not_stop_the_sweep(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row is already gone, so the object is now an orphan — which is a
    state the other sweep handles. Raising here would leave the rest of the
    batch untouched for ever."""
    from leka.platform import storage

    alpha, _ = tenants
    now = datetime.now(UTC)
    await _store_payload(store, alpha, expires=now - timedelta(days=1))

    async def refuse(self: Any, key: str) -> bool:
        msg = "the bucket said no"
        raise storage.ObjectStoreError(msg)

    monkeypatch.setattr(LocalObjectStore, "delete", refuse)

    result = await sweep_expired_payloads(now=now)

    assert result["rows"] == 1, "the row must still be deleted"
    assert result["objects_failed"] == 1
    assert await _rows_for(alpha.workspace_id) == 0


# ── Erasing a customer ───────────────────────────────────────────────────────


async def test_erasing_a_workspace_removes_its_rows_and_its_objects(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant]
) -> None:
    """THE test of this ticket.

    The cascade takes the rows. Nothing in PostgreSQL can take the objects,
    so if this passes only on the row half, a deleted customer's data is
    still with us — which is not a deletion at all.
    """
    alpha, beta = tenants
    doomed = await _store_payload(store, alpha)
    kept = await _store_payload(store, beta)

    with system_scope():
        async with session_factory() as session:
            workspace = await session.get(Workspace, alpha.workspace_id)
            assert workspace is not None
            workspace.status = WorkspaceStatus.PENDING_DELETION
            workspace.deletion_requested_at = datetime.now(UTC) - DELETION_GRACE_PERIOD
            await session.commit()

    result = await erase_workspaces_past_grace()

    assert result["workspaces"] == 1
    assert result["objects"] == 1
    assert not await store.exists(doomed), "the customer's bytes are still in the store"
    assert await _rows_for(alpha.workspace_id) == 0
    assert await store.exists(kept), "another customer's data was taken with it"
    assert await _rows_for(beta.workspace_id) == 1


async def test_a_deletion_still_inside_its_grace_period_is_left_alone(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant]
) -> None:
    """A customer who changes their mind in time must lose nothing."""
    alpha, _ = tenants
    key = await _store_payload(store, alpha)

    with system_scope():
        async with session_factory() as session:
            workspace = await session.get(Workspace, alpha.workspace_id)
            assert workspace is not None
            workspace.status = WorkspaceStatus.PENDING_DELETION
            workspace.deletion_requested_at = datetime.now(UTC)
            await session.commit()

    result = await erase_workspaces_past_grace()

    assert result["workspaces"] == 0
    assert await store.exists(key)
    assert await _rows_for(alpha.workspace_id) == 1


async def test_purging_a_workspace_prefix_is_safe_to_repeat(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant]
) -> None:
    """Reconciliation calls it without knowing whether the first try worked."""
    alpha, _ = tenants
    await _store_payload(store, alpha)

    assert await purge_workspace_objects(str(alpha.workspace_id)) == 1
    assert await purge_workspace_objects(str(alpha.workspace_id)) == 0


async def test_erase_enqueues_the_object_purge_rather_than_doing_it_inline(
    tenants: tuple[Tenant, Tenant], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A workspace can hold hundreds of thousands of objects.

    Deleting them inside the request that asked for the deletion would make
    that request time out, and the customer would try again.
    """
    from leka.platform import service as platform_service
    from leka.platform.repository import WorkspaceRepository

    alpha, _ = tenants
    enqueued: list[tuple[str, tuple[Any, ...]]] = []

    async def record(job: str, *args: Any, **kwargs: Any) -> bool:
        enqueued.append((job, args))
        return True

    monkeypatch.setattr(platform_service, "enqueue", record)

    with system_scope():
        async with session_factory() as session:
            workspace = await session.get(Workspace, alpha.workspace_id)
            assert workspace is not None
            await platform_service.WorkspaceService(WorkspaceRepository(session), session).erase(
                workspace
            )
            await session.commit()

    assert enqueued == [
        ("leka.platform.tasks.run_purge_workspace_objects", (str(alpha.workspace_id),))
    ]


async def test_a_deletion_goes_through_even_when_the_queue_is_down(
    tenants: tuple[Tenant, Tenant], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusing to delete a customer because Redis is down would be the worse
    failure. The reconciliation sweep is what makes that safe."""
    from leka.platform import service as platform_service
    from leka.platform.repository import WorkspaceRepository

    alpha, _ = tenants

    async def fail(job: str, *args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(platform_service, "enqueue", fail)

    with system_scope():
        async with session_factory() as session:
            workspace = await session.get(Workspace, alpha.workspace_id)
            assert workspace is not None
            await platform_service.WorkspaceService(WorkspaceRepository(session), session).erase(
                workspace
            )
            await session.commit()

    assert await _rows_for(alpha.workspace_id) == 0


# ── The net: reconciliation ──────────────────────────────────────────────────


async def test_reconciliation_finds_an_object_no_row_speaks_for(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant]
) -> None:
    """Exactly what a purge that failed halfway leaves behind."""
    alpha, _ = tenants
    old = datetime.now(UTC) - ORPHAN_GRACE - timedelta(days=1)
    orphan = object_key(alpha.workspace_id, alpha.source_id, old)
    await store.put(orphan, from_bytes(b"nobody's"), content_type="application/json")
    claimed = await _store_payload(store, alpha, fetched_at=old)

    result = await reconcile_orphaned_objects()

    assert result["orphans"] == 1
    assert result["removed"] == 1
    assert not await store.exists(orphan)
    assert await store.exists(claimed), "an object with a row was deleted"


async def test_reconciliation_will_not_touch_a_payload_still_being_written(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant]
) -> None:
    """THE failure mode of this function, and the reason for the grace period.

    An object is written BEFORE its row is committed — it has to be, since
    the row records what the store measured. For a moment a perfectly good
    payload has no row. A reconciliation without a grace period would delete
    data that was arriving correctly, and nothing would ever say so.
    """
    alpha, _ = tenants
    arriving = object_key(alpha.workspace_id, alpha.source_id, datetime.now(UTC))
    await store.put(arriving, from_bytes(b"mid-flight"), content_type="application/json")

    result = await reconcile_orphaned_objects()

    assert result["orphans"] == 0
    assert result["skipped_recent"] == 1
    assert await store.exists(arriving)


async def test_reconciliation_leaves_a_key_it_cannot_read(
    store: LocalObjectStore,
) -> None:
    """An unrecognised key is left alone rather than deleted.

    Being wrong by leaving something is recoverable. Being wrong by deleting
    it is not.
    """
    await store.put("not-a-leka-key.txt", from_bytes(b"?"), content_type="text/plain")

    result = await reconcile_orphaned_objects()

    assert result["orphans"] == 0
    assert await store.exists("not-a-leka-key.txt")


async def test_reconciliation_can_report_without_deleting(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant]
) -> None:
    """The first run against a real bucket should always be a dry run: this
    function's failure mode is deleting live data."""
    alpha, _ = tenants
    old = datetime.now(UTC) - ORPHAN_GRACE - timedelta(days=1)
    orphan = object_key(alpha.workspace_id, alpha.source_id, old)
    await store.put(orphan, from_bytes(b"nobody's"), content_type="application/json")

    result = await reconcile_orphaned_objects(dry_run=True)

    assert result["orphans"] == 1
    assert result["removed"] == 0
    assert await store.exists(orphan), "a dry run deleted something"


async def test_reconciliation_catches_a_whole_workspace_the_purge_missed(
    store: LocalObjectStore, tenants: tuple[Tenant, Tenant]
) -> None:
    """The end-to-end guarantee: a customer erased while the queue was down
    does not stay with us."""
    alpha, beta = tenants
    old = datetime.now(UTC) - ORPHAN_GRACE - timedelta(days=1)
    abandoned = [
        await _store_payload(store, alpha, fetched_at=old, body=f"{index}".encode())
        for index in range(3)
    ]
    kept = await _store_payload(store, beta, fetched_at=old)

    # The rows go, the objects do not — a purge that never ran.
    await _remove(alpha.workspace_id)
    assert all([await store.exists(key) for key in abandoned])

    result = await reconcile_orphaned_objects()

    assert result["removed"] == 3
    assert not any([await store.exists(key) for key in abandoned])
    assert await store.exists(kept)
    assert [key async for key in store.iter_prefix(workspace_prefix(alpha.workspace_id))] == []


# ── The queue itself ─────────────────────────────────────────────────────────


async def test_enqueue_puts_the_job_on_the_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Named by string, not imported.

    leka.platform sits BELOW leka.ingestion in the dependency order, so
    importing a task to enqueue it would invert the one rule the module
    layout exists to enforce — and RQ stores a dotted path anyway.
    """
    from leka.background import jobs

    class FakeQueue:
        def __init__(self) -> None:
            self.jobs: list[tuple[str, tuple[Any, ...]]] = []

        def enqueue(self, job: str, *args: Any, **kwargs: Any) -> None:
            self.jobs.append((job, args))

    fake = FakeQueue()
    monkeypatch.setattr(jobs, "_queue", fake)

    assert await jobs.enqueue("leka.ingestion.tasks.run_sweep", "argument") is True
    assert fake.jobs == [("leka.ingestion.tasks.run_sweep", ("argument",))]


async def test_a_queue_that_is_down_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers are in the middle of something that matters.

    Every job this queue carries is housekeeping with the reconciliation
    sweep behind it. Refusing to delete a customer's account because Redis
    was briefly unreachable would be the worse outcome by a long way.
    """
    from leka.background import jobs

    class BrokenQueue:
        def enqueue(self, job: str, *args: Any, **kwargs: Any) -> None:
            msg = "Error 61 connecting to localhost:6379. Connection refused."
            raise ConnectionError(msg)

    monkeypatch.setattr(jobs, "_queue", BrokenQueue())

    assert await jobs.enqueue("leka.ingestion.tasks.run_sweep") is False


def test_the_queue_is_built_once_and_can_be_forgotten() -> None:
    """Built on first use rather than at import: a module import must not
    open a network connection, or every test and every migration pays for
    one it never uses."""
    from leka.background import jobs

    jobs.reset_queue()
    first = jobs.queue()

    assert jobs.queue() is first
    assert first.name == jobs.QUEUE_NAME

    jobs.reset_queue()
    assert jobs.queue() is not first


# ── The documentation must agree with the code ───────────────────────────────


def test_the_lifecycle_document_matches_the_policy() -> None:
    """docs/data-lifecycle.md is what a customer's DPO is shown.

    A retention table that drifts from the code is worse than no table: it is
    a written promise about data we are not actually keeping to. The same
    reasoning as tests/test_permissions_matrix.py, applied to the other
    document somebody outside the team reads.
    """
    from pathlib import Path

    document = Path(__file__).resolve().parents[2] / "docs" / "data-lifecycle.md"
    text = document.read_text(encoding="utf-8")

    missing = [kind.value for kind in SourceKind if kind.value not in text.lower()]
    assert not missing, (
        f"source kinds absent from docs/data-lifecycle.md: {missing}. "
        "Every kind LEKA connects to must say how long its payloads are kept."
    )

    for kind, days in DEFAULT_RETENTION_DAYS.items():
        assert f"| {days} |" in text, (
            f"{kind.value} is kept for {days} days in retention.py, and that "
            "number does not appear in the retention table of "
            "docs/data-lifecycle.md."
        )

    assert str(FALLBACK_RETENTION_DAYS) in text, (
        "the fallback retention is not stated in docs/data-lifecycle.md"
    )


def test_the_runbook_records_a_drill_that_was_actually_run() -> None:
    """A backup that has never been restored is an assumption.

    This does not check the numbers — it checks that the document contains
    measurements and a date rather than intentions, so that "we will test the
    backups" cannot quietly become the permanent state of the file.
    """
    from pathlib import Path

    runbook = (Path(__file__).resolve().parents[2] / "docs" / "runbook.md").read_text(
        encoding="utf-8"
    )

    for expected in ("**Performed:**", "RPO", "RTO", "pg_restore", "Verification"):
        assert expected in runbook, f"docs/runbook.md no longer records {expected!r}"
