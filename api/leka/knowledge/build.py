"""The company model's build (LEKA-361): what resolution and enrichment made,
as the company's canonical entities — typed, checked, versioned, with a
lifecycle and where every piece came from.

    resolved entities (LEKA-357) + their keys per source
    enriched attributes and relationships (LEKA-359)
    the model as the last build left it
        │
        ▼
    build()  ──▶  entities to write, versions to record, relationships

IDENTITY. An entity is the resolved entity: its id, stable from one
resolution to the next, is the model's.

WHAT IT SAYS. Its sources' attributes; where they say nothing, enrichment's
— each with its origin in `provenance`. Checked against its kind's schema
(registry.py).

LIFECYCLE. `archived` when its source says so; `dormant` when enrichment
finds nothing done to it for 180 days; `removed` when no source shows it any
more — kept with its history, never deleted; `active` otherwise. A removed
thing that comes back is active again, the same entity.

VERSIONS. What it says — its name, its attributes, its lifecycle — hashed:
a different hash is a new version, recorded with what changed. Measures
that move with time alone (last activity, activity over 90 days, incidents
of the last 90 days) are kept current but make no version: a version is a
change of the thing, not of the clock.

Pure: rows in, rows out; the job reads and writes (job.py).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from leka.knowledge.models import Lifecycle
from leka.knowledge.registry import BUILT_FROM, RELATIONSHIP_FROM, clean

# Measures that move with the clock: current, but no version of their own.
MEASURES = frozenset(
    {
        "last_activity_at",
        "activity_90d",
        "incidents_90d",
        "open_incidents",
        "mttr_minutes",
        "stale",
        "lifecycle",
    }
)
ARCHIVED_STATES = frozenset({"archived"})
MAX_SOURCES = 20


@dataclass(frozen=True)
class SeenKey:
    """A key an entity goes by, as one source gave it."""

    key: str
    source_id: uuid.UUID
    kind: str
    first_seen: datetime | None = None
    last_seen: datetime | None = None


@dataclass(frozen=True)
class Enriched:
    """An attribute enrichment added (docs/enrichment.md)."""

    value: object
    rule: str
    confidence: float


@dataclass(frozen=True)
class Candidate:
    """A resolved entity, and what enrichment added to it."""

    id: uuid.UUID
    type: str
    key: str
    name: str
    attributes: dict[str, object]
    confidence: float = 1.0
    quality: float | None = None
    keys: tuple[SeenKey, ...] = ()
    enriched: dict[str, Enriched] = field(default_factory=dict)


@dataclass(frozen=True)
class Link:
    """A relationship enrichment made between two resolved entities."""

    from_id: uuid.UUID
    to_id: uuid.UUID
    type: str
    origin: str
    rule: str
    confidence: float
    cross_source: bool = False
    provenance: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class Current:
    """An entity as the last build left it."""

    id: uuid.UUID
    name: str
    attributes: dict[str, object]
    lifecycle: str
    version: int
    content_hash: str
    first_seen_at: datetime | None
    lifecycle_changed_at: datetime | None
    provenance: dict[str, object]
    key: str
    type: str
    schema_version: int
    confidence: float
    quality: float | None
    last_seen_at: datetime | None


@dataclass
class Built:
    entities: list[dict[str, object]]
    versions: list[dict[str, object]]
    relationships: list[dict[str, object]]
    counts: Counter[str]


def content_of(name: str, attributes: dict[str, object], lifecycle: str) -> dict[str, object]:
    """What a version is made of: the thing, not the clock."""
    return {
        "name": name,
        "attributes": {k: v for k, v in attributes.items() if k not in MEASURES},
        "lifecycle": lifecycle,
    }


def fingerprint(content: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def changes(before: dict[str, object], after: dict[str, object]) -> list[str]:
    """What differs between two contents: "name", "lifecycle",
    "attributes.<name>"."""
    changed = [part for part in ("name", "lifecycle") if before.get(part) != after.get(part)]
    old, new = _attributes(before), _attributes(after)
    changed += [
        f"attributes.{name}"
        for name in sorted(set(old) | set(new))
        if old.get(name) != new.get(name)
    ]
    return changed


def _attributes(content: dict[str, object]) -> dict[str, object]:
    found = content.get("attributes")
    return found if isinstance(found, dict) else {}


def lifecycle_of(attributes: dict[str, object]) -> Lifecycle:
    if attributes.get("state") in ARCHIVED_STATES:
        return Lifecycle.ARCHIVED
    if attributes.get("lifecycle") == "dormant":
        return Lifecycle.DORMANT
    return Lifecycle.ACTIVE


def build(
    candidates: list[Candidate],
    links: list[Link],
    current: dict[uuid.UUID, Current],
    *,
    now: datetime,
) -> Built:
    # What a build did, said even when it is nothing.
    counts: Counter[str] = Counter(dict.fromkeys(("created", "changed", "unchanged", "removed"), 0))
    entities: list[dict[str, object]] = []
    versions: list[dict[str, object]] = []
    modelled: set[uuid.UUID] = set()

    for candidate in candidates:
        kind = BUILT_FROM.get(candidate.type)
        if kind is None:
            counts["not_modelled"] += 1
            continue
        merged = dict(candidate.attributes)
        origins: dict[str, object] = {}
        for name, value in candidate.enriched.items():
            if name in merged:
                continue
            merged[name] = value.value
            origins[name] = {
                "origin": "enrichment",
                "rule": value.rule,
                "confidence": value.confidence,
            }
        attributes, dropped = clean(kind, merged)
        counts["attributes_dropped"] += len(dropped)
        lifecycle = lifecycle_of(attributes)
        content = content_of(candidate.name, attributes, lifecycle.value)
        digest = fingerprint(content)
        before = current.get(candidate.id)
        firsts = [k.first_seen for k in candidate.keys if k.first_seen]
        lasts = [k.last_seen for k in candidate.keys if k.last_seen]
        first_seen = min(
            [*firsts, *([before.first_seen_at] if before and before.first_seen_at else [])],
            default=now,
        )
        sources = sorted(
            {(str(k.source_id), k.key, k.kind) for k in candidate.keys},
        )[:MAX_SOURCES]
        provenance = {
            "sources": [
                {"source_id": source, "key": key, "kind": seen} for source, key, seen in sources
            ],
            "attributes": {
                name: origins.get(name, {"origin": "source"}) for name in sorted(attributes)
            },
            "dropped": dropped,
        }

        if before is None:
            version, changed = 1, ["created"]
        elif before.content_hash != digest:
            version = before.version + 1
            changed = changes(content_of(before.name, before.attributes, before.lifecycle), content)
        else:
            version, changed = before.version, []
        if changed:
            versions.append(
                {
                    "entity_id": candidate.id,
                    "version": version,
                    "content": content,
                    "changed": changed,
                    "schema_version": kind.version,
                    "recorded_at": now,
                }
            )
            counts["created" if before is None else "changed"] += 1
        else:
            counts["unchanged"] += 1

        entities.append(
            {
                "id": candidate.id,
                "type": kind.type.value,
                "key": candidate.key[:1000],
                "name": candidate.name[:500],
                "attributes": attributes,
                "lifecycle": lifecycle.value,
                "version": version,
                "schema_version": kind.version,
                "content_hash": digest,
                "confidence": min(1.0, max(0.0, candidate.confidence)),
                "quality": candidate.quality,
                "provenance": provenance,
                "first_seen_at": first_seen,
                "last_seen_at": max(lasts, default=before.last_seen_at if before else None),
                "removed_at": None,
                "lifecycle_changed_at": (
                    now
                    if before is None or before.lifecycle != lifecycle.value
                    else before.lifecycle_changed_at
                ),
            }
        )
        modelled.add(candidate.id)
        counts[f"type.{kind.type.value}"] += 1

    # What no source shows any more: removed, kept, its history with it.
    for gone in current.values():
        if gone.id in modelled:
            continue
        if gone.lifecycle == Lifecycle.REMOVED.value:
            counts["still_removed"] += 1
            continue
        content = content_of(gone.name, gone.attributes, Lifecycle.REMOVED.value)
        version = gone.version + 1
        versions.append(
            {
                "entity_id": gone.id,
                "version": version,
                "content": content,
                "changed": ["lifecycle"],
                "schema_version": gone.schema_version,
                "recorded_at": now,
            }
        )
        entities.append(
            {
                "id": gone.id,
                "type": gone.type,
                "key": gone.key,
                "name": gone.name,
                "attributes": gone.attributes,
                "lifecycle": Lifecycle.REMOVED.value,
                "version": version,
                "schema_version": gone.schema_version,
                "content_hash": fingerprint(content),
                "confidence": gone.confidence,
                "quality": gone.quality,
                "provenance": gone.provenance,
                "first_seen_at": gone.first_seen_at,
                "last_seen_at": gone.last_seen_at,
                "removed_at": now,
                "lifecycle_changed_at": now,
            }
        )
        counts["removed"] += 1

    relationships: dict[tuple[uuid.UUID, uuid.UUID, str], dict[str, object]] = {}
    for link in links:
        relation = RELATIONSHIP_FROM.get(link.type)
        if relation is None:
            counts["relationships_not_modelled"] += 1
            continue
        if link.from_id not in modelled or link.to_id not in modelled:
            counts["relationships_to_unmodelled"] += 1
            continue
        key = (link.from_id, link.to_id, relation.value)
        held = relationships.get(key)
        stronger = held is None or (
            (link.origin == "stated", link.confidence)
            > (held["origin"] == "stated", float(str(held["confidence"])))
        )
        if stronger:
            relationships[key] = {
                "from_entity_id": link.from_id,
                "to_entity_id": link.to_id,
                "type": relation.value,
                "confidence": min(1.0, max(0.0, link.confidence)),
                "origin": link.origin,
                "rule": link.rule[:100],
                "cross_source": link.cross_source,
                "provenance": list(link.provenance),
            }
    counts["entities"] = len(modelled)
    counts["relationships"] = len(relationships)
    return Built(
        entities=entities,
        versions=versions,
        relationships=list(relationships.values()),
        counts=counts,
    )
