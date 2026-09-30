"""The processing pipeline (LEKA-360): order, runs, recovery.

The fake source of test_sync.py through the chain, against the test
database. What is asserted: the stages run in their order and hand over
only when they end; each run is recorded with what it did; a stage that
crashes half-way is failed, queues nothing, and its retry finishes the work
with nothing downstream half-made; a run a dead worker left `running` is
found `abandoned`.
"""

# ruff: noqa: F811 — the fixtures of test_sync and test_parsing_job are imported by name.
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select

from leka.background.runner import _resolve
from leka.connectors import Capability, Source
from leka.db import session_factory, workspace_scope
from leka.ingestion import (
    ExtractedRecordRow,
    ExtractionRepository,
    ProcessingRun,
    ProcessingRunStatus,
    ProcessingStage,
)
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.normalisation.job import NORMALISE_JOB, normalise_source
from leka.ingestion.parsing import job as parsing_job
from leka.ingestion.parsing.engine import PARSER_VERSION
from leka.ingestion.parsing.job import PARSE_JOB, parse_source
from leka.ingestion.repository import ParsingRepository
from tests import test_sync as sync_tests
from tests.test_parsing_job import pipeline, queued  # noqa: F401 — fixture
from tests.test_sync import _sync, fake, source  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration


async def _runs(source: Source) -> list[ProcessingRun]:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(ProcessingRun)
                .where(ProcessingRun.source_id == source.id)
                .order_by(ProcessingRun.started_at)
            )
            return list(rows.scalars())


async def _extracted_rows(source: Source) -> int:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            found = await session.execute(
                select(func.count())
                .select_from(ExtractedRecordRow)
                .where(ExtractedRecordRow.source_id == source.id)
            )
            return int(found.scalar_one())


def _crash_on(
    monkeypatch: pytest.MonkeyPatch, owner: type, method: str, call: int
) -> Callable[[], None]:
    """Make owner.method raise on its `call`-th call — a worker killed, a
    database gone. Returns what puts it back."""
    original: Callable[..., Awaitable[Any]] = getattr(owner, method)
    calls = {"n": 0}

    async def crashing(self: object, *args: object, **kwargs: object) -> Any:
        calls["n"] += 1
        if calls["n"] == call:
            raise ConnectionError("the database went away")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(owner, method, crashing)
    return lambda: monkeypatch.setattr(owner, method, original)


# ── the definition ───────────────────────────────────────────────────────────


def test_the_stages_run_in_their_order_each_under_its_own_key() -> None:
    names = [stage.name for stage in pipeline_module.STAGES]
    keys = {stage.key(uuid.UUID(int=1)) for stage in pipeline_module.STAGES}

    assert names == [
        ProcessingStage.EXTRACTION,
        ProcessingStage.PARSING,
        ProcessingStage.NORMALISATION,
        ProcessingStage.VALIDATION,
    ]
    assert len(keys) == 4  # one run per stage per source; stages of a source never collide


@pytest.mark.parametrize("stage", pipeline_module.STAGES, ids=lambda s: s.name.value)
def test_every_stage_names_a_job_that_exists(stage: pipeline_module.Stage) -> None:
    assert callable(_resolve(stage.job))


# ── end to end ───────────────────────────────────────────────────────────────


async def test_a_pass_runs_through_every_stage_in_order(source: Source) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 3}

    await _sync(source)
    assert queued() == [pipeline_module.STAGES[0].job]  # the extraction only, for now
    await extract_source(source.workspace_id, source.id)
    assert queued()[-1] == PARSE_JOB
    await parse_source(source.workspace_id, source.id)
    assert queued()[-1] == NORMALISE_JOB
    await normalise_source(source.workspace_id, source.id)

    runs = await _runs(source)
    assert [(r.stage, r.status) for r in runs] == [
        (ProcessingStage.EXTRACTION, ProcessingRunStatus.SUCCEEDED),
        (ProcessingStage.PARSING, ProcessingRunStatus.SUCCEEDED),
        (ProcessingStage.NORMALISATION, ProcessingRunStatus.SUCCEEDED),
    ]
    extraction, parsing, normalisation = runs
    assert extraction.counts["extracted"] == 3
    assert extraction.versions == {"commits": 1}  # the fake commits' strategy
    assert parsing.counts["parsed"] == 3
    assert parsing.versions == {"parser": PARSER_VERSION}
    assert normalisation.counts["failed"] == 3  # the fake vendor has no rules: unsupported
    assert all(r.finished_at is not None and r.finished_at >= r.started_at for r in runs)
    # Processed through: nothing left to queue.
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            assert (
                await pipeline_module.advance(session, source.workspace_id, source, after=None)
                is None
            )


# ── recovery ─────────────────────────────────────────────────────────────────


async def test_an_extraction_that_crashes_half_way_is_retried_to_the_end(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 5}  # batches of 2: three saves
    await _sync(source)
    sync_tests.queued_purges.clear()
    restore = _crash_on(monkeypatch, ExtractionRepository, "save", call=2)

    with pytest.raises(ConnectionError):
        await extract_source(source.workspace_id, source.id)

    (failed,) = await _runs(source)
    assert (failed.status, failed.error) == (ProcessingRunStatus.FAILED, "ConnectionError")
    assert isinstance(failed.counts["extracted"], int)
    assert failed.counts["extracted"] > 0  # what it did before it stopped
    assert PARSE_JOB not in queued()  # nothing downstream reads a half-made stage
    saved = await _extracted_rows(source)
    assert 0 < saved < 5

    restore()
    result = await extract_source(source.workspace_id, source.id)  # the runner's retry

    assert result["extracted"] == 5 - saved  # what was saved is not redone
    assert PARSE_JOB in queued()
    assert (await _runs(source))[-1].status is ProcessingRunStatus.SUCCEEDED
    await parse_source(source.workspace_id, source.id)
    parsing = (await _runs(source))[-1]
    assert parsing.counts["parsed"] == 5  # downstream sees every record, once


async def test_a_parse_that_crashes_does_not_queue_the_normalisation(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 3}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)
    monkeypatch.setattr(parsing_job, "CHUNK", 1)
    sync_tests.queued_purges.clear()
    restore = _crash_on(monkeypatch, ParsingRepository, "save", call=2)

    with pytest.raises(ConnectionError):
        await parse_source(source.workspace_id, source.id)
    assert NORMALISE_JOB not in queued()

    restore()
    assert (await parse_source(source.workspace_id, source.id))["parsed"] == 2
    assert NORMALISE_JOB in queued()
    assert (await normalise_source(source.workspace_id, source.id))["failed"] == 3


async def test_a_run_a_dead_worker_left_running_is_found_abandoned(source: Source) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 1}
    await _sync(source)
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            session.add(
                ProcessingRun(
                    workspace_id=source.workspace_id,
                    source_id=source.id,
                    stage=ProcessingStage.EXTRACTION,
                    status=ProcessingRunStatus.RUNNING,
                    started_at=datetime(2026, 9, 27, tzinfo=UTC),
                )
            )
            await session.commit()

    await extract_source(source.workspace_id, source.id)

    dead, fresh = await _runs(source)
    assert dead.status is ProcessingRunStatus.ABANDONED and dead.finished_at is not None
    assert fresh.status is ProcessingRunStatus.SUCCEEDED
