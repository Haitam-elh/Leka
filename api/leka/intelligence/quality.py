"""Knowledge quality (LEKA-381): how far what LEKA knows can be trusted —
measured for each thing, for each area of the company, and kept over time.

Four dimensions, each read from what the model and the other analyses
already say — nothing measured twice:

    completeness   what a thing of its kind should say and does not: an
                   owner, a description, a document — and the gaps of
                   LEKA-379, called rather than found again (gaps.py)
    freshness      when a source last showed it, how its sources are doing,
                   whether the documents describing it are current
    consistency    what its sources disagree on and no one settled
                   (LEKA-382), what the last build found wrong with its
                   relationships (LEKA-368)
    confidence     how sure the merges that made it are (resolution), the
                   quality of its records (validation, LEKA-358), how its
                   ties and its attributes were made — said by a source,
                   validated, inferred

    score = .30 completeness + .25 freshness + .20 consistency
            + .25 confidence, over the dimensions known

A factor nothing measures is unknown — left out, never guessed: a cloud
resource is asked no owner. high from 0.85, medium from 0.6 — the context's
thresholds (LEKA-375), so the product says one thing — and high only when
no dimension measured is under 0.6 and no contradiction is left open. What it lacks is
kept beside each score (`missing`), with what it lowers: a score always
says why.

AREAS — a team, an application, a column of Mon environnement, the
workspace — are the weighted mean of their things': what more things rely
on weighs more. Low quality is said as findings (category `quality`), the
more relied on first; every score is kept by the run (measures.py), and
its changes over time.

Pure: Material → findings and scores. Methodology: docs/intelligence.md § 15.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from leka.intelligence.analysis import (
    Analyzer,
    Draft,
    Evidence,
    Material,
    Method,
    QualityScore,
    Reads,
    Severity,
    Subject,
)
from leka.intelligence.gaps import (
    CRITICAL,
    READING,
    STALE_SOURCE,
    cards_of,
    dependents_of,
    documentation,
    missing_entities,
    missing_relationships,
)
from leka.knowledge import ArchitectureCardRead, EntityStanding

VERSION = 1
HIGH, MEDIUM = 0.85, 0.6
WEIGHTS = {"completeness": 0.30, "freshness": 0.25, "consistency": 0.20, "confidence": 0.25}
DIMENSIONS = tuple(WEIGHTS)

# What runs or keeps data: what is asked an owner, a description, a page.
OWNED_COLUMNS = frozenset({"services", "data"})

# Completeness: 1, less what is missing — each gap, each thing unsaid.
MISSING = {
    "isolated": 0.35,
    "no_owner": 0.25,
    "undocumented": 0.2,
    "runtime": 0.15,
    "code": 0.15,
    "data_model": 0.15,
    "business": 0.1,
    "no_description": 0.1,
}
GAP_CODES = {
    "gap.missing_relationship.isolated": "isolated",
    "gap.missing_documentation": "undocumented",
    "gap.missing_entity.runtime": "runtime",
    "gap.missing_entity.code": "code",
    "gap.missing_entity.data_model": "data_model",
    "gap.missing_relationship.business": "business",
}

# Freshness: a thing a pass saw within 8 days is fresh, at 30 it is not —
# validation's curve (LEKA-358).
FRESH, STALE = timedelta(days=8), timedelta(days=30)
FRESHNESS = {"seen": 0.45, "sources": 0.35, "documents": 0.2}
SOURCE_HEALTH = {"error": 0.3, "disabled": 0.3, "degraded": 0.7}
LATE_SOURCE = 0.5

# Consistency: 1, less each contradiction.
DISPUTE, CRITICAL_DISPUTE = 0.25, 0.35
ISSUE_ERROR, ISSUE_WARNING = 0.25, 0.1
# What decides an answer: a disagreement on it weighs more (LEKA-375).
DECISIVE = frozenset(
    {
        "status",
        "state",
        "version",
        "environment",
        "owner",
        "team",
        "tier",
        "criticality",
        "sla",
        "slo",
        "lifecycle",
        "region",
        "manager",
        "lead",
        "parent",
    }
)

# Confidence: how what it says was made. A source's word 1, a validated
# fact 0.9, an inference 0.7 — the context engine's trust (LEKA-372).
CONFIDENCE = {"merge": 0.3, "records": 0.3, "ties": 0.2, "attributes": 0.2}
TRUST = {"stated": 1.0, "source": 1.0, "accepted": 0.9, "inferred": 0.7, "enrichment": 0.7}

# A contradiction left open, a relationship broken — or one dimension
# measured weak: no owner and no page, say — holds it to medium. Reliable
# knowledge is reliable on every side measured.
CAPPED = 0.84
# An area's thing weighs 1, and 0.2 more per thing relying on it, up to 5.
PER_DEPENDENT, MAX_DEPENDENTS = 0.2, 5
# An area is said low only once it holds this many things.
MIN_AREA = 3
# What a score's evidence names at most.
MAX_NAMED = 5


def level(score: float) -> str:
    if score >= HIGH:
        return "high"
    if score >= MEDIUM:
        return "medium"
    return "low"


@dataclass(frozen=True)
class Lack:
    """What lowers a score: a code the interface words, the dimension it
    lowers, by how much — what it takes from that dimension, at most, so
    lacks compare across dimensions once weighed by them — and what shows
    it (English)."""

    code: str
    dimension: str
    weight: float
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "dimension": self.dimension,
            "weight": round(self.weight, 3),
            "detail": self.detail,
        }


@dataclass
class Measure:
    """One dimension: its factors, each known or not, and what it lacks."""

    factors: dict[str, float | None] = field(default_factory=dict)
    weights: Mapping[str, float] = field(default_factory=dict)
    lacks: list[Lack] = field(default_factory=list)

    def value(self) -> float | None:
        return weighted(
            {name: (v, self.weights.get(name, 1.0)) for name, v in self.factors.items()}
        )


def weighted(values: Mapping[str, tuple[float | None, float]]) -> float | None:
    """The weighted mean of what is known; None when nothing is."""
    known = [(v, w) for v, w in values.values() if v is not None and w > 0]
    total = sum(w for _, w in known)
    if not total:
        return None
    return round(sum(v * w for v, w in known) / total, 4)


# ── the four dimensions of one thing ──────────────────────────────────


def completeness(card: ArchitectureCardRead, gaps: set[str], owned: bool) -> Measure:
    """1, less what it should say and does not. Asked only of what runs or
    keeps data; the rest is unknown."""
    if card.column not in OWNED_COLUMNS:
        return Measure(factors={"expected": None})
    lacks: list[Lack] = []
    for missing in sorted(gaps):
        lacks.append(Lack(missing, "completeness", MISSING[missing], _GAP_DETAIL[missing]))
    if not owned:
        lacks.append(
            Lack("no_owner", "completeness", MISSING["no_owner"], "no team or person owns it")
        )
    if not (card.description or "").strip() and card.type != "database":
        lacks.append(
            Lack(
                "no_description",
                "completeness",
                MISSING["no_description"],
                "no source says what it is",
            )
        )
    value = max(0.0, 1.0 - sum(lack.weight for lack in lacks))
    return Measure(factors={"expected": round(value, 4)}, lacks=lacks)


_GAP_DETAIL = {
    "isolated": "tied to nothing",
    "undocumented": "no document describes it",
    "runtime": "where it runs is unknown",
    "code": "its code is unknown",
    "data_model": "its tables are unknown",
    "business": "no application, capability or process holds it",
}


def freshness(
    standing: EntityStanding | None,
    sources: Mapping[str, tuple[str, datetime | None]],
    now: datetime,
) -> Measure:
    """When a source last showed it, how its sources are doing, how current
    its documents are."""
    measure = Measure(weights=FRESHNESS)
    if standing is None:
        measure.factors = {"seen": None, "sources": None, "documents": None}
        return measure
    seen = standing.last_seen_at
    if seen is None:
        measure.factors["seen"] = None
    else:
        age = now - seen
        value = 1.0 if age <= FRESH else max(0.0, 1.0 - (age - FRESH) / (STALE - FRESH))
        measure.factors["seen"] = round(value, 4)
        if value < 0.5:
            measure.lacks.append(
                Lack(
                    "unseen",
                    "freshness",
                    round((1 - value) * FRESHNESS["seen"], 3),
                    f"no source has shown it since {seen.date().isoformat()}",
                )
            )
    health: list[float] = []
    for source_id in standing.source_ids:
        said = sources.get(str(source_id))
        if said is None:
            continue
        status, synced = said
        value = SOURCE_HEALTH.get(status, 1.0)
        if status in READING and (synced is None or now - synced > STALE_SOURCE):
            value = min(value, LATE_SOURCE)
        health.append(value)
    measure.factors["sources"] = round(sum(health) / len(health), 4) if health else None
    if health and min(health) < 1:
        measure.lacks.append(
            Lack(
                "source_unhealthy",
                "freshness",
                round((1 - min(health)) * FRESHNESS["sources"], 3),
                "a source showing it is failing, switched off or not read for days",
            )
        )
    if standing.documents:
        value = standing.fresh_documents / standing.documents
        measure.factors["documents"] = round(value, 4)
        if not standing.fresh_documents:
            measure.lacks.append(
                Lack(
                    "stale_documents",
                    "freshness",
                    FRESHNESS["documents"],
                    f"none of its {standing.documents} document(s) is known current",
                )
            )
    else:
        measure.factors["documents"] = None
    return measure


def consistency(
    standing: EntityStanding | None, disputes: Sequence[tuple[str, str]] | None
) -> Measure:
    """1, less what its sources disagree on and no one settled, and what the
    last build found wrong with its relationships. `disputes`, read from the
    conflicts when the run read them (LEKA-382) — each (kind, about) — else
    the attributes its provenance says disputed."""
    lacks: list[Lack] = []
    said = (
        list(disputes)
        if disputes is not None
        else [("attribute", name) for name in (standing.disputed if standing else ())]
    )
    for kind, about in said:
        decisive = about.lower() in DECISIVE or kind == "relationship"
        lacks.append(
            Lack(
                "disputed",
                "consistency",
                CRITICAL_DISPUTE if decisive else DISPUTE,
                f"its sources disagree on its {about}, and no one settled it",
            )
        )
    errors, warnings = standing.issues if standing else (0, 0)
    if errors:
        lacks.append(
            Lack(
                "relationship_error",
                "consistency",
                ISSUE_ERROR * errors,
                f"{errors} of its relationships break their contract",
            )
        )
    if warnings:
        lacks.append(
            Lack(
                "relationship_warning",
                "consistency",
                ISSUE_WARNING * warnings,
                f"{warnings} of its relationships contradict themselves",
            )
        )
    value = max(0.0, 1.0 - sum(lack.weight for lack in lacks))
    return Measure(factors={"contradictions": round(value, 4)}, lacks=lacks)


def confidence(standing: EntityStanding | None, ties: Sequence[str]) -> Measure:
    """How sure the merges that made it are, how good its records were, how
    its ties and attributes were made."""
    measure = Measure(weights=CONFIDENCE)
    if standing is None:
        measure.factors = {"merge": None, "records": None, "ties": None, "attributes": None}
    else:
        measure.factors["merge"] = round(standing.confidence, 4)
        measure.factors["records"] = (
            round(standing.quality, 4) if standing.quality is not None else None
        )
        counted = sum(standing.origins.values())
        measure.factors["attributes"] = (
            round(
                sum(TRUST.get(origin, 0.7) * n for origin, n in standing.origins.items()) / counted,
                4,
            )
            if counted
            else None
        )
        if standing.confidence < 0.7:
            measure.lacks.append(
                Lack(
                    "uncertain_identity",
                    "confidence",
                    round((1 - standing.confidence) * CONFIDENCE["merge"], 3),
                    "the records that make it were merged with little certainty",
                )
            )
        if standing.quality is not None and standing.quality < MEDIUM:
            measure.lacks.append(
                Lack(
                    "weak_records",
                    "confidence",
                    round((1 - standing.quality) * CONFIDENCE["records"], 3),
                    f"its best record was judged {standing.quality:.2f} by validation",
                )
            )
    measure.factors["ties"] = (
        round(sum(TRUST.get(origin, 0.7) for origin in ties) / len(ties), 4) if ties else None
    )
    inferred = sum(1 for origin in ties if origin == "inferred")
    if len(ties) >= 2 and inferred * 2 > len(ties):
        measure.lacks.append(
            Lack(
                "mostly_inferred",
                "confidence",
                round(inferred / len(ties) * (1 - TRUST["inferred"]) * CONFIDENCE["ties"], 3),
                f"{inferred} of its {len(ties)} ties are inferred, not said by a source",
            )
        )
    return measure


# ── a thing, and an area ───────────────────────────────────────────────


@dataclass(frozen=True)
class Scored:
    """One thing, measured: what an area and a finding are made of."""

    card: ArchitectureCardRead
    score: QualityScore
    dependents: int
    critical: bool


def _subject(card: ArchitectureCardRead) -> Subject:
    return Subject(type="entity", id=card.entity_id, name=card.name, kind=card.type)


def score_entity(
    card: ArchitectureCardRead,
    *,
    material: Material,
    gaps: set[str],
    disputes: Sequence[tuple[str, str]] | None,
    ties: Sequence[str],
    sources: Mapping[str, tuple[str, datetime | None]],
    areas: Sequence[str],
) -> QualityScore:
    standing = material.standing.get(card.entity_id) if card.entity_id else None
    owned = card.team is not None or bool(
        card.entity_id is not None and material.owners.get(card.entity_id)
    )
    measures = {
        "completeness": completeness(card, gaps, owned),
        "freshness": freshness(standing, sources, material.now),
        "consistency": consistency(standing, disputes),
        "confidence": confidence(standing, ties),
    }
    values = {name: measure.value() for name, measure in measures.items()}
    lacks = sorted(
        (lack for measure in measures.values() for lack in measure.lacks),
        key=lambda lack: (-lack.weight * WEIGHTS[lack.dimension], lack.code),
    )
    score = weighted({name: (values[name], WEIGHTS[name]) for name in DIMENSIONS}) or 0.0
    capped = None
    if score > CAPPED:
        if any(lack.code in ("disputed", "relationship_error") for lack in lacks):
            score, capped = CAPPED, "contradiction"
        elif any(value is not None and value < MEDIUM for value in values.values()):
            score, capped = CAPPED, "weak_dimension"
    return QualityScore(
        key=f"entity:{card.entity_id}",
        scope="entity",
        subject=_subject(card),
        column=card.column,
        score=round(score, 4),
        level=level(score),
        dimensions=values,
        factors={name: dict(measure.factors) for name, measure in measures.items()},
        missing=tuple(lack.as_dict() for lack in lacks),
        areas=tuple(areas),
        capped=capped,
        sources=tuple(sorted(card.sources)),
    )


def score_area(key: str, scope: str, subject: Subject, members: Sequence[Scored]) -> QualityScore:
    """The weighted mean of its things': what more rely on weighs more."""
    weights = [1 + PER_DEPENDENT * min(m.dependents, MAX_DEPENDENTS) for m in members]

    def mean(read: Iterable[tuple[float | None, float]]) -> float | None:
        known = [(v, w) for v, w in read if v is not None]
        total = sum(w for _, w in known)
        return round(sum(v * w for v, w in known) / total, 4) if total else None

    values = {
        name: mean((m.score.dimensions.get(name), w) for m, w in zip(members, weights, strict=True))
        for name in DIMENSIONS
    }
    score = mean((m.score.score, w) for m, w in zip(members, weights, strict=True)) or 0.0
    # An area is held as a thing is: a dimension weak across it.
    capped = None
    if score > CAPPED and any(v is not None and v < MEDIUM for v in values.values()):
        score, capped = CAPPED, "weak_dimension"
    levels = Counter(m.score.level for m in members)
    weakest = sorted(members, key=lambda m: (m.score.score, m.card.name))[:MAX_NAMED]
    lacking = Counter(
        str(lack["code"]) for m in members for lack in m.score.missing if lack.get("code")
    )
    return QualityScore(
        key=key,
        scope=scope,
        subject=subject,
        column=None,
        score=round(score, 4),
        level=level(score),
        dimensions=values,
        factors={
            "levels": {name: levels.get(name, 0) for name in ("high", "medium", "low")},
            "weakest": [
                {
                    "id": str(m.card.entity_id),
                    "name": m.card.name,
                    "kind": m.card.type,
                    "score": m.score.score,
                    "level": m.score.level,
                }
                for m in weakest
            ],
        },
        missing=tuple(
            {"code": code, "count": count}
            for code, count in sorted(lacking.items(), key=lambda item: (-item[1], item[0]))
        ),
        entities=len(members),
        capped=capped,
        sources=tuple(sorted({s for m in members for s in m.score.sources})),
    )


