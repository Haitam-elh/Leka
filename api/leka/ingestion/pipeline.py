"""The processing pipeline (LEKA-360): its stages, their order, how one hands
over to the next, and the record of each run.

    collection ──▶ extraction ──▶ parsing ──▶ normalisation ──▶ resolution
    (a pass)       extract:<id>   parse:<id>  normalise:<id>   resolve:<workspace>

ONE DEFINITION. `STAGES` is the order; each stage depends on the one before
it and reads only what that one wrote. The pass and every stage end with
`advance`, which queues the FIRST later stage that has work — never two at
once for one source: a later stage waits for the rows the earlier one is
writing, and is queued by it when it ends. A later stage alone has work when
only its own version changed; `advance` finds it all the same.

THEN THE WORKSPACE. Entity resolution (LEKA-357) decides across sources
what is one thing, so it is the workspace's, not a source's: `advance`,
finding nothing left for a source, queues `resolve:<workspace>` when
normalisation made something since its last success
(leka/ingestion/resolution/job.py).

PARALLEL WHERE SAFE. One run of a stage at a time per source (its
concurrency key); stages of one source run in order; different sources run
side by side.

RECOVERY. Every stage is incremental and idempotent: it saves chunk by
chunk, and a row is replaced only by a complete one. A run that fails —
retried by the job runner with backoff — or whose worker dies starts again
where the last committed chunk ended, and the next stage is queued only
when this one ends: downstream never reads a half-written stage as done.
`stage_run` records each run (`processing_runs`), and marks `abandoned` the
run a dead worker left `running`.

Contract: docs/processing.md.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import Event, enqueue_job
from leka.connectors import Mapping, Source, SourceService
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion.extraction.engine import versions as extraction_versions
from leka.ingestion.models import ProcessingRunStatus, ProcessingStage
from leka.ingestion.normalisation import engine as normalisation_engine
from leka.ingestion.parsing import engine as parsing_engine
from leka.ingestion.repository import (
    ExtractionRepository,
    NormalisationRepository,
    ParsingRepository,
    ProcessingRunRepository,
    ResolutionRepository,
)
from leka.ingestion.resolution import RESOLVER_VERSION
from leka.ingestion.resolution.job import RESOLVE_JOB
from leka.ingestion.resolution.job import concurrency_key as resolution_key

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Stage:
    name: ProcessingStage
    job: str  # the job's dotted path
    prefix: str  # of its concurrency key

    def key(self, source_id: uuid.UUID) -> str:
        return f"{self.prefix}:{source_id}"


STAGES: tuple[Stage, ...] = (
    Stage(ProcessingStage.EXTRACTION, "leka.ingestion.extraction.job.run_extraction", "extract"),
    Stage(ProcessingStage.PARSING, "leka.ingestion.parsing.job.run_parsing", "parse"),
    Stage(
        ProcessingStage.NORMALISATION,
        "leka.ingestion.normalisation.job.run_normalisation",
        "normalise",
    ),
)
BY_NAME = {stage.name: stage for stage in STAGES}


def versions(stage: ProcessingStage, source: Source) -> dict[str, object]:
    """What a stage's rows are compared with: each extraction strategy's
    version for the source's kind, or the parser's or normaliser's."""
    if stage is ProcessingStage.EXTRACTION:
        return dict(extraction_versions(source.kind))
    if stage is ProcessingStage.PARSING:
        return {"parser": parsing_engine.PARSER_VERSION}
    return {"normaliser": normalisation_engine.NORMALISER_VERSION}


async def pending(
    session: AsyncSession, workspace_id: uuid.UUID, source: Source, stage: ProcessingStage
) -> bool:
    """Whether the stage has rows to (re)make for this source."""
    if stage is ProcessingStage.EXTRACTION:
        return await ExtractionRepository(session, workspace_id).has_stale(
            source.id, extraction_versions(source.kind)
        )
    if stage is ProcessingStage.PARSING:
        return await ParsingRepository(session, workspace_id).has_stale(
            source.id, parsing_engine.PARSER_VERSION
        )
    settings_version, _mapping = await source_mapping(session, workspace_id, source)
    return await NormalisationRepository(session, workspace_id).has_stale(
        source.id, normalisation_engine.NORMALISER_VERSION, settings_version
    )


