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

LIFECYCLE. `archived` when its source says so — or its catalogue says it is
retired, its provider that it is terminated or deleted; `dormant` when
enrichment finds nothing done to it for 180 days; `removed` when no source
shows it any more — kept with its history, never deleted; `active`
otherwise. A removed thing that comes back is active again, the same
entity.

VERSIONS. What it says — its name, its attributes, its lifecycle — hashed:
a different hash is a new version, recorded with what changed. Measures
that move with time alone (last activity, activity over 90 days, incidents
of the last 90 days) are kept current but make no version: a version is a
change of the thing, not of the clock.

WHEN IT HAPPENED. An incident, a change, a deployment, a release, a merged
pull request is an event too: `occurred_at` says when, from its sources'
dates — what enrichment carries from the records, resolution keeping none
(LEKA-367) — else when a source first showed it. Such an attribute's
origin is its source's.

RELATIONSHIPS are checked against their kinds' contracts (contracts.py,
LEKA-368): one whose ends a contract does not take is dropped; an inferred
link closing a loop where none may be is dropped; the rest said. Each
keeps when it first appeared and last changed; what appeared, changed or
went since the last build is recorded.

RELATIONSHIPS keep the environments they are true in: an end that runs in a
single environment — a production instance, a service seen in production
only, the production environment itself — makes the edge that
environment's (LEKA-362). An end that runs in several says nothing.

WHAT SEARCH READS. Each entity's names, and what else says what it is,
folded for search (search.py, LEKA-369) — written with it at each build.

Pure: rows in, rows out; the job reads and writes (job.py).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from leka.knowledge.contracts import Previous, check, history
from leka.knowledge.models import Lifecycle
from leka.knowledge.registry import BUILT_FROM, RELATIONSHIP_FROM, clean
from leka.knowledge.search import fields

# When an event happened, by kind: the first of these dates it has — the
# earliest, for an incident (LEKA-367).
OCCURRED: dict[str, tuple[str, ...]] = {
    "incident": ("detected_at", "created_at"),
    "deployment": ("finished_at", "started_at", "created_at"),
    "change": ("started_at", "planned_start_at", "created_at"),
    "release": ("published_at", "created_at"),
    "pull_request": ("merged_at",),
}
EARLIEST = frozenset({"incident"})
# An incident, a change, a deployment, a release whose sources say no date
# happened when a source first showed it: an event is always in time. A
# pull request is an event once merged only.
UNDATED = frozenset({"incident", "deployment", "change", "release"})
# What enrichment carries from the records, as they say it: a source's.
RECORD = "record"
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
        # A table's size moves with every write (LEKA-364).
        "estimated_rows",
        "size_bytes",
        # What someone's work shows they know moves with their work (LEKA-365).
        "expertise",
        "languages",
        # A document grows stale with time alone (LEKA-366).
        "freshness",
    }
)
# Its source says it is no more: archived; a resource terminated, an account
# deleted, at its provider (LEKA-363).
ARCHIVED_STATES = frozenset({"archived", "terminated", "deleted"})
MAX_SOURCES = 20
# The sources' disagreements kept in an entity's provenance: this many, of
# this many values each.
MAX_CONFLICTS = 20
MAX_VALUES = 10
ENVIRONMENTS = frozenset({"production", "staging", "development", "test"})


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
    # What its sources disagree on (resolution's `conflicts`): {attribute,
    # chosen, values: [{value, source_id, …}]}.
    conflicts: tuple[dict[str, object], ...] = ()


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
    # What appeared, changed or went; what is wrong (LEKA-368).
    changes: list[dict[str, object]] = field(default_factory=list)
    issues: list[dict[str, object]] = field(default_factory=list)


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


def _conflicts(found: tuple[dict[str, object], ...]) -> list[dict[str, object]]:
    """Resolution's disagreements, as provenance keeps them: the attribute,
    the value chosen, every value with the source that gave it."""
    kept: list[dict[str, object]] = []
    for conflict in found[:MAX_CONFLICTS]:
        values = conflict.get("values")
        listed = values if isinstance(values, list) else []
        kept.append(
            {
                "attribute": conflict.get("attribute"),
                "chosen": conflict.get("chosen"),
                "values": [
                    {"value": v.get("value"), "source_id": v.get("source_id")}
                    for v in listed[:MAX_VALUES]
                    if isinstance(v, dict)
                ],
            }
        )
    return kept


def _environment_of(kind: str, key: str, attributes: dict[str, object]) -> str | None:
    """The one environment a thing runs in: its own, for an environment;
    the one its source says, for anything else — none for what runs in
    several, or where nobody says."""
    if kind == "environment":
        return key.removeprefix("environment:")
    found = attributes.get("environment")
    return found if isinstance(found, str) and found in ENVIRONMENTS else None


