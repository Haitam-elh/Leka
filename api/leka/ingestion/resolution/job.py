"""The entity resolution job (LEKA-357): a workspace's candidates, resolved.

    normalisation of any source ──▶ advance ──▶ resolve:<workspace>
                                               (one run at a time per workspace)
    normalised_records (every source)
        │  each row's entity, and the people, services, teams it names —
        │  a Mention per key per source
        ▼
    resolve()  (engine.py) ──▶ resolved_entities, resolved_keys,
                               resolution_decisions — replaced whole
                               resolution_runs — the run, its counts

A WORKSPACE STAGE, where the others are a source's: what is one thing is
decided across sources. Queued by `advance` (leka/ingestion/pipeline.py)
once a source's stages have nothing left to do and normalisation has made
something since the last success — or the rules changed (RESOLVER_VERSION).

MADE AGAIN WHOLE, IDS KEPT. Each run reads every candidate and replaces
what the last one made, in one transaction: what reads the entities never
sees half a run. An entity keeps the id its keys had — the id most of them
had — so an entity found again tomorrow is the same row id; a new one's id
is derived from its key, the same for the same input.

A run that sees normalisation move while it ran runs again, up to ROUNDS
times; what moves after is the next run's — queued by the next `advance`.
What it made is then enriched (LEKA-359): a run that succeeds queues
`enrich:<workspace>`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import structlog

from leka.db import session_factory, workspace_scope
from leka.ingestion.enrichment.job import enrich_if_pending
from leka.ingestion.models import (
    ResolutionDecision,
    ResolvedEntity,
    ResolvedKey,
)
from leka.ingestion.repository import ResolutionRepository
from leka.ingestion.resolution.engine import (
    RESOLVER_VERSION,
    Decision,
    Identity,
    Mention,
    Resolution,
    resolve,
)

logger = structlog.get_logger(__name__)

RESOLVE_JOB = "leka.ingestion.resolution.job.run_resolution"
CHUNK = 2_000
ROUNDS = 3
# New entities' ids: derived from the workspace and their key.
IDS = uuid.UUID("7b1d4c1e-3f5a-4e8a-9c57-357e5017e357")
EARLIEST = datetime.min.replace(tzinfo=UTC)


def concurrency_key(workspace_id: uuid.UUID) -> str:
    return f"resolve:{workspace_id}"


def run_resolution(workspace_id: str) -> dict[str, object]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(resolve_workspace(uuid.UUID(workspace_id)))


async def resolve_workspace(workspace_id: uuid.UUID) -> dict[str, object]:
    counts: dict[str, object] = {"status": "nothing"}
    with workspace_scope(workspace_id):
        for _ in range(ROUNDS):
            async with session_factory() as session:
                repository = ResolutionRepository(session, workspace_id)
                fingerprint = await repository.fingerprint()
                if not await repository.pending(fingerprint, RESOLVER_VERSION):
                    break
                now = datetime.now(UTC)
                run = await repository.start(fingerprint, RESOLVER_VERSION, at=now)
                await session.commit()
                try:
                    mentions = await _mentions(repository)
                    resolution = resolve(mentions)
                    counts = await _replace(repository, resolution, now)
                    counts["mentions"] = len(mentions)
                    run.status = "succeeded"
                    run.counts = counts
                    run.finished_at = datetime.now(UTC)
                    await session.commit()
                except BaseException as error:
                    await session.rollback()
                    run.status = "failed"
                    run.error = type(error).__name__[:200]
                    run.finished_at = datetime.now(UTC)
                    await session.commit()
                    raise
        async with session_factory() as session:
            await enrich_if_pending(session, workspace_id)
    logger.info("workspace_resolved", workspace_id=str(workspace_id), **counts)
    return counts


# ── what normalisation made ──────────────────────────────────────────────────


async def _mentions(repository: ResolutionRepository) -> list[Mention]:
    """Every candidate of the workspace, a Mention per key per source: the
    record's own entity, and every one it names."""
    found: dict[tuple[str, uuid.UUID], Mention] = {}
    ranks: dict[tuple[str, uuid.UUID], tuple[bool, datetime]] = {}
    after: uuid.UUID | None = None
    while rows := await repository.normalised(after=after, limit=CHUNK):
        for row_id, source_id, result, quality in rows:
            entity = result.get("entity")
            if isinstance(entity, dict):
                _add(found, ranks, entity, source_id, row_id, own=True, quality=quality)
            related = result.get("related")
            for named in related if isinstance(related, list) else []:
                if isinstance(named, dict):
                    _add(found, ranks, named, source_id, row_id, own=False)
        after = rows[-1][0]
    return list(found.values())