async def source_mapping(
    session: AsyncSession, workspace_id: uuid.UUID, source: Source
) -> tuple[int, Mapping]:
    """The source's settings version and its mapping (LEKA-351); 0 and the
    defaults before any is saved."""
    service = SourceService(session, workspace_id, actor_user_id=None)
    version, settings = await service.settings(source)
    return version, settings.mapping


async def advance(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    source: Source,
    *,
    after: ProcessingStage | None,
) -> ProcessingStage | None:
    """Queue the first stage after `after` (None: after collection) that has
    work. Returns it, or None when the source is processed through — and
    then the workspace's resolution, if it has something new to read."""
    names = [stage.name for stage in STAGES]
    start = 0 if after is None else names.index(after) + 1
    for stage in STAGES[start:]:
        if await pending(session, workspace_id, source, stage.name):
            await enqueue_job(
                stage.job,
                str(workspace_id),
                str(source.id),
                for_workspace_id=workspace_id,
                concurrency_key=stage.key(source.id),
            )
            return stage.name
    await resolve_if_pending(session, workspace_id)
    return None


async def resolve_if_pending(session: AsyncSession, workspace_id: uuid.UUID) -> bool:
    """Queue the workspace's entity resolution (LEKA-357) when normalisation
    made something since its last success, or its rules changed. Already
    queued or running: that run takes it — or runs again (ROUNDS)."""
    resolution = ResolutionRepository(session, workspace_id)
    if not await resolution.pending(await resolution.fingerprint(), RESOLVER_VERSION):
        return False
    await enqueue_job(
        RESOLVE_JOB,
        str(workspace_id),
        for_workspace_id=workspace_id,
        concurrency_key=resolution_key(workspace_id),
    )
    return True


@asynccontextmanager
async def stage_run(
    workspace_id: uuid.UUID,
    source: Source,
    stage: ProcessingStage,
    *,
    versions_used: dict[str, object] | None = None,
) -> AsyncIterator[dict[str, int]]:
    """Record one run of a stage, in a session of its own: `running` now,
    then `succeeded` with the counts the body filled in, or `failed` with the
    exception's type — which is raised again, for the job runner to retry.
    The caller holds the workspace scope."""
    counts: dict[str, int] = {}
    async with session_factory() as session:
        runs = ProcessingRunRepository(session, workspace_id)
        now = datetime.now(UTC)
        abandoned = await runs.abandon_running(source.id, stage, at=now)
        if abandoned:
            logger.warning("processing_run_abandoned", source_id=str(source.id), stage=stage.value)
        run = runs.start(
            source.id, stage, versions=versions_used or versions(stage, source), at=now
        )
        await session.commit()
        try:
            yield counts
        except BaseException as error:
            run.status = ProcessingRunStatus.FAILED
            run.error = type(error).__name__[:200]
            run.counts = dict(counts)
            run.finished_at = datetime.now(UTC)
            await session.commit()
            raise
        run.status = ProcessingRunStatus.SUCCEEDED
        run.counts = dict(counts)
        run.finished_at = datetime.now(UTC)
        await session.commit()


def run_advance_for_event(event_id: str) -> str:
    """`source.mapping_changed` (leka/background/routes.py): the source's
    records are normalised again with its new mapping — no pass: nothing to
    read again. Published with the settings version, so it never runs with
    the old mapping."""
    return asyncio.run(_advance_for_event(uuid.UUID(event_id)))


async def _advance_for_event(event_id: uuid.UUID) -> str:
    with system_scope():
        async with session_factory() as session:
            event = await session.get(Event, event_id)
    if event is None:
        return "gone"
    workspace_id = event.workspace_id
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            source = await session.get(Source, uuid.UUID(str(event.payload["source_id"])))
            if source is None:
                return "gone"
            queued = await advance(session, workspace_id, source, after=None)
    return queued.value if queued else "nothing"
