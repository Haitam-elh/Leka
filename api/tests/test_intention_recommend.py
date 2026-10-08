"""What LEKA recommends (LEKA-389), pure — from what LEKA-388's own
capabilities find, run on the material its tests build.

What these protect: a recommendation is apart from the findings, said as a
proposal — what to do, why, how risky, whether it can be undone, how
urgent, how sure, never surer than what it follows from — and traceable:
every one names the findings and causes it follows from and the evidence
they rest on, all of it in the result; a change said to have caused an
incident proposed undone, one only suspected confirmed first; an incident
nothing explains, investigated; nobody owning, several owners, no current
document, a failed check — each its remedy; a reach of high risk, its
people told; an inconclusive analysis proposes asking differently, a
failed one nothing; changing systems is said, so a person decides.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from leka.intentions.analysis import Output, Result, StepOutcome, assemble
from leka.intentions.capabilities import compliance, documentation, incidents, ownership
from leka.intentions.recommend import as_mapping, recommend
from leka.intentions.schemas import AnalysisRecommendation
from leka.knowledge import EntityStanding, Lifecycle, Tie
from leka.knowledge.schemas import TimelineEvent
from tests.test_intention_analysis import (
    DEPLOY,
    NOW,
    PAYMENT,
    PAYMENTS,
    SHOP,
    _incident,
    asked,
    brief,
    material,
    subject,
)


def result_of(*outputs: tuple[str, Output], status: str | None = None) -> Result:
    found = assemble(
        [StepOutcome(name, 1, "succeeded", output=out) for name, out in outputs],
        readiness="ready",
        sources=2,
        contradictions=0,
        context_level="high",
    )
    return found if status is None else Result(**{**found.__dict__, "status": status})


def codes(result: Result, goal: str = "explain_cause") -> list[str]:
    return [r.code for r in recommend(result, asked(goal, subjects=(subject(),)))]


def traceable(result: Result) -> None:
    """Every recommendation names what it follows from, and its evidence,
    all in the result."""
    ids = {s.id for _, s in result.findings} | {c.id for _, c in result.causes}
    evidence = {e.id for e in result.evidence}
    for recommendation in recommend(result, asked("explain_cause", subjects=(subject(),))):
        assert set(recommendation.basis) <= ids, recommendation.code
        assert set(recommendation.evidence) <= evidence, recommendation.code
        # Kept as the contract says.
        AnalysisRecommendation.model_validate(as_mapping(recommendation))


# ── causes ─────────────────────────────────────────────────────────────────


def _incident_result(**fields: Any) -> Result:
    return result_of(
        ("incidents", incidents(material("explain_cause", incidents=(_incident(**fields),))))
    )


def test_a_change_said_to_have_caused_it_is_proposed_undone() -> None:
    result = _incident_result(
        suspected_causes=[Tie(entity=DEPLOY, origin="stated", rule="stated", confidence=0.83)]
    )
    [undo] = [
        r for r in recommend(result, asked("explain_cause")) if r.code == "recommend.rollback"
    ]
    assert (undo.action, undo.changes_systems, undo.reversible) == ("rollback", True, True)
    assert undo.priority == "high"
    # Never surer than the cause it follows from.
    assert undo.confidence == 0.83
    assert undo.target is not None and undo.target.name == "payment-api v2.8.4"
    assert undo.params["incident"] == "p99 above 2s"
    assert undo.basis == (f"cause:{DEPLOY.id}",)
    assert undo.why.code == "recommend.why.cause"
    assert "recommend.confirm_cause" not in codes(result)
    traceable(result)


def test_a_change_only_suspected_is_confirmed_first() -> None:
    hotfix = brief("hotfix", "change")
    result = _incident_result(
        changed_before=[
            TimelineEvent(
                entity=hotfix,
                kind="change",
                at=NOW - timedelta(hours=27),
                state=None,
                environment=None,
                via=None,
            )
        ]
    )
    found = {r.code: r for r in recommend(result, asked("explain_cause"))}
    assert set(found) == {"recommend.rollback", "recommend.confirm_cause"}
    # Confirming comes first; undoing is less sure than the suspicion.
    assert next(iter(found)) == "recommend.confirm_cause"
    assert found["recommend.rollback"].priority == "medium"
    assert found["recommend.rollback"].confidence == 0.56  # 0.7 x 0.8
    assert found["recommend.confirm_cause"].changes_systems is False
    traceable(result)


def test_an_incident_nothing_explains_is_proposed_investigated() -> None:
    result = _incident_result(causes=[])
    assert codes(result) == ["recommend.investigate"]
    [investigate] = recommend(result, asked("explain_cause"))
    assert (investigate.action, investigate.changes_systems) == ("monitor", False)


# ── what it found ──────────────────────────────────────────────────────────


def test_nobody_owning_it_or_several_owners_each_its_remedy() -> None:
    nobody = result_of(("ownership", ownership(material("find_owner"))))
    assert codes(nobody, "find_owner") == ["recommend.assign_owner"]
    [assign] = recommend(nobody, asked("find_owner", subjects=(subject(),)))
    assert assign.target is not None and assign.target.ref_id == PAYMENT.id
    traceable(nobody)

    several = result_of(
        (
            "ownership",
            ownership(
                material("find_owner", owners={PAYMENT.id: (PAYMENTS, brief("Billing", "team"))})
            ),
        )
    )
    assert "recommend.settle_owner" in codes(several, "find_owner")
    traceable(several)


def test_no_current_document_is_proposed_documented() -> None:
    held = EntityStanding(
        criticality=None,
        lifecycle=Lifecycle.ACTIVE,
        documents=1,
        fresh_documents=0,
        last_documented_at=None,
        business=True,
    )
    result = result_of(
        ("documentation", documentation(material("find_knowledge", standing={PAYMENT.id: held})))
    )
    assert codes(result, "find_knowledge") == ["recommend.update_documentation"]
    traceable(result)


def test_a_failed_check_proposes_its_remedy() -> None:
    held = EntityStanding(
        criticality=None,
        lifecycle=Lifecycle.ACTIVE,
        documents=0,
        fresh_documents=0,
        last_documented_at=None,
        business=True,
    )
    result = result_of(
        ("compliance", compliance(material("check_compliance", standing={PAYMENT.id: held})))
    )
    assert set(codes(result, "check_compliance")) >= {
        "recommend.assign_owner",
        "recommend.update_documentation",
        "recommend.set_criticality",
    }
    traceable(result)


def test_a_reach_of_high_risk_tells_its_people() -> None:
    result = _incident_result(
        severity="sev1",
        impact=_incident().impact.model_copy(update={"applications": [SHOP]}),
    )
    [notify] = [
        r for r in recommend(result, asked("explain_cause")) if r.code == "recommend.notify"
    ]
    assert notify.params["applications"] == ["Shop"]
    assert notify.priority == "high"
    assert notify.changes_systems is False


# ── when it could not conclude ─────────────────────────────────────────────


def test_inconclusive_proposes_asking_differently_failed_nothing() -> None:
    nothing = result_of(("ownership", Output()), status="inconclusive")
    assert codes(nothing) == ["recommend.ask_differently"]
    [ask] = recommend(nothing, asked("explain_cause"))
    assert ask.confidence is None
    assert recommend(result_of(("ownership", Output()), status="failed"), asked("x")) == ()


def test_recommendations_are_never_findings() -> None:
    """Kept apart in the result, said as proposals."""
    result = _incident_result(
        suspected_causes=[Tie(entity=DEPLOY, origin="stated", rule="stated", confidence=0.9)]
    )
    found = {s.code for _, s in result.findings}
    assert not any(code.startswith("recommend.") for code in found)
    assert all(r.code.startswith("recommend.") for r in recommend(result, asked("x")))
