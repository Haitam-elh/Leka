"""The enterprise agent library (LEKA-400), as the catalogue loads it —
each agent's contract, and where the router sends what people ask.

What these protect: the eleven agents of the library are registered and
active, each an agent of the runtime's contract — run by a model, read-only
but the build fixer, which only proposes; what it is about named in entity
types LEKA knows; the tools it declares, among the runtime's, searching and
reading always; what it takes, never required, so a routed intention runs
it as asked; delivering markdown; its instructions saying what it looks at,
what it produces and what it must never do. And realistic requests go to
the right one — an incident to the investigation, a security question to
the security review, a broken build, asked to be fixed, to the build fixer
(never a mere question about it).
"""

from __future__ import annotations

import pytest

import leka.schema  # noqa: F401 — every module provides its capabilities
from leka.capabilities import Availability, Kind, Lifecycle, RouteQuery, route
from leka.capabilities.registry import catalogue
from leka.capabilities.skills import agent_skill_tools
from leka.capabilities.tools import NAMES
from leka.knowledge import EntityType

LIBRARY = {
    "architecture-analysis",
    "code-review",
    "security-review",
    "test-analysis",
    "debug-assistant",
    "documentation-assistant",
    "incident-investigation",
    "infrastructure-analysis",
    "data-analysis",
    "release-analysis",
    "build-fixer",
}


def test_the_library_is_registered_each_agent_to_the_runtime_s_contract() -> None:
    found = {d.key: d for d in catalogue()}
    assert set(found) >= LIBRARY
    types = {t.value for t in EntityType}
    for key in sorted(LIBRARY):
        d = found[key]
        # Given their skills (LEKA-401): a new version each.
        assert (d.kind, d.lifecycle, d.model, d.version) == (
            Kind.AGENT,
            Lifecycle.ACTIVE,
            True,
            "1.0.0" if key == "build-fixer" else "1.1.0",
        ), key
        assert set(d.entity_types) <= types, key
        assert {"search_entities", "read_entity"} <= set(d.tools) <= NAMES, key
        assert all(not i.required for i in d.contract.inputs), key
        assert d.contract.formats == ("markdown",), key
        assert d.mode == ("proposes_action" if key == "build-fixer" else "read_only"), key
        said = d.instructions or ""
        for section in ("Ce qu'il regarde", "Ce qu'il produit", "Ce qu'il ne doit jamais faire"):
            assert section in said, (key, section)
        assert "Rien d'inventé" in said, key
        # Each names the library's skills of its domain, and is offered them
        # all: none reads beyond what the agent may (LEKA-401).
        if key != "build-fixer":
            given, withheld = agent_skill_tools(d)
            assert [t.name for t in given] == list(d.skills) and d.skills, key
            assert withheld == [], key
            assert "## Ses compétences" in said, key


ASKED = [
    (
        RouteQuery(
            text="Investigue l'incident de payment-api de cette nuit",
            goal="explain_cause",
            kind="diagnose",
        ),
        "incident-investigation",
    ),
    (
        RouteQuery(
            text="Fais une revue de sécurité de payment-api",
            goal="check_compliance",
            kind="compliance",
        ),
        "security-review",
    ),
    (
        RouteQuery(
            text="Que faut-il tester avant de livrer checkout ?",
            goal="assess_impact",
            kind="change",
        ),
        "test-analysis",
    ),
    (
        RouteQuery(
            text="Où sont stockées les données de facturation ?",
            goal="map_dependencies",
            kind="dependency",
        ),
        "data-analysis",
    ),
    (
        RouteQuery(
            text="Qu'est-ce qui est parti dans la release d'hier de checkout ?",
            goal="find_change",
            kind="change",
        ),
        "release-analysis",
    ),
    (
        RouteQuery(
            text="Répare le build de payment-api, il est cassé",
            goal="act",
            kind="diagnose",
            mode="request",
            acting=True,
        ),
        "build-fixer",
    ),
]


@pytest.mark.parametrize(("asked", "expected"), ASKED, ids=[e for _, e in ASKED])
def test_what_people_ask_goes_to_the_right_agent(asked: RouteQuery, expected: str) -> None:
    every = catalogue()
    routed = route(asked, every, {d.key: Availability(True) for d in every})
    assert routed.outcome == "routed"
    assert expected in [c.key for c in routed.selected], [
        (c.key, c.score) for c in routed.candidates[:5]
    ]


def test_a_question_about_a_broken_build_never_goes_to_the_fixer() -> None:
    every = catalogue()
    asked = RouteQuery(
        text="Pourquoi le build de payment-api est cassé ?", goal="explain_cause", kind="diagnose"
    )
    routed = route(asked, every, {d.key: Availability(True) for d in every})
    assert "build-fixer" not in [c.key for c in routed.selected]
    assert "build-fixer" in [c.key for c in routed.excluded]