# ── what a run measures ────────────────────────────────────────────────


def _gaps(material: Material) -> dict[str, set[str]]:
    """The gaps of LEKA-379 each thing has, as gaps.py finds them."""
    found: dict[str, set[str]] = defaultdict(set)
    for draft in (
        *missing_entities(material),
        *missing_relationships(material),
        *documentation(material),
    ):
        missing = GAP_CODES.get(draft.code)
        if missing and draft.subject.id is not None:
            found[str(draft.subject.id)].add(missing)
    return found


def _disputes(material: Material) -> dict[str, list[tuple[str, str]]] | None:
    """What the sources disagree on, no one having settled it, by thing —
    when the run read it (LEKA-382)."""
    if material.disputes is None:
        return None
    found: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for dispute in material.disputes:
        if dispute.settled is None:
            found[str(dispute.entity.id)].append((dispute.kind, dispute.about))
    return found


def measure(material: Material) -> list[Draft | QualityScore]:
    """Every thing of the architecture measured, every area, and what is
    weak said."""
    architecture = material.architecture
    if architecture is None:
        return []
    cards = {card.id: card for card in cards_of(material)}
    if not cards:
        return []
    gaps = _gaps(material)
    disputes = _disputes(material)
    dependents = dependents_of(material)
    sources = {
        str(source.source_id): (source.status, source.last_synced_at)
        for source in architecture.sources
    }
    ties: dict[str, list[str]] = defaultdict(list)
    applications: dict[str, set[str]] = defaultdict(set)
    for link in architecture.links:
        for end in {link.from_id, link.to_id}:
            ties[end].append(link.origin)
        target = cards.get(link.to_id)
        if link.role == "part_of" and target is not None and target.type == "application":
            applications[link.from_id].add(link.to_id)

    scored: list[Scored] = []
    for card in cards.values():
        entity = str(card.entity_id)
        within = [f"column:{card.column}"]
        if card.team is not None:
            within.append(f"team:{card.team.id}")
        held = applications.get(card.id, set()) | (
            {card.id} if card.type == "application" else set()
        )
        within += sorted(f"application:{cards[app].entity_id}" for app in held)
        standing = material.standing.get(card.entity_id) if card.entity_id else None
        scored.append(
            Scored(
                card=card,
                score=score_entity(
                    card,
                    material=material,
                    gaps=gaps.get(entity, set()),
                    disputes=disputes.get(entity, []) if disputes is not None else None,
                    ties=ties.get(card.id, []),
                    sources=sources,
                    areas=within,
                ),
                dependents=dependents[card.id],
                critical=(standing.criticality or "").lower() in CRITICAL
                if standing and standing.criticality
                else False,
            )
        )

    said: list[Draft | QualityScore] = [s.score for s in scored]
    areas = _areas(scored, cards)
    said += areas
    said += [_entity_finding(s) for s in scored if _weak(s)]
    said += [_area_finding(area) for area in areas if _weak_area(area)]
    return said


