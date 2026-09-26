"""What the database refuses about source syncs, and the one write that races (LEKA-352).

`source_syncs` says how far each capability of each source has been read.
These tests hold the schema to what leka/ingestion/models.py promises: one
row per (source, capability), never pointing at another workspace's source,
gone with its source, and made once however many passes arrive together.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import Source, SourceKind
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import (
    SourceRecord,
    SourceSync,
    SourceSyncRepository,
    SyncRun,
    SyncRunStatus,
    SyncTrigger,
)
from leka.platform import Workspace

pytestmark = pytest.mark.integration


async def _workspace(session: AsyncSession, label: str) -> Workspace:
    workspace = Workspace(name=label, slug=f"{label}-{uuid.uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    return workspace


async def _source(session: AsyncSession, workspace: Workspace) -> Source:
    source = Source(
        workspace_id=workspace.id, kind=SourceKind.GITHUB, name=f"gh-{uuid.uuid4().hex[:8]}"
    )
    session.add(source)
    await session.flush()
    return source


def _sync(source: Source, capability: str = "commits") -> SourceSync:
    return SourceSync(workspace_id=source.workspace_id, source_id=source.id, capability=capability)


async def test_a_new_sync_starts_idle_with_nothing_read(session: AsyncSession) -> None:
    source = await _source(session, await _workspace(session, "defaults"))
    sync = _sync(source)
    session.add(sync)
    await session.flush()
    await session.refresh(sync)

    assert sync.status is SyncRunStatus.IDLE
    assert (sync.records_last_run, sync.records_total, sync.consecutive_failures) == (0, 0, 0)
    assert sync.since is None
    assert sync.last_error is None


async def test_one_row_per_source_and_capability(session: AsyncSession) -> None:
    source = await _source(session, await _workspace(session, "unique"))
    session.add(_sync(source))
    await session.flush()

    session.add(_sync(source))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_sync_cannot_point_at_another_workspace_source(session: AsyncSession) -> None:
    mine = await _workspace(session, "mine")
    theirs = await _source(session, await _workspace(session, "theirs"))

    session.add(SourceSync(workspace_id=mine.id, source_id=theirs.id, capability="commits"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.parametrize(
    "values",
    [
        {"status": "paused"},
        {"capability": ""},
        {"records_total": -1},
        {"records_last_run": -1},
        {"consecutive_failures": -1},
    ],
    ids=[
        "unknown-status",
        "empty-capability",
        "negative-total",
        "negative-last",
        "negative-failures",
    ],
)
async def test_what_the_database_refuses(session: AsyncSession, values: dict[str, object]) -> None:
    source = await _source(session, await _workspace(session, "refused"))
    row = _sync(source)
    for name, value in values.items():
        setattr(row, name, value)
    session.add(row)

    with pytest.raises((IntegrityError, DBAPIError, LookupError)):
        await session.flush()


async def test_a_sync_goes_with_its_source(session: AsyncSession) -> None:
    source = await _source(session, await _workspace(session, "cascade"))
    session.add(_sync(source))
    await session.flush()

    await session.delete(source)
    await session.flush()

    with system_scope():
        left = await session.execute(select(SourceSync).where(SourceSync.source_id == source.id))
    assert left.scalars().all() == []


async def test_passes_arriving_together_find_one_row(session: AsyncSession) -> None:
    workspace = await _workspace(session, "race")
    source = await _source(session, workspace)
    await session.commit()

    async def arrive() -> uuid.UUID:
        with workspace_scope(workspace.id):
            async with session_factory() as own:
                repository = SourceSyncRepository(own, workspace.id)
                row = await repository.get_or_create(source.id, "commits")
                await own.commit()
                return row.id

    ids = await asyncio.gather(*(arrive() for _ in range(5)))

    assert len(set(ids)) == 1


async def test_a_workspace_sees_only_its_own_syncs(session: AsyncSession) -> None:
    mine = await _workspace(session, "reader")
    theirs = await _workspace(session, "other")
    my_source = await _source(session, mine)
    their_source = await _source(session, theirs)
    session.add_all([_sync(my_source), _sync(their_source, capability="issues")])
    await session.flush()

    repository = SourceSyncRepository(session, mine.id)

    with workspace_scope(mine.id):
        assert [row.capability for row in await repository.for_source(my_source.id)] == ["commits"]
        assert await repository.for_source(their_source.id) == []


# ── sync_runs (LEKA-353) ─────────────────────────────────────────────────────


def _run(source: Source, **values: object) -> SyncRun:
    run = SyncRun(
        workspace_id=source.workspace_id,
        source_id=source.id,
        trigger=SyncTrigger.SCHEDULE,
        full_read=False,
        started_at=datetime.now(UTC),
    )
    for name, value in values.items():
        setattr(run, name, value)
    return run


@pytest.mark.parametrize(
    "values",
    [
        {"trigger": "webhook"},
        {"status": "paused"},
        {"records": -1},
        {"finished_at": datetime(2000, 1, 1, tzinfo=UTC)},
    ],
    ids=["unknown-trigger", "unknown-status", "negative-records", "finished-before-started"],
)
async def test_what_the_database_refuses_of_a_run(
    session: AsyncSession, values: dict[str, object]
) -> None:
    source = await _source(session, await _workspace(session, "runs"))
    session.add(_run(source, **values))

    with pytest.raises((IntegrityError, DBAPIError, LookupError)):
        await session.flush()


async def test_a_run_goes_with_its_source(session: AsyncSession) -> None:
    source = await _source(session, await _workspace(session, "run-cascade"))
    session.add(_run(source))
    await session.flush()

    await session.delete(source)
    await session.flush()

    with system_scope():
        left = await session.execute(select(SyncRun).where(SyncRun.source_id == source.id))
    assert left.scalars().all() == []


# ── source_records (LEKA-353) ────────────────────────────────────────────────


def _record(source: Source, **values: object) -> SourceRecord:
    now = datetime.now(UTC)
    record = SourceRecord(
        workspace_id=source.workspace_id,
        source_id=source.id,
        kind="commits",
        external_id="c-1",
        checksum="a" * 64,
        first_seen_at=now,
        last_seen_at=now,
    )
    for name, value in values.items():
        setattr(record, name, value)
    return record


async def test_one_index_row_per_record_of_a_source(session: AsyncSession) -> None:
    source = await _source(session, await _workspace(session, "records"))
    session.add(_record(source))
    await session.flush()

    session.add(_record(source))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.parametrize(
    "values",
    [{"checksum": "short"}, {"external_id": ""}, {"kind": ""}],
    ids=["not-a-sha256", "empty-id", "empty-kind"],
)
async def test_what_the_database_refuses_of_a_record(
    session: AsyncSession, values: dict[str, object]
) -> None:
    source = await _source(session, await _workspace(session, "records-refused"))
    session.add(_record(source, **values))

    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


async def test_a_record_outlives_its_run_and_goes_with_its_source(session: AsyncSession) -> None:
    source = await _source(session, await _workspace(session, "records-cascade"))
    run = _run(source)
    session.add(run)
    await session.flush()
    record = _record(source, last_seen_run_id=run.id)
    session.add(record)
    await session.flush()

    await session.delete(run)
    await session.flush()
    await session.refresh(record)
    assert record.last_seen_run_id is None

    await session.delete(source)
    await session.flush()
    with system_scope():
        left = await session.execute(
            select(SourceRecord).where(SourceRecord.source_id == source.id)
        )
    assert left.scalars().all() == []
