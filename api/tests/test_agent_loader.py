"""The agent loader, and what it refuses.

An agent is a markdown file that becomes an instruction executed by a model
with access to a customer's production data. There is no compiler between a
typo and production, so the front-matter validation is what stands in its
place. These tests are that validation's specification.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from leka.capabilities import (
    AgentLoadError,
    AgentMode,
    AgentRegistry,
    discover,
    load_all,
    parse_agent,
)
from leka.core.config import settings

GOOD_DESCRIPTION = "description: Use when something specific happens that this agent can explain."

VALID = """---
name: example-agent
description: Use when something specific happens that this agent can explain.
version: 1.0.0
entity_types: [service, deployment]
requires: [github]
mode: read_only
risk: low
outputs: finding
origin: internal
category: operations
---

The body.
"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


# ── The repository's own agents ──────────────────────────────────────────────


# Agents that propose actions — each a decision reviewed as such: the build
# fixer proposes a fix, never applies it (LEKA-400, docs/agent-library.md);
# the code-change agent proposes a diff a person accepts as a pull request.
# The test generation proposes tests the same way, never the tested code
# changed (LEKA-461).
PROPOSES = frozenset({"build-fixer", "code-change", "test-generation"})


def test_the_repository_agents_all_load() -> None:
    """agents/ must never contain a file the loader would choke on.

    This is the test that fails when someone adds an agent with a malformed
    header — before it reaches a customer, rather than at startup.
    """
    registry = load_all(settings.agents_dir)
    assert len(registry) >= 3

    for agent in registry.all():
        if agent.front_matter.name in PROPOSES:
            continue
        assert agent.front_matter.mode is AgentMode.READ_ONLY, (
            f"{agent.front_matter.name} is not read_only. That is allowed, but "
            "it must be a deliberate decision reviewed as such."
        )


def test_the_template_is_not_loaded_as_an_agent() -> None:
    """_template/ is a file to copy, not an agent.

    Its placeholder header is invalid on purpose, so that forgetting to fill
    it in fails loudly.
    """
    assert all("_template" not in path.parts for path in discover(settings.agents_dir))

    with pytest.raises(AgentLoadError):
        parse_agent(settings.agents_dir / "_template" / "SKILL.md")


# ── What is accepted ─────────────────────────────────────────────────────────


def test_a_valid_agent_parses(tmp_path: Path) -> None:
    agent = parse_agent(_write(tmp_path, VALID))

    assert agent.front_matter.name == "example-agent"
    assert agent.front_matter.entity_types == ("service", "deployment")
    assert agent.front_matter.mode is AgentMode.READ_ONLY
    assert agent.front_matter.is_vendor is False
    assert agent.body == "The body."


def test_a_vendor_origin_is_recognised(tmp_path: Path) -> None:
    """Vendor skills are reviewed line by line; the loader must be able to
    tell which they are."""
    agent = parse_agent(
        _write(tmp_path, VALID.replace("origin: internal", "origin: vendor:acme/skills"))
    )

    assert agent.front_matter.is_vendor is True


# ── What is refused ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "replacement"),
    [
        ("name is not kebab-case", ("name: example-agent", "name: ExampleAgent")),
        ("version is not semver", ("version: 1.0.0", "version: v1")),
        (
            "description says nothing",
            (
                "description: Use when something specific happens that this agent can explain.",
                "description: Does stuff.",
            ),
        ),
        ("mode is invented", ("mode: read_only", "mode: executes_freely")),
        ("risk is invented", ("risk: low", "risk: catastrophic")),
        ("origin is malformed", ("origin: internal", "origin: vendor")),
        ("entity_types is empty", ("entity_types: [service, deployment]", "entity_types: []")),
    ],
)
def test_malformed_front_matter_is_refused(
    tmp_path: Path, label: str, replacement: tuple[str, str]
) -> None:
    with pytest.raises(AgentLoadError):
        parse_agent(_write(tmp_path, VALID.replace(*replacement)))


def test_an_unknown_field_is_refused(tmp_path: Path) -> None:
    """The case that matters most.

    An unknown key is a typo in a field that decides whether an agent
    triggers or how it may behave — or a field a third-party skill added
    hoping nobody would look. Ignoring it silently is how a skill gets a
    capability nobody granted it.
    """
    with pytest.raises(AgentLoadError):
        parse_agent(
            _write(
                tmp_path, VALID.replace("origin: internal", "origin: internal\nallow_shell: true")
            )
        )


@pytest.mark.parametrize(
    ("label", "content"),
    [
        ("no front matter at all", "Just a markdown file.\n"),
        ("front matter never closed", "---\nname: x\ndescription: y\n"),
        ("front matter is not a mapping", "---\n- a\n- b\n---\nbody\n"),
        ("front matter is not valid yaml", "---\nname: [unclosed\n---\nbody\n"),
    ],
)
def test_a_file_that_is_not_an_agent_is_refused(tmp_path: Path, label: str, content: str) -> None:
    with pytest.raises(AgentLoadError):
        parse_agent(_write(tmp_path, content))


# ── The registry ─────────────────────────────────────────────────────────────


def test_two_agents_cannot_share_a_name(tmp_path: Path) -> None:
    """Names select agents. A duplicate means one silently shadows the other."""
    registry = AgentRegistry()
    registry.register(parse_agent(_write(tmp_path, VALID)))

    with pytest.raises(AgentLoadError, match="duplicate"):
        registry.register(parse_agent(_write(tmp_path, VALID)))


def test_strict_loading_refuses_to_start_on_a_bad_file(tmp_path: Path) -> None:
    """A platform that boots with half its agents missing is worse than one
    that refuses to boot: the feature is simply absent, with no error."""
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "SKILL.md").write_text(VALID, encoding="utf-8")
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "SKILL.md").write_text("not an agent", encoding="utf-8")

    with pytest.raises(AgentLoadError):
        load_all(tmp_path, strict=True)

    tolerant = load_all(tmp_path, strict=False)
    assert len(tolerant) == 1
