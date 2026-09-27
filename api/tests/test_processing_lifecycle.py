"""The lifecycle of processed data (LEKA-360): replaced on demand, swept daily.

The fake source of test_sync.py processed through, against the test
database; then a reprocess from a stage, and the daily sweep.
"""

# ruff: noqa: F811 — the fixtures of test_sync and test_parsing_job are imported by name.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from leka.connectors import Capability, Source
from leka.db import session_factory, workspace_scope
from leka.ingestion import (
    ExtractedRecordRow,
    NormalisedRecordRow,
    ParsedRecordRow,
    ProcessingRun,
    ProcessingRunStatus,
    ProcessingStage,
)
from leka.ingestion.extraction.job import EXTRACT_JOB, extract_source
from leka.ingestion.lifecycle import HISTORY_DAYS, POLICIES, reprocess, sweep_processing
from leka.ingestion.normalisation.job import normalise_source
from leka.ingestion.parsing.job import PARSE_JOB, parse_source
from leka.ingestion.pipeline import STAGES
from tests import test_sync as sync_tests
from tests.test_parsing_job import pipeline, queued  # noqa: F401 — fixture
from tests.test_sync import _sync, fake, source  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration


async def _processed(source: Source, commits: int) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: commits}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)
    await parse_source(source.workspace_id, source.id)
    await normalise_source(source.workspace_id, source.id)


async def _counts(source: Source) -> tuple[int, int, int]:
    """Extracted, parsed and normalised rows of the source."""
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            out = []
            for table in (ExtractedRecordRow, ParsedRecordRow, NormalisedRecordRow):
                found = await session.execute(
                    select(func.count()).select_from(table).where(table.source_id == source.id)
                )
                out.append(int(found.scalar_one()))
            return out[0], out[1], out[2]


async def _sql(source: Source, statement: str, **values: object) -> None:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            await session.execute(text(statement), {"s": source.id, **values})
            await session.commit()


def test_every_stage_has_its_policy() -> None:
    assert set(POLICIES) == {stage.name for stage in STAGES}


# ── replaced on demand ───────────────────────────────────────────────────────


async def test_reprocessing_a_stage_drops_it_and_what_followed_and_queues_it(
    source: Source,
) -> None:
    await _processed(source, 2)
    assert await _counts(source) == (2, 2, 2)
    sync_tests.queued_purges.clear()

    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            queued_stage = await reprocess(
                session, source.workspace_id, source, ProcessingStage.PARSING
            )

    assert queued_stage is ProcessingStage.PARSING
    assert queued() == [PARSE_JOB]
    assert await _counts(source) == (2, 0, 0)  # the extraction is kept
    await parse_source(source.workspace_id, source.id)
    await normalise_source(source.workspace_id, source.id)
    assert await _counts(source) == (2, 2, 2)


async def test_reprocessing_the_extraction_starts_again_from_the_records(source: Source) -> None:
    await _processed(source, 2)
    sync_tests.queued_purges.clear()

    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            await reprocess(session, source.workspace_id, source, ProcessingStage.EXTRACTION)

    assert await _counts(source) == (0, 0, 0)
    assert queued() == [EXTRACT_JOB]


# ── the daily sweep ──────────────────────────────────────────────────────────


async def test_the_sweep_abandons_runs_a_dead_worker_left_and_prunes_old_history(
    source: Source,
) -> None:
    await _processed(source, 1)
    now = datetime.now(UTC)
    stuck, old, recent = now - timedelta(hours=5), now - timedelta(days=HISTORY_DAYS + 1), now
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            for started, status in (
                (stuck, ProcessingRunStatus.RUNNING),
                (old, ProcessingRunStatus.SUCCEEDED),
                (recent - timedelta(minutes=5), ProcessingRunStatus.RUNNING),
            ):
                session.add(
                    ProcessingRun(
                        workspace_id=source.workspace_id,
                        source_id=source.id,
                        stage=ProcessingStage.PARSING,
                        status=status,
                        started_at=started,
                    )
                )
            await session.commit()

    result = await sweep_processing(now=now)

    assert (result["abandoned"], result["pruned"]) == (1, 1)
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(ProcessingRun.started_at, ProcessingRun.status).where(
                        ProcessingRun.source_id == source.id,
                        ProcessingRun.stage == ProcessingStage.PARSING,
                    )
                )
            ).all()
    statuses = {row.started_at: row.status for row in rows}
    assert statuses[stuck] is ProcessingRunStatus.ABANDONED
    assert old not in statuses
    # A run started five minutes ago may well be alive.
    assert statuses[recent - timedelta(minutes=5)] is ProcessingRunStatus.RUNNING


async def test_the_sweep_removes_what_deleted_records_gave_when_nothing_else_will(
    source: Source,
) -> None:
    await _processed(source, 2)
    # The record is gone at the vendor, and the source is switched off since:
    # no extraction will run to forget it.
    await _sql(
        source,
        "UPDATE source_records SET deleted_at = now() "
        "WHERE source_id = :s AND external_id = 'commits-0'",
    )

    result = await sweep_processing()

    assert result["forgotten"] >= 1
    assert await _counts(source) == (1, 1, 1)  # the cascade took its parse and candidates
    assert (await sweep_processing())["forgotten"] == 0  # idempotent
