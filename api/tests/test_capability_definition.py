"""What a capability is (LEKA-393), pure.

What these protect: a capability is registered only as it can be — its key,
its version, its category, its contract, what it needs, who may use it —
checked against what LEKA knows; its lifecycle moves only where it may, and
retired is final; what it does is fingerprinted, where it stands is not;
whether it can be used here says every reason it cannot — refused,
lifecycle, turned off, a source missing, no model, a permission — and a
deprecated one is used, said so; what it is given is checked against its
contract; what answers a question is ranked, with why — never retired, the
unavailable left out when asked.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from leka.capabilities import (
    Contract,
    Definition,
    DefinitionError,
    Input,
    Kind,
    Lifecycle,
    Query,
    Situation,
    availability,
    check_input,
    discover_capabilities,
    may_move,
    mentions,
    validated,
)

ARCHITECTURE = Definition(
    key="application-architecture",
    title="Architecte applicatif",
    summary="Use when someone asks for the application architecture of a business journey.",
    category="architecture",
    kind=Kind.AGENT,
    version="18.0.0",
    lifecycle=Lifecycle.ACTIVE,
    contract=Contract(
        inputs=(
            Input("parcours"),
            Input("perimetre"),
            Input("vue_applicative", type="boolean", required=False),
        ),
        output="document",
        formats=("pptx", "pdf"),
    ),
    sources=(("confluence", "microsoft_365"),),
    model=True,
    goals=frozenset({"map_dependencies"}),
    kinds=frozenset({"dependency"}),
    entity_types=("application", "business_process"),
    examples=("Construis l'architecture du parcours Paiement CB",),
    instructions="Tu es l'agent architecte…",
)
OWNERSHIP = Definition(
    key="ownership",
    title="Ownership",
    summary="Who owns it, maintains it, leads its teams, knows it.",
    category="knowledge",
    kind=Kind.RULES,
    version="1.0.0",
    lifecycle=Lifecycle.ACTIVE,
    goals=frozenset({"find_owner"}),
    kinds=frozenset({"ownership"}),
)
KNOWN = {
    "entity_types": ["application", "business_process", "service"],
    "source_kinds": ["confluence", "microsoft_365", "github"],
    "permissions": ["intention:create", "intention:approve"],
}
EVERYONE = frozenset({"intention:create", "intention:read"})


def test_a_capability_is_registered_only_as_it_can_be() -> None:
    assert validated(ARCHITECTURE, **KNOWN) is ARCHITECTURE
    for wrong in (
        replace(ARCHITECTURE, key="Application Architecture"),
        replace(ARCHITECTURE, version="v18"),
        replace(ARCHITECTURE, category="magic"),
        replace(ARCHITECTURE, summary="Decks."),
        replace(ARCHITECTURE, model=False),
        replace(ARCHITECTURE, mode="acts_freely"),
        replace(ARCHITECTURE, contract=Contract(output="document", formats=("gif",))),
        replace(ARCHITECTURE, contract=Contract(inputs=(Input("a"), Input("a")))),
        replace(ARCHITECTURE, contract=Contract(inputs=(Input("pick", type="choice"),))),
        replace(ARCHITECTURE, goals=frozenset({"Map Dependencies"})),
        replace(ARCHITECTURE, entity_types=("spaceship",)),
        replace(ARCHITECTURE, sources=(("sharepoint",),)),
        replace(ARCHITECTURE, permission="everything"),
    ):
        with pytest.raises(DefinitionError):
            validated(wrong, **KNOWN)


def test_its_lifecycle_moves_only_where_it_may() -> None:
    a = Lifecycle
    assert may_move(a.DRAFT, a.ACTIVE) and may_move(a.REVIEW, a.ACTIVE)
    assert may_move(a.ACTIVE, a.DEPRECATED) and may_move(a.DEPRECATED, a.ACTIVE)
    assert may_move(a.DEPRECATED, a.RETIRED) and may_move(a.ACTIVE, a.ACTIVE)
    assert not may_move(a.ACTIVE, a.DRAFT)
    # Retired is final.
    assert not any(may_move(a.RETIRED, other) for other in a if other is not a.RETIRED)


def test_what_it_does_is_fingerprinted_where_it_stands_is_not() -> None:
    print_ = ARCHITECTURE.fingerprint()
    assert replace(ARCHITECTURE, lifecycle=Lifecycle.DEPRECATED).fingerprint() == print_
    assert replace(ARCHITECTURE, path="/elsewhere").fingerprint() == print_
    assert replace(ARCHITECTURE, instructions="Autre chose").fingerprint() != print_
    assert replace(ARCHITECTURE, summary=ARCHITECTURE.summary + "!").fingerprint() != print_
    # What the catalogue keeps of it never holds its instructions.
    assert ARCHITECTURE.described()["instructions"] is None


def test_whether_it_can_be_used_here_every_reason() -> None:
    nothing = Situation(permissions=EVERYONE)
    able = availability(ARCHITECTURE, nothing)
    assert not able.available
    assert able.codes == ("missing_source", "no_model")
    assert able.reasons[0].detail == {"any_of": ["confluence", "microsoft_365"]}

    ready = Situation(connected=frozenset({"microsoft_365"}), model=True, permissions=EVERYONE)
    assert availability(ARCHITECTURE, ready).available

    off = Situation(enabled=False, model=True, permissions=frozenset())
    assert availability(ARCHITECTURE, off).codes == (
        "disabled",
        "missing_source",
        "not_permitted",
    )
    draft = replace(ARCHITECTURE, lifecycle=Lifecycle.DRAFT)
    assert availability(draft, ready).codes == ("lifecycle",)
    refused = availability(ARCHITECTURE, ready, refused="changed_without_version")
    assert refused.codes == ("refused",)
    # Deprecated: used, and said.
    old = availability(replace(ARCHITECTURE, lifecycle=Lifecycle.DEPRECATED), ready)
    assert old.available and [n.code for n in old.notes] == ["deprecated"]
    # LEKA's own rules need nothing but the permission to ask.
    assert availability(OWNERSHIP, Situation(permissions=EVERYONE)).available


def test_what_it_is_given_is_checked_against_its_contract() -> None:
    contract = replace(
        ARCHITECTURE.contract,
        inputs=(
            *ARCHITECTURE.contract.inputs,
            Input("format", type="choice", required=False, choices=("a4",)),
        ),
    )
    assert check_input(contract, {"parcours": "Paiement CB", "perimetre": "Digital"}) == []
    errors = check_input(
        contract,
        {"parcours": " ", "vue_applicative": "yes", "format": "a3", "colour": "red"},
    )
    assert {(e.name, e.code) for e in errors} == {
        ("colour", "unknown"),
        ("parcours", "missing"),
        ("perimetre", "missing"),
        ("vue_applicative", "type"),
        ("format", "choice"),
    }


def test_what_answers_a_question_is_ranked_with_why() -> None:
    retired = replace(OWNERSHIP, key="old-ownership", lifecycle=Lifecycle.RETIRED)
    standing = replace(OWNERSHIP, key="standing", goals=frozenset(), kinds=frozenset(), always=True)
    found = [ARCHITECTURE, OWNERSHIP, retired, standing]
    everyone = Situation(permissions=EVERYONE)
    able = {d.key: availability(d, everyone) for d in found}
    matches = discover_capabilities(
        found,
        Query(
            goal="map_dependencies",
            kind="dependency",
            entity_types=frozenset({"application"}),
            text="architecture du parcours Paiement",
        ),
        able,
    )
    assert [(m.definition.key, m.reasons) for m in matches] == [
        ("application-architecture", ("goal", "kind", "entity:application", "words")),
        ("standing", ("always",)),
    ]
    assert matches[0].score == 3 + 2 + 1 + 3
    assert not matches[0].availability.available

    owner = discover_capabilities(found, Query(goal="find_owner"), able)
    assert next(m.definition.key for m in owner) == "ownership"
    # Only what can be used, when asked so; never retired.
    only = discover_capabilities(found, Query(goal="map_dependencies", available_only=True), able)
    assert "application-architecture" not in {m.definition.key for m in only}
    assert "old-ownership" not in {m.definition.key for m in owner}


def test_searched_by_its_words_accents_aside() -> None:
    assert mentions(ARCHITECTURE, "architecte")
    assert mentions(ARCHITECTURE, "PARCOURS paiement")
    assert mentions(OWNERSHIP, "teams")
    assert not mentions(OWNERSHIP, "architecture")
