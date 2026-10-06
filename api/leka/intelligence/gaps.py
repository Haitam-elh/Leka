"""Knowledge gaps (LEKA-379): what LEKA does not know, or no longer knows,
that limits what it can understand — and how much each matters.

Five families, five analyses, one code each family's own, so the API and
the interface tell them apart (`gap.<family>…`):

    gaps_entities       a thing whose other half is missing: a service no
                        resource is known to run, no code is known for; a
                        database whose tables nothing reads
    gaps_relationships  a thing tied to nothing; a service no application,
                        capability or process holds
    gaps_documentation  no document describes it — or none known current
    gaps_staleness      a source not read for days, or failing: all it
                        showed is what it was; a thing dormant for months
                        that others still rely on
    gaps_coverage       a whole family of sources not connected — no
                        monitoring, no cloud, no code, no documentation, no
                        organisation, no database — said once, for all it
                        leaves unknown, rather than once per thing

A per-thing gap is said only when its family IS connected: with no cloud
source, every service's runtime is unknown, and that is one coverage gap,
not forty findings. And one question at a time: what is tied to nothing is
that gap, not five; an application runs as its services do; what has gone
dormant is asked only whether it is still used.

PRIORITY — defined, documented (docs/intelligence.md § 12): a base by kind
of gap, then what makes this one matter more —

    relied_on   +0.06 a thing relying on it, up to +0.3
    critical    +0.2  its sources say it is critical
    unwell      +0.1  in incident, or needing attention
    production  +0.1  it runs in production
    changing    +0.15 a current change touched or reached it (LEKA-378)

up to 1: high from 0.6, medium from 0.35, low under.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta

from leka.intelligence.analysis import (
    Analyzer,
    Draft,
    Evidence,
    Material,
    Method,
    Reads,
    Severity,
    Subject,
)
from leka.intelligence.changes import current
from leka.knowledge import RELIED_ON, ArchitectureCardRead, Lifecycle

# A source not read for this long shows what was, not what is.
STALE_SOURCE = timedelta(days=3)
# Sources a person switched on: the others are drafts, or switched off.
READING = frozenset({"active", "degraded", "error"})
CRITICAL = frozenset({"critical", "high", "tier1", "tier-1", "p1"})
UNWELL = frozenset({"incident", "attention"})
PRODUCTION = ("prod", "live", "prd")

HIGH, MEDIUM = 0.6, 0.35
# Each gap's own weight before anything else is known of it.
BASE = {
    "gap.missing_entity.runtime": 0.25,
    "gap.missing_entity.code": 0.2,
    "gap.missing_entity.data_model": 0.15,
    "gap.missing_relationship.isolated": 0.2,
    "gap.missing_relationship.business": 0.15,
    "gap.missing_documentation": 0.15,
    "gap.stale_documentation": 0.1,
    "gap.stale_source": 0.35,
    "gap.stale_knowledge.dormant": 0.2,
    "gap.coverage": 0.3,
}
SIGNALS = {
    "critical": 0.2,
    "unwell": 0.1,
    "production": 0.1,
    "changing": 0.15,
}
PER_DEPENDENT, MAX_DEPENDENTS = 0.06, 0.3
# What a coverage gap leaves unknown weighs: per thing, at most.
PER_THING, MAX_THINGS = 0.03, 0.3

# The families of sources a gap waits for, by connector category.
# Documentation is read from the documents themselves — a custom source
# brings them too (LEKA-350) — and the organisation from who owns what.
FAMILIES = {
    "monitoring": "observability",
    "cloud": "cloud",
    "code": "code",
    "data": "data",
}


@dataclass(frozen=True)
class Priority:
    score: float
    signals: tuple[str, ...]

    @property
    def severity(self) -> Severity:
        if self.score >= HIGH:
            return Severity.HIGH
        if self.score >= MEDIUM:
            return Severity.MEDIUM
        return Severity.LOW


def priority(
    code: str,
    *,
    dependents: int = 0,
    criticality: str | None = None,
    status: str | None = None,
    production: bool = False,
    changing: bool = False,
    extra: float = 0.0,
) -> Priority:
    """How much a gap matters: its base, and what about the thing it is
    about makes it matter more."""
    family = code if code in BASE else "gap.coverage"
    score = BASE[family] + extra
    found: list[str] = []
    if dependents:
        score += min(MAX_DEPENDENTS, PER_DEPENDENT * dependents)
        found.append("relied_on")
    for signal, holds in (
        ("critical", (criticality or "").lower() in CRITICAL),
        ("unwell", status in UNWELL),
        ("production", production),
        ("changing", changing),
    ):
        if holds:
            score += SIGNALS[signal]
            found.append(signal)
    return Priority(score=round(min(score, 1.0), 3), signals=tuple(found))


# ── what the material says, read once ──────────────────────────────────


def cards_of(material: Material, *, active: bool = True) -> list[ArchitectureCardRead]:
    """The things a gap can be about — not a module or a tool, drawn from
    the code. Active only, by default: what has gone dormant is asked one
    question first (is it still used?), not every other."""
    architecture = material.architecture
    if architecture is None:
        return []
    return [
        card
        for card in architecture.cards
        if card.entity_id is not None
        and card.type not in ("module", "tool")
        and (not active or _lifecycle(material, card) is Lifecycle.ACTIVE)
    ]


def _lifecycle(material: Material, card: ArchitectureCardRead) -> Lifecycle:
    standing = material.standing.get(card.entity_id) if card.entity_id else None
    return standing.lifecycle if standing else Lifecycle.ACTIVE


def dependents_of(material: Material) -> Counter[str]:
    architecture = material.architecture
    if architecture is None:
        return Counter()
    pairs = {
        (link.from_id, link.to_id)
        for link in architecture.links
        if link.role in RELIED_ON and link.from_id != link.to_id
    }
    return Counter(to for _, to in pairs)


def tied_of(material: Material) -> set[str]:
    architecture = material.architecture
    if architecture is None:
        return set()
    return {end for link in architecture.links for end in (link.from_id, link.to_id)}


def _changing(material: Material) -> set[str]:
    """The entities a current change touched or reached (LEKA-378)."""
    if material.changes is None:
        return set()
    found: set[str] = set()
    for footprint in material.changes:
        if current(footprint, material.now):
            found |= {str(t.entity.id) for t in footprint.touched}
            found |= {str(r.entity.id) for r in footprint.reached}
    return found


def connected_families(material: Material) -> set[str]:
    """The families of sources a person switched on: monitoring, cloud…"""
    architecture = material.architecture
    if architecture is None:
        return set()
    categories = {
        material.categories.get(source.kind)
        for source in architecture.sources
        if source.status in READING
    }
    return {family for family, category in FAMILIES.items() if category in categories}


def _production(card: ArchitectureCardRead) -> bool:
    said = (card.environment or "").lower()
    return any(word in said for word in PRODUCTION)


def _subject(card: ArchitectureCardRead) -> Subject:
    return Subject(type="entity", id=card.entity_id, name=card.name, kind=card.type)


@dataclass(frozen=True)
class Seen:
    """What every gap of one analysis is weighed against, read once."""

    material: Material
    dependents: Counter[str]
    changing: set[str]

    @classmethod
    def of(cls, material: Material) -> Seen:
        return cls(material, dependents_of(material), _changing(material))


def _draft(
    seen: Seen,
    card: ArchitectureCardRead,
    code: str,
    family: str,
    statement: str,
    detail: str,
    *,
    params: dict[str, object] | None = None,
    confidence: float = 0.9,
) -> Draft:
    """A gap about one thing: its priority from the thing, its evidence."""
    dependents = seen.dependents[card.id]
    standing = seen.material.standing.get(card.entity_id) if card.entity_id else None
    found = priority(
        code,
        dependents=dependents,
        criticality=standing.criticality if standing else None,
        status=card.status,
        production=_production(card),
        changing=str(card.entity_id) in seen.changing,
    )
    return Draft(
        key=f"{code}:{card.entity_id}",
        code=code,
        severity=found.severity,
        subject=_subject(card),
        statement=statement,
        params={
            "gap": family,
            "name": card.name,
            "kind": card.kind,
            "dependents": dependents,
            "signals": list(found.signals),
            **(params or {}),
        },
        score=found.score,
        confidence=confidence,
        evidence=(Evidence(kind="entity", id=str(card.entity_id), name=card.name, detail=detail),),
        sources=tuple(sorted(card.sources)),
    )


# ── the five analyses ──────────────────────────────────────────────────


def missing_entities(material: Material) -> list[Draft]:
    """A service whose runtime or code is unknown, a database whose tables
    are — when the family that would say it is connected. Not an
    application, which runs as its services do; not what is tied to
    nothing, which one gap says (gaps_relationships)."""
    connected = connected_families(material)
    tied = tied_of(material)
    seen = Seen.of(material)
    drafts: list[Draft] = []
    for card in cards_of(material):
        if card.id not in tied:
            continue
        if card.column == "services" and card.type == "service":
            if "cloud" in connected and card.host_id is None:
                drafts.append(
                    _draft(
                        seen,
                        card,
                        "gap.missing_entity.runtime",
                        "entity",
                        f"Where {card.name} runs is unknown: no cloud resource is tied to it.",
                        "no resource of a connected cloud is said to run it",
                    )
                )
            if "code" in connected and card.repository_id is None:
                drafts.append(
                    _draft(
                        seen,
                        card,
                        "gap.missing_entity.code",
                        "entity",
                        f"The code of {card.name} is unknown: no repository is tied to it.",
                        "no repository of a connected code host is said to be its code",
                    )
                )
        if (
            card.column == "data"
            and card.type == "database"
            and "data" in connected
            and not card.stats.get("tables")
        ):
            drafts.append(
                _draft(
                    seen,
                    card,
                    "gap.missing_entity.data_model",
                    "entity",
                    f"The tables of {card.name} are unknown: no database source reads it.",
                    "no table, view or collection is known of it",
                )
            )
    return drafts


def missing_relationships(material: Material) -> list[Draft]:
    """What runs or keeps data tied to nothing at all — that, and nothing
    more of it; a service no application, capability or process holds —
    when the business is known at all."""
    tied = tied_of(material)
    business_known = any(standing.business for standing in material.standing.values())
    seen = Seen.of(material)
    drafts: list[Draft] = []
    for card in cards_of(material):
        if card.column not in ("services", "data"):
            continue
        if card.id not in tied:
            drafts.append(
                _draft(
                    seen,
                    card,
                    "gap.missing_relationship.isolated",
                    "relationship",
                    f"{card.name} is tied to nothing: no source says what it calls or what "
                    "calls it.",
                    "no relationship of any kind",
                )
            )
            continue
        standing = material.standing.get(card.entity_id) if card.entity_id else None
        if (
            business_known
            and card.column == "services"
            and card.type == "service"
            and standing is not None
            and not standing.business
        ):
            drafts.append(
                _draft(
                    seen,
                    card,
                    "gap.missing_relationship.business",
                    "relationship",
                    f"No application, capability or process is said to hold {card.name}.",
                    "not part of an application, supporting no capability, used by no process",
                )
            )
    return drafts


def documentation(material: Material) -> list[Draft]:
    """What runs or keeps data that no document describes — or none known
    to be current — when the workspace has documents at all: what the
    Documentation page calls a gap (LEKA-366), weighed."""
    if not material.documents:
        return []
    seen = Seen.of(material)
    drafts: list[Draft] = []
    for card in cards_of(material):
        if card.column not in ("services", "data") or card.entity_id is None:
            continue
        standing = material.standing.get(card.entity_id)
        if standing is None:
            continue
        if standing.documents == 0:
            drafts.append(
                _draft(
                    seen,
                    card,
                    "gap.missing_documentation",
                    "documentation",
                    f"No document describes {card.name}.",
                    "no document or space describes it",
                )
            )
        elif standing.fresh_documents == 0:
            drafts.append(
                _draft(
                    seen,
                    card,
                    "gap.stale_documentation",
                    "documentation",
                    f"No document describing {card.name} is known to be current"
                    + (
                        f": the latest changed {standing.last_documented_at[:10]}."
                        if standing.last_documented_at
                        else "."
                    ),
                    f"{standing.documents} document(s), none of them fresh or aging",
                    params={
                        "documents": standing.documents,
                        "last_documented_at": standing.last_documented_at,
                    },
                )
            )
    return drafts


def staleness(material: Material) -> list[Draft]:
    """Sources not read for days, or failing; things dormant for months
    that others still rely on."""
    architecture = material.architecture
    if architecture is None:
        return []
    seen = Seen.of(material)
    drafts: list[Draft] = []
    for source in architecture.sources:
        if source.status not in READING:
            continue
        synced = source.last_synced_at
        failing = source.status == "error"
        late = synced is None or material.now - synced > STALE_SOURCE
        if not (failing or late):
            continue
        found = priority(
            "gap.stale_source",
            extra=min(MAX_THINGS, PER_THING * source.entities) + (0.1 if failing else 0.0),
        )
        since = synced.date().isoformat() if synced else None
        drafts.append(
            Draft(
                key=f"gap.stale_source:{source.source_id}",
                code="gap.stale_source",
                severity=found.severity,
                subject=Subject(
                    type="source", id=source.source_id, name=source.name, kind=source.kind
                ),
                statement=_stale_statement(
                    source.name, source.kind, failing, since, source.entities
                ),
                params={
                    "gap": "staleness",
                    "name": source.name,
                    "kind": source.kind,
                    "status": source.status,
                    "since": synced.isoformat() if synced else None,
                    "entities": source.entities,
                },
                score=found.score,
                confidence=1.0,
                evidence=(
                    Evidence(
                        kind="source",
                        id=str(source.source_id),
                        name=source.name,
                        detail=f"status {source.status}, last read "
                        + (synced.isoformat() if synced else "never"),
                    ),
                ),
                sources=(source.kind,),
            )
        )
    for card in cards_of(material, active=False):
        standing = material.standing.get(card.entity_id) if card.entity_id else None
        if (
            standing is None
            or standing.lifecycle is not Lifecycle.DORMANT
            or not seen.dependents[card.id]
        ):
            continue
        drafts.append(
            _draft(
                seen,
                card,
                "gap.stale_knowledge.dormant",
                "staleness",
                f"Nothing has been done to {card.name} for months, yet "
                f"{seen.dependents[card.id]} thing(s) rely on it: is it still what they use?",
                "dormant: no activity for 180 days",
            )
        )
    return drafts


def _stale_statement(name: str, kind: str, failing: bool, since: str | None, things: int) -> str:
    if failing:
        state = f"is failing — last read {since}" if since else "is failing and has never been read"
    else:
        state = f"has not been read since {since}" if since else "has never been read"
    if since is None:
        return f"{name} ({kind}) {state}: what it holds cannot be told current."
    shown = f"what it says of {things} thing(s)" if things else "what it shows"
    return f"{name} ({kind}) {state}: {shown} may no longer be so."


def coverage(material: Material) -> list[Draft]:
    """A whole family of sources not connected, said once for all it leaves
    unknown."""
    architecture = material.architecture
    if architecture is None:
        return []
    cards = cards_of(material)
    services = [c for c in cards if c.column == "services" and c.type == "service"]
    databases = [c for c in cards if c.column == "data" and c.type == "database"]
    things = [c for c in cards if c.column in ("services", "data", "cloud")]
    connected = connected_families(material)
    said: list[tuple[str, int, str]] = []
    if services and "monitoring" not in connected:
        said.append(
            (
                "monitoring",
                len(services),
                f"Nothing watches the {len(services)} service(s): no monitoring source is "
                "connected — their state is deduced at best.",
            )
        )
    if services and "cloud" not in connected:
        said.append(
            (
                "cloud",
                len(services),
                f"Where the {len(services)} service(s) run is unknown: no cloud source is "
                "connected.",
            )
        )
    if things and "code" not in connected:
        said.append(
            (
                "code",
                len(things),
                f"The code behind {len(things)} thing(s) is unknown: no code host is connected.",
            )
        )
    if things and not material.documents:
        said.append(
            (
                "documentation",
                len(things),
                f"No document describes the {len(things)} thing(s) LEKA knows: no "
                "documentation is read.",
            )
        )
    if databases and "data" not in connected:
        said.append(
            (
                "data",
                len(databases),
                f"The tables of the {len(databases)} database(s) are unknown: no database "
                "source is connected.",
            )
        )
    if things and architecture.figures.teams == 0 and not any(material.owners.values()):
        said.append(
            (
                "organisation",
                len(things),
                "No team or person is known to own anything: who to call cannot be said.",
            )
        )
    drafts: list[Draft] = []
    for family, count, statement in said:
        found = priority("gap.coverage", extra=min(MAX_THINGS, PER_THING * count))
        drafts.append(
            Draft(
                key=f"gap.coverage:{family}",
                code=f"gap.coverage.{family}",
                severity=found.severity,
                subject=Subject(type="coverage", id=None, name=family, kind=family),
                statement=statement,
                params={"gap": "coverage", "family": family, "count": count},
                score=found.score,
                confidence=1.0,
                evidence=tuple(_census(material, family)),
            )
        )
    return drafts


def _census(material: Material, family: str) -> Iterable[Evidence]:
    architecture = material.architecture
    if architecture is None:
        return []
    kinds = sorted({source.kind for source in architecture.sources})
    return [
        Evidence(
            kind="coverage",
            name=family,
            detail="sources connected: " + (", ".join(kinds) if kinds else "none"),
        )
    ]


def _analyzer(name: str, summary: str, run: Callable[[Material], Sequence[Draft]]) -> Analyzer:
    return Analyzer(
        name=name,
        version=1,
        category="gaps",
        method=Method.RULES,
        reads=frozenset({Reads.MODEL}),
        summary=summary,
        run=run,
        heeds=frozenset({Reads.CHANGES}),
    )


ANALYZERS: tuple[Analyzer, ...] = (
    _analyzer(
        "gaps_entities",
        "A service whose runtime or code is unknown, a database whose tables are.",
        missing_entities,
    ),
    _analyzer(
        "gaps_relationships",
        "What is tied to nothing, and services no application, capability or process holds.",
        missing_relationships,
    ),
    _analyzer(
        "gaps_documentation",
        "What no document describes, or none known to be current does.",
        documentation,
    ),
    _analyzer(
        "gaps_staleness",
        "Sources not read for days or failing; dormant things others still rely on.",
        staleness,
    ),
    _analyzer(
        "gaps_coverage",
        "Whole families of sources not connected, and all they leave unknown.",
        coverage,
    ),
)
