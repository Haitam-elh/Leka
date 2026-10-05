"""How good a context is (LEKA-375) — pure: what it is judged on, how,
and what it lacks.

An analysis must tell strong evidence from a guess. A version of a context
is judged on three measures, each the weighted mean of what it can be read
from — a factor nothing measures is said unknown and left out, never
guessed — and each factor names the elements it was read from:

    completeness  .35   does it hold what the question needs?
        start      .25  the things it starts from are in it — or, from
                        words, something was found
        facets     .25  the sides it should cover — an intention's (§ 13),
                        or what its roots are: a service has an owner side
        retrieval  .20  the retrievers that ran succeeded
        knowledge  .20  what the model knows of what it is about: an owner,
                        a page that describes it, a source that watches it
        budget     .10  nothing relevant left out for the budget
    freshness     .25   is what it holds current?
        model      .35  the model it was read from was built lately — a
                        day of grace, then halved each week
        evidence   .40  how lately a source showed what it holds, weighed
                        by how much each counts
        sources    .25  how the sources it came from are doing
    confidence    .40   can it be relied on?
        trust      .50  the trust of what it holds (LEKA-372), weighed
        corroboration .20  the share of things two sources or more say
        stated     .15  the share of ties a source stated, not inferred
        consistency .15  what its sources disagree on, the critical twice

    score = .35 completeness + .40 confidence + .25 freshness
    high from 0.85, medium from 0.6, low under — as the screens say it.
    A critical gap holds it to low (0.59 at most); a critical conflict,
    to medium (0.84).

WHAT IT LACKS — each gap with its severity, what it lowers, the elements
it is about: an intention's (LEKA-373), as read; and nothing found, a root
gone, a side uncovered, a retriever failed, relevant things left for the
budget, a root with no owner, no page, no watching source — critical when
that is what the intention asks (who owns it, where it is written, why it
is slow) — a model or evidence gone stale, a source failing, ties mostly
inferred.

WHAT IT DISAGREES ON, AND HOW BADLY — LEKA-372's conflicts, judged:
critical when it is about what was asked and on what decides an answer —
two of a kind that admits one, an attribute that matters (status, version,
environment, owner, SLA…), a tie to a thing gone; a warning when one of
the two; else said for information.

WHAT EACH RETRIEVER BROUGHT — found, kept, found by it alone, among the
first ranks: what weighing it next time can read (with people's feedback,
service.py).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from leka.context.assembly import Element
from leka.context.intent import facet_of
from leka.context.schemas import (
    ContextConflictRead,
    ContextQuality,
    ContextRequest,
    IntentGap,
    IntentPlan,
    MeasureName,
    QualityConflict,
    QualityFactor,
    QualityGap,
    QualityMeasure,
    QualitySupport,
    RankingReport,
    RetrieverRunRead,
    RetrieverYield,
    Severity,
)

# Raised each time quality is judged differently; kept with every version.
QUALITY_VERSION = 1
HIGH, MEDIUM = 0.85, 0.6
# What a critical gap, a critical conflict hold the score to.
CAP_GAP, CAP_CONFLICT = 0.59, 0.84

MEASURES: dict[MeasureName, float] = {"completeness": 0.35, "confidence": 0.40, "freshness": 0.25}
COMPLETENESS = {"start": 0.25, "facets": 0.25, "retrieval": 0.20, "knowledge": 0.20, "budget": 0.10}
FRESHNESS = {"model": 0.35, "evidence": 0.40, "sources": 0.25}
CONFIDENCE = {"trust": 0.50, "corroboration": 0.20, "stated": 0.15, "consistency": 0.15}

# The model read is current for a day, then half as fresh each week.
MODEL_GRACE = timedelta(hours=24)
MODEL_HALF_LIFE = timedelta(days=7)
# A thing a source last showed a month ago is half as fresh (LEKA-372).
STALE = 0.5
# A source failing, or deleted.
FAILING = 0.3
# Left for the budget, and this relevant: it should have been in.
RELEVANT = 0.5
# What matters most: the first ranks.
TOP = 10
# How many elements a factor names, at most.
MAX_REFS = 5

# What has an owner, a page, a watching source to know of.
OWNABLE = frozenset({"service", "application", "repository", "database"})
# What happened.
EVENTS = frozenset({"incident", "deployment", "change", "release", "alert"})
# What an answer turns on: a disagreement on it about what was asked is critical.
KEY_ATTRIBUTES = frozenset(
    {
        "status",
        "state",
        "version",
        "environment",
        "environments",
        "owner",
        "team",
        "tier",
        "criticality",
        "sla",
        "slo",
        "lifecycle",
        "region",
    }
)
# Where an intention's gaps count (LEKA-373).
INTENT_MEASURES: dict[str, MeasureName] = {
    "model_not_built": "freshness",
    "model_stale": "freshness",
    "disputed_subject": "confidence",
}
ORDER: dict[str, int] = {"critical": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class RootProfile:
    """What the company model knows of a thing a context is about, beyond
    the context: who owns it, whether a page describes it, whether a
    monitoring source watches it."""

    entity_id: uuid.UUID
    name: str
    type: str
    owner: bool
    documented: bool
    watched: bool


def assess(
    elements: Sequence[Element],
    *,
    request: ContextRequest,
    retrieval: Sequence[RetrieverRunRead],
    ranking: RankingReport | None,
    conflicts: Sequence[ContextConflictRead],
    plan: IntentPlan | None,
    intent_gaps: Sequence[IntentGap] = (),
    model_built_at: datetime | None,
    assembled_at: datetime,
    roots: Sequence[RootProfile] | None,
    assessed: Literal["assembled", "read"] = "assembled",
) -> ContextQuality:
    """A version of a context, judged: its measures, what it lacks, what it
    disagrees on and how badly, what each retriever brought. `roots` is
    what the model knows of its roots — None when that was not read."""
    entities = [e for e in elements if e.kind == "entity"]
    subjects = set(request.roots) | ({s.entity_id for s in plan.subjects} if plan else set())
    judged = [_judged(conflict, subjects) for conflict in conflicts]
    critical_refs = {r for c in judged if c.severity == "critical" for r in c.refs}
    disputed_refs = {r for c in judged if c.severity != "critical" for r in c.refs}

    completeness = _completeness(entities, request, retrieval, ranking, plan, roots)
    freshness = _freshness(entities, model_built_at, assembled_at)
    confidence = _confidence(elements, entities, critical_refs, disputed_refs)
    measures = [completeness, confidence, freshness]

    gaps = _gaps(entities, elements, request, retrieval, ranking, plan, intent_gaps, roots)
    gaps += _stale_gaps(entities, model_built_at, assembled_at, plan)
    gaps.sort(key=lambda gap: ORDER[gap.severity])
    judged.sort(key=lambda conflict: ORDER[conflict.severity])

    known = [(m.score, m.weight) for m in measures if m.score is not None]
    score = _mean(known)
    capped: Literal["critical_gap", "critical_conflict"] | None = None
    if score is not None:
        if any(gap.severity == "critical" for gap in gaps) and score > CAP_GAP:
            score, capped = CAP_GAP, "critical_gap"
        elif critical_refs and score > CAP_CONFLICT:
            score, capped = CAP_CONFLICT, "critical_conflict"
    return ContextQuality(
        version=QUALITY_VERSION,
        score=None if score is None else round(score, 4),
        level=_level(score),
        capped=capped,
        measures=measures,
        gaps=gaps,
        conflicts=judged,
        support=QualitySupport(
            entities=len(entities),
            sources=len({s.source_id for e in elements for s in e.provenance.sources}),
            events=sum(1 for e in entities if e.ref_type in EVENTS),
            corroborated=sum(1 for e in entities if _sources(e) >= 2),
            conflicts=len(judged),
            critical=sum(1 for c in judged if c.severity == "critical"),
        ),
        retrieval=_yields(elements, retrieval),
        assessed=assessed,
    )


def _level(score: float | None) -> Literal["high", "medium", "low", "unknown"]:
    if score is None:
        return "unknown"
    if score >= HIGH:
        return "high"
    return "medium" if score >= MEDIUM else "low"


# ── the measures ────────────────────────────────────────────────────────────


def _completeness(
    entities: Sequence[Element],
    request: ContextRequest,
    retrieval: Sequence[RetrieverRunRead],
    ranking: RankingReport | None,
    plan: IntentPlan | None,
    roots: Sequence[RootProfile] | None,
) -> QualityMeasure:
    held = {e.ref_id: e for e in entities}
    factors: list[QualityFactor] = []

    if request.roots:
        present = [r for r in request.roots if r in held and not _removed(held[r])]
        factors.append(
            _factor(
                "start",
                len(present) / len(request.roots),
                COMPLETENESS,
                f"{len(present)} of the {len(request.roots)} things it starts from are in it.",
                present,
                asked=len(request.roots),
                held=len(present),
            )
        )
    else:
        factors.append(
            _factor(
                "start",
                1.0 if entities else 0.0,
                COMPLETENESS,
                f"Its words found {len(entities)} things."
                if entities
                else "Its words found nothing.",
                [e.ref_id for e in entities[:MAX_REFS]],
                found=len(entities),
            )
        )

    expected = _expected(plan, [held[r] for r in request.roots if r in held])
    covered: dict[str, uuid.UUID] = {}
    for element in entities:
        covered.setdefault(_facet(element), element.ref_id)
    if expected:
        met = [facet for facet in expected if facet in covered]
        missing = [facet for facet in expected if facet not in covered]
        factors.append(
            _factor(
                "facets",
                len(met) / len(expected),
                COMPLETENESS,
                f"It covers {', '.join(met) or 'none'} of the sides it should"
                + (f"; nothing {', '.join(missing)}." if missing else "."),
                [covered[facet] for facet in met],
                expected=list(expected),
                covered=met,
                missing=missing,
            )
        )
    else:
        factors.append(
            _factor("facets", None, COMPLETENESS, "Nothing says which sides it should cover.")
        )

    ran = [run for run in retrieval if run.status != "skipped"]
    failed = [run.retriever for run in ran if run.status in {"failed", "timeout"}]
    factors.append(
        _factor(
            "retrieval",
            (len(ran) - len(failed)) / len(ran) if ran else None,
            COMPLETENESS,
            (
                f"{', '.join(failed)} failed: what it would have found is missing."
                if failed
                else f"The {len(ran)} retrievers that ran succeeded."
            )
            if ran
            else "No retriever ran.",
            failed=failed,
        )
    )

    if roots is None:
        factors.append(
            _factor(
                "knowledge",
                None,
                COMPLETENESS,
                "What the model knew of its roots then was not read.",
            )
        )
    elif not roots:
        factors.append(
            _factor(
                "knowledge",
                None,
                COMPLETENESS,
                "None of what it starts from has an owner, a page or a watching source to know of."
                if request.roots
                else "It starts from words, not from a thing to know of.",
            )
        )
    else:
        checks = [(root, what) for root in roots for what in _known(root)]
        known = sum(1 for _, ok in checks if ok)
        lacking = [f"{root.name}: {what}" for root, what in _lacking(roots)]
        factors.append(
            _factor(
                "knowledge",
                known / len(checks),
                COMPLETENESS,
                "The model knows who owns what it is about, where it is written, what watches it."
                if not lacking
                else f"The model does not know: {'; '.join(lacking)}.",
                [root.entity_id for root in roots],
                lacking=lacking,
            )
        )

    relevant = _left_for_budget(ranking)
    factors.append(
        _factor(
            "budget",
            len(entities) / (len(entities) + len(relevant)) if relevant else 1.0,
            COMPLETENESS,
            f"{len(relevant)} relevant things were left out for its budget of {request.limit}."
            if relevant
            else "Nothing relevant was left out for its budget.",
            relevant=len(relevant),
            budget=request.limit,
        )
    )
    return _measure("completeness", factors)


def _freshness(
    entities: Sequence[Element], model_built_at: datetime | None, assembled_at: datetime
) -> QualityMeasure:
    factors: list[QualityFactor] = []
    if model_built_at is None:
        factors.append(_factor("model", 0.0, FRESHNESS, "The company model had never been built."))
    else:
        age = max(assembled_at - model_built_at, timedelta(0))
        value = 1.0 if age <= MODEL_GRACE else 0.5 ** ((age - MODEL_GRACE) / MODEL_HALF_LIFE)
        hours = round(age.total_seconds() / 3600)
        factors.append(
            _factor(
                "model",
                value,
                FRESHNESS,
                f"The model it was read from was built {hours} hours before.",
                hours=hours,
            )
        )
    evidence, stalest = _weighed(entities, "freshness")
    factors.append(
        _factor(
            "evidence",
            evidence,
            FRESHNESS,
            "How lately a source showed what it holds, weighed by how much each counts."
            if evidence is not None
            else "When a source last showed what it holds is not known.",
            stalest,
        )
    )
    health, worst = _weighed(entities, "sources")
    factors.append(
        _factor(
            "sources",
            health,
            FRESHNESS,
            "How the sources it came from are doing."
            if health is not None
            else "How its sources are doing is not known.",
            worst,
        )
    )
    return _measure("freshness", factors)


def _confidence(
    elements: Sequence[Element],
    entities: Sequence[Element],
    critical: set[uuid.UUID],
    disputed: set[uuid.UUID],
) -> QualityMeasure:
    factors: list[QualityFactor] = []
    trusted = [e for e in elements if e.ranking is not None and e.ranking.trust is not None]
    trust = _mean([(e.ranking.trust or 0.0, _weight(e)) for e in trusted if e.ranking])
    weakest = sorted(trusted, key=lambda e: (e.ranking.trust if e.ranking else 1.0) or 0.0)
    factors.append(
        _factor(
            "trust",
            trust,
            CONFIDENCE,
            "How far what it holds can be relied on, weighed by how much each counts."
            if trust is not None
            else "How far what it holds can be relied on is not known.",
            [e.ref_id for e in weakest[:MAX_REFS]],
        )
    )
    corroborated = [e for e in entities if _sources(e) >= 2]
    single = [e for e in entities if _sources(e) == 1]
    factors.append(
        _factor(
            "corroboration",
            len(corroborated) / len(entities) if entities else None,
            CONFIDENCE,
            f"{len(corroborated)} of the {len(entities)} things it holds are said by two "
            "sources or more."
            if entities
            else "It holds nothing to corroborate.",
            [e.ref_id for e in single[:MAX_REFS]],
            corroborated=len(corroborated),
        )
    )
    ties = [e for e in elements if e.kind == "relationship"]
    inferred = [e for e in ties if e.provenance.origin == "inferred"]
    factors.append(
        _factor(
            "stated",
            (len(ties) - len(inferred)) / len(ties) if ties else None,
            CONFIDENCE,
            f"{len(ties) - len(inferred)} of its {len(ties)} ties were stated by a source; "
            f"{len(inferred)} inferred."
            if ties
            else "It holds no tie.",
            [e.ref_id for e in inferred[:MAX_REFS]],
            inferred=len(inferred),
        )
    )
    weight = len(disputed - critical) + 2 * len(critical)
    factors.append(
        _factor(
            "consistency",
            max(0.0, 1 - weight / len(elements)) if elements else None,
            CONFIDENCE,
            f"{len(critical)} things are part of a critical conflict, {len(disputed - critical)} "
            "of another."
            if critical or disputed
            else "Its sources agree on what it holds.",
            [*sorted(critical, key=str), *sorted(disputed - critical, key=str)][:MAX_REFS],
        )
    )
    return _measure("confidence", factors)


# ── what it lacks ───────────────────────────────────────────────────────────


def _gaps(
    entities: Sequence[Element],
    elements: Sequence[Element],
    request: ContextRequest,
    retrieval: Sequence[RetrieverRunRead],
    ranking: RankingReport | None,
    plan: IntentPlan | None,
    intent_gaps: Sequence[IntentGap],
    roots: Sequence[RootProfile] | None,
) -> list[QualityGap]:
    gaps = [
        QualityGap(
            kind=gap.kind,
            severity=gap.severity,
            measure=INTENT_MEASURES.get(gap.kind, "completeness"),
            origin="intent",
            said=gap.said,
            detail=dict(gap.detail),
        )
        for gap in intent_gaps
    ]
    held = {e.ref_id: e for e in entities}
    if not entities:
        gaps.append(_gap("nothing_found", "critical", "completeness", "It holds nothing."))
    gone = [r for r in request.roots if r not in held or _removed(held[r])]
    if gone and entities:
        gaps.append(
            _gap(
                "root_missing",
                "critical",
                "completeness",
                f"{len(gone)} of the things it starts from are no longer in the company model.",
                gone,
            )
        )
    expected = _expected(plan, [held[r] for r in request.roots if r in held])
    covered = {_facet(e) for e in entities}
    # An intention says these itself: nothing happened, no business side.
    said = {"temporal", "business"} if plan else set()
    for facet in expected:
        if facet not in covered and facet not in said and entities:
            gaps.append(
                _gap(
                    "facet_missing",
                    "warning",
                    "completeness",
                    f"Nothing {facet} is in it, and what it is about calls for it.",
                    facet=facet,
                )
            )
    if plan is None:
        for run in retrieval:
            if run.status in {"failed", "timeout"}:
                gaps.append(
                    _gap(
                        "retriever_failed",
                        "warning",
                        "completeness",
                        f"The {run.retriever} retriever {run.status}: what it would have found "
                        "is missing.",
                        retriever=run.retriever,
                        status=run.status,
                    )
                )
    relevant = _left_for_budget(ranking)
    if relevant:
        gaps.append(
            _gap(
                "budget_cut",
                "warning" if len(relevant) >= max(3, len(entities) // 4) else "info",
                "completeness",
                f"{len(relevant)} relevant things were left out for its budget of "
                f"{request.limit}: widen it to hold them.",
                count=len(relevant),
                budget=request.limit,
                best=relevant[:MAX_REFS],
            )
        )
    for root, what in _lacking(roots or ()):
        gaps.append(_knowledge_gap(root, what, plan))
    top = [e for e in entities if e.ranking is not None and (e.ranking.rank or TOP + 1) <= TOP]
    stale = [e for e in top if (_value(e, "freshness") or 1.0) < STALE]
    if stale:
        gaps.append(
            _gap(
                "stale_evidence",
                "warning",
                "freshness",
                f"{len(stale)} of what matters most were last shown by a source more than a "
                "month ago.",
                [e.ref_id for e in stale],
            )
        )
    failing = [e for e in top if (_value(e, "sources") or 1.0) <= FAILING]
    if failing:
        gaps.append(
            _gap(
                "source_unhealthy",
                "warning",
                "freshness",
                f"{len(failing)} of what matters most come from a source failing, or deleted.",
                [e.ref_id for e in failing],
            )
        )
    ties = [e for e in elements if e.kind == "relationship"]
    inferred = [e for e in ties if e.provenance.origin == "inferred"]
    if len(ties) >= 4 and len(inferred) * 2 > len(ties):
        gaps.append(
            _gap(
                "mostly_inferred",
                "info",
                "confidence",
                f"{len(inferred)} of its {len(ties)} ties were inferred by LEKA, not stated by a "
                "source.",
                [e.ref_id for e in inferred[:MAX_REFS]],
            )
        )
    return gaps


def _stale_gaps(
    entities: Sequence[Element],
    model_built_at: datetime | None,
    assembled_at: datetime,
    plan: IntentPlan | None,
) -> list[QualityGap]:
    """The model never built, or old — an intention's reading says it
    already (LEKA-373)."""
    if plan is not None:
        return []
    if model_built_at is None:
        return [
            _gap(
                "model_not_built",
                "critical",
                "freshness",
                "The company model had never been built: there was nothing to read.",
            )
        ]
    if assembled_at - model_built_at > MODEL_GRACE:
        hours = round((assembled_at - model_built_at).total_seconds() / 3600)
        return [
            _gap(
                "model_stale",
                "warning",
                "freshness",
                f"The company model was built {hours} hours before: what changed since is not "
                "in it.",
                hours=hours,
            )
        ]
    return []


def _knowledge_gap(root: RootProfile, what: str, plan: IntentPlan | None) -> QualityGap:
    """What the model does not know of a thing asked about — critical when
    that is what the intention asks."""
    kind = plan.kind if plan else None
    rules: dict[str, tuple[str, Severity, str]] = {
        "owner": (
            "no_owner",
            "critical" if kind == "ownership" else "warning",
            f"Nobody is known to own {root.name}: no team or person the sources tie to it.",
        ),
        "page": (
            "undocumented",
            "critical" if kind == "knowledge" else "info",
            f"No page describes {root.name}: nothing written on it was found.",
        ),
        "watching source": (
            "unwatched",
            "warning" if kind in {"diagnose", "change"} else "info",
            f"No monitoring source watches {root.name}: how it behaves is not seen.",
        ),
    }
    gap, severity, said = rules[what]
    return _gap(gap, severity, "completeness", said, [root.entity_id], entity=root.name)


# ── what it disagrees on, and how badly ─────────────────────────────────────


def _judged(conflict: ContextConflictRead, subjects: set[uuid.UUID]) -> QualityConflict:
    on_subject = conflict.subject in subjects or bool(set(conflict.refs) & subjects)
    key = conflict.about.casefold() in KEY_ATTRIBUTES
    severity: Severity
    if conflict.kind == "competing":
        severity = "critical" if on_subject else "warning"
        why = (
            "It is about what was asked, and there can be only one: an answer turns on it."
            if on_subject
            else "There can be only one, but it is not what was asked about."
        )
    elif conflict.kind == "gone":
        severity = "critical" if on_subject else "warning"
        why = (
            "What was asked about is tied to a thing gone from every source."
            if on_subject
            else "A tie stays to a thing gone from every source."
        )
    else:
        severity = "critical" if on_subject and key else "warning" if on_subject or key else "info"
        why = {
            "critical": f"It is about what was asked, on its {conflict.about}: an answer turns "
            "on it.",
            "warning": f"It is about what was asked, on its {conflict.about}."
            if on_subject
            else f"Its {conflict.about} matters, but it is not what was asked about.",
            "info": "Said for information: it is neither what was asked about nor what decides "
            "an answer.",
        }[severity]
    return QualityConflict(
        id=conflict.id,
        kind=conflict.kind,
        subject=conflict.subject,
        label=conflict.label,
        about=conflict.about,
        severity=severity,
        why=why,
        said=conflict.said,
        refs=list(conflict.refs),
    )


# ── what each retriever brought ─────────────────────────────────────────────


def _yields(
    elements: Sequence[Element], retrieval: Sequence[RetrieverRunRead]
) -> list[RetrieverYield]:
    found_by = {e.ref_id: {m.retriever for m in e.reason.retrievers} for e in elements}
    yields: list[RetrieverYield] = []
    for run in retrieval:
        kept = [e for e in elements if run.retriever in found_by[e.ref_id]]
        only = [e for e in kept if found_by[e.ref_id] == {run.retriever}]
        top = [e for e in kept if e.ranking is not None and (e.ranking.rank or TOP + 1) <= TOP]
        yields.append(
            RetrieverYield(
                retriever=run.retriever,
                status=run.status,
                found=run.found,
                kept=len(kept),
                only=len(only),
                top=len(top),
                said=(
                    f"Found {run.found}: {len(kept)} kept, {len(only)} by it alone, {len(top)} "
                    f"among the first {TOP}."
                    if run.status == "ok"
                    else f"It {run.status}: {run.error or run.detail or 'no reason given'}."
                ),
            )
        )
    return yields


# ── reading what it holds ───────────────────────────────────────────────────


def _expected(plan: IntentPlan | None, roots: Sequence[Element]) -> list[str]:
    """The sides a context should cover: its intention's — or what its
    roots are, and an owner side for what has one."""
    if plan is not None:
        return list(plan.facets)
    sides: list[str] = list(dict.fromkeys(facet_of(root.ref_type) for root in roots))
    if any(root.ref_type in OWNABLE for root in roots) and "organizational" not in sides:
        sides.append("organizational")
    return sides


def _facet(element: Element) -> str:
    return "temporal" if element.ref_type in EVENTS else facet_of(element.ref_type)


def _known(root: RootProfile) -> Iterable[bool]:
    return (root.owner, root.documented, root.watched)


def _lacking(roots: Iterable[RootProfile]) -> list[tuple[RootProfile, str]]:
    return [
        (root, what)
        for root in roots
        for what, known in (
            ("owner", root.owner),
            ("page", root.documented),
            ("watching source", root.watched),
        )
        if not known
    ]


def _left_for_budget(ranking: RankingReport | None) -> list[str]:
    """What was left for the budget and should have been in: its label."""
    if ranking is None:
        return []
    return [
        left.label for left in ranking.left if left.reason == "budget" and left.score >= RELEVANT
    ]


def _removed(element: Element) -> bool:
    return element.entity is not None and element.entity.lifecycle == "removed"


def _sources(element: Element) -> int:
    return len({s.source_id for s in element.provenance.sources})


def _value(element: Element, name: str) -> float | None:
    if element.ranking is None:
        return None
    return next((s.value for s in element.ranking.signals if s.name == name), None)


def _weight(element: Element) -> float:
    """How much an element counts: its score, never nothing."""
    return max(element.ranking.score if element.ranking else 0.0, 0.01)


def _weighed(entities: Sequence[Element], signal: str) -> tuple[float | None, list[uuid.UUID]]:
    """A trust signal across what a context holds, weighed by how much each
    counts — and the elements it is lowest on."""
    read = [(value, e) for e in entities if (value := _value(e, signal)) is not None]
    if not read:
        return None, []
    lowest = sorted(read, key=lambda pair: pair[0])
    return (
        _mean([(value, _weight(e)) for value, e in read]),
        [e.ref_id for value, e in lowest[:MAX_REFS] if value < 1.0],
    )


def _mean(pairs: Sequence[tuple[float, float]]) -> float | None:
    total = sum(weight for _, weight in pairs)
    if not pairs or total <= 0:
        return None
    return sum(value * weight for value, weight in pairs) / total


def _factor(
    name: str,
    value: float | None,
    weights: dict[str, float],
    said: str,
    refs: Sequence[uuid.UUID] = (),
    **detail: object,
) -> QualityFactor:
    return QualityFactor(
        name=name,
        value=None if value is None else round(min(1.0, max(0.0, value)), 4),
        weight=weights[name],
        said=said,
        refs=list(dict.fromkeys(refs))[:MAX_REFS],
        detail=detail,
    )


def _measure(name: MeasureName, factors: list[QualityFactor]) -> QualityMeasure:
    score = _mean([(f.value, f.weight) for f in factors if f.value is not None])
    return QualityMeasure(
        name=name,
        score=None if score is None else round(score, 4),
        weight=MEASURES[name],
        factors=factors,
    )


def _gap(
    kind: str,
    severity: Severity,
    measure: MeasureName,
    said: str,
    refs: Sequence[uuid.UUID] = (),
    **detail: object,
) -> QualityGap:
    return QualityGap(
        kind=kind,
        severity=severity,
        measure=measure,
        origin="quality",
        said=said,
        refs=list(dict.fromkeys(refs))[:MAX_REFS],
        detail=detail,
    )