def _areas(
    scored: Sequence[Scored], cards: Mapping[str, ArchitectureCardRead]
) -> list[QualityScore]:
    members: dict[str, list[Scored]] = defaultdict(list)
    subjects: dict[str, tuple[str, Subject]] = {
        "workspace": ("workspace", Subject(type="workspace", id=None, name="workspace"))
    }
    applications = {str(c.entity_id): c for c in cards.values() if c.type == "application"}
    for item in scored:
        members["workspace"].append(item)
        for key in item.score.areas:
            members[key].append(item)
            scope, _, ident = key.partition(":")
            if key in subjects:
                continue
            if scope == "column":
                subjects[key] = (scope, Subject(type="column", id=None, name=ident, kind=ident))
            elif scope == "team" and item.card.team is not None:
                team = item.card.team
                subjects[key] = (
                    scope,
                    Subject(type="entity", id=team.id, name=team.name, kind="team"),
                )
            elif scope == "application" and ident in applications:
                app = applications[ident]
                subjects[key] = (
                    scope,
                    Subject(type="entity", id=app.entity_id, name=app.name, kind="application"),
                )
    return [
        score_area(key, scope, subject, members[key])
        for key, (scope, subject) in sorted(subjects.items())
        if members.get(key)
    ]


# ── what is said: weak knowledge, the more relied on first ─────────────


