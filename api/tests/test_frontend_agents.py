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

The designer (design-review 2.0.0) works by Emil Kowalski's design
engineering (emilkowalski/skills @ 2d22863, MIT): its core in its
instructions, word for word; every guide of the library named, read with
read_method before it judges; how they apply here said — no file written,
no command, nothing claimed seen; its deliverable the method's: the findings
before, after and why, the worst case, the phone, what should move, the
plans, and on a pull request its comments on the diff's lines. The motion
review and the interface's quality read their guides too; the motion review
never asks for ease-in again.
"""

from __future__ import annotations

import pytest

import leka.schema  # noqa: F401 — every module provides its capabilities
from leka.billing import catalogue as commercial
from leka.capabilities import Availability, Kind, Lifecycle, RouteQuery, route
from leka.capabilities.registry import catalogue
from leka.capabilities.skills import agent_skill_tools
from leka.core.config import settings

FRONTEND = {
    "ui-quality-review": "standard",
    "accessibility-audit": "standard",
    "design-review": "specialized",
    "motion-review": "specialized",
}
CODE = {"list_files", "read_file", "list_pull_requests", "read_pull_request"}
# The designer's library, and who reads it (agents/_library/README.md).
LIBRARY = "_library/emilkowalski-skills"
VERSIONS = {
    "ui-quality-review": "1.1.0",
    "accessibility-audit": "1.1.0",
    "design-review": "2.1.0",
    "motion-review": "1.1.0",
}


def test_each_is_registered_read_only_reading_the_code_it_cites() -> None:
    found = {d.key: d for d in catalogue()}
    for key in FRONTEND:
        d = found[key]
        assert (d.kind, d.lifecycle, d.model, d.mode, d.version) == (
            Kind.AGENT,
            Lifecycle.ACTIVE,
            True,
            "read_only",
            VERSIONS[key],
        ), key
        reads = {"read_method"} if d.method else set()
        assert {"search_entities", "read_entity"} | CODE | reads == set(d.tools), key
        assert d.method == (None if key == "accessibility-audit" else LIBRARY), key
        # The designer draws its proposal too: the screen before and after.
        drawn = ("markdown", "html") if key == "design-review" else ("markdown",)
        assert d.contract.formats == drawn, key
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
    # 2026-10-18: home-made widgets suspect until their keyboard is proven,
    # native HTML before ARIA, a page change announced, zoom and targets;
    # each finding with how to check its fix, and where to start.
    for step in (
        "Les composants faits maison",
        "Les changements de page",
        "L'agrandissement et les cibles",
    ):
        assert step in said, step
    assert "2.5.8" in said and "2.4.11" in said
    assert "comment vérifier" in said and "**Par où commencer**" in said
    assert "msitarzewski/agency-agents" in said


def test_the_motion_review_respects_reduced_motion_and_what_composes() -> None:
    said = {d.key: d for d in catalogue()}["motion-review"].instructions or ""
    assert "prefers-reduced-motion" in said and "2.3.3" in said
    assert "`transform` et `opacity`" in said
    # Its bar is the designer's: never ease-in, an exit included (it once
    # asked for one), and the guides read before it judges.
    assert "**Jamais `ease-in`" in said and "sortie en accélération" not in said
    assert "skills/review-animations/STANDARDS.md" in said and "**Block** ou **Approve**" in said


def test_the_interface_s_quality_breaks_it_with_real_world_data_and_on_a_phone() -> None:
    said = {d.key: d for d in catalogue()}["ui-quality-review"].instructions or ""
    assert "skills/break-ui/CATALOG.md" in said and "skills/mobile-native/SKILL.md" in said
    assert "« 1 membres »" in said and "non bornée" in said


def test_the_designer_works_by_emil_kowalski_s_method_whole() -> None:
    designer = {d.key: d for d in catalogue()}["design-review"]
    said = designer.instructions or ""
    assert (designer.rounds, designer.method) == (30, LIBRARY)
    assert [i.name for i in designer.contract.inputs] == [
        "depot",
        "perimetre",
        "reference",
        "demande",
    ]
    # Its core, word for word: emil-design-eng from « You are a design
    # engineer » to its last line, its headings one level down.
    guide = (settings.agents_dir / LIBRARY / "skills/emil-design-eng/SKILL.md").read_text()
    core = guide[guide.index("You are a design engineer") :].rstrip()
    demoted = "\n".join(
        line[1:] if line.startswith("##") else line
        for line in said[said.index("You are a design engineer") :].rstrip().split("\n")
    )
    assert demoted == core
    assert "emilkowalski/skills" in said and "MIT, © 2026 Emil Kowalski" in said
    # Every guide of its library named, read before it judges.
    for skill in sorted((settings.agents_dir / LIBRARY / "skills").iterdir()):
        assert f"`skills/{skill.name}/SKILL.md`" in said, skill.name
    for reference in ("STANDARDS.md", "AUDIT.md", "PLAN-TEMPLATE.md", "CATALOG.md", "RECIPES.md"):
        assert reference in said, reference
    assert "**Sans précision" in said and "c'est la revue\ncomplète" in said
    # How its guides apply here: nothing written, run, opened — nor claimed.
    assert "« Initial Response » ne s'applique pas" in said
    assert "Tu n'écris aucun fichier" in said and "« à vérifier à l'écran »" in said
    assert "Tu ne dis jamais l'avoir appliqué" in said
    # Its deliverable: the method's, and on a pull request, its lines.
    for part in (
        "| # | Sévérité | Où | Avant | Après | Pourquoi |",
        "**Block** ou\n   **Approve**",
        "**Le pire des cas**",
        "**Sur téléphone**",
        "**Ce qui devrait bouger — et ce qui ne doit pas**",
        "**Les plans de correction**",
        "```leka-review",
        # A design proposed is drawn: the line that asks LEKA to, and what
        # the section holds for it to draw the screen before and after.
        "### La proposition — ce que LEKA dessine",
        "<!-- leka-design -->",
        "**avec leurs valeurs**",
        "N'écris aucun HTML : LEKA dessine.",
    ):
        assert part in said, part
    assert designer.renders == "design_mockups"


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
    (
        "Qu'est-ce qui casse avec des noms très longs dans la liste des membres de acme/web ?",
        "design-review",
    ),
    ("Propose-moi un meilleur design pour la page d'accueil de acme/web", "design-review"),
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
