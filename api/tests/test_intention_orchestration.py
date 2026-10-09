"""Capability orchestration (LEKA-399): the capabilities one intention calls
for, planned as one graph and run as one. Pure: no database.

What these protect:
- A plan in levels: what waits on nothing first, together; what reads
  another after it; what a model runs — the conclusion — last. A cycle is
  refused, said which.
- A level runs together: two slow capabilities take the time of one.
- A capability is handed what the ones it names produced — those only.
- A prerequisite that did not succeed: skipped, said which. Something it
  uses that did not succeed: run without it, said degraded. A failure with a
  fallback: the fallback in its place, said, and what follows reads it.
- LEKA's own capabilities hand on what they found: the incidents read the
  causes the changes of the period reach; an action reads who owns what it
  acts on, and what depends on it.
"""

from __future__ import annotations

import time

import pytest

from leka.intentions.analysis import Capability, Cause, Material, Output, Statement, assemble
from leka.intentions.capabilities import CAPABILITIES, action, incidents
from leka.intentions.grounding import side
from leka.intentions.orchestration import OrchestrationError, plan, run
from tests.test_intention_analysis import (
    DEPLOY,
    INCIDENT,
    _incident,
    asked,
    material,
)


def capability(name: str, run_: object = None, **fields: object) -> Capability:
    said: dict[str, object] = {
        "name": name,
        "version": 1,
        "summary": name,
        "goals": frozenset(),
        "run": run_ or (lambda m: Output(summary=None)),
        **fields,
    }
    return Capability(**said)  # type: ignore[arg-type]


def test_a_plan_in_levels_the_conclusion_last() -> None:
    chosen = [
        c
        for c in CAPABILITIES
        if c.name
        in {"standing", "ownership", "dependencies", "changes", "incidents", "action", "synthesis"}
    ]
    the_plan = plan(chosen)
    assert the_plan.levels == (
        ("standing", "ownership", "dependencies", "changes"),
        ("incidents", "action"),
        ("synthesis",),
    )
    incident = the_plan.step("incidents")
    assert (incident.level, incident.uses) == (1, ("changes",))
    # The conclusion reads every one before it.
    assert set(the_plan.step("synthesis").uses) == {
        "standing",
        "ownership",
        "dependencies",
        "changes",
        "incidents",
        "action",
    }
    # As it is kept with the analysis.
    said = the_plan.said()
    assert said["levels"] == [list(level) for level in the_plan.levels]
    # A capability it names that was not chosen is no prerequisite.
    alone = plan([c for c in CAPABILITIES if c.name == "incidents"])
    assert alone.levels == (("incidents",),) and alone.step("incidents").uses == ()


def test_a_cycle_is_refused_said_which() -> None:
    with pytest.raises(OrchestrationError, match="a, b"):
        plan(
            [
                capability("a", after=frozenset({"b"})),
                capability("b", uses=frozenset({"a"})),
                capability("c"),
            ]
        )


def _slow(_: Material) -> Output:
    time.sleep(0.3)
    return Output()


async def test_a_level_runs_together() -> None:
    chosen = [capability("a", _slow), capability("b", _slow)]
    started = time.monotonic()
    outcomes = await run(
        plan(chosen), {c.name: c for c in chosen}, material(), side=side, started=started
    )
    took = time.monotonic() - started
    assert [o.status for o in outcomes] == ["succeeded", "succeeded"]
    assert took < 0.55, f"two of 0.3 s took {took:.2f} s: one after the other"


async def test_each_is_handed_what_it_names_and_only_that() -> None:
    seen: dict[str, set[str]] = {}

    def watching(name: str) -> object:
        def look(m: Material) -> Output:
            seen[name] = set(m.handed)
            return Output(summary=None)

        return look

    chosen = [
        capability("a", watching("a")),
        capability("b", watching("b"), uses=frozenset({"a"})),
        capability("c", watching("c")),
    ]
    outcomes = await run(
        plan(chosen), {c.name: c for c in chosen}, material(), side=side, started=time.monotonic()
    )
    assert seen == {"a": set(), "b": {"a"}, "c": set()}
    by = {o.name: o for o in outcomes}
    assert (by["b"].level, by["b"].handed) == (1, ("a",))


