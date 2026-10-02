"""The enrichment job (LEKA-359): a workspace's resolved entities, enriched.

    resolution run succeeded ──▶ enrich:<workspace>  (one run at a time)
    resolved_entities, resolved_keys          what resolution made
    normalised_records' relationships          what the sources stated —
                                               the quarantined left out
        │
        ▼
    enrich()  (engine.py) ──▶ enriched_relationships, entity_enrichments
                              — replaced whole; enrichment_runs — the run

A WORKSPACE STAGE, after entity resolution: it reads what the last
successful resolution run made — that run's id is what it was made from,
and a new one is something new to read. Queued by that run when it ends;
and by `advance`, through `resolve_if_pending`, when nothing is left to
resolve but enrichment has something to do (a new ENRICHER_VERSION, a run
that failed).

NOTHING OF THE BASE IS WRITTEN. Resolved entities stay as resolution made
them; what is enriched lives in its own tables, replaced in one
transaction: a failed run changes nothing — the last good enrichment stays
— and is recorded `failed` with the error's type. An enricher that fails
inside a run costs only its own output (`failures`).

A run that sees resolution run again while it read runs again, up to
ROUNDS times: what it keeps is made from one resolution run.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import enqueue_job, publish_event
from leka.db import session_factory, workspace_scope
from leka.ingestion.enrichment.engine import (
    ENRICHER_VERSION,
    Node,
    Snapshot,
    Stated,
    enrich,
)
from leka.ingestion.repository import EnrichmentRepository

logger = structlog.get_logger(__name__)

ENRICH_JOB = "leka.ingestion.enrichment.job.run_enrichment"
# Published when a run succeeds: leka/background/routes.py routes it.
ENRICHED = "ingestion.enriched"
CHUNK = 2_000
ROUNDS = 3
# Where an entity's records open it: the first few (LEKA-366).
MAX_LINKS = 5


def concurrency_key(workspace_id: uuid.UUID) -> str:
    return f"enrich:{workspace_id}"


def run_enrichment(workspace_id: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(enrich_workspace(uuid.UUID(workspace_id)))


async def enrich_if_pending(session: AsyncSession, workspace_id: uuid.UUID) -> bool:
    """Queue the workspace's enrichment when resolution made something it
    has not read, or its rules changed. Already queued or running: that run
    takes it — or runs again (ROUNDS)."""
    repository = EnrichmentRepository(session, workspace_id)
    if not await repository.pending(await repository.basis(), ENRICHER_VERSION):
        return False
    await enqueue_job(
        ENRICH_JOB,
        str(workspace_id),
        for_workspace_id=workspace_id,
        concurrency_key=concurrency_key(workspace_id),
    )
    return True


async def enrich_workspace(
    workspace_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, object]:
    counts: dict[str, object] = {"status": "nothing"}
    with workspace_scope(workspace_id):
        for _ in range(ROUNDS):
            async with session_factory() as session:
                repository = EnrichmentRepository(session, workspace_id)
                basis = await repository.basis()
                if not await repository.pending(basis, ENRICHER_VERSION):
                    break
                started = datetime.now(UTC)
                run = await repository.start(basis, ENRICHER_VERSION, at=started)
                await session.commit()
                try:
                    snapshot = await _snapshot(repository, now or started)
                    if await repository.basis() != basis:
                        # Resolution ran again while this read: read again.
                        run.status = "abandoned"
                        run.finished_at = datetime.now(UTC)
                        await session.commit()
                        continue
                    enrichment = enrich(snapshot)
                    await repository.replace(enrichment, run_id=run.id, at=started)
                    counts = dict(enrichment.counts)
                    run.status = "succeeded"
                    run.counts = counts
                    run.failures = [dict(failure) for failure in enrichment.failures]
                    run.finished_at = datetime.now(UTC)
                    # What reads the enrichment next — the company model
                    # (LEKA-361, leka.knowledge) — is told, not called.
                    await publish_event(
                        session,
                        workspace_id,
                        ENRICHED,
                        {"run_id": str(run.id)},
                        dedupe_key=f"enriched:{run.id}",
                    )
                    await session.commit()
                except BaseException as error:
                    await session.rollback()
                    run.status = "failed"
                    run.error = type(error).__name__[:200]
                    run.finished_at = datetime.now(UTC)
                    await session.commit()
                    raise
                if run.failures:
                    logger.warning(
                        "enrichers_failed", workspace_id=str(workspace_id), failures=run.failures
                    )
    logger.info("workspace_enriched", workspace_id=str(workspace_id), **counts)
    return counts


async def _snapshot(repository: EnrichmentRepository, now: datetime) -> Snapshot:
    """The workspace as resolution left it: its entities, every key each
    goes by and the sources that show it; their dates, and what the sources
    stated between keys, from the records."""
    holders: dict[str, set[uuid.UUID]] = defaultdict(set)
    sources: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for entity_id, key, source_id in await repository.keys():
        holders[key].add(entity_id)
        sources[entity_id].add(source_id)
    stated: list[Stated] = []
    dates: dict[uuid.UUID, dict[str, str]] = defaultdict(dict)
    links: dict[uuid.UUID, dict[str, None]] = defaultdict(dict)
    tools: dict[uuid.UUID, dict[str, None]] = defaultdict(dict)
    after: uuid.UUID | None = None
    while rows := await repository.records(after=after, limit=CHUNK):
        for row_id, source_id, own_key, attributes, found in rows:
            owner = holders.get(own_key or "", set())
            if len(owner) == 1 and isinstance(attributes, dict):
                _dates(dates[next(iter(owner))], attributes)
                entity_id = next(iter(owner))
                url, tool = attributes.get("url"), attributes.get("source_kind")
                if isinstance(url, str) and url and len(links[entity_id]) < MAX_LINKS:
                    links[entity_id][url] = None
                if isinstance(tool, str) and tool:
                    tools[entity_id][tool] = None
            for relationship in found if isinstance(found, list) else []:
                item = _stated(relationship, row_id, source_id)
                if item is not None:
                    stated.append(item)
        after = rows[-1][0]
    nodes = {
        entity_id: Node(
            id=entity_id,
            type=kind,
            key=key,
            name=name,
            attributes=dict(attributes or {}),
            sources=frozenset(sources.get(entity_id, ())),
            dates=dates.get(entity_id, {}),
            links=tuple(links.get(entity_id, {})),
            tools=tuple(sorted(tools.get(entity_id, {}))),
        )
        for entity_id, kind, key, name, attributes in await repository.entities()
    }
    return Snapshot(nodes=nodes, holders=dict(holders), stated=stated, now=now)


def _dates(into: dict[str, str], attributes: dict[str, object]) -> None:
    """A record's dates, added to its entity's: the earliest creation, the
    latest of every other. Normalisation writes them in UTC, to the second
    (`2026-09-20T08:00:00Z`): as text, they compare as dates."""
    for name, value in attributes.items():
        if not name.endswith("_at") or not isinstance(value, str) or not value:
            continue
        held = into.get(name)
        if held is None or (value < held if name == "created_at" else value > held):
            into[name] = value


def _stated(relationship: object, row_id: uuid.UUID, source_id: uuid.UUID) -> Stated | None:
    """A relationship as normalisation wrote it — none for what is not one."""
    if not isinstance(relationship, dict):
        return None
    kind, from_key, to_key = (relationship.get(k) for k in ("type", "from_key", "to_key"))
    if not (isinstance(kind, str) and isinstance(from_key, str) and isinstance(to_key, str)):
        return None
    confidence = relationship.get("confidence")
    evidence = relationship.get("evidence")
    return Stated(
        type=kind,
        from_key=from_key,
        to_key=to_key,
        source_id=source_id,
        record_id=row_id,
        confidence=min(1.0, max(0.0, float(confidence)))
        if isinstance(confidence, int | float)
        else 1.0,
        evidence=evidence[:100] if isinstance(evidence, str) else "",
    )
