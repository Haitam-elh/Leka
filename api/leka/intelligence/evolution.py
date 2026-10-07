"""How the company has been moving (LEKA-383): what the model's recent
course says — each insight drawn from the changes that show it, kept as
evidence, and a recommendation.

    evolution_dependencies   dependency      a thing that depends on
                                             DEPENDENCY_GROWTH more things
                                             than a month ago: what can
                                             break it grew
    evolution_ownership      organisational  a thing whose owner went this
                                             month — and none named since;
                                             or another named instead
    evolution_removals       risk            what went from every source
                                             while things still relied on
                                             it — not moved to anything else
    evolution_architecture   architecture    what appeared and went this
                                             month, said once for the
                                             workspace
    evolution_incidents      operational     a thing's incidents rising: as
                                             many as INCIDENTS_RISING this
                                             month, twice the month before
    evolution_volatility     risk            a thing that changed VOLATILE
                                             times or more this month
    evolution_quality        risk            an area whose knowledge quality
                                             fell this month (LEKA-381's
                                             history): QUALITY_FELL or more,
                                             or a level lower

What the first build made is no change: a model begins with everything
created, and that is not the architecture moving. Each finding says its
insight (`params.insight`) and what to do (`params.recommendation`), a
code the interface words. Pure: the material in, findings out; what it
reads is leka.knowledge's (`EvolutionMaterial`).
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime

from leka.intelligence.analysis import (
    Analyzer,
    Draft,
    Evidence,
    Material,
    Method,
    QualityMove,
    Reads,
    Severity,
    Subject,
)
from leka.intelligence.models import QualityPoint, QualityScoreRow
from leka.knowledge import EvolutionMaterial, EvolvedEntity, EvolvedTie, EvolvedVersion

VERSION = 1
# A thing depending on this many more things than a month ago.
DEPENDENCY_GROWTH = 3
MANY_DEPENDENCIES = 5
# Incidents this month, at least twice the month before.
INCIDENTS_RISING = 3
MANY_INCIDENTS = 5
# Changes in a month.
VOLATILE = 4
# What appeared and went in a month, before it is said.
ARCHITECTURE_MOVED = 3
# What relying on something is, as a tie says it.
RELIED_TIES = frozenset(
    {"depends_on", "uses", "reads_from", "deployed_to", "runs_in", "supported_by"}
)
# What is asked an owner; what makes the architecture.
OWNED = frozenset({"service", "application", "database", "repository", "infra_resource"})
ARCHITECTURE = frozenset({"service", "application", "database", "infra_resource"})
# A quality score this much lower than a month ago — or a level lower.
QUALITY_FELL = 0.1
LEVELS = {"high": 2, "medium": 1, "low": 0}
# What changes by nature — an incident's state, a ticket's — is not volatile.
EVENTS = frozenset(
    {"incident", "deployment", "change", "release", "pull_request", "issue", "commit"}
)
CRITICAL = frozenset({"critical", "high"})
MAX_NAMED = 10


def _day(at: datetime) -> str:
    return at.date().isoformat()


def _entity(evolution: EvolutionMaterial, entity_id: uuid.UUID) -> EvolvedEntity | None:
    return evolution.entities.get(entity_id)


def _subject(entity: EvolvedEntity) -> Subject:
    return Subject(type="entity", id=entity.id, name=entity.name, kind=entity.type)


def _critical(entity: EvolvedEntity) -> bool:
    return (entity.criticality or "").lower() in CRITICAL


def _since_first(evolution: EvolutionMaterial, at: datetime) -> bool:
    """After the model's first build: a change, not its beginning."""
    return evolution.began_at is None or at > evolution.began_at


def _ties(evolution: EvolutionMaterial) -> list[EvolvedTie]:
    return [t for t in evolution.ties if _since_first(evolution, t.recorded_at)]


def _versions(evolution: EvolutionMaterial) -> list[EvolvedVersion]:
    return [v for v in evolution.versions if _since_first(evolution, v.recorded_at)]


