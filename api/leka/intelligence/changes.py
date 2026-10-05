"""Change and impact (LEKA-378): which changes matter, and what they reach.

The company model says what a change was made to, what depends on that, the
business holding it and the incidents that followed (knowledge's
`ChangeFootprint`). This judges it — pure functions, tested in a
millisecond:

    signals       what is notable about it: in production, failed, an
                  incident followed, its source says it caused one, it
                  reaches widely, the business holds it
    significance  how much it matters, 0 to 1, from those signals
    current       recent enough to still be playing out (CURRENT, 72 h) —
                  older is history
    impacts       what it reaches, ranked: what an incident hit first,
                  then the nearest, the most critical, the business
    change_impact the analysis: each current change that matters, a
                  finding about the service it was made to

Nothing is inferred that the model does not say: an incident is tied to a
change because its source says so, or because it opened on the change's
footprint within AFTER of it — and the finding says which.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

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
from leka.knowledge import ChangeFootprint, EntityBrief

# Recent enough to be playing out: the incident-detail window (LEKA-367).
CURRENT = timedelta(hours=72)
# How long after a change an incident on its footprint is tied to it.
AFTER = timedelta(hours=48)
# How far back a run reads changes: history, kept for the timeline.
HISTORY = timedelta(days=30)
# Reaching this many is reaching widely.
WIDE = 3
# A change that matters at least this much, or that an incident followed.
SIGNIFICANT = 0.4
# The impacts and incidents a finding names at most.
MAX_NAMED = 8

PRODUCTION = ("prod", "live", "prd")
FAILED = frozenset({"failed", "error", "rolled_back", "canceled"})
CRITICAL = frozenset({"critical", "high", "tier1", "tier-1", "p1"})

# What each kind weighs before anything else is known of it.
BASE = {"deployment": 0.35, "change": 0.3, "release": 0.25, "pull_request": 0.1}
WEIGHTS = {
    "production": 0.2,
    "failed": 0.25,
    "incident_after": 0.3,
    "stated_cause": 0.4,
    "wide": 0.15,
    "business": 0.1,
    "critical": 0.1,
}


def _brief(entity: EntityBrief, kind: str | None = None) -> Subject:
    return Subject(type="entity", id=entity.id, name=entity.name, kind=kind or entity.type.value)


def production(footprint: ChangeFootprint) -> bool:
    said = (footprint.environment or "").lower()
    return any(word in said for word in PRODUCTION)


def signals(footprint: ChangeFootprint) -> tuple[str, ...]:
    """What is notable about a change, in the order WEIGHTS lists them."""
    found: list[str] = []
    if production(footprint):
        found.append("production")
    if (footprint.state or "").lower() in FAILED:
        found.append("failed")
    if any(not incident.stated for incident in footprint.incidents):
        found.append("incident_after")
    if any(incident.stated for incident in footprint.incidents):
        found.append("stated_cause")
    if len(footprint.reached) + len(footprint.applications) >= WIDE:
        found.append("wide")
    if footprint.capabilities or footprint.processes:
        found.append("business")
    criticalities = [touch.criticality for touch in footprint.touched] + [
        reach.criticality for reach in footprint.reached
    ]
    if any((said or "").lower() in CRITICAL for said in criticalities):
        found.append("critical")
    return tuple(found)


def significance(footprint: ChangeFootprint) -> float:
    """How much a change matters, 0 to 1: its kind's weight, and each of
    its signals'. Made to nothing the model knows, it reaches nothing it
    can say: a third of that."""
    score = BASE.get(footprint.kind, 0.1) + sum(WEIGHTS[s] for s in signals(footprint))
    if not footprint.touched:
        score /= 3
    return round(min(score, 1.0), 3)


def current(footprint: ChangeFootprint, now: datetime) -> bool:
    return now - footprint.at <= CURRENT


@dataclass(frozen=True)
class Impacted:
    """One thing a change reaches, and why it ranks where it does."""

    subject: Subject
    distance: int
    score: float
    reasons: tuple[str, ...]


def impacts(footprint: ChangeFootprint) -> list[Impacted]:
    """What a change reaches, the most affected first: what an incident
    hit, then what it was made to, then what depends on that — the nearer,
    the more critical, the higher."""
    hit = {incident.on.id for incident in footprint.incidents if incident.on is not None}
    ranked: list[Impacted] = []

    def scored(entity: EntityBrief, distance: int, criticality: str | None, how: str) -> None:
        reasons = [how]
        score = {0: 0.5, 1: 0.3, 2: 0.15}.get(distance, 0.1)
        if entity.id in hit:
            score += 0.4
            reasons.append("incident")
        if (criticality or "").lower() in CRITICAL:
            score += 0.1
            reasons.append("critical")
        ranked.append(
            Impacted(
                subject=_brief(entity),
                distance=distance,
                score=round(min(score, 1.0), 3),
                reasons=tuple(reasons),
            )
        )

    for touch in footprint.touched:
        scored(touch.entity, 0, touch.criticality, "touched")
    for reach in footprint.reached:
        scored(reach.entity, reach.distance, reach.criticality, f"depends_on:{reach.through.name}")
    seen = {item.subject.id for item in ranked}
    for application in footprint.applications:
        if application.id not in seen:
            ranked.append(
                Impacted(subject=_brief(application), distance=1, score=0.25, reasons=("holds",))
            )
    return sorted(ranked, key=lambda item: (-item.score, item.distance, item.subject.name.lower()))


def _primary(footprint: ChangeFootprint) -> Subject:
    """What a change is said to be about: the service it was made to,
    else what else it touched, else the change itself."""
    for kind in ("service", "application"):
        for touch in footprint.touched:
            if touch.entity.type.value == kind:
                return _brief(touch.entity)
    if footprint.touched:
        return _brief(footprint.touched[0].entity)
    return _brief(footprint.change)


def _severity(footprint: ChangeFootprint, found: Sequence[str]) -> Severity:
    if "stated_cause" in found or "incident_after" in found:
        return Severity.HIGH
    if "failed" in found and "production" in found and footprint.reached:
        return Severity.HIGH
    if "production" in found and (footprint.reached or "wide" in found or "business" in found):
        return Severity.MEDIUM
    if "failed" in found or "critical" in found:
        return Severity.MEDIUM
    return Severity.LOW


def change_impact(material: Material) -> list[Draft]:
    """Each current change that matters — significant enough, or followed
    by an incident — a finding about what it was made to: what it reaches,
    the most affected first, and what followed."""
    if material.changes is None:
        return []
    drafts: list[Draft] = []
    for footprint in material.changes:
        if not current(footprint, material.now):
            continue
        found = signals(footprint)
        score = significance(footprint)
        followed = "incident_after" in found or "stated_cause" in found
        if score < SIGNIFICANT and not followed:
            continue
        ranked = impacts(footprint)
        hours = max(0, round((material.now - footprint.at).total_seconds() / 3600))
        subject = _primary(footprint)
        incidents = footprint.incidents[:MAX_NAMED]
        statement = (
            f"{footprint.kind.replace('_', ' ').capitalize()} {footprint.change.name} "
            f"({hours} h ago"
            + (f", {footprint.environment}" if footprint.environment else "")
            + (f", {footprint.state}" if footprint.state else "")
            + f") reaches {len(ranked)} thing{'s' if len(ranked) != 1 else ''}"
        )
        if incidents:
            statement += f"; {len(footprint.incidents)} incident(s) followed: " + ", ".join(
                incident.entity.name for incident in incidents[:3]
            )
        evidence = [
            Evidence(
                kind="change",
                id=str(footprint.change.id),
                name=footprint.change.name,
                detail=f"{footprint.kind} at {footprint.at.isoformat()}"
                + "".join(f", {k} {v}" for k, v in sorted(footprint.details.items()) if k != "url"),
            ),
            *(
                Evidence(
                    kind="entity",
                    id=str(touch.entity.id),
                    name=touch.entity.name,
                    detail=f"made to it: {touch.how}",
                )
                for touch in footprint.touched[:MAX_NAMED]
            ),
            *(
                Evidence(
                    kind="incident",
                    id=str(incident.entity.id),
                    name=incident.entity.name,
                    detail=(
                        "its source says this change caused it"
                        if incident.stated
                        else f"opened {_after(footprint.at, incident.opened_at)} after, on "
                        f"{incident.on.name if incident.on else 'its footprint'}"
                    ),
                )
                for incident in incidents
            ),
        ]
        drafts.append(
            Draft(
                key=f"change:{footprint.change.id}",
                code="change.impact",
                severity=_severity(footprint, found),
                subject=subject,
                statement=statement + ".",
                params={
                    "change": footprint.change.name,
                    "kind": footprint.kind,
                    "at": footprint.at.isoformat(),
                    "hours": hours,
                    "environment": footprint.environment,
                    "state": footprint.state,
                    "reached": len(ranked),
                    "incidents": len(footprint.incidents),
                    "stated": any(incident.stated for incident in footprint.incidents),
                    "top": [item.subject.name for item in ranked[:3]],
                    "signals": list(found),
                },
                score=score,
                # Stated by a source: sure. Followed in time: likely, not proven.
                confidence=1.0 if "stated_cause" in found or not followed else 0.7,
                related=tuple(item.subject for item in ranked[:MAX_NAMED])
                + tuple(_brief(incident.entity) for incident in incidents),
                evidence=tuple(evidence),
                sources=tuple(footprint.sources),
            )
        )
    return drafts


def _after(at: datetime, then: datetime | None) -> str:
    if then is None:
        return "some time"
    hours = (then - at).total_seconds() / 3600
    return f"{hours:.0f} h" if hours >= 1 else f"{max(1, round(hours * 60))} min"


ANALYZER = Analyzer(
    name="change_impact",
    version=1,
    category="change",
    method=Method.RULES,
    reads=frozenset({Reads.CHANGES}),
    summary="The current changes that matter, what they reach, and what followed them.",
    run=change_impact,
)
