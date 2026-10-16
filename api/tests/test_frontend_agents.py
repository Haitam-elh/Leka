"""Frontend Craft's four agents (LEKA-461): the interface's quality, its
accessibility, its design, its motion.

What these protect: each is registered and active, an agent of the runtime's
contract — run by a model, read-only, reading the code of a connected GitHub
repository through the code tools it names, offered the repository's
profile, delivering markdown, none of what it takes required; its
instructions say what it looks at, its method, what it produces and what it
must never do — nothing invented, every finding a file and a line, never
pretending to have seen the screen. Each is sold at its reference's tier,
and with the four built, the Frontend Craft bundle is on sale at 29 € — its
saving the one its members' prices show. And what people ask about an
interface reaches them, while a pull request's review still goes to the code
review.
"""

from __future__ import annotations

import pytest

import leka.schema  # noqa: F401 — every module provides its capabilities
from leka.billing import catalogue as commercial
from leka.capabilities import Availability, Kind, Lifecycle, RouteQuery, route
from leka.capabilities.registry import catalogue
from leka.capabilities.skills import agent_skill_tools

FRONTEND = {
    "ui-quality-review": "standard",
    "accessibility-audit": "standard",
    "design-review": "specialized",
    "motion-review": "specialized",
}
CODE = {"list_files", "read_file", "list_pull_requests", "read_pull_request"}


def test_each_is_registered_read_only_reading_the_code_it_cites() -> None:
    found = {d.key: d for d in catalogue()}
    for key in FRONTEND:
        d = found[key]
        assert (d.kind, d.lifecycle, d.model, d.mode, d.version) == (
            Kind.AGENT,
            Lifecycle.ACTIVE,
            True,
            "read_only",
            "1.0.0",
        ), key
        assert {"search_entities", "read_entity"} | CODE == set(d.tools), key
        assert d.contract.formats == ("markdown",), key
        assert all(not i.required for i in d.contract.inputs), key
        given, withheld = agent_skill_tools(d)
        assert [t.name for t in given] == ["repository-profile"] and withheld == [], key
        said = d.instructions or ""
        for section in (
            "Ce qu'il regarde",
            "Sa méthode",
            "Ce qu'il produit",
            "Ce qu'il ne doit jamais faire",
            "## Ses compétences",
        ):
            assert section in said, (key, section)
        assert "Rien d'inventé" in said and "fichier et la ligne" in said, key
        assert "Zéro constat" in said, key


def test_the_accessibility_audit_cites_its_criteria_and_never_declares_conformity() -> None:
    said = {d.key: d for d in catalogue()}["accessibility-audit"].instructions or ""
    assert "WCAG 2.2" in said and "RGAA" in said
    assert "4,5:1" in said and "sans ratio inventé" in said
    assert "jamais une\nconformité" in said or "jamais une conformité" in said


def test_the_motion_review_respects_reduced_motion_and_what_composes() -> None:
    said = {d.key: d for d in catalogue()}["motion-review"].instructions or ""
    assert "prefers-reduced-motion" in said and "2.3.3" in said
    assert "`transform` et `opacity`" in said


def test_each_is_sold_at_its_reference_tier_and_frontend_craft_is_on_sale() -> None:
    sold = commercial().add_ons
    for key, tier in FRONTEND.items():
        assert sold.agents[key].tier == tier, key
    bundle = sold.bundle("frontend-craft")
    assert bundle is not None
    assert (bundle.sellable, bundle.missing) == (True, ())
    assert set(bundle.agents) == set(FRONTEND)
    # 29 € against 9 + 9 + 15 + 15 alone: the saving its members show.
    assert (bundle.monthly_price, bundle.alone_price, bundle.savings_percent) == (2900, 4800, 40)


ASKED = [
    ("Audite l'accessibilité du formulaire d'inscription de acme/web", "accessibility-audit"),
    (
        "Est-ce que les écrans de notre front gèrent bien les états vides et les erreurs ?",
        "ui-quality-review",
    ),
    ("Fais une revue de design de l'accueil de acme/web", "design-review"),
    ("Nos transitions respectent-elles le mouvement réduit ?", "motion-review"),
]


@pytest.mark.parametrize(("text", "expected"), ASKED, ids=[e for _, e in ASKED])
def test_what_people_ask_about_an_interface_reaches_its_agent(text: str, expected: str) -> None:
    every = catalogue()
    asked = RouteQuery(text=text, goal="check_compliance", kind="compliance")
    routed = route(asked, every, {d.key: Availability(True) for d in every})
    assert routed.outcome == "routed"
    assert expected in [c.key for c in routed.selected], [
        (c.key, c.score) for c in routed.candidates[:5]
    ]