def occurred(kind: str, attributes: dict[str, object]) -> datetime | None:
    """When an event happened: its kind's first date — an incident's
    earliest — none for what is not an event, or says no date."""
    found = [d for name in OCCURRED.get(kind, ()) if (d := _when(attributes.get(name)))]
    if not found:
        return None
    return min(found) if kind in EARLIEST else found[0]


def _when(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _searched(key: str, name: str, attributes: dict[str, object]) -> dict[str, object]:
    search_name, search_text = fields(key, name, attributes)
    return {"search_name": search_name, "search_text": search_text}


def lifecycle_of(attributes: dict[str, object]) -> Lifecycle:
    if attributes.get("state") in ARCHIVED_STATES or attributes.get("stage") == "retired":
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
    previous: dict[tuple[uuid.UUID, uuid.UUID, str], Previous] | None = None,
) -> Built:
    # What a build did, said even when it is nothing.
    counts: Counter[str] = Counter(dict.fromkeys(("created", "changed", "unchanged", "removed"), 0))
    entities: list[dict[str, object]] = []
    versions: list[dict[str, object]] = []
    modelled: set[uuid.UUID] = set()
    types: dict[uuid.UUID, str] = {}
    # The one environment a thing runs in, when it runs in one.
    scope: dict[uuid.UUID, str | None] = {}

    for candidate in candidates:
        kind = BUILT_FROM.get(candidate.type)
        if kind is None:
            counts["not_modelled"] += 1
            continue
        merged = dict(candidate.attributes)
        origins: dict[str, dict[str, object]] = {}
        for name, value in candidate.enriched.items():
            if name in merged:
                continue
            merged[name] = value.value
            origins[name] = (
                {"origin": "source", "rule": RECORD}
                if value.rule == RECORD
                else {
                    "origin": "enrichment",
                    "rule": value.rule,
                    "confidence": value.confidence,
                }
            )
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
        conflicts = _conflicts(candidate.conflicts)
        disputed = {str(c["attribute"]) for c in conflicts}
        provenance = {
            "sources": [
                {"source_id": source, "key": key, "kind": seen} for source, key, seen in sources
            ],
            "attributes": {
                name: {
                    **origins.get(name, {"origin": "source"}),
                    **({"disputed": True} if name in disputed else {}),
                }
                for name in sorted(attributes)
            },
            "dropped": dropped,
            "conflicts": conflicts,
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
                "occurred_at": occurred(kind.type.value, attributes)
                or (first_seen if kind.type.value in UNDATED else None),
                **_searched(candidate.key, candidate.name, attributes),
            }
        )
        modelled.add(candidate.id)
        types[candidate.id] = kind.type.value
        scope[candidate.id] = _environment_of(kind.type.value, candidate.key, attributes)
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
                "occurred_at": occurred(gone.type, gone.attributes)
                or (gone.first_seen_at if gone.type in UNDATED else None),
                **_searched(gone.key, gone.name, gone.attributes),
            }
        )
        counts["removed"] += 1

    # Where each thing runs, by its `runs_in`: one environment makes it that
    # environment's, as its own `environment` does.
    runs: dict[uuid.UUID, set[str]] = defaultdict(set)
    for link in links:
        target = scope.get(link.to_id)
        if link.type == "runs_in" and target and link.from_id in scope:
            runs[link.from_id].add(target)
    for thing, places in runs.items():
        if scope[thing] is None and len(places) == 1:
            scope[thing] = next(iter(places))

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
            environments = sorted({e for e in (scope[link.from_id], scope[link.to_id]) if e})
            relationships[key] = {
                "from_entity_id": link.from_id,
                "to_entity_id": link.to_id,
                "type": relation.value,
                "confidence": min(1.0, max(0.0, link.confidence)),
                "origin": link.origin,
                "rule": link.rule[:100],
                "cross_source": link.cross_source,
                "attributes": {"environments": environments} if environments else {},
                "provenance": list(link.provenance),
            }
    # Their contracts, then their history (LEKA-368).
    kept, issues = check(relationships, types)
    moved = history(kept, previous or {}, now)
    counts["relationships_invalid"] = sum(1 for i in issues if i.severity == "error")
    counts["relationship_warnings"] = sum(1 for i in issues if i.severity == "warning")
    for change in moved:
        counts[f"relationships_{change['change']}"] += 1
    counts["entities"] = len(modelled)
    counts["relationships"] = len(kept)
    return Built(
        entities=entities,
        versions=versions,
        relationships=list(kept.values()),
        counts=counts,
        changes=moved,
        issues=[issue.row() for issue in issues],
    )