def _tie_evidence(evolution: EvolutionMaterial, tie: EvolvedTie) -> Evidence:
    start, end = _entity(evolution, tie.from_id), _entity(evolution, tie.to_id)
    named = f"{start.name if start else '?'} → {end.name if end else '?'}"
    return Evidence(
        kind="relationship_change",
        id=str(tie.id),
        name=named,
        detail=f"{tie.type} {tie.change} on {_day(tie.recorded_at)}",
    )


def _draft(
    code: str,
    entity: EvolvedEntity,
    statement: str,
    *,
    severity: Severity,
    score: float,
    insight: str,
    recommendation: str,
    params: dict[str, object],
    evidence: Iterable[Evidence],
) -> Draft:
    return Draft(
        key=f"{code}:{entity.id}",
        code=code,
        severity=severity,
        subject=_subject(entity),
        statement=statement,
        params={
            "insight": insight,
            "recommendation": recommendation,
            "name": entity.name,
            "kind": entity.type,
            "dependents": entity.dependents,
            **params,
        },
        score=max(0.0, min(score, 1.0)),
        evidence=tuple(evidence)[:MAX_NAMED],
    )


# ── the analyses ─────────────────────────────────────────────────────────────


def dependencies(material: Material) -> list[Draft]:
    """A thing depending on DEPENDENCY_GROWTH more things than a month ago:
    what can break it grew."""
    evolution = material.evolution
    if evolution is None:
        return []
    added: dict[uuid.UUID, list[EvolvedTie]] = defaultdict(list)
    removed: Counter[uuid.UUID] = Counter()
    for tie in _ties(evolution):
        if tie.type != "depends_on":
            continue
        if tie.change == "added":
            added[tie.from_id].append(tie)
        elif tie.change == "removed":
            removed[tie.from_id] += 1
    drafts: list[Draft] = []
    for start, ties in added.items():
        entity = _entity(evolution, start)
        grown = len(ties) - removed[start]
        if entity is None or entity.lifecycle == "removed" or grown < DEPENDENCY_GROWTH:
            continue
        names = sorted({e.name for t in ties if (e := _entity(evolution, t.to_id))})
        many = grown >= MANY_DEPENDENCIES or _critical(entity)
        drafts.append(
            _draft(
                "evolution.dependencies_grew",
                entity,
                f"{entity.name} depends on {grown} more things than a month ago "
                f"({entity.dependencies} now): {', '.join(names[:MAX_NAMED])}.",
                severity=Severity.MEDIUM if many else Severity.LOW,
                score=grown / 10 + entity.dependents / 20,
                insight="dependency",
                recommendation="review_dependencies",
                params={
                    "added": grown,
                    "now": entity.dependencies,
                    "names": names[:MAX_NAMED],
                    "since": evolution.since.isoformat(),
                },
                evidence=(_tie_evidence(evolution, t) for t in ties),
            )
        )
    return drafts


def ownership(material: Material) -> list[Draft]:
    """A thing whose owner went this month: none named since — or another."""
    evolution = material.evolution
    if evolution is None:
        return []
    went: dict[uuid.UUID, list[EvolvedTie]] = defaultdict(list)
    came: dict[uuid.UUID, list[EvolvedTie]] = defaultdict(list)
    for tie in _ties(evolution):
        if tie.type not in ("owned_by", "owns"):
            continue
        owned = tie.from_id if tie.type == "owned_by" else tie.to_id
        if tie.change == "removed":
            went[owned].append(tie)
        elif tie.change == "added":
            came[owned].append(tie)
    drafts: list[Draft] = []
    for owned, ties in went.items():
        entity = _entity(evolution, owned)
        if entity is None or entity.type not in OWNED or entity.lifecycle == "removed":
            continue
        before = sorted(
            {
                e.name
                for t in ties
                if (e := _entity(evolution, t.to_id if t.type == "owned_by" else t.from_id))
            }
        )
        evidence = [_tie_evidence(evolution, t) for t in [*ties, *came.get(owned, [])]]
        if not entity.owners:
            relied = entity.dependents >= DEPENDENCY_GROWTH or _critical(entity)
            drafts.append(
                _draft(
                    "evolution.owner_lost",
                    entity,
                    f"{entity.name} has had no owner since {', '.join(before)} "
                    f"stopped being named on {_day(ties[0].recorded_at)}.",
                    severity=Severity.HIGH if relied else Severity.MEDIUM,
                    score=0.5 + entity.dependents / 20,
                    insight="organisational",
                    recommendation="name_owner",
                    params={"before": before, "at": ties[0].recorded_at.isoformat()},
                    evidence=evidence,
                )
            )
        elif came.get(owned):
            drafts.append(
                _draft(
                    "evolution.owner_changed",
                    entity,
                    f"{entity.name} changed owner this month: {', '.join(before)} "
                    f"before, {', '.join(entity.owners)} now.",
                    severity=Severity.LOW,
                    score=0.3 + entity.dependents / 20,
                    insight="organisational",
                    recommendation="confirm_owner",
                    params={
                        "before": before,
                        "after": list(entity.owners),
                        "at": ties[0].recorded_at.isoformat(),
                    },
                    evidence=evidence,
                )
            )
    return drafts


