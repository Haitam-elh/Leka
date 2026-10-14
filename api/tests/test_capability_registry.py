"""The capabilities LEKA has, as definitions (LEKA-393).

What these protect: the repository's catalogue loads whole — LEKA's own
analyses and the agents — and the first agent, the application architect, is
there as written: active, what it takes, what it delivers, what it needs, its
instructions kept server-side; an agent's status is registry.yaml's — a draft
when it is not indexed — and the index must say the file's version and a
status that exists; two capabilities never share a key, and one naming what
LEKA does not know refuses the catalogue.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import leka.intentions  # noqa: F401 — declares LEKA's own analyses
from leka.capabilities import (
    AgentLoadError,
    DefinitionError,
    Kind,
    Lifecycle,
    catalogue,
    definitions,
    provide,
)
from leka.capabilities.registry import _providers
from leka.intentions.capabilities import definitions as analyses

AGENT = """---
name: {name}
description: Use when something specific happens that this agent can explain.
version: {version}
entity_types: [{types}]
requires: [github]
mode: read_only
risk: low
outputs: finding
origin: internal
category: operations
---

The body.
"""


def _agent(root: Path, name: str, *, version: str = "1.0.0", types: str = "service") -> None:
    folder = root / "ops" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        AGENT.format(name=name, version=version, types=types), encoding="utf-8"
    )


def _index(root: Path, *rows: tuple[str, str, str]) -> None:
    lines = ["version: 1", "agents:"]
    for name, version, status in rows:
        lines += [
            f"  - path: ops/{name}/SKILL.md",
            f"    version: {version}",
            f"    status: {status}",
        ]
    (root / "registry.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_repositorys_catalogue_loads_whole() -> None:
    found = {d.key: d for d in catalogue()}
    rules = [d for d in found.values() if d.kind in (Kind.RULES, Kind.MODEL)]
    assert {d.key for d in rules} == {d.key for d in analyses()}
    # The synthesis is LEKA's own, written by a model: what it needs of one, said.
    assert found["synthesis"].kind is Kind.MODEL
    assert (found["synthesis"].model_needs.structured, found["synthesis"].model) == (True, True)
    assert all(d.lifecycle is Lifecycle.ACTIVE for d in rules)
    assert found["standing"].always

    architect = found["application-architecture"]
    assert (architect.kind, architect.lifecycle, architect.version) == (
        Kind.AGENT,
        Lifecycle.ACTIVE,
        "19.1.0",
    )
    assert architect.title == "Architecte applicatif"
    assert [(i.name, i.required) for i in architect.contract.inputs] == [
        ("parcours", True),
        ("perimetre", True),
        ("organisation", False),
        ("entite", False),
        ("service", False),
        ("vue_applicative", False),
    ]
    assert (architect.contract.output, architect.contract.formats) == ("document", ("pptx", "pdf"))
    # Any documentation, code, ticket or database source: what it draws on,
    # Confluence or not; LEKA draws its deck.
    [any_of] = architect.sources
    assert {"confluence", "microsoft_365", "github", "jira", "postgresql"} <= set(any_of)
    assert architect.renders == "architecture_deck"
    assert architect.model and architect.mode == "read_only"
    # Its instructions, as written — kept here, never in what is sent.
    assert architect.instructions and "PRINCIPE ABSOLU" in architect.instructions
    # Generic: any organisation's, said by its inputs — none of its own.
    assert "ENGIE" not in architect.title + architect.summary + architect.instructions
    assert "{{ORGANISATION}}" in architect.instructions
    # Not indexed as live: the drafts.
    assert found["correlate-deploy-with-latency"].lifecycle is Lifecycle.DRAFT


def test_an_agents_status_is_the_indexs(tmp_path: Path) -> None:
    _agent(tmp_path, "indexed-agent", version="2.1.0")
    _agent(tmp_path, "forgotten-agent")
    _index(tmp_path, ("indexed-agent", "2.1.0", "deprecated"))
    found = {d.key: d for d in definitions(tmp_path)}
    assert found["indexed-agent"].lifecycle is Lifecycle.DEPRECATED
    # Going live is a line in the index.
    assert found["forgotten-agent"].lifecycle is Lifecycle.DRAFT


@pytest.mark.parametrize(("version", "status"), [("1.0.1", "active"), ("1.0.0", "shipped")])
def test_the_index_says_the_files_version_and_a_status_that_exists(
    tmp_path: Path, version: str, status: str
) -> None:
    _agent(tmp_path, "some-agent")
    _index(tmp_path, ("some-agent", version, status))
    with pytest.raises(AgentLoadError):
        definitions(tmp_path)


def test_two_capabilities_never_share_a_key_nor_name_the_unknown(tmp_path: Path) -> None:
    _agent(tmp_path, "ownership")
    with pytest.raises(DefinitionError, match="two capabilities"):
        definitions(tmp_path)

    unknown = tmp_path / "unknown"
    unknown.mkdir()
    _agent(unknown, "lost-agent", types="spaceship")
    with pytest.raises(DefinitionError, match="spaceship"):
        definitions(unknown)


def test_a_module_declares_its_own(tmp_path: Path) -> None:
    before = len(definitions(tmp_path))
    provide("tests.extra", lambda: [d for d in analyses() if d.key == "standing"])
    try:
        with pytest.raises(DefinitionError, match="two capabilities"):
            definitions(tmp_path)
    finally:
        _providers.pop("tests.extra")
        catalogue.cache_clear()
    assert len(definitions(tmp_path)) == before
