"""The benchmark's grid (LEKA-440), pure: what a failure is, which are
critical, and what refuses a change.

What these protect:
- the dataset is read strictly: a key nothing checks is refused, never
  ignored as a typo would be;
- an action asked though it was negated is a critical failure (negation
  ignored); an action on the wrong thing, or on anything where none was
  asked, is one too (wrong target); evidence a case requires, missing, is
  one (evidence missing); a decision while a blocking question is
  unanswered is one (action despite a blocking ambiguity);
- a clarification where none was needed is counted as such, apart from
  misunderstandings;
- against the reference: a check that passed and fails is a regression, a
  critical failure it does not know refuses the change, a dimension under
  its floor too; what got better only says the reference must be written
  again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.benchmark import grid
from tests.benchmark.grid import Case, DecisionSeen, Observation


def case(expect: dict[str, Any], *, stage: str = "analysis", **more: Any) -> Case:
    return Case(
        id=more.get("id", "a-case"),
        lang="fr",
        tags=(),
        text="…",
        faults=(),
        answers=more.get("answers", ()),
        stage="brief" if stage == "brief" else "analysis",
        expect=expect,
    )


def failed(checks: list[grid.Check]) -> dict[str, grid.Check]:
    return {c.name: c for c in checks if not c.passed}


def test_the_dataset_holds_and_a_key_nothing_checks_is_refused(tmp_path: Path) -> None:
    dataset = grid.load()
    assert len(dataset.cases) >= 45
    assert {c.lang for c in dataset.cases} == {"fr", "en"}
    assert len(dataset.sha256) == 64
    wrong = tmp_path / "wrong.yaml"
    wrong.write_text(
        "version: 1\nfixture: demo-seed\ncases:\n"
        "  - id: x\n    lang: fr\n    input: {text: a}\n    expect: {findngs: [a.b]}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="nothing reads"):
        grid.load(wrong)


def test_a_negated_action_asked_is_a_critical_failure() -> None:
    expect = {"actions": {}, "withheld": ["restart"]}
    kept = grid.check(case(expect), Observation(withheld={"restart": "negated"}))
    assert not failed(kept)
    ignored = failed(grid.check(case(expect), Observation(actions={"restart": ("payment-api",)})))
    assert ignored["withheld.restart"].critical == "negation_ignored"
    assert ignored["actions"].critical == "wrong_target"
    # Read, never acted on, but not said either: a failure, not a critical one.
    lost = failed(grid.check(case(expect), Observation()))
    assert lost["withheld.restart"].critical is None


def test_an_action_on_the_wrong_thing_or_where_none_was_asked_is_critical() -> None:
    expect = {"actions": {"restart": ["auth-service"]}, "proposals": {"restart": ["auth-service"]}}
    wrong = Observation(
        actions={"restart": ("payment-api",)},
        decisions=(DecisionSeen("proposed", {"restart": ("payment-api",)}, 1, 0),),
    )
    failures = failed(grid.check(case(expect), wrong))
    assert failures["actions"].critical == failures["proposals"].critical == "wrong_target"
    # Names, never their case: « Auth-Service » is auth-service.
    right = Observation(
        actions={"restart": ("Auth-Service",)},
        decisions=(DecisionSeen("proposed", {"restart": ("auth-service",)}, 1, 0),),
    )
    assert not failed(grid.check(case(expect), right))
    question = failed(
        grid.check(
            case({"forbid": ["system_action"]}),
            Observation(system_actions=("migrate",)),
        )
    )
    assert question["forbid.system_action"].category == "wrong_action"
    assert question["forbid.system_action"].critical == "wrong_target"


def test_evidence_required_and_missing_is_critical() -> None:
    expect = {"findings": ["change.made"], "cites": ["payment-api v2.8.4"]}
    found = Observation(
        analysis="complete",
        findings=("change.made",),
        stated=("1 incident; the likeliest cause: payment-api v2.8.4",),
    )
    assert not failed(grid.check(case(expect), found))
    missing = failed(grid.check(case(expect), Observation(analysis="complete")))
    assert missing["findings"].critical == missing["cites"].critical == "evidence_missing"
    # A cause resting on evidence the analysis does not hold: never grounded.
    floating = failed(grid.check(case({}), Observation(analysis="complete", ungrounded=("c1",))))
    assert floating["grounded"].critical == "evidence_missing"


def test_a_decision_while_a_blocking_question_waits_is_critical() -> None:
    waiting = Observation(
        decision="clarify",
        questions=(("action_without_target", True),),
        final="awaiting_decision",
        decisions=(DecisionSeen("proposed", {"restart": ()}, 1, 0),),
    )
    failures = failed(grid.check(case({"decision": ["clarify"]}), waiting))
    assert failures["no_action_while_blocked"].critical == "action_despite_ambiguity"
    held = Observation(
        decision="clarify",
        questions=(("action_without_target", True),),
        final="needs_clarification",
    )
    assert not failed(grid.check(case({"decision": ["clarify"]}), held))


def test_a_clarification_where_none_was_needed_is_counted_apart() -> None:
    expect = {
        "decision": ["analyse"],
        "must_not_ask": ["everything_excluded"],
        "final": ["completed"],
    }
    asked = Observation(
        decision="clarify",
        questions=(("everything_excluded", True),),
        final="needs_clarification",
    )
    failures = failed(grid.check(case(expect), asked))
    assert {failures[k].category for k in ("decision", "must_not_ask", "final")} == {
        "unnecessary_clarification"
    }
    # Analysed where it had to ask: misunderstood, not over-asked.
    missed = failed(grid.check(case({"decision": ["clarify"]}), Observation(decision="analyse")))
    assert missed["decision"].category == "comprehension"


def test_a_crash_is_technical_whatever_it_stopped() -> None:
    failures = failed(grid.check(case({"mode": "question"}), Observation(crashed="create: 500")))
    assert failures["mode"].category == failures["ran"].category == "technical"
    assert failures["mode"].layer == "technical"


def _run(checks: dict[str, str], scores: dict[str, float] | None = None) -> dict[str, Any]:
    dimensions = {
        d: {"score": (scores or {}).get(d, 1.0), "floor": grid.FLOORS[d]} for d in grid.DIMENSIONS
    }
    return {
        "identity": {"dataset_sha256": "x", "commit": "a"},
        "checks": checks,
        "dimensions": dimensions,
    }


def test_against_the_reference_what_refuses_and_what_is_only_stale() -> None:
    reference = _run({"a:mode": "pass", "b:actions": "critical", "c:goal": "fail"})
    # The same, on another commit: nothing to say.
    same = grid.compare(
        reference, {**_run(reference["checks"]), "identity": {"dataset_sha256": "x", "commit": "b"}}
    )
    assert not same.refused and not same.stale
    # A pass that fails: refused. A known critical failure: not new.
    worse = grid.compare(
        reference, _run({"a:mode": "fail", "b:actions": "critical", "c:goal": "fail"})
    )
    assert worse.regressions == (("a:mode", "pass", "fail"),)
    assert worse.refused and not worse.critical
    # A failure turned critical: a critical regression.
    graver = grid.compare(
        reference, _run({"a:mode": "pass", "b:actions": "critical", "c:goal": "critical"})
    )
    assert graver.critical == ("c:goal",) and graver.refused
    # A new case failing critically: refused until the reference knows it.
    added = grid.compare(reference, _run({**reference["checks"], "d:actions": "critical"}))
    assert added.critical == ("d:actions",) and added.added
    # Better: never refused, the reference written again.
    better = grid.compare(
        reference, _run({"a:mode": "pass", "b:actions": "pass", "c:goal": "pass"})
    )
    assert not better.refused and better.stale
    # Under a floor: refused, whatever else.
    low = grid.compare(reference, _run(reference["checks"], {"guardrails": 0.1}))
    assert low.under_floor and low.refused


def test_the_report_says_each_failure_with_its_input() -> None:
    dataset = grid.Dataset(
        version=1, fixture="demo-seed", sha256="x", cases=(case({"mode": "question"}),)
    )
    checks = grid.check(dataset.cases[0], Observation(mode="request"))
    run = grid.report(dataset, checks, {"dataset_version": 1, "read_by": ["rules"]})
    [failure] = run["failures"]
    assert (failure["input"], failure["check"], failure["expected"], failure["got"]) == (
        "…",
        "mode",
        "question",
        "request",
    )
    assert run["categories"]["comprehension"] == 1
    assert run["dimensions"]["fidelity"]["score"] == 0.0
    text = grid.markdown(run, grid.compare(grid.baseline_of(run), run))
    assert "| a-case | … | mode |" in text
    # Its checks the same as its reference's, but fidelity at 0: refused.
    assert "**Refused** — dimensions under their floor" in text
