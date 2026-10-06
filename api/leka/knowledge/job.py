"""The company model's build job (LEKA-361).

    enrichment run succeeded ──▶ event "ingestion.enriched"
                               ──▶ run_model_build_for_event ──▶ model:<workspace>
    resolved entities, their keys, what enrichment added (leka.ingestion)
        │
        ▼
    build()  (build.py) ──▶ entities (upserted, ids kept), entity_versions,
                            relationships (replaced); model_runs — the run

An EVENT, not a call: leka.ingestion must not import this module
(architecture rule 1), so the enrichment job publishes what happened and
leka/background/routes.py routes it here. The event's job queues the build
under one concurrency key per workspace: one build at a time.

It reads what the last successful enrichment run made; that run's id is
what it was made from, and a new one is something new to build. A failed
build changes nothing — the model is written in one transaction — and is
recorded `failed` with the error's type.

A build that changed something says so: the event "knowledge.model_built",
written in the build's own transaction — the contexts that hold what
changed follow it (leka.context, LEKA-374).

A FACT VALIDATED or withdrawn (LEKA-380, leka.intelligence) queues a build
too (`queue_model_build`): the build applies the validated facts, and their
fingerprint is part of what it was made from.

THE SWEEP, hourly (leka/background/schedule.py), queues what no event
will: a workspace enriched before this module existed, a build that
failed, a new MODEL_VERSION, a fact validated whose build did not run. It
closes the runs a dead worker left and forgets the history past
HISTORY_DAYS — never a workspace's last success.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import structlog

from leka.background import Event, enqueue_job, publish_event
from leka.background.runner import RQ_JOB_TIMEOUT
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import EnrichedWorkspaces, EnrichmentRepository
from leka.knowledge.build import Candidate, Enriched, Link, SeenKey, build
from leka.knowledge.registry import MODEL_VERSION
from leka.knowledge.repository import AssertionRepository, ModelRepository, ModelSweeper

logger = structlog.get_logger(__name__)

MODEL_JOB = "leka.knowledge.job.run_model_build"
# What a build that changed something publishes (LEKA-374).
MODEL_BUILT = "knowledge.model_built"
ROUNDS = 3
HISTORY_DAYS = 90
RELATIONSHIP_HISTORY_DAYS = 365
# Longer than RQ lets a job's work-horse live: a run older than this is dead.
STUCK_AFTER = timedelta(seconds=RQ_JOB_TIMEOUT) + timedelta(hours=1)
# Builds one sweep queues at most; the next hour takes the rest.
SWEEP_BATCH = 200


def concurrency_key(workspace_id: uuid.UUID) -> str:
    return f"model:{workspace_id}"


def run_model_build_for_event(event_id: str) -> str:
    """`ingestion.enriched` (leka/background/routes.py): queue the build."""
    return asyncio.run(_queue_for_event(uuid.UUID(event_id)))


async def _queue_for_event(event_id: uuid.UUID) -> str:
    with system_scope():
        async with session_factory() as session:
            event = await session.get(Event, event_id)
    if event is None:
        return "gone"
    return "queued" if await _queue(event.workspace_id) else "already queued"


async def queue_model_build(workspace_id: uuid.UUID) -> bool:
    """Build the workspace's model again — a fact was validated or withdrawn
    (LEKA-380); False when a build is already queued or running, which
    will read it."""
    return await _queue(workspace_id)


async def _queue(workspace_id: uuid.UUID) -> bool:
    """Queue the workspace's build; False when one is already queued or running."""
    run = await enqueue_job(
        MODEL_JOB,
        str(workspace_id),
        for_workspace_id=workspace_id,
        concurrency_key=concurrency_key(workspace_id),
    )
    return run is not None


def run_model_sweep() -> dict[str, int]:
    """Entry point for the schedule (leka/background/schedule.py)."""
    return asyncio.run(sweep_models())