def removals(material: Material) -> list[Draft]:
    """What went from every source while things still relied on it — and
    those things did not move to something else in the same build."""
    evolution = material.evolution
    if evolution is None:
        return []
    gone = {v.entity_id: v for v in _versions(evolution) if v.change == "removed"}
    if not gone:
        return []
    lost: dict[uuid.UUID, list[EvolvedTie]] = defaultdict(list)
    found: set[tuple[uuid.UUID, str, uuid.UUID | None]] = set()
    for tie in _ties(evolution):
        if tie.type not in RELIED_TIES:
            continue
        if tie.change == "removed" and tie.to_id in gone:
            lost[tie.to_id].append(tie)
        elif tie.change == "added":
            found.add((tie.from_id, tie.type, tie.run_id))
    drafts: list[Draft] = []
    for removed, ties in lost.items():
        entity = _entity(evolution, removed)
        if entity is None or entity.lifecycle != "removed":
            continue
        relying = [
            t
            for t in ties
            if (e := _entity(evolution, t.from_id)) is not None and e.lifecycle != "removed"
        ]
        stranded = [t for t in relying if (t.from_id, t.type, t.run_id) not in found]
        if not stranded:
            continue
        names = sorted({e.name for t in stranded if (e := _entity(evolution, t.from_id))})
        critical = any((e := _entity(evolution, t.from_id)) and _critical(e) for t in stranded)
        version = gone[removed]
        drafts.append(
            _draft(
                "evolution.removed_relied",
                entity,
                f"{entity.name} is no longer shown by any source since "
                f"{_day(version.recorded_at)}, yet {', '.join(names)} relied on it and "
                "relies on nothing else in its place.",
                severity=Severity.HIGH if len(stranded) >= 2 or critical else Severity.MEDIUM,
                score=0.6 + len(stranded) / 10,
                insight="risk",
                recommendation="confirm_removal",
                params={
                    "at": version.recorded_at.isoformat(),
                    "relying": len(names),
                    "names": names[:MAX_NAMED],
                    "moved": len({t.from_id for t in relying}) - len(names),
                },
                evidence=(
                    Evidence(
                        kind="version",
                        id=str(version.id),
                        name=entity.name,
                        detail=f"removed on {_day(version.recorded_at)}, version {version.version}",
                    ),
                    *(_tie_evidence(evolution, t) for t in stranded),
                ),
            )
        )
    return drafts


