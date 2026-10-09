"""Workflows (LEKA-397), pure — what a workflow is, how it is checked, in
what order and on what conditions its steps run.

What these protect: the repository's workflows load, checked against the
catalogue, and register as capabilities of kind workflow — versioned like
any other, their steps fingerprinted; a workflow that cannot be — a cycle, a
step after one that does not exist, a capability LEKA does not have or that
cannot be a step, given what it does not take or not given what it needs, a
condition reading a step it does not run after or an input the workflow
does not take, an unknown field — is refused, said why; its steps run in
the order of their dependencies; a condition — a status, a code found, an
input, all, any, not — skips what it does not hold for; a step that stops
it, failed, ends the run failed, one that does not, is passed; a run's
steps read back as they were asked.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

import leka.schema  # noqa: F401 — every module provides its capabilities
from leka.capabilities import Kind, Lifecycle, WorkflowError, workflow_catalogue
from leka.capabilities.registry import catalogue
from leka.capabilities.workflow import (
    Ended,
    StepStatus,
    build,
    condition_of,
    from_spec,
    holds,
    next_steps,
    order,
    outcome,
    validated,
)

KNOWN = {d.key: d for d in catalogue() if d.kind is not Kind.WORKFLOW}


def flow(*steps: dict[str, Any], **more: Any) -> dict[str, Any]:
    return {
        "key": "review",
        "title": "Review",
        "summary": "Use when something must be reviewed, step by step.",
        "category": "operations",
        "version": "1.0.0",
        "lifecycle": "active",
        "steps": list(steps),
        **more,
    }


def refused(said: dict[str, Any], match: str) -> None:
    with pytest.raises(WorkflowError, match=match):
        validated(build(said), KNOWN)


def test_the_repository_s_workflows_load_as_capabilities() -> None:
    loaded = workflow_catalogue()
    assert set(loaded) >= {"incident-review", "architecture-dossier"}
    review = next(d for d in catalogue() if d.key == "incident-review")
    assert (review.kind, review.lifecycle, review.version) == (
        Kind.WORKFLOW,
        Lifecycle.ACTIVE,
        "1.0.0",
    )
    assert review.uses == ("incidents", "changes", "ownership", "documentation")
    # Its steps are what its version stands for.
    workflow = loaded["incident-review"]
    changed = replace(workflow, steps=workflow.steps[:2])
    assert changed.definition().fingerprint() != review.fingerprint()
    assert order(loaded["architecture-dossier"]) == [
        "standing",
        "dependencies",
        "documentation",
        "deck",
    ]


def test_a_workflow_that_cannot_be_is_refused_said_why() -> None:
    ok = {"id": "owners", "uses": "ownership"}
    refused(
        flow(
            {**ok, "after": ["docs"]}, {"id": "docs", "uses": "documentation", "after": ["owners"]}
        ),
        "wait on each other",
    )
    refused(flow({**ok, "after": ["nowhere"]}), "not another step")
    refused(flow({"id": "x", "uses": "nothing-like-this"}), "no capability")
    refused(flow({"id": "x", "uses": "synthesis"}), "cannot run as a step")
    refused(flow({**ok, "with": {"parcours": "x"}}), "does not take")
    refused(flow({"id": "deck", "uses": "application-architecture"}), "needs")
    refused(
        flow(
            ok,
            {"id": "docs", "uses": "documentation", "when": {"step": "owners", "status": "failed"}},
        ),
        "does not run after",
    )
    refused(flow({**ok, "when": {"input": "deck", "equals": True}}), "input the workflow")
    refused(flow({**ok, "retry": {"attempts": 9}}), "attempts")
    refused(flow({**ok, "on_failure": "ignore"}), "on_failure")
    refused(flow(ok, ok), "share an id")
    with pytest.raises(WorkflowError, match="unknown"):
        build(flow(ok, owner="me"))
    with pytest.raises(WorkflowError, match="status, or a code"):
        condition_of({"step": "x"}, "here")


def test_a_condition_reads_statuses_codes_inputs_and_combines_them() -> None:
    ended = {
        "incidents": Ended("succeeded", frozenset({"incident.no_cause"})),
        "docs": Ended("failed"),
    }
    said = condition_of(
        {
            "all": [
                {"step": "incidents", "found": "incident.no_cause"},
                {
                    "any": [
                        {"step": "docs", "status": ["failed", "skipped"]},
                        {"input": "deep", "equals": True},
                    ]
                },
                {"not": {"step": "incidents", "status": "failed"}},
            ]
        },
        "here",
    )
    assert holds(said, ended, {})
    assert not holds(condition_of({"step": "never", "status": "succeeded"}, "here"), ended, {})
    assert holds(condition_of({"input": "deep", "equals": True}, "here"), {}, {"deep": True})


def test_steps_run_in_order_skipped_when_their_condition_fails() -> None:
    workflow = workflow_catalogue()["incident-review"]
    start = next_steps(workflow, {}, {}, {})
    assert start.run == ("incidents",)
    # Something explained it: what changed before is not looked for.
    done = {"incidents": StepStatus.SUCCEEDED}
    explained = next_steps(workflow, done, {"incidents": Ended("succeeded")}, {})
    assert (explained.run, explained.skip) == (("ownership",), ("changes",))
    unexplained = next_steps(
        workflow, done, {"incidents": Ended("succeeded", frozenset({"incident.no_cause"}))}, {}
    )
    assert unexplained.run == ("changes", "ownership")


def test_a_failure_stops_it_or_is_passed() -> None:
    workflow = workflow_catalogue()["incident-review"]
    stopped = {
        "incidents": StepStatus.SUCCEEDED,
        "changes": StepStatus.SKIPPED,
        "ownership": StepStatus.FAILED,
    }
    said = next_steps(workflow, stopped, {}, {})
    assert (said.done, said.failed) == (True, "ownership")
    assert outcome(stopped, workflow).value == "failed"
    passed = {**stopped, "ownership": StepStatus.SUCCEEDED, "documentation": StepStatus.FAILED}
    assert next_steps(workflow, passed, {}, {}).done
    assert outcome(passed, workflow).value == "succeeded"


def test_a_run_reads_its_steps_back_as_they_were_asked() -> None:
    workflow = workflow_catalogue()["architecture-dossier"]
    again = from_spec(workflow.key, workflow.version, workflow.spec())
    assert again.spec() == workflow.spec()
    assert again.digest() == workflow.digest()