def _boom(_: Material) -> Output:
    raise RuntimeError("boom")


async def test_what_did_not_succeed_is_said_and_coordinated() -> None:
    chosen = [
        capability("a", _boom),
        capability("needs_a", after=frozenset({"a"})),
        capability("reads_a", uses=frozenset({"a"})),
    ]
    outcomes = await run(
        plan(chosen), {c.name: c for c in chosen}, material(), side=side, started=time.monotonic()
    )
    by = {o.name: o for o in outcomes}
    assert by["a"].status == "failed"
    # A prerequisite that failed: not run, said which.
    assert (by["needs_a"].status, by["needs_a"].reason, by["needs_a"].error) == (
        "skipped",
        "upstream",
        "a",
    )
    # What it uses failed: run with the rest, said degraded.
    assert (by["reads_a"].status, by["reads_a"].degraded) == ("succeeded", ("a",))
    result = assemble(
        outcomes, readiness="ready", sources=1, contradictions=0, context_level="high"
    )
    assert {n.code for n in result.missing} >= {
        "capability.failed",
        "capability.degraded",
        "capability.upstream",
    }


async def test_a_fallback_stands_in_and_what_follows_reads_it() -> None:
    said = Output(summary=None, findings=(Statement(id="f", code="x", text="from the fallback"),))
    stand_in = capability("stand_in", lambda m: said)
    chosen = [
        capability("a", _boom, fallback="stand_in"),
        capability("after_a", lambda m: Output(), after=frozenset({"a"})),
    ]
    outcomes = await run(
        plan(chosen),
        {c.name: c for c in chosen},
        material(),
        side=side,
        started=time.monotonic(),
        fallbacks={"stand_in": stand_in},
    )
    assert [(o.name, o.status, o.fallback_of) for o in outcomes] == [
        ("a", "failed", None),
        ("stand_in", "succeeded", "a"),
        ("after_a", "succeeded", None),
    ]
    # What follows it ran: its prerequisite stood in for.
    assert outcomes[2].handed == ("a",)


def test_the_incidents_read_the_causes_the_changes_reach() -> None:
    """A deployment reaches the service an incident affects through what
    depends on what it touched: the changes find it — the incident's own
    record ties nothing to it."""
    reached = Cause(
        id=f"cause:{DEPLOY.id}",
        code="cause.followed",
        label=DEPLOY.name,
        basis="inferred",
        why=f"{INCIDENT.name} opened after it, on what it touched.",
        confidence=0.55,
        ref_id=DEPLOY.id,
        params={"incident": INCIDENT.name, "kind": "deployment"},
    )
    found = _incident(suspected_causes=[], changed_before=[])
    alone = incidents(material("explain_cause", incidents=(found,)))
    assert not alone.causes
    handed = incidents(
        material(
            "explain_cause",
            incidents=(found,),
            handed={"changes": Output(causes=(reached,))},
        )
    )
    [cause] = handed.causes
    assert cause.id == reached.id
    assert cause.why.endswith("(found with the changes of the period)")


def test_an_action_reads_who_owns_it_and_what_depends_on_it() -> None:
    restart = asked("act", actions=(("restart", True),))
    owned = Output(
        findings=(
            Statement(
                id="owner",
                code="ownership.owner",
                text="payment-api is owned by Payments.",
                params={"owners": ["Payments"]},
            ),
        )
    )
    handed = action(material(asked=restart, handed={"ownership": owned}))
    inform = next(f for f in handed.findings if f.code == "action.inform")
    assert inform.params["owners"] == ["Payments"]
    assert not any(f.code == "action.inform" for f in action(material(asked=restart)).findings)