def architecture(material: Material) -> list[Draft]:
    """What appeared and went this month among what runs and keeps data,
    said once for the workspace."""
    evolution = material.evolution
    if evolution is None:
        return []
    moved: dict[str, list[tuple[EvolvedVersion, EvolvedEntity]]] = defaultdict(list)
    for version in _versions(evolution):
        entity = _entity(evolution, version.entity_id)
        if entity is None or entity.type not in ARCHITECTURE:
            continue
        if version.change in ("created", "removed"):
            moved[version.change].append((version, entity))
    created, removed = moved["created"], moved["removed"]
    if len(created) + len(removed) < ARCHITECTURE_MOVED:
        return []

    def named(said: Sequence[tuple[EvolvedVersion, EvolvedEntity]]) -> list[str]:
        return sorted({e.name for _, e in said})[:MAX_NAMED]

    kinds = Counter(f"{v.change}.{e.type}" for v, e in [*created, *removed])
    return [
        Draft(
            key="evolution.architecture_moved:workspace",
            code="evolution.architecture_moved",
            severity=Severity.LOW,
            subject=Subject(type="workspace", id=None, name="workspace"),
            statement=(
                f"The architecture moved this month: {len(created)} appeared, {len(removed)} went."
            ),
            params={
                "insight": "architecture",
                "recommendation": "review_architecture",
                "created": len(created),
                "removed": len(removed),
                "appeared": named(created),
                "went": named(removed),
                "kinds": dict(sorted(kinds.items())),
                "since": evolution.since.isoformat(),
            },
            score=min(1.0, (len(created) + len(removed)) / 20),
            evidence=tuple(
                Evidence(
                    kind="version",
                    id=str(v.id),
                    name=e.name,
                    detail=f"{v.change} on {_day(v.recorded_at)}",
                )
                for v, e in [*removed, *created][:MAX_NAMED]
            ),
        )
    ]


def incidents(material: Material) -> list[Draft]:
    """A thing's incidents rising: INCIDENTS_RISING this month at least,
    twice the month before."""
    evolution = material.evolution
    if evolution is None:
        return []
    recent: dict[uuid.UUID, list[str]] = defaultdict(list)
    before: Counter[uuid.UUID] = Counter()
    evidence: dict[uuid.UUID, list[Evidence]] = defaultdict(list)
    for incident in evolution.incidents:
        for affected in incident.affects:
            if incident.occurred_at >= evolution.since:
                recent[affected].append(incident.name)
                evidence[affected].append(
                    Evidence(
                        kind="incident",
                        id=str(incident.id),
                        name=incident.name,
                        detail=f"{incident.severity or 'incident'} on {_day(incident.occurred_at)}",
                    )
                )
            else:
                before[affected] += 1
    drafts: list[Draft] = []
    for affected, names in recent.items():
        entity = _entity(evolution, affected)
        count, earlier = len(names), before[affected]
        if entity is None or count < INCIDENTS_RISING or count < 2 * earlier:
            continue
        many = count >= MANY_INCIDENTS or _critical(entity)
        drafts.append(
            _draft(
                "evolution.incidents_rising",
                entity,
                f"{entity.name} had {count} incidents this month, {earlier} the month before.",
                severity=Severity.HIGH if many else Severity.MEDIUM,
                score=count / 10 + entity.dependents / 20,
                insight="operational",
                recommendation="investigate_incidents",
                params={"recent": count, "before": earlier, "names": names[:5]},
                evidence=evidence[affected],
            )
        )
    return drafts


def volatility(material: Material) -> list[Draft]:
    """A thing that changed VOLATILE times or more this month — not an event,
    which changes by nature."""
    evolution = material.evolution
    if evolution is None:
        return []
    changed: dict[uuid.UUID, list[EvolvedVersion]] = defaultdict(list)
    for version in _versions(evolution):
        if version.change == "changed":
            changed[version.entity_id].append(version)
    drafts: list[Draft] = []
    for thing, versions in changed.items():
        entity = _entity(evolution, thing)
        if entity is None or entity.type in EVENTS or len(versions) < VOLATILE:
            continue
        fields = Counter(f for v in versions for f in v.fields)
        relied = entity.dependents >= DEPENDENCY_GROWTH or _critical(entity)
        drafts.append(
            _draft(
                "evolution.volatile",
                entity,
                f"{entity.name} changed {len(versions)} times this month, most often "
                f"{', '.join(f for f, _ in fields.most_common(3))}.",
                severity=Severity.MEDIUM if relied else Severity.LOW,
                score=len(versions) / 20 + entity.dependents / 20,
                insight="risk",
                recommendation="watch_changes",
                params={
                    "changes": len(versions),
                    "fields": [f for f, _ in fields.most_common(3)],
                },
                evidence=(
                    Evidence(
                        kind="version",
                        id=str(v.id),
                        name=f"{entity.name} v{v.version}",
                        detail=f"{', '.join(v.fields[:3])} on {_day(v.recorded_at)}",
                    )
                    for v in versions
                ),
            )
        )
    return drafts


