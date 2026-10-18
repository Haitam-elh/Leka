"""A plan LEKA's rules wrote (LEKA-495): its words in French and English,
so each reader sees it in theirs whatever the request's language was."""

from __future__ import annotations

from leka.intentions.proposal import GENERIC, PLANS, plan_by_rules


def test_a_rules_plan_says_each_step_in_both_languages() -> None:
    steps = plan_by_rules("investigate", "fr", ["incident-investigation"])
    assert [s.title for s in steps] == [t for t, _ in PLANS["explain_cause"]["fr"]]
    for at, step in enumerate(steps):
        assert step.words is not None
        assert (step.words["en"].title, step.words["en"].detail) == PLANS["explain_cause"]["en"][at]
        assert step.words["fr"].title == step.title
    # The agent kept on its step.
    assert steps[1].agent == "incident-investigation" and steps[1].words is not None


def test_every_rules_table_has_as_many_steps_in_each_language() -> None:
    for goal, tables in {**PLANS, "generic": GENERIC}.items():
        assert len(tables["fr"]) == len(tables["en"]), goal
