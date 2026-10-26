"""The Engineering bundle's four agents (LEKA-461): the codebase explored,
tests generated, regressions weighed, a change's reach.

What these protect: each is registered and active, run by a model; the
three that read are read-only, the test generation only proposes — a diff a
person accepts before LEKA opens a pull request, never the code it tests
changed; each offered the skills of its domain, none beyond what it may
read; delivering what it says; its instructions saying what it looks at,
its method, what it produces and what it must never do. Each is sold at its
reference's tier, and with the four built, Engineering is on sale at 59 € —
its saving the one its members' prices show. And what people ask reaches
them, while the existing agents keep what is theirs.
"""

from __future__ import annotations

import pytest

import leka.schema  # noqa: F401 — every module provides its capabilities
from leka.billing import catalogue as commercial
from leka.capabilities import Availability, Kind, Lifecycle, RouteQuery, route
from leka.capabilities.registry import catalogue
from leka.capabilities.skills import agent_skill_tools

ENGINEERING = {
    "codebase-explorer": ("standard", ["repository-profile"]),
    "test-generation": ("standard", []),
    "regression-analysis": ("specialized", ["change-review", "test-scope"]),
    "change-impact-analysis": ("specialized", ["blast-radius", "change-review"]),
}
# A new version each for its method (2026-10-18).
VERSIONS = {
    "codebase-explorer": "1.1.0",
    "test-generation": "1.1.0",
    "change-impact-analysis": "1.2.0",
    "regression-analysis": "1.2.0",
}


def test_each_is_registered_reads_or_only_proposes() -> None:
    found = {d.key: d for d in catalogue()}
    for key, (_, skills) in ENGINEERING.items():
        d = found[key]
        assert (d.kind, d.lifecycle, d.model, d.version) == (
            Kind.AGENT,
            Lifecycle.ACTIVE,
            True,
            VERSIONS.get(key, "1.0.0"),
        ), key
        assert {"search_entities", "read_entity"} <= set(d.tools), key
        assert all(not i.required for i in d.contract.inputs), key
        given, withheld = agent_skill_tools(d)
        assert [t.name for t in given] == skills and withheld == [], key
        said = d.instructions or ""
        for section in (
            "Ce qu'il regarde",
            "Sa méthode",
            "Ce qu'il produit",
            "Ce qu'il ne doit jamais faire",
        ):
            assert section in said, (key, section)
        assert "Rien d'inventé" in said, key
        if key == "test-generation":
            # It proposes: a diff a person accepts — never the tested code changed.
            assert (d.mode, d.renders, d.contract.formats) == (
                "proposes_action",
                "code_change",
                ("diff",),
            )
            assert {"list_files", "read_file"} <= set(d.tools)
            assert "jamais le code testé" in said and "pull request" in said
        else:
            assert (d.mode, d.contract.formats) == ("read_only", ("markdown",)), key
            assert "## Ses compétences" in said, key


def test_each_is_sold_at_its_reference_tier_and_engineering_is_on_sale() -> None:
    sold = commercial().add_ons
    for key, (tier, _) in ENGINEERING.items():
        assert sold.agents[key].tier == tier, key
    bundle = sold.bundle("engineering")
    assert bundle is not None
    assert (bundle.sellable, bundle.missing) == (True, ())
    assert set(ENGINEERING) <= set(bundle.agents)
    # 49 € against its six agents alone (9 + 9 + 9 + 9 + 15 + 15) — the
    # architect, dedicated since 2026-10-25, out of it.
    assert (bundle.monthly_price, bundle.alone_price, bundle.savings_percent) == (4900, 6600, 26)


ASKED = [
    (
        RouteQuery(
            text="Explore le code de acme/payment-api et explique-moi comment il est organisé",
            goal="find_knowledge",
            kind="knowledge",
        ),
        "codebase-explorer",
    ),
    (
        RouteQuery(
            text="Écris les tests manquants du calcul des remises dans acme/checkout",
            goal="act",
            kind="change",
            mode="request",
            acting=True,
        ),
        "test-generation",
    ),
    (
        RouteQuery(
            text="Quels risques de régression dans la PR #412 de payment-api ?",
            goal="assess_impact",
            kind="change",
        ),
        "regression-analysis",
    ),
    (
        RouteQuery(
            text="Quel est l'impact de la migration de la base de facturation ?",
            goal="assess_impact",
            kind="change",
        ),
        "change-impact-analysis",
    ),
]


@pytest.mark.parametrize(("asked", "expected"), ASKED, ids=[e for _, e in ASKED])
def test_what_people_ask_reaches_its_agent(asked: RouteQuery, expected: str) -> None:
    every = catalogue()
    routed = route(asked, every, {d.key: Availability(True) for d in every})
    assert routed.outcome == "routed"
    assert expected in [c.key for c in routed.selected], [
        (c.key, c.score) for c in routed.candidates[:5]
    ]


def test_a_question_never_goes_to_the_test_generation() -> None:
    every = catalogue()
    asked = RouteQuery(
        text="Quels tests existent pour le calcul des remises de checkout ?",
        goal="investigate",
        kind="change",
    )
    routed = route(asked, every, {d.key: Availability(True) for d in every})
    assert "test-generation" not in [c.key for c in routed.selected]


def test_the_codebase_explorer_explains_in_three_levels_and_names_the_traps() -> None:
    # 2026-10-18: one line, five minutes, the deep dive; the three files to
    # read first; a real path followed, where it forks into a job said; the
    # traps; describing, never judging; the files read and those not.
    said = {d.key: d for d in catalogue()}["codebase-explorer"].instructions or ""
    for part in (
        "**En une phrase**",
        "**En cinq minutes**",
        "les trois fichiers à lire en premier",
        "**Les pièges**",
    ):
        assert part in said, part
    for step in (
        "Suivre un vrai chemin",
        "Traduire les abstractions",
        "Décrire, pas juger",
        "Une partie n'est pas le tout",
    ):
        assert step in said, step
    assert "msitarzewski/agency-agents" not in said and "<sub>" not in said


def test_the_test_generation_writes_tests_that_would_fail() -> None:
    # 2026-10-18: the lowest level that proves it, no fixed waits, data of
    # its own, found as a person finds it, and for each test the change of
    # the code that would make it fail.
    said = {d.key: d for d in catalogue()}["test-generation"].instructions or ""
    for step in (
        "Le plus bas niveau qui le prouve",
        "Des tests qui ne clignotent pas",
        "Chercher comme une personne",
        "Un test qui échouerait",
    ):
        assert step in said, step
    assert "ce qui le ferait échouer" in said
    assert "msitarzewski/agency-agents" not in said and "<sub>" not in said


def test_the_regression_and_the_impact_weigh_contracts_and_the_way_back() -> None:
    # 2026-10-18: a broken contract and an irreversible migration, the way
    # back and how to ship a wide change, by stages.
    found = {d.key: d for d in catalogue()}
    regression = found["regression-analysis"].instructions or ""
    assert "**Le contrat.**" in regression and "**La migration.**" in regression
    impact = found["change-impact-analysis"].instructions or ""
    assert "**Le retour arrière.**" in impact and "**Comment le livrer.**" in impact