def quality_move(row: QualityScoreRow, point: QualityPoint) -> QualityMove:
    """An area's score now, against the point it stood at then."""
    kind = row.scope if row.scope in ("workspace", "column") else "entity"
    return QualityMove(
        key=row.key,
        scope=row.scope,
        subject=Subject(
            type=kind,
            id=row.subject_id,
            name=row.subject_name,
            kind=row.subject_kind,
        ),
        column=row.column,
        before=point.score,
        after=row.score,
        level_before=point.level,
        level_after=row.level,
        since=point.measured_at,
    )


def quality(material: Material) -> list[Draft]:
    """An area whose knowledge quality fell this month: QUALITY_FELL or
    more, or a level lower — what LEKA knows of it can be trusted less."""
    if material.evolution is None:
        return []
    drafts: list[Draft] = []
    for move in material.quality_moves:
        fell = move.before - move.after
        lower = LEVELS.get(move.level_after, 0) < LEVELS.get(move.level_before, 0)
        if fell < QUALITY_FELL and not lower:
            continue
        severe = move.level_after == "low" or fell >= 2 * QUALITY_FELL
        drafts.append(
            Draft(
                key=f"evolution.quality_fell:{move.key}",
                code="evolution.quality_fell",
                severity=Severity.MEDIUM if severe else Severity.LOW,
                subject=move.subject,
                statement=(
                    f"What LEKA knows of {move.subject.name} can be trusted less than a month "
                    f"ago: {move.before:.2f} then, {move.after:.2f} now."
                ),
                params={
                    "insight": "risk",
                    "recommendation": "review_quality",
                    "name": move.subject.name,
                    "scope": move.scope,
                    "column": move.column,
                    "before": round(move.before, 3),
                    "after": round(move.after, 3),
                    "level_before": move.level_before,
                    "level_after": move.level_after,
                    "since": move.since.isoformat(),
                },
                score=max(0.0, min(1.0, fell * 3)),
                evidence=(
                    Evidence(
                        kind="quality",
                        id=move.key,
                        name=move.subject.name,
                        detail=(
                            f"{move.before:.2f} ({move.level_before}) on {_day(move.since)}, "
                            f"{move.after:.2f} ({move.level_after}) now"
                        ),
                    ),
                ),
            )
        )
    return drafts


def _analyzer(name: str, summary: str, run: Callable[[Material], Sequence[Draft]]) -> Analyzer:
    return Analyzer(
        name=name,
        version=VERSION,
        category="evolution",
        method=Method.RULES,
        reads=frozenset({Reads.EVOLUTION}),
        summary=summary,
        run=run,
    )


ANALYZERS: tuple[Analyzer, ...] = (
    _analyzer(
        "evolution_dependencies",
        "What depends on many more things than a month ago.",
        dependencies,
    ),
    _analyzer(
        "evolution_ownership",
        "What lost its owner this month, or changed owner.",
        ownership,
    ),
    _analyzer(
        "evolution_removals",
        "What went from every source while things still relied on it.",
        removals,
    ),
    _analyzer(
        "evolution_architecture",
        "What appeared and went this month among what runs and keeps data.",
        architecture,
    ),
    _analyzer(
        "evolution_incidents",
        "What has more incidents this month, twice the month before.",
        incidents,
    ),
    _analyzer(
        "evolution_quality",
        "What an area's knowledge quality lost this month.",
        quality,
    ),
    _analyzer(
        "evolution_volatility",
        "What changed again and again this month.",
        volatility,
    ),
)