def _weak(item: Scored) -> bool:
    """A thing that runs or keeps data, active, whose knowledge is low."""
    return item.card.column in OWNED_COLUMNS and item.score.level == "low"


def _entity_finding(item: Scored) -> Draft:
    card, score = item.card, item.score
    if item.dependents >= 3 or item.critical:
        severity = Severity.HIGH
    elif item.dependents or card.column == "services":
        severity = Severity.MEDIUM
    else:
        severity = Severity.LOW
    weakest = min(
        (name for name in DIMENSIONS if score.dimensions.get(name) is not None),
        key=lambda name: (score.dimensions[name] or 0.0, name),
    )
    lacks = [dict(lack) for lack in score.missing[:3]]
    named = ", ".join(str(lack["detail"]) for lack in lacks)
    return Draft(
        key=score.key,
        code="quality.low",
        severity=severity,
        subject=score.subject,
        statement=f"What LEKA knows of {card.name} is weak ({score.score:.2f}), "
        f"its {weakest} first" + (f": {named}." if named else "."),
        params={
            "name": card.name,
            "kind": card.kind,
            "score": score.score,
            "level": score.level,
            "weakest": weakest,
            "dimensions": dict(score.dimensions),
            "missing": [lack["code"] for lack in lacks],
            "dependents": item.dependents,
        },
        score=round(1 - score.score, 3),
        evidence=tuple(
            Evidence(
                kind="quality",
                id=str(card.entity_id),
                name=str(lack["code"]),
                detail=f"{lack['dimension']}: {lack['detail']}",
            )
            for lack in lacks
        ),
        sources=score.sources,
    )


