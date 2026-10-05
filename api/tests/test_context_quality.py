"""How good a context is (LEKA-375) — the judgement, pure:
leka/context/quality.py.

Billing API, as tests/test_context_assembly.py makes its material: owned by
Payments, described by its runbook, watched by PagerDuty, an incident on it.

What these protect: a context that holds what it needs, said by sources
that agree and are well, from a model built lately, is high — each measure
saying what it rests on, each factor naming its elements; the same context
judged twice is judged the same; a factor nothing measures is unknown,
never guessed; what the model does not know of what is asked — an owner,
a page, a watching source — is a gap, critical when that is the question,
and holds the level to low; a model and evidence gone stale, a source
failing, are said and lower freshness; a retriever failed and relevant
things left for the budget lower completeness and say so; a disagreement
about what was asked, on what decides an answer, is critical and holds the
level to medium — two owners too — and one elsewhere is said, not
critical; nothing found is low; what each retriever brought is counted.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta

from leka.context.assembly import Assembly, assemble
from leka.context.quality import CAP_CONFLICT, CAP_GAP, RootProfile, assess
from leka.context.schemas import (
    ContextQuality,
    ContextRequest,
    IntentGap,
    IntentPeriod,
    IntentPlan,
    LeftOutRead,
    RetrievalMatch,
    RetrieverRunRead,
)
from leka.knowledge import (
    ContextMaterial,
    EntityType,
    MaterialEntity,
    MaterialRelationship,
    MaterialSource,
    RelationshipType,
)
from tests.test_context_assembly import CATALOGUE, HR, NOW, _entity, _tie

PAGER = uuid.uuid4()
WELL = [
    MaterialSource(
        source_id=CATALOGUE, kind="backstage", name="Catalogue", status="active", health="healthy"
    ),
    MaterialSource(source_id=HR, kind="bamboohr", name="HR", status="active", health="healthy"),
    MaterialSource(
        source_id=PAGER, kind="pagerduty", name="PagerDuty", status="active", health="healthy"
    ),
]


def _said_by(
    *sources: uuid.UUID, conflicts: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "sources": [
            {"source_id": str(source), "key": f"k-{i}", "kind": "key"}
            for i, source in enumerate(sources)
        ],
        "conflicts": conflicts or [],
    }


BILLING = _entity(
    "Billing API", EntityType.SERVICE, 0, confidence=0.95, provenance=_said_by(CATALOGUE, PAGER)
)
PAYMENTS = _entity(
    "Payments", EntityType.TEAM, 1, confidence=0.95, provenance=_said_by(CATALOGUE, HR)
)
RUNBOOK = _entity("Billing runbook", EntityType.DOCUMENT, 1, provenance=_said_by(CATALOGUE, HR))
INCIDENT = _entity(
    "Billing API p99 above 2s", EntityType.INCIDENT, 1, provenance=_said_by(PAGER, CATALOGUE)
)
STRONG = [BILLING, PAYMENTS, RUNBOOK, INCIDENT]
TIES = [
    _tie(PAYMENTS, BILLING, RelationshipType.OWNS, confidence=0.95),
    _tie(RUNBOOK, BILLING, RelationshipType.DESCRIBES),
    _tie(INCIDENT, BILLING, RelationshipType.AFFECTS),
]
KNOWN = RootProfile(
    entity_id=BILLING.entity.id,
    name="Billing API",
    type="service",
    owner=True,
    documented=True,
    watched=True,
)
RUNS = [
    RetrieverRunRead(retriever=name, version=1, status="ok", found=4, ms=5, detail=None, error=None)
    for name in ("graph", "search", "timeline")
]


def _built(
    entities: list[MaterialEntity] = STRONG,
    ties: list[MaterialRelationship] = TIES,
    *,
    sources: list[MaterialSource] = WELL,
    limit: int = 100,
) -> Assembly:
    return assemble(
        ContextMaterial(
            roots=[BILLING.entity.id],
            entities=entities,
            relationships=ties,
            sources=sources,
            truncated=False,
            built_at=NOW,
            model_version=9,
        ),
        limit=limit,
        strategy="hybrid",
        now=NOW,
    )


def _request(**over: object) -> ContextRequest:
    return ContextRequest.model_validate(
        {
            "roots": [str(BILLING.entity.id)],
            "depth": 1,
            "relationships": [],
            "environment": None,
            "limit": 100,
            "strategy": "hybrid",
            **over,
        }
    )


def _plan(kind: str) -> IntentPlan:
    return IntentPlan.model_validate(
        {
            "version": 1,
            "text": "Qui est responsable de Billing API ?",
            "intention_id": None,
            "kind": kind,
            "kind_said": [],
            "facets": ["organizational", "technical"],
            "subjects": [
                {
                    "entity_id": str(BILLING.entity.id),
                    "name": "Billing API",
                    "type": "service",
                    "facet": "technical",
                    "how": "named",
                    "confidence": 1.0,
                }
            ],
            "period": IntentPeriod(since=NOW - timedelta(days=30), until=NOW, origin="kind"),
            "environment": None,
            "constraints": [],
            "request": _request(),
            "gaps": [],
        }
    )


def _judge(
    built: Assembly | None = None,
    *,
    request: ContextRequest | None = None,
    runs: list[RetrieverRunRead] = RUNS,
    plan: IntentPlan | None = None,
    gaps: list[IntentGap] | None = None,
    built_at: datetime | None = NOW,
    roots: list[RootProfile] | None = None,
) -> ContextQuality:
    made = built or _built()
    return assess(
        made.elements,
        request=request or _request(),
        retrieval=runs,
        ranking=made.ranking,
        conflicts=made.conflicts,
        plan=plan,
        intent_gaps=gaps or [],
        model_built_at=built_at,
        assembled_at=NOW,
        roots=[KNOWN] if roots is None else roots,
    )


def _measure(quality: ContextQuality, name: str) -> dict[str, float | None]:
    measure = next(m for m in quality.measures if m.name == name)
    return {"score": measure.score, **{f.name: f.value for f in measure.factors}}


def _kinds(quality: ContextQuality) -> dict[str, str]:
    return {gap.kind: gap.severity for gap in quality.gaps}


# ── strong evidence ─────────────────────────────────────────────────────────


def test_a_context_that_holds_what_it_needs_well_said_and_current_is_high() -> None:
    quality = _judge()

    assert (quality.level, quality.capped, quality.version) == ("high", None, 1)
    assert quality.score is not None and quality.score >= 0.85
    assert _measure(quality, "completeness") == {
        "score": 1.0,
        "start": 1.0,
        "facets": 1.0,
        "retrieval": 1.0,
        "knowledge": 1.0,
        "budget": 1.0,
    }
    freshness = _measure(quality, "freshness")
    assert (freshness["model"], freshness["evidence"], freshness["sources"]) == (1.0, 1.0, 1.0)
    confidence = _measure(quality, "confidence")
    assert (confidence["corroboration"], confidence["stated"], confidence["consistency"]) == (
        1.0,
        1.0,
        1.0,
    )
    assert quality.gaps == []
    assert quality.conflicts == []
    support = quality.support
    assert (support.entities, support.sources, support.events, support.corroborated) == (
        4,
        3,
        1,
        4,
    )
    # Each factor names what it was read from.
    start = next(f for f in quality.measures[0].factors if f.name == "start")
    assert start.refs == [BILLING.entity.id]
    facets = next(f for f in quality.measures[0].factors if f.name == "facets")
    assert facets.detail["covered"] == ["technical", "organizational"]


def test_the_same_context_is_judged_the_same_and_what_nothing_measures_is_unknown() -> None:
    assert _judge() == _judge()

    # roots=None means, here, "read" — the profile left out, never guessed.
    unread = assess(
        _built().elements,
        request=_request(),
        retrieval=[],
        ranking=None,
        conflicts=[],
        plan=None,
        model_built_at=NOW,
        assembled_at=NOW,
        roots=None,
        assessed="read",
    )
    completeness = _measure(unread, "completeness")
    assert (completeness["knowledge"], completeness["retrieval"]) == (None, None)
    assert unread.assessed == "read"
    assert unread.score is not None


# ── what the model does not know of what is asked ───────────────────────────


def test_no_owner_known_is_a_gap_critical_when_that_is_the_question() -> None:
    nobody = RootProfile(
        entity_id=BILLING.entity.id,
        name="Billing API",
        type="service",
        owner=False,
        documented=True,
        watched=False,
    )
    built = _built([BILLING, RUNBOOK, INCIDENT], TIES[1:])

    asked = _judge(built, roots=[nobody])
    # Nobody tied to it: no organizational side either.
    assert _kinds(asked) == {
        "no_owner": "warning",
        "facet_missing": "warning",
        "unwatched": "info",
    }
    assert _measure(asked, "completeness")["knowledge"] == round(1 / 3, 4)
    no_owner = next(g for g in asked.gaps if g.kind == "no_owner")
    assert (no_owner.refs, no_owner.measure, no_owner.origin) == (
        [BILLING.entity.id],
        "completeness",
        "quality",
    )
    assert asked.capped is None

    who = _judge(built, roots=[nobody], plan=_plan("ownership"))
    assert _kinds(who)["no_owner"] == "critical"
    assert (who.level, who.capped, who.score) == ("low", "critical_gap", CAP_GAP)
    # No organizational side either: the intention calls for one.
    assert _kinds(who)["facet_missing"] == "warning"

    why = _judge(built, roots=[nobody], plan=_plan("diagnose"))
    assert _kinds(why)["unwatched"] == "warning"


# ── stale ───────────────────────────────────────────────────────────────────


def test_a_model_and_evidence_gone_stale_and_a_source_failing_lower_freshness() -> None:
    old = _entity(
        "Billing API",
        EntityType.SERVICE,
        0,
        provenance=_said_by(CATALOGUE),
        seen=NOW - timedelta(days=120),
    )
    failing = [
        MaterialSource(
            source_id=CATALOGUE, kind="backstage", name="Catalogue", status="error", health=None
        )
    ]
    quality = _judge(
        _built([old], [], sources=failing), built_at=NOW - timedelta(days=10), roots=[]
    )

    freshness = _measure(quality, "freshness")
    assert freshness["model"] == round(0.5 ** (9 / 7), 4)
    assert freshness["evidence"] is not None and freshness["evidence"] < 0.1
    assert freshness["sources"] == 0.3
    assert _kinds(quality) == {
        "model_stale": "warning",
        "stale_evidence": "warning",
        "source_unhealthy": "warning",
        "facet_missing": "warning",
    }
    stale = next(g for g in quality.gaps if g.kind == "stale_evidence")
    assert stale.refs == [old.entity.id]


# ── incomplete ──────────────────────────────────────────────────────────────


def test_a_retriever_failed_and_relevant_things_left_for_the_budget_are_said() -> None:
    built = _built()
    assert built.ranking is not None
    cut = Assembly(
        elements=built.elements,
        dropped=6,
        truncated=True,
        summary=built.summary,
        fingerprint=built.fingerprint,
        ranking=built.ranking.model_copy(
            update={
                "left": [
                    LeftOutRead(
                        ref_id=uuid.uuid4(),
                        ref_type="service",
                        label=f"Service {i}",
                        reason="budget",
                        score=0.7,
                        said="Left for the budget.",
                    )
                    for i in range(6)
                ]
            }
        ),
        conflicts=[],
    )
    failed = [
        *RUNS,
        RetrieverRunRead(
            retriever="content",
            version=1,
            status="failed",
            found=0,
            ms=5,
            detail=None,
            error="ProgrammingError",
        ),
    ]
    quality = _judge(cut, runs=failed, request=_request(limit=4))

    completeness = _measure(quality, "completeness")
    assert completeness["retrieval"] == 0.75
    assert completeness["budget"] == round(4 / 10, 4)
    assert _kinds(quality) == {"retriever_failed": "warning", "budget_cut": "warning"}
    budget = next(g for g in quality.gaps if g.kind == "budget_cut")
    assert budget.detail["count"] == 6
    assert "widen it" in budget.said
    content = next(y for y in quality.retrieval if y.retriever == "content")
    assert (content.status, content.kept) == ("failed", 0)


# ── what it disagrees on, and how badly ─────────────────────────────────────


def test_a_disagreement_on_what_decides_an_answer_about_what_was_asked_is_critical() -> None:
    disputed = _entity(
        "Billing API",
        EntityType.SERVICE,
        0,
        confidence=0.95,
        provenance=_said_by(
            CATALOGUE,
            PAGER,
            conflicts=[
                {
                    "attribute": "sla",
                    "chosen": "99.95",
                    "values": [
                        {"value": "99.95", "source_id": str(CATALOGUE)},
                        {"value": "99.9", "source_id": str(PAGER)},
                    ],
                }
            ],
        ),
    )
    language = _entity(
        "Payments",
        EntityType.TEAM,
        1,
        provenance=_said_by(
            CATALOGUE,
            HR,
            conflicts=[
                {
                    "attribute": "slack_channel",
                    "values": [
                        {"value": "#payments", "source_id": str(CATALOGUE)},
                        {"value": "#pay", "source_id": str(HR)},
                    ],
                }
            ],
        ),
    )
    quality = _judge(_built([disputed, language, RUNBOOK, INCIDENT], TIES))

    assert [(c.about, c.severity) for c in quality.conflicts] == [
        ("sla", "critical"),
        ("slack_channel", "info"),
    ]
    critical = quality.conflicts[0]
    assert critical.refs == [BILLING.entity.id]
    assert "an answer turns on it" in critical.why
    assert (quality.level, quality.capped, quality.score) == (
        "medium",
        "critical_conflict",
        CAP_CONFLICT,
    )
    assert (quality.support.conflicts, quality.support.critical) == (2, 1)
    assert _measure(quality, "confidence")["consistency"] < 1.0  # type: ignore[operator]


def test_two_owners_of_what_was_asked_are_critical_elsewhere_a_warning() -> None:
    finance = _entity("Finance", EntityType.TEAM, 1, provenance=_said_by(HR, CATALOGUE))
    quality = _judge(
        _built([*STRONG, finance], [*TIES, _tie(finance, BILLING, RelationshipType.OWNS)])
    )
    [competing] = quality.conflicts
    assert (competing.kind, competing.about, competing.severity) == (
        "competing",
        "owner",
        "critical",
    )

    other = _judge(
        _built([*STRONG, finance], [*TIES, _tie(finance, BILLING, RelationshipType.OWNS)]),
        request=_request(roots=[str(PAYMENTS.entity.id)]),
    )
    assert other.conflicts[0].severity == "critical"  # Billing's owner is Payments, a root
    elsewhere = _judge(
        _built([*STRONG, finance], [*TIES, _tie(finance, BILLING, RelationshipType.OWNS)]),
        request=_request(roots=[str(RUNBOOK.entity.id)]),
    )
    assert elsewhere.conflicts[0].severity == "warning"


# ── nothing ─────────────────────────────────────────────────────────────────


def test_nothing_found_is_low_and_says_so() -> None:
    quality = _judge(Assembly([], 0, False, _built().summary, ""), runs=[], roots=[])

    assert quality.level == "low"
    assert _kinds(quality) == {"nothing_found": "critical"}
    assert _measure(quality, "completeness")["start"] == 0.0


# ── what each retriever brought ─────────────────────────────────────────────


def test_what_each_retriever_brought_is_counted() -> None:
    built = _built()
    found = [
        replace(
            element,
            reason=element.reason.model_copy(
                update={
                    "retrievers": [
                        RetrievalMatch(retriever="search", rank=1, score=1.0, detail=None),
                        *(
                            [RetrievalMatch(retriever="timeline", rank=1, score=1.0, detail=None)]
                            if element.ref_type == "incident"
                            else []
                        ),
                    ]
                }
            ),
        )
        for element in built.elements
    ]
    quality = _judge(Assembly(found, 0, False, built.summary, built.fingerprint, built.ranking, []))
    yields = {y.retriever: (y.found, y.kept, y.only, y.top) for y in quality.retrieval}
    assert yields["search"] == (4, len(found), len(found) - 1, 4)
    assert yields["timeline"] == (4, 1, 0, 1)
    assert yields["graph"] == (4, 0, 0, 0)