def _add(
    found: dict[tuple[str, uuid.UUID], Mention],
    ranks: dict[tuple[str, uuid.UUID], tuple[bool, datetime]],
    entity: dict[str, Any],
    source_id: uuid.UUID,
    row_id: uuid.UUID,
    *,
    own: bool,
    quality: float | None = None,
) -> None:
    """One more saying of a key by a source. Its name, type and attributes
    are what speaks best for it: the thing's own record before a record
    naming it, then the latest."""
    key, kind = entity.get("key"), entity.get("type")
    if not isinstance(key, str) or not key or not isinstance(kind, str):
        return
    name = entity.get("name")
    observed = _moment(entity.get("observed_at"))
    attributes = entity.get("attributes")
    rank = (own, observed or EARLIEST)
    mention = found.setdefault(
        (key, source_id),
        Mention(key=key, type=kind, source_id=source_id, name=key, example=row_id),
    )
    mention.aliases |= {a for a in entity.get("aliases") or [] if isinstance(a, str)}
    mention.confidence = max(
        mention.confidence if mention.records + mention.named else 0.0,
        float(entity.get("confidence") or 1.0),
    )
    mention.records += 1 if own else 0
    mention.named += 0 if own else 1
    if quality is not None:
        mention.quality = max(quality, mention.quality or 0.0)
    if observed is not None:
        mention.first_seen = min(filter(None, (mention.first_seen, observed)))
        mention.last_seen = max(filter(None, (mention.last_seen, observed)))
    if (key, source_id) not in ranks or rank >= ranks[(key, source_id)]:
        ranks[(key, source_id)] = rank
        mention.type = kind
        mention.name = name if isinstance(name, str) and name else key
        mention.attributes = dict(attributes) if isinstance(attributes, dict) else {}


def _moment(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        found = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


# ── what it made ─────────────────────────────────────────────────────────────


def _ids(
    workspace_id: uuid.UUID, identities: list[Identity], previous: dict[str, set[uuid.UUID]]
) -> list[uuid.UUID]:
    """Each entity's id: the one most of its keys had, if no bigger entity
    took it first — else one derived from its key."""
    order = sorted(
        range(len(identities)), key=lambda i: (-len(identities[i].keys), identities[i].key)
    )
    taken: set[uuid.UUID] = set()
    ids: dict[int, uuid.UUID] = {}
    for i in order:
        votes = Counter(
            old
            for seen in identities[i].keys
            for old in previous.get(seen.key, ())
            if old not in taken
        )
        chosen = votes.most_common(1)[0][0] if votes else None
        if chosen is None:
            chosen = uuid.uuid5(IDS, f"{workspace_id}:{identities[i].type}:{identities[i].key}")
            if chosen in taken:
                chosen = uuid.uuid4()
        taken.add(chosen)
        ids[i] = chosen
    return [ids[i] for i in range(len(identities))]


async def _replace(
    repository: ResolutionRepository, resolution: Resolution, now: datetime
) -> dict[str, object]:
    identities = resolution.identities
    ids = _ids(repository.workspace_id, identities, await repository.previous_ids())
    await repository.clear()
    await repository.write(
        ResolvedEntity,
        [
            {
                "id": ids[i],
                "type": identity.type,
                "key": identity.key[:1000],
                "name": identity.name[:500],
                "names": identity.names,
                "attributes": identity.attributes,
                "conflicts": identity.conflicts,
                "confidence": identity.confidence,
                "sources": len(identity.sources),
                "quality": identity.quality,
                "resolver_version": RESOLVER_VERSION,
                "resolved_at": now,
            }
            for i, identity in enumerate(identities)
        ],
    )
    await repository.write(
        ResolvedKey,
        [
            {
                "entity_id": ids[i],
                "source_id": seen.source_id,
                "key": seen.key[:1000],
                "kind": seen.kind,
                "name": seen.name[:500] if seen.name else None,
                "records": seen.records,
                "named": seen.named,
                "first_seen_at": seen.first_seen,
                "last_seen_at": seen.last_seen,
                "example_record_id": seen.example,
            }
            for i, identity in enumerate(identities)
            for seen in identity.keys
        ],
    )
    decisions = [
        _decision(ids[i], None, decision)
        for i, identity in enumerate(identities)
        for decision in identity.decisions
    ] + [_decision(ids[i], ids[j], decision) for i, j, decision in resolution.links]
    await repository.write(ResolutionDecision, decisions)
    kinds = Counter(str(d["kind"]) for d in decisions)
    return {
        "entities": len(identities),
        "merged": sum(
            1
            for identity in identities
            if len({k.key for k in identity.keys if k.kind == "key"}) > 1
        ),
        "links": kinds["link"],
        "ambiguous": kinds["ambiguous"],
        "conflicted": sum(1 for identity in identities if identity.conflicts),
    }


def _decision(
    entity_id: uuid.UUID, other: uuid.UUID | None, decision: Decision
) -> dict[str, object]:
    return {
        "entity_id": entity_id,
        "other_entity_id": other,
        "kind": decision.kind,
        "rule": decision.rule[:100],
        "confidence": decision.confidence,
        "keys": list(decision.keys),
        "evidence": decision.evidence[:1000],
    }