def _weak_area(area: QualityScore) -> bool:
    return (
        area.scope in ("team", "application", "workspace")
        and area.entities >= MIN_AREA
        and area.level == "low"
    )


def _area_finding(area: QualityScore) -> Draft:
    weakest = area.factors.get("weakest")
    named = (
        [str(w["name"]) for w in weakest if isinstance(w, dict)]
        if isinstance(weakest, list)
        else []
    )
    severity = Severity.HIGH if area.scope == "workspace" else Severity.MEDIUM
    where = "the workspace" if area.scope == "workspace" else f"{area.subject.name} ({area.scope})"
    return Draft(
        key=area.key,
        code="quality.low_area",
        severity=severity,
        subject=area.subject,
        statement=f"What LEKA knows of {where} is weak ({area.score:.2f}) over "
        f"{area.entities} thing(s); the weakest: {', '.join(named[:3])}.",
        params={
            "name": area.subject.name,
            "scope": area.scope,
            "score": area.score,
            "level": area.level,
            "entities": area.entities,
            "weakest": named[:3],
            "dimensions": dict(area.dimensions),
        },
        score=round(1 - area.score, 3),
        evidence=tuple(
            Evidence(kind="quality", id=str(w["id"]), name=str(w["name"]), detail=f"{w['score']}")
            for w in (weakest if isinstance(weakest, list) else [])[:3]
            if isinstance(w, dict)
        ),
        sources=area.sources,
    )


ANALYZER = Analyzer(
    name="quality",
    version=VERSION,
    category="quality",
    method=Method.RULES,
    reads=frozenset({Reads.MODEL}),
    summary="How complete, fresh, consistent and sure what LEKA knows is — each thing, "
    "each area, over time.",
    run=measure,
    heeds=frozenset({Reads.CONFLICTS}),
)
