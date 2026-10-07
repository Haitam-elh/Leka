"""An intention's analysis (LEKA-388): pure, no database.

What these protect: the capabilities an intention's goal and kind call
for are chosen — the standing of what it is about always — and every
other one is said not called; an agent waits for a model. Each runs
isolated: one that raises is failed, one over its budget timed out, one
missing what it reads skipped — the others go on. The result says how it
went — complete, partial, inconclusive, failed — every piece of evidence
once, how sure (less on a limited context), and on what.

And each capability, on a hand-made company: who owns it, with the record
that says so; what relies on it and what that reaches — the business
makes it high; an incident's cause said by its source before one only
suspected, a change just before it a probable cause; a change followed by
an incident; the documents describing it, a stale one said; what a thing
should have, checked; a migration without where to; an action on systems,
said to wait for a person, with what it reaches and its constraints.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from leka.context import ContextElementRead
from leka.intentions.analysis import (
    Asked,
    Capability,
    FindingBrief,
    Material,
    Output,
    Part,
    Statement,
    StepOutcome,
    Subject,
    assemble,
    execute,
    select,
)
from leka.intentions.capabilities import (
    CAPABILITIES,
    action,
    changes,
    compliance,
    dependencies,
    documentation,
    incidents,
    migration,
    ownership,
    standing,
)
from leka.intentions.grounding import side
from leka.knowledge import (
    BusinessTie,
    ChangeFootprint,
    ChangeIncident,
    ChangeTouch,
    Dependencies,
    DependencyNode,
    EntityBrief,
    EntityStanding,
    EntityType,
    Impact,
    IncidentDetail,
    Lifecycle,
    Responsibility,
    Tie,
)
from leka.knowledge.schemas import TimelineEvent

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
SOURCE = uuid.uuid4()


def brief(name: str, kind: str = "service") -> EntityBrief:
    return EntityBrief(
        id=uuid.uuid4(), type=EntityType(kind), key=f"{kind}:{name}", name=name, lifecycle="active"
    )


PAYMENT = brief("payment-api")
PAYMENTS = brief("Payments", "team")
NADIA = brief("Nadia", "person")
CHECKOUT = brief("checkout")
SHOP = brief("Shop", "application")
INVOICING = brief("Invoicing", "business_capability")
DEPLOY = brief("payment-api v2.8.4", "deployment")
INCIDENT = brief("p99 above 2s", "incident")
RUNBOOK = brief("Payment API runbook", "document")


def subject(thing: EntityBrief = PAYMENT) -> Subject:
    return Subject(thing.id, thing.name, thing.type.value, "active")


def asked(goal: str, kind: str = "general", **fields: Any) -> Asked:
    said: dict[str, Any] = {
        "id": uuid.uuid4(),
        "text": "…",
        "mode": "question",
        "kind": kind,
        "goal": goal,
        "subjects": (subject(),),
        "since": NOW - timedelta(days=7),
        "until": NOW,
        **fields,
    }
    return Asked(**said)


def element(kind: str, **fields: Any) -> ContextElementRead:
    """A context element, as the context engine gives it."""
    base: dict[str, Any] = {
        "position": 0,
        "kind": kind,
        "ref_id": str(uuid.uuid4()),
        "ref_type": "service",
        "label": "x",
        "entity": None,
        "relationship": None,
        "provenance": {
            "origin": "stated",
            "rule": "stated",
            "confidence": 1.0,
            "sources": [
                {
                    "source_id": str(SOURCE),
                    "kind": "github",
                    "name": "acme/backend",
                    "key": None,
                    "record_id": "rec-42",
                }
            ],
            "evidence": ["CODEOWNERS says so"],
            "inferred_from": [],
            "attributes": {},
            "conflicts": [],
            "first_seen_at": None,
            "last_seen_at": None,
            "changed_at": None,
        },
        "reason": {"strategy": "graph", "role": "root", "depth": 0, "root": None, "via": None},
        "relevance": 1.0,
        "text": "x",
        **fields,
    }
    return ContextElementRead.model_validate(base)


def tie_element(start: EntityBrief, kind: str, end: EntityBrief) -> ContextElementRead:
    def end_of(thing: EntityBrief) -> dict[str, Any]:
        return {"id": str(thing.id), "type": thing.type.value, "key": thing.key, "name": thing.name}

    return element(
        "relationship",
        ref_type=kind,
        label=f"{start.name} {kind} {end.name}",
        relationship={
            "type": kind,
            "start": end_of(start),
            "end": end_of(end),
            "confidence": 1.0,
            "origin": "stated",
            "rule": "stated",
            "cross_source": False,
            "attributes": {},
        },
    )


def material(goal: str = "investigate", **fields: Any) -> Material:
    said: dict[str, Any] = {
        "asked": fields.pop("asked", asked(goal)),
        "now": NOW,
        "readiness": "ready",
        "parts": frozenset(Part),
        **fields,
    }
    return Material(**said)


def nodes(*things: EntityBrief, critical: str | None = None) -> Dependencies:
    return Dependencies(
        root=PAYMENT,
        direction="upstream",
        environment=None,
        depth=2,
        nodes=[DependencyNode(entity=t, depth=1, criticality=critical) for t in things],
        relationships=[],
        truncated=False,
    )


# ── choosing ─────────────────────────────────────────────────────────────────


def chosen(goal: str, kind: str = "general", **fields: Any) -> set[str]:
    return {c.name for c in select(asked(goal, kind, **fields), CAPABILITIES) if c.chosen}


def test_what_its_goal_and_kind_call_for_and_its_standing_always() -> None:
    assert chosen("find_owner") == {"standing", "ownership"}
    assert chosen("explain_cause", "diagnose") == {"standing", "incidents", "changes"}
    assert chosen("assess_impact", "dependency") == {"standing", "dependencies"}
    assert chosen("check_compliance", "compliance") == {"standing", "documentation", "compliance"}
    assert chosen("plan_migration", "migration") == {"standing", "dependencies", "migration"}
    # An action on systems: what it reaches, who owns it, what changed.
    assert chosen("act", actions=(("restart", True),)) == {
        "standing",
        "ownership",
        "changes",
        "action",
    }
    every = select(asked("find_owner"), CAPABILITIES)
    assert {c.name: c.reason for c in every}["incidents"] == "not_called"
    assert {c.name: c.reason for c in every}["standing"] == "always"


def test_an_agent_waits_for_a_model() -> None:
    agent = Capability(
        "correlate-deploy-with-latency",
        1,
        "An agent.",
        goals=frozenset({"explain_cause"}),
        method="model",
    )
    [choice] = select(asked("explain_cause"), [agent])
    assert (choice.chosen, choice.reason) == (False, "no_model")
    [ran] = select(asked("explain_cause"), [agent], model=True)
    assert ran.chosen


# ── running ──────────────────────────────────────────────────────────────────


def _boom(_: Material) -> Output:
    raise RuntimeError("boom")


def _slow(_: Material) -> Output:
    time.sleep(0.5)
    return Output()


def test_each_runs_isolated_and_is_said_how_it_went() -> None:
    caps = {
        "boom": Capability("boom", 1, ".", goals=frozenset(), run=_boom),
        "slow": Capability("slow", 1, ".", goals=frozenset(), run=_slow, budget=0.05),
        "blind": Capability(
            "blind", 1, ".", goals=frozenset(), run=standing, reads=frozenset({Part.QUALITY})
        ),
        "fine": Capability("fine", 1, ".", goals=frozenset(), run=standing),
    }
    thin = material(parts=frozenset({Part.STANDING}))

    async def run() -> dict[str, StepOutcome]:
        return {name: await execute(c, thin) for name, c in caps.items()}

    outcomes = asyncio.run(run())
    assert (outcomes["boom"].status, outcomes["boom"].error) == ("failed", "RuntimeError")
    assert (outcomes["slow"].status, outcomes["slow"].error) == ("timed_out", "TimeoutError")
    assert (outcomes["blind"].status, outcomes["blind"].reason) == ("skipped", "no_material")
    assert outcomes["fine"].status == "succeeded"

    result = assemble(
        list(outcomes.values()),
        readiness="limited",
        sources=2,
        contradictions=1,
        context_level="medium",
    )
    assert result.status == "partial"
    assert {n.code for n in result.missing} == {"capability.failed", "capability.timed_out"}
    # Read from a limited context: a little less sure.
    assert result.confidence is not None and result.confidence < 0.8
    support = {n.code: n.params["established"] for n in result.support}
    assert support == {
        "support.sources": True,
        "support.contradictions": False,
        "support.context": False,
    }


def test_nothing_that_ran_is_failed_and_nothing_found_inconclusive() -> None:
    failed = StepOutcome("x", 1, "failed", error="KeyError")
    assert (
        assemble(
            [failed], readiness="ready", sources=0, contradictions=0, context_level=None
        ).status
        == "failed"
    )
    empty = StepOutcome("x", 1, "succeeded", output=Output())
    assert (
        assemble([empty], readiness="ready", sources=0, contradictions=0, context_level=None).status
        == "inconclusive"
    )
    # What sets the scene does not answer: the thing's state alone, when
    # what was asked about found nothing, concludes nothing.
    scene = StepOutcome(
        "standing",
        1,
        "succeeded",
        output=Output(findings=(Statement("s", "standing.state", "It is active."),)),
    )

    def judged(*outcomes: StepOutcome) -> str:
        return assemble(
            outcomes,
            readiness="ready",
            sources=1,
            contradictions=0,
            context_level="high",
            background=frozenset({"standing"}),
        ).status

    assert judged(scene, empty) == "inconclusive"
    # Asked about nothing else, it is the answer.
    assert judged(scene) == "complete"


# ── each capability ──────────────────────────────────────────────────────────


def test_the_owner_with_the_record_that_says_so() -> None:
    said = material(
        "find_owner",
        elements=(tie_element(PAYMENT, "owned_by", PAYMENTS),),
        owners={PAYMENT.id: (PAYMENTS,)},
        responsibility={
            PAYMENT.id: Responsibility(
                entity=PAYMENT,
                owners=[],
                leads=[NADIA],
                maintainers=[
                    Tie(entity=NADIA, origin="inferred", rule="works_with", confidence=0.7)
                ],
                experts=[],
                escalation_policy="payments-oncall",
            )
        },
    )
    out = ownership(said)

    codes = [f.code for f in out.findings]
    assert codes == [
        "ownership.owner",
        "ownership.maintainers",
        "ownership.leads",
        "ownership.escalation",
    ]
    owner = out.findings[0]
    assert owner.params["owners"] == ["Payments"]
    [proof] = [e for e in out.evidence if e.id == owner.evidence[0]]
    # The context's word on it: GitHub, the record, a source's statement.
    assert (proof.kind, proof.records, proof.sources[0].kind) == ("record", ("rec-42",), "github")
    # Its ends, for the interface to word the tie in its language.
    assert proof.params == {"from": "payment-api", "to": "Payments"}
    assert out.summary is not None and out.summary.code == "ownership.summary"

    nobody = ownership(material("find_owner"))
    assert [n.code for n in nobody.uncertainties] == ["ownership.unknown"]
    assert nobody.confidence is None


def test_what_relies_on_it_and_what_that_reaches() -> None:
    out = dependencies(
        material(
            "assess_impact",
            upstream={PAYMENT.id: nodes(CHECKOUT)},
            downstream={},
            impact=Impact(
                affected=[PAYMENT],
                dependents=[CHECKOUT],
                applications=[SHOP],
                capabilities=[
                    BusinessTie(
                        entity=INVOICING,
                        relation="supported_by",
                        via=None,
                        path="direct",
                        origin="stated",
                        rule="stated",
                        confidence=1.0,
                    )
                ],
                processes=[],
            ),
        )
    )
    relied = out.findings[0]
    assert (relied.code, relied.params["names"]) == ("dependency.relied_on", ["checkout"])
    assert {a.code for a in out.impact} == {"dependents", "applications", "capabilities"}
    # The business relies on it: high.
    assert out.risk == "high"
    lonely = dependencies(material("map_dependencies"))
    assert [n.code for n in lonely.uncertainties] == ["dependency.none"]


def _incident(**fields: Any) -> IncidentDetail:
    said: dict[str, Any] = {
        "id": INCIDENT.id,
        "key": INCIDENT.key,
        "name": INCIDENT.name,
        "lifecycle": Lifecycle.ACTIVE,
        "url": None,
        "tools": ["jira"],
        "state": "closed",
        "priority": None,
        "severity": "sev2",
        "urgency": None,
        "opened_at": NOW - timedelta(hours=25),
        "acknowledged_at": None,
        "resolved_at": None,
        "time_to_acknowledge_minutes": None,
        "duration_minutes": 240,
        "affects": [PAYMENT],
        "commander": None,
        "assignees": [],
        "causes": [DEPLOY],
        "attributes": {},
        "provenance": {},
        "timeline": [],
        "affected": [Tie(entity=PAYMENT, origin="stated", rule="stated", confidence=1.0)],
        "people": [],
        "suspected_causes": [],
        "changed_before": [],
        "impact": Impact(
            affected=[PAYMENT],
            dependents=[CHECKOUT],
            applications=[],
            capabilities=[],
            processes=[],
        ),
        **fields,
    }
    return IncidentDetail.model_validate(said)


def test_an_incident_its_cause_said_before_one_suspected() -> None:
    hotfix = brief("hotfix", "change")
    out = incidents(
        material(
            "explain_cause",
            incidents=(
                _incident(
                    suspected_causes=[
                        Tie(entity=DEPLOY, origin="stated", rule="stated", confidence=0.83)
                    ],
                    changed_before=[
                        TimelineEvent(
                            entity=hotfix,
                            kind="change",
                            at=NOW - timedelta(hours=27),
                            state=None,
                            environment=None,
                            via=None,
                        )
                    ],
                ),
            ),
        )
    )
    assert [f.code for f in out.findings] == ["incident.seen"]
    said, suspected = out.causes
    assert (said.label, said.basis, said.code) == ("payment-api v2.8.4", "stated", "cause.said")
    # Two hours before it opened: a probable cause, to confirm.
    assert (suspected.label, suspected.basis, suspected.confidence) == ("hotfix", "inferred", 0.7)
    assert out.risk == "medium"  # sev2
    assert out.summary is not None and out.summary.params["cause"] == "payment-api v2.8.4"
    assert {a.code for a in out.impact} == {"dependents"}

    # Before the period: not this intention's.
    old = incidents(
        material("explain_cause", incidents=(_incident(opened_at=NOW - timedelta(days=30)),))
    )
    assert [n.code for n in old.uncertainties] == ["incident.none"]


def _footprint(**fields: Any) -> ChangeFootprint:
    said: dict[str, Any] = {
        "change": DEPLOY,
        "kind": "deployment",
        "at": NOW - timedelta(hours=26),
        "state": "succeeded",
        "environment": "production",
        "details": {},
        "sources": ["github"],
        "source_ids": [str(SOURCE)],
        "touched": [ChangeTouch(entity=PAYMENT, how="part_of", criticality=None)],
        "reached": [],
        "applications": [],
        "capabilities": [],
        "processes": [],
        "incidents": [
            ChangeIncident(
                entity=INCIDENT,
                opened_at=NOW - timedelta(hours=25),
                severity="sev2",
                state="closed",
                on=PAYMENT,
                stated=True,
            )
        ],
        **fields,
    }
    return ChangeFootprint.model_validate(said)


def test_a_change_and_the_incident_that_followed() -> None:
    out = changes(material("find_change", changes=(_footprint(),)))
    [made] = out.findings
    assert (made.code, made.params["incidents"], made.params["environment"]) == (
        "change.made",
        1,
        "production",
    )
    [cause] = out.causes
    assert (cause.code, cause.basis) == ("cause.said", "stated")
    assert [n.code for n in changes(material("find_change")).uncertainties] == ["change.none"]


def test_the_documents_describing_it_and_a_stale_one_said() -> None:
    doc = element(
        "entity",
        ref_id=str(RUNBOOK.id),
        ref_type="document",
        label=RUNBOOK.name,
        entity={
            "type": "document",
            "key": RUNBOOK.key,
            "name": RUNBOOK.name,
            "attributes": {"freshness": "stale"},
            "lifecycle": "active",
            "version": 1,
            "confidence": 1.0,
            "quality": None,
        },
    )
    held = EntityStanding(
        criticality=None,
        lifecycle=Lifecycle.ACTIVE,
        documents=1,
        fresh_documents=0,
        last_documented_at="2026-02-06",
        business=False,
    )
    out = documentation(
        material(
            "find_knowledge",
            elements=(doc, tie_element(RUNBOOK, "describes", PAYMENT)),
            standing={PAYMENT.id: held},
        )
    )
    [found] = out.findings
    assert found.params["documents"] == ["Payment API runbook"]
    assert [n.code for n in out.uncertainties] == ["documentation.stale"]


def test_what_a_service_should_have_checked() -> None:
    held = EntityStanding(
        criticality="high",
        lifecycle=Lifecycle.ACTIVE,
        documents=1,
        fresh_documents=0,
        last_documented_at=None,
        business=True,
    )
    serious = FindingBrief(
        uuid.uuid4(), "change.impact", "change", "high", "…", PAYMENT.id, PAYMENT.name, NOW
    )
    out = compliance(
        material(
            "check_compliance",
            standing={PAYMENT.id: held},
            owners={PAYMENT.id: (PAYMENTS,)},
            findings=(serious,),
        )
    )
    checks = {f.params["check"]: f.params["passed"] for f in out.findings}
    assert checks == {
        "owner": True,
        "documented": False,
        "criticality": True,
        "nothing_serious": False,
    }
    assert (out.risk, out.summary.params if out.summary else None) == (
        "medium",
        {"passed": 2, "checks": 4},
    )


def test_a_migration_without_where_to_is_missing_it() -> None:
    out = migration(material("plan_migration", upstream={PAYMENT.id: nodes(CHECKOUT)}))
    assert [n.code for n in out.missing] == ["migration.no_target"]
    target = migration(
        material(
            "plan_migration",
            asked=asked("plan_migration", constraints=(("target", "aurora", True),)),
        )
    )
    assert target.findings[0].params == {"target": "aurora"}


def test_an_action_waits_for_a_person_with_what_it_reaches() -> None:
    out = action(
        material(
            asked=asked(
                "act",
                mode="request",
                actions=(("restart", True), ("notify", False)),
                constraints=(("no_downtime", True, True), ("urgency", "high", False)),
            ),
            upstream={PAYMENT.id: nodes(CHECKOUT, SHOP, INVOICING)},
            changes=(_footprint(),),
        )
    )
    codes = [f.code for f in out.findings]
    assert codes == ["action.asked", "action.last_deployment", "action.reach", "action.constraint"]
    assert out.findings[0].params["action"] == "restart"
    # Only what is hard: urgency weighs, it is not a constraint.
    assert out.findings[-1].params["kind"] == "no_downtime"
    assert out.risk == "high"
    assert action(material(asked=asked("investigate"))) == Output()


def test_the_context_a_capability_receives_is_on_its_sides() -> None:
    held = material(
        elements=(
            element("entity", ref_type="incident"),
            element("entity", ref_type="team"),
            tie_element(PAYMENT, "owned_by", PAYMENTS),
        )
    )
    temporal = held.on(frozenset({"temporal"}), side)
    assert [e.ref_type for e in temporal.elements] == ["incident", "owned_by"]
    assert held.on(frozenset(), side) is held


def test_standing_says_the_state_and_what_leka_already_concluded() -> None:
    found = FindingBrief(
        uuid.uuid4(),
        "ownership.no_owner",
        "organisation",
        "high",
        "No owner.",
        PAYMENT.id,
        "payment-api",
        NOW,
        {"name": "payment-api", "dependents": 3},
    )
    out = standing(material(findings=(found,)))
    assert [f.code for f in out.findings] == ["standing.state", "standing.findings"]
    assert out.findings[1].params["high"] == 1
    assert [e.kind for e in out.evidence] == ["entity", "inference"]
    # What LEKA concluded, for the interface to word as Insights does.
    assert out.evidence[1].params == {
        "code": "ownership.no_owner",
        "params": {"name": "payment-api", "dependents": 3},
    }
    assert standing(material(asked=asked("investigate", subjects=()))).missing[0].code == (
        "analysis.no_subject"
    )
