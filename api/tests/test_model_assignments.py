"""The model each agent runs on (LEKA-530): agents/models.yaml.

What these protect: every agent of the registry has its model, a model LEKA
knows, able to do every step the agent asks of it — the hardest included —
and so is every fallback approved for it; LEKA's own work has its model too.
A call runs on its agent's model, every step of it, then on the fallbacks
approved for that agent only — never on another model LEKA holds a key for,
never one chosen per task. A trial model replaces them all, never in
production. A file that says a model wrong is refused whole.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from leka.capabilities.catalogue import needs_of
from leka.capabilities.changes import HARD_QUALITY
from leka.capabilities.definition import Kind
from leka.capabilities.gateway import Assignment, Needs, profile, route
from leka.capabilities.gateway import assignment as assigned_module
from leka.capabilities.gateway.assignment import (
    AssignmentError,
    agent_of,
    assigned,
    assignments,
    problems,
    read,
)
from leka.capabilities.registry import agents
from leka.core.config import settings
from leka.intentions.analyst import NEEDS as ANALYST
from leka.intentions.proposal import NEEDS as PROPOSAL
from leka.intentions.reading import NEEDS as READING
from leka.intentions.writing import NEEDS as WRITING

# The steps of an agent that ask the most of its model (changes.py): a code
# change, its repair, a review, mock-ups drawn.
HARDEST = Needs(structured=True, quality=HARD_QUALITY)
KEYS: dict[str, str | None] = {"google": "g", "mistral": "m", "anthropic": "a", "openai": "o"}


def _agents() -> dict[str, object]:
    return {d.key: d for d in agents(settings.agents_dir) if d.kind is Kind.AGENT}


def test_every_agent_has_its_model_one_leka_knows() -> None:
    found = _agents()
    assert len(found) >= 30
    assert problems(found) == []


def test_each_model_and_approved_fallback_does_every_step_its_agent_asks() -> None:
    found = assignments()
    for key, definition in _agents().items():
        for name, model in found.agents[key].models():
            said = profile(name, model)
            for needs in (needs_of(definition), HARDEST):  # type: ignore[arg-type]
                assert needs.unmet(said) is None, f"{key}: {name}:{model} — {needs}"
    for name, model in found.operations.models():
        said = profile(name, model)
        for needs in (ANALYST, PROPOSAL, READING, WRITING):
            assert needs.unmet(said) is None, f"operations: {name}:{model} — {needs}"


def test_a_call_runs_on_its_agent_s_model_every_step_of_it() -> None:
    found = assignments()
    assert agent_of("agent:code-change:repair") == "code-change"
    assert agent_of("agent:code-change") == "code-change"
    assert agent_of("intention.understanding") is None
    assert assigned("agent:code-change:repair") == found.agents["code-change"]
    assert assigned("agent:code-change:review-fix") == found.agents["code-change"]
    # LEKA's own work, and a capability no agent is: LEKA's own work's model.
    assert assigned("intention.understanding") == found.operations
    assert assigned("agent:intention-synthesis") == found.operations
    assert assigned(None) == found.operations


def test_only_the_assigned_model_then_the_fallbacks_approved_for_it() -> None:
    work = Assignment(
        model=("google", "gemini-3.8-flash"), fallbacks=(("mistral", "mistral-large-latest"),)
    )
    routing = route(Needs(structured=True), own=None, keys=KEYS, assignment=work)
    assert [(r.endpoint.provider, r.profile.model, r.why) for r in routing.routes] == [
        ("google", "gemini-3.8-flash", "assigned"),
        ("mistral", "mistral-large-latest", "fallback"),
    ]
    # No fallback approved: the assigned model alone — every key LEKA holds
    # for Anthropic or OpenAI is never an alternative.
    alone = route(
        Needs(structured=True),
        own=None,
        keys=KEYS,
        assignment=Assignment(model=("google", "gemini-3.8-flash")),
    )
    assert [r.profile.model for r in alone.routes] == ["gemini-3.8-flash"]
    # Its key missing: said, and nothing in its place.
    missing = route(
        Needs(),
        own=None,
        keys={**KEYS, "google": None},
        assignment=Assignment(model=("google", "gemini-3.8-flash")),
    )
    assert missing.routes == ()
    assert [(p.provider, p.reason) for p in missing.passed] == [("google", "no_key")]
    # What the assigned model cannot do: not done by another, said.
    blind = route(
        Needs(vision=True),
        own=None,
        keys=KEYS,
        assignment=Assignment(model=("mistral", "mistral-medium-latest")),
    )
    assert blind.routes == () and blind.passed[0].reason == "vision"


def test_a_trial_model_replaces_them_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        assigned_module,
        "settings",
        settings.model_copy(update={"llm_trial_model": "mistral:mistral-medium-latest"}),
    )
    tried = assigned("agent:code-change")
    assert (tried.model, tried.fallbacks, tried.trial) == (
        ("mistral", "mistral-medium-latest"),
        (),
        True,
    )
    assert assigned("intention.understanding") == tried
    routing = route(Needs(), own=None, keys=KEYS, assignment=tried)
    assert [r.why for r in routing.routes] == ["trial"]
    # Refused in production: tests/test_config.py.


@pytest.mark.parametrize(
    ("said", "wrong"),
    [
        ("version: 2\n", "version 1"),
        ("version: 1\noperations: {model: nobody:x}\n", "nobody:x"),
        ("version: 1\noperations: {model: google}\n", "provider:model"),
        (
            "version: 1\noperations: {model: google:gemini-3.8-flash}\n"
            "agents: {code-change: {model: google:gemini-3.8-flash, fallbacks: mistral}}\n",
            "fallbacks are a list",
        ),
    ],
)
def test_a_file_saying_a_model_wrong_is_refused_whole(
    tmp_path: Path, said: str, wrong: str
) -> None:
    path = tmp_path / "models.yaml"
    path.write_text(said, encoding="utf-8")
    with pytest.raises(AssignmentError, match=wrong):
        read(path)
