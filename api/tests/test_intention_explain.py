"""On what an analysis rests (LEKA-441), pure — the ticket's scenarios,
each with what goes in, what it rests on, how sure it must be, what must
never be said, and what is shown (docs/intentions.md § 12 ter).

What these protect:
- several sources really agreeing: sure, and said why;
- a source failing, a capability that did not answer: never shown read,
  the result partial, what that leaves unknown said, never sure;
- sources disagreeing on what it asks: said, every side, settled first;
- a source out of date: said, never sure;
- a change tied to an incident by time alone: a correlation, never called
  a cause, never sure, confirmed before anything is undone;
- a recommendation that cannot be carried out as it stands: what it needs,
  said, prepared before deciding — no version to go back to invented;
- an analysis finished before a source did: partial, never complete,
  analysed again once it has synced;
- a figure nothing counts is not said: no people reached without a source
  stating how many;
- an analysis that could not run: no confidence at all.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from leka.intentions.analysis import (
    Answer,
    Asked,
    Cause,
    Evidence,
    Point,
    Result,
    SourceRef,
    Statement,
    StepOutcome,
    Subject,
)
from leka.intentions.explain import ContextRead, SourceState, explain
from leka.intentions.recommend import recommend
from leka.intentions.schemas import AnalysisExplanation, IntentionAnalysisResult
from leka.knowledge import ChangeFootprint, EntityBrief, EntityType

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
PAYMENT = Subject(uuid.uuid5(uuid.NAMESPACE_URL, "payment-api"), "payment-api", "service")
GITHUB = SourceRef(uuid.uuid5(uuid.NAMESPACE_URL, "github"), "github", "acme/backend")
JIRA = SourceRef(uuid.uuid5(uuid.NAMESPACE_URL, "jira"), "jira", "OPS board")
DATADOG = SourceRef(uuid.uuid5(uuid.NAMESPACE_URL, "datadog"), "datadog", "production")
DEPLOYMENT = uuid.uuid5(uuid.NAMESPACE_URL, "payment-api v2.8.4")
WELL = SourceState("active", "idle", "healthy", NOW - timedelta(hours=2))


def asked(text: str = "Pourquoi payment-api est lente ?", **fields: object) -> Asked:
    said: dict[str, object] = {
        "id": uuid.uuid4(),
        "text": text,
        "mode": "question",
        "kind": "diagnose",
        "goal": "explain_cause",
        "subjects": (PAYMENT,),
        "since": NOW - timedelta(days=2),
        "until": NOW,
        **fields,
    }
    return Asked(**said)  # type: ignore[arg-type]


def evidence(key: str, *sources: SourceRef) -> Evidence:
    return Evidence(id=key, kind="event", label=key, sources=sources)


def incident_seen(*sources: SourceRef) -> tuple[str, Statement]:
    return (
        "incidents",
        Statement(
            "incident:1",
            "incident.seen",
            "payment-api p99 above 2s, sev2.",
            {"name": "p99 above 2s"},
            ("e:incident",),
        ),
    )


def cause(basis: str = "stated", confidence: float = 0.9) -> tuple[str, Cause]:
    return (
        "incidents",
        Cause(
            id=f"cause:{DEPLOYMENT}",
            code="cause.said" if basis == "stated" else "cause.changed_before",
            label="payment-api v2.8.4",
            basis=basis,
            why="Its source says so." if basis == "stated" else "It came 26 hours before.",
            confidence=confidence,
            ref_type="deployment",
            ref_id=DEPLOYMENT,
            params={"incident": "p99 above 2s"},
            evidence=("e:deployment", "e:incident"),
        ),
    )


def result(
    *,
    causes: tuple[tuple[str, Cause], ...] = (),
    sources: tuple[SourceRef, ...] = (GITHUB, JIRA),
    status: str = "complete",
    confidence: float | None = 0.9,
) -> Result:
    return Result(
        status=status,
        summary=(),
        findings=(incident_seen(),) if status != "failed" else (),
        causes=causes,
        impact=(),
        risk="medium",
        risk_basis=None,
        uncertainties=(),
        missing=(),
        confidence=confidence,
        support=(),
        evidence=(
            evidence("e:incident", *sources[1:] or sources),
            evidence("e:deployment", sources[0]),
        ),
    )


def ran(*failed: str) -> list[StepOutcome]:
    names = ("standing", "changes", "incidents")
    return [
        StepOutcome(n, 1, "failed" if n in failed else "succeeded", error="RuntimeError")
        if n in failed
        else StepOutcome(n, 1, "succeeded")
        for n in names
    ]


def context(*sources: SourceRef, conflicts: tuple[dict[str, object], ...] = ()) -> ContextRead:
    return ContextRead(
        version=3,
        sources=[(s.id, s.kind, s.name, 4) for s in sources if s.id is not None],
        conflicts=list(conflicts),
    )


def explained(
    found: Result,
    *,
    question: Asked | None = None,
    read: ContextRead | None = None,
    states: dict[uuid.UUID, SourceState] | None = None,
    outcomes: list[StepOutcome] | None = None,
    readiness: str = "ready",
) -> tuple[Result, AnalysisExplanation]:
    question = question or asked()
    read = read or context(GITHUB, JIRA)
    found = replace(found, recommendations=recommend(found, question))
    return explain(
        found,
        question,
        None,
        outcomes if outcomes is not None else ran(),
        context=read,
        states=states if states is not None else {s: WELL for s, *_ in read.sources},
        readiness=readiness,
        now=NOW,
        background=("standing",),
    )


def reasons(explanation: AnalysisExplanation) -> list[str]:
    return [r.code for r in explanation.confidence.reasons]


def claim(explanation: AnalysisExplanation, code: str) -> int | None:
    return next((c.count for c in explanation.claims if c.code == code), None)


# ── the scenarios ────────────────────────────────────────────────────────────


def test_several_sources_really_agreeing_make_it_sure_and_say_why() -> None:
    held, said = explained(result(causes=(cause("stated"),)))
    assert held.status == "complete"
    assert said.confidence.level == "high"
    assert reasons(said) == ["confidence.cause_confirmed"]
    assert claim(said, "sources") == 2
    assert claim(said, "contradictions") == 0
    assert [s.state for s in said.consulted] == ["read", "read"]
    # The figure kept beside the words never says more than they do.
    assert held.confidence == 0.9


def test_a_source_failing_or_a_capability_silent_is_never_shown_read() -> None:
    held, said = explained(
        result(causes=(cause("stated"),)),
        states={
            GITHUB.id: WELL,  # type: ignore[dict-item]
            JIRA.id: SourceState("error", "failed", "unhealthy", NOW - timedelta(days=3)),  # type: ignore[dict-item]
        },
        outcomes=ran("changes"),
    )
    by_name = {s.name: s.state for s in said.consulted}
    assert by_name == {"acme/backend": "read", "OPS board": "error"}
    assert held.status == "partial"
    assert "analysis.sources_pending" in {n.code for n in held.missing}
    assert said.confidence.level == "medium"
    assert {"confidence.capability_failed", "confidence.sources_unsure"} <= set(reasons(said))
    [silent] = [c for c in said.capabilities if c.status != "succeeded"]
    assert silent.leaves is not None and "cause may be missing" in silent.leaves.text
    assert {"limit.capability.changes", "limit.source_error"} <= {n.code for n in said.limits}
    assert held.confidence is not None and held.confidence <= 0.84


def test_sources_disagreeing_on_what_it_asks_are_said_and_settled_first() -> None:
    sla: dict[str, object] = {
        "id": "conflict:sla",
        "kind": "attribute",
        "subject": str(PAYMENT.id),
        "label": "payment-api",
        "about": "sla",
        "values": [
            {"value": "99.95", "by": ["acme/backend"]},
            {"value": "99.9", "by": ["OPS board"]},
        ],
        "said": "acme/backend says 99.95, OPS board 99.9.",
    }
    elsewhere: dict[str, object] = {
        **sla,
        "id": "conflict:email",
        "subject": str(uuid.uuid4()),
        "about": "email",
    }
    question = asked("Quel est le SLA de payment-api ?", goal="find_knowledge", kind="general")
    _, said = explained(
        result(), question=question, read=context(GITHUB, JIRA, conflicts=(sla, elsewhere))
    )
    # What they disagree on about something else does not weigh on it.
    assert [c.id for c in said.conflicts] == ["conflict:sla"]
    [conflict] = said.conflicts
    assert [v["value"] for v in conflict.values] == ["99.95", "99.9"]
    assert claim(said, "contradictions") == 1
    assert said.confidence.level == "medium"
    assert said.next.code == "settle_conflict"


def test_a_source_out_of_date_is_said_and_never_sure() -> None:
    old = SourceState("active", "idle", "healthy", NOW - timedelta(days=30))
    held, said = explained(
        result(causes=(cause("stated"),)),
        states={GITHUB.id: WELL, JIRA.id: old},  # type: ignore[dict-item]
    )
    assert {s.name: s.state for s in said.consulted}["OPS board"] == "stale"
    assert [n.code for n in said.stale] == ["stale.source"]
    assert said.confidence.level == "medium"
    # Out of date is not failing: complete, said what may be old.
    assert held.status == "complete"


def test_a_change_tied_by_time_alone_is_a_correlation_never_a_cause() -> None:
    held, said = explained(result(causes=(cause("inferred", 0.55),)))
    assert said.confidence.level == "low"
    assert reasons(said) == ["confidence.cause_correlated"]
    assert claim(said, "correlated_events") == 1
    # Confirmed before anything is undone: never surer than a correlation.
    assert [r.code for r in held.recommendations][:1] == ["recommend.confirm_cause"]
    assert said.next.code == "confirm_cause"
    assert held.confidence is not None and held.confidence <= 0.59


def test_a_recommendation_that_cannot_be_carried_out_says_what_it_needs() -> None:
    held, said = explained(result(causes=(cause("stated"),)))
    [rollback] = [r for r in held.recommendations if r.code == "recommend.rollback"]
    assert not rollback.executable
    unmet = {p.code for p in rollback.preconditions if p.blocking and not p.met}
    # No version to go back to is invented: none of its sources says it.
    assert unmet == {"precondition.version_to_restore", "precondition.environment"}
    assert said.next.code == "prepare"
    assert "precondition.version_to_restore" in said.next.why.params["preconditions"]  # type: ignore[operator]
    # Said where and to what, it can be.
    footprint = ChangeFootprint(
        change=EntityBrief(
            id=DEPLOYMENT,
            type=EntityType.DEPLOYMENT,
            key="deploy",
            name="payment-api v2.8.4",
            lifecycle="active",
        ),
        kind="deployment",
        at=NOW - timedelta(hours=26),
        state="succeeded",
        environment="production",
        details={"version": "2.8.4", "previous_version": "2.8.3"},
        sources=["github"],
        source_ids=[str(GITHUB.id)],
        touched=[],
        reached=[],
        applications=[],
        capabilities=[],
        processes=[],
        incidents=[],
    )
    [ready] = [
        r
        for r in recommend(result(causes=(cause("stated"),)), asked(), [footprint])
        if r.code == "recommend.rollback"
    ]
    assert ready.executable
    assert ready.preconditions[0].params["version"] == "2.8.3"


def test_an_analysis_finished_before_a_source_did_is_partial() -> None:
    syncing = SourceState("active", "running", "healthy", NOW - timedelta(hours=1))
    held, said = explained(
        result(causes=(cause("stated"),)),
        states={GITHUB.id: WELL, JIRA.id: syncing},  # type: ignore[dict-item]
    )
    assert held.status == "partial"
    assert {s.name: s.state for s in said.consulted}["OPS board"] == "syncing"
    assert said.next.code == "rerun"
    assert "OPS board" in said.next.text


def test_a_figure_nothing_counts_is_not_said() -> None:
    _, said = explained(result(causes=(cause("stated"),)))
    assert "impacted_users" not in {c.code for c in said.claims}
    stated = replace(
        result(causes=(cause("stated"),)),
        findings=(
            (
                "incidents",
                Statement("incident:1", "incident.seen", "…", {"impacted_users": 2400}, ()),
            ),
        ),
    )
    _, counted = explained(stated)
    assert claim(counted, "impacted_users") == 2400


def test_an_answer_resting_on_what_a_model_read_counts_its_sources() -> None:
    # 2026-10-14: « 0 source à l'appui » — GitHub read by the analyst, its
    # files cited by the answer, nothing found by the rules.
    read = evidence("e:file", GITHUB)
    bare = replace(result(), findings=(), evidence=(read,))
    _, nothing = explained(bare)
    assert claim(nothing, "sources") == 0
    answered = replace(
        bare,
        answer=Answer(
            text="auth-service is maintained by Sara.",
            points=(Point("CODEOWNERS names her.", ("e:file",)),),
            caveats=(),
            provider="google",
            model="gemini",
            version="1",
        ),
    )
    _, said = explained(answered)
    assert claim(said, "sources") == 1


def test_an_analysis_that_could_not_run_has_no_confidence() -> None:
    held, said = explained(
        result(status="failed", confidence=None), outcomes=ran("standing", "changes", "incidents")
    )
    assert said.confidence.level == "unknown"
    assert held.confidence is None
    assert said.next.code == "rerun"


def test_what_it_understood_is_said_with_what_it_does_not_know() -> None:
    stranger = asked(
        "Pourquoi billing-gateway est en panne ?", subjects=(), unknown=("billing-gateway",)
    )
    _, said = explained(result(), question=stranger, read=context())
    assert "billing-gateway" in said.understood.text
    assert said.understood.params["unknown"] == ["billing-gateway"]
    assert said.confidence.level == "low"
    assert said.next.code == "ask_differently"


def test_a_result_made_before_reads_without_what_it_rests_on() -> None:
    """Kept before LEKA-441: no explanation, no strength, no preconditions —
    read as it was, never invented after the fact."""
    old = IntentionAnalysisResult.model_validate(
        {
            "status": "complete",
            "summary": [],
            "findings": [],
            "causes": [
                {
                    "id": "c",
                    "capability": "incidents",
                    "code": "cause.said",
                    "label": "v2.8.4",
                    "basis": "stated",
                    "why": "…",
                    "confidence": 0.9,
                    "ref_type": None,
                    "ref_id": None,
                    "params": {},
                    "evidence": [],
                }
            ],
            "impact": [],
            "risk": "unknown",
            "risk_basis": None,
            "uncertainties": [],
            "missing": [],
            "confidence": 0.9,
            "support": [],
            "evidence": [],
        }
    )
    assert old.explanation is None
    assert old.causes[0].strength is None