async def sweep_models(*, now: datetime | None = None) -> dict[str, int]:
    """Every workspace whose model is behind its enrichment, queued; dead
    runs closed; old history forgotten. Idempotent."""
    now = now or datetime.now(UTC)
    with system_scope():
        async with session_factory() as session:
            sweeper = ModelSweeper(session)
            abandoned = await sweeper.abandon_stuck(before=now - STUCK_AFTER, at=now)
            pruned = await sweeper.prune(before=now - timedelta(days=HISTORY_DAYS))
            # The relationships' history (LEKA-368): a year of it.
            pruned += await sweeper.prune_changes(
                before=now - timedelta(days=RELATIONSHIP_HISTORY_DAYS)
            )
            enriched = await EnrichedWorkspaces(session).latest()
            built = await sweeper.built()
            asserted = await sweeper.asserted()
            await session.commit()
    behind = [
        workspace_id
        for workspace_id, basis in enriched.items()
        if built.get(workspace_id) != (basis, MODEL_VERSION, asserted.get(workspace_id))
    ]
    result = {"abandoned": abandoned, "pruned": pruned, "queued": 0, "already_active": 0}
    for workspace_id in behind[:SWEEP_BATCH]:
        result["queued" if await _queue(workspace_id) else "already_active"] += 1
    logger.info("models_swept", **result)
    return result


def run_model_build(workspace_id: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(build_workspace(uuid.UUID(workspace_id)))


async def build_workspace(workspace_id: uuid.UUID) -> dict[str, object]:
    counts: dict[str, object] = {"status": "nothing"}
    with workspace_scope(workspace_id):
        for _ in range(ROUNDS):
            async with session_factory() as session:
                inputs = EnrichmentRepository(session, workspace_id)
                model = ModelRepository(session, workspace_id)
                validated = AssertionRepository(session, workspace_id)
                basis = await inputs.latest_enrichment()
                facts = await validated.fingerprint()
                if not await model.pending(basis, MODEL_VERSION, facts):
                    break
                now = datetime.now(UTC)
                run = await model.start(basis, MODEL_VERSION, at=now, assertions=facts)
                await session.commit()
                try:
                    candidates, links = await _inputs(inputs)
                    assertions = await validated.active()
                    if (
                        await inputs.latest_enrichment() != basis
                        or await validated.fingerprint() != facts
                    ):
                        # Enrichment ran again, or a fact was validated,
                        # while this read: read again.
                        run.status = "abandoned"
                        run.finished_at = datetime.now(UTC)
                        await session.commit()
                        continue
                    built = build(
                        candidates,
                        links,
                        await model.current(),
                        now=now,
                        previous=await model.current_links(),
                        assertions=assertions,
                    )
                    await model.write(built, run_id=run.id)
                    counts = dict(built.counts)
                    run.status = "succeeded"
                    run.counts = counts
                    run.finished_at = datetime.now(UTC)
                    if built.versions or built.changes:
                        await publish_event(
                            session,
                            workspace_id,
                            MODEL_BUILT,
                            {"run_id": str(run.id)},
                            dedupe_key=f"{MODEL_BUILT}:{run.id}",
                        )
                    await session.commit()
                except BaseException as error:
                    await session.rollback()
                    run.status = "failed"
                    run.error = type(error).__name__[:200]
                    run.finished_at = datetime.now(UTC)
                    await session.commit()
                    raise
    logger.info("company_model_built", workspace_id=str(workspace_id), **counts)
    return counts


async def _inputs(inputs: EnrichmentRepository) -> tuple[list[Candidate], list[Link]]:
    """What resolution and enrichment made, as the build reads it."""
    keys: dict[uuid.UUID, list[SeenKey]] = defaultdict(list)
    for entity_id, key, source_id, kind, first, last in await inputs.seen_keys():
        keys[entity_id].append(SeenKey(key, source_id, kind, first, last))
    enriched: dict[uuid.UUID, dict[str, Enriched]] = defaultdict(dict)
    for entity_id, attribute, value, rule, confidence, evidence in await inputs.enrichments():
        enriched[entity_id][attribute] = Enriched(value, rule, confidence, evidence)
    candidates = [
        Candidate(
            id=entity_id,
            type=kind,
            key=key,
            name=name,
            attributes=dict(attributes or {}),
            confidence=confidence,
            quality=quality,
            keys=tuple(keys.get(entity_id, ())),
            enriched=enriched.get(entity_id, {}),
            conflicts=tuple(conflicts or ()),
        )
        for (
            entity_id,
            kind,
            key,
            name,
            attributes,
            confidence,
            quality,
            conflicts,
        ) in await inputs.resolved()
    ]
    links = [
        Link(
            from_id=edge.from_entity_id,
            to_id=edge.to_entity_id,
            type=edge.type,
            origin=edge.origin,
            rule=edge.rule,
            confidence=edge.confidence,
            cross_source=edge.cross_source,
            provenance=tuple(edge.provenance),
        )
        for edge in await inputs.enriched_edges()
    ]
    return candidates, links
