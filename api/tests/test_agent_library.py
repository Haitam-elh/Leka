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
(never a mere question about it). Each agent offered for sale has its case
(LEKA-447); and the router weighs what is asked, not a name in it: an agent
whose source is not connected, or that the asker may not use, is excluded,
never proposed; a question never goes to an agent that acts.
"""

from __future__ import annotations

import pytest

import leka.schema  # noqa: F401 — every module provides its capabilities
from leka.capabilities import Availability, Kind, Lifecycle, Reason, RouteQuery, route
from leka.capabilities.registry import catalogue
from leka.capabilities.skills import agent_skill_tools
from leka.capabilities.tools import NAMES
from leka.knowledge import EntityType

VERSIONS = {
    "architecture-analysis": "1.2.0",
    "code-review": "1.2.0",
    "documentation-assistant": "1.2.0",
    "security-review": "1.2.0",
    "test-analysis": "1.2.0",
}

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
        # Given their skills (LEKA-401): a new version each; the code
        # reviews and the build fixer again for their method (LEKA-447).
        assert (d.kind, d.lifecycle, d.model, d.version) == (
            Kind.AGENT,
            Lifecycle.ACTIVE,
            True,
            VERSIONS.get(key, "1.1.0"),
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
    # The agents offered for sale had no case (LEKA-447).
    (
        RouteQuery(
            text="Fais la revue de la dernière PR de payment-api",
            goal="investigate",
            kind="change",
        ),
        "code-review",
    ),
    (
        RouteQuery(
            text="Explique-moi l'architecture de checkout",
            goal="map_dependencies",
            kind="dependency",
        ),
        "architecture-analysis",
    ),
    (
        RouteQuery(
            text="Est-ce que payment-api est bien documenté ?",
            goal="find_knowledge",
            kind="knowledge",
        ),
        "documentation-assistant",
    ),
    (
        RouteQuery(
            text="payment-api renvoie des erreurs 500 depuis ce matin, pourquoi ?",
            goal="explain_cause",
            kind="diagnose",
        ),
        "debug-assistant",
    ),
    (
        RouteQuery(
            text="Sur quelle infrastructure tourne checkout ?",
            goal="map_dependencies",
            kind="dependency",
        ),
        "infrastructure-analysis",
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


@pytest.mark.parametrize(
    ("asked", "key", "why"),
    [
        (
            RouteQuery(
                text="Est-ce que payment-api est bien documenté ?",
                goal="find_knowledge",
                kind="knowledge",
            ),
            "documentation-assistant",
            Reason("missing_source", {"any_of": ["confluence"]}),
        ),
        (
            RouteQuery(
                text="Fais une revue de sécurité de payment-api",
                goal="check_compliance",
                kind="compliance",
            ),
            "security-review",
            Reason("not_permitted"),
        ),
    ],
    ids=["no-source", "not-permitted"],
)
def test_an_agent_that_cannot_run_here_is_excluded_never_proposed(
    asked: RouteQuery, key: str, why: Reason
) -> None:
    every = catalogue()
    able = {d.key: Availability(True) for d in every}
    able[key] = Availability(False, (why,))
    routed = route(asked, every, able)
    # The request is still answered — by what can run here.
    assert routed.outcome == "routed"
    assert key not in [c.key for c in routed.selected]
    assert key in [c.key for c in routed.excluded]


def test_a_name_in_the_request_is_not_enough() -> None:
    every = catalogue()
    asked = RouteQuery(
        text="Qui fait la revue de code sur payment-api ?", goal="find_owner", kind="ownership"
    )
    routed = route(asked, every, {d.key: Availability(True) for d in every})
    # « Revue de code » is in the words; who owns it is what is asked.
    assert "code-review" not in [c.key for c in routed.selected]
    assert "ownership" in [c.key for c in routed.selected]


def test_a_question_never_goes_to_an_agent_that_acts() -> None:
    every = catalogue()
    asked = RouteQuery(
        text="Pourquoi la dernière PR de checkout a cassé la prod ?",
        goal="explain_cause",
        kind="diagnose",
    )
    routed = route(asked, every, {d.key: Availability(True) for d in every})
    acting = {d.key for d in every if d.mode == "proposes_action"}
    assert acting >= {"build-fixer", "code-change"}
    assert not acting & {c.key for c in routed.selected}


def test_the_code_review_reviews_by_a_method_it_can_prove() -> None:
    # LEKA-447: ECC's code-reviewer and gstack's review, rewritten for what
    # LEKA sees — the scope said against the scope touched, a gate before
    # each finding, a severity that needs its proof, zero findings allowed.
    said = {d.key: d for d in catalogue()}["code-review"].instructions or ""
    assert "## Sa méthode" in said
    for step in (
        "périmètre annoncé",
        "La porte avant chaque constat",
        "La sévérité",
        "La confiance",
    ):
        assert step in said, step
    assert "Zéro constat est une revue valide" in said
    assert "Un avis, jamais une décision" in said
    # Credited, as their licence asks.
    assert "affaan-m/ECC" in said and "garrytan/gstack" in said


def test_the_security_review_separates_what_it_proves_from_what_it_suspects() -> None:
    # LEKA-447: gstack's cso and ECC's security-reviewer, rewritten for the
    # company model — the model first, three judgements kept apart, a
    # supported finding against a hypothesis, the unknown kept unknown.
    said = {d.key: d for d in catalogue()}["security-review"].instructions or ""
    assert "## Sa méthode" in said
    for step in (
        "Le modèle d'abord",
        "Trois jugements, séparés",
        "Un constat appuyé",
        "L'inconnu reste inconnu",
    ):
        assert step in said, step
    assert "Hypothèses" in said
    assert "Aucun constat appuyé dans le périmètre" in said
    assert "garrytan/gstack" in said and "affaan-m/ECC" in said


def test_the_build_fixer_proposes_the_smallest_fix() -> None:
    # LEKA-447: ECC's build-error-resolver, rewritten for what LEKA sees —
    # the last green against the first red, suspects ranked, the smallest
    # fix and nothing more, what that fix risks.
    said = {d.key: d for d in catalogue()}["build-fixer"].instructions or ""
    assert "## Sa méthode" in said
    for step in (
        "Le moment de la casse",
        "Les suspects, triés",
        "Le plus petit correctif",
        "Ce que le correctif risque",
    ):
        assert step in said, step
    assert "Pas de refonte, pas" in said
    assert "affaan-m/ECC" in said


def test_the_architecture_analysis_reads_the_real_links() -> None:
    # LEKA-447: ECC's architect, code-architect, code-explorer and
    # change-impact, rewritten for the company model — from the entry points,
    # by layer, each weak point proven by its links, the unverified said.
    said = {d.key: d for d in catalogue()}["architecture-analysis"].instructions or ""
    assert "## Sa méthode" in said
    for step in (
        "Les points d'entrée",
        "Les couches",
        "Les fragilités, chacune prouvée",
        "Le rayon d'impact",
        "Vérifié ou non vérifié",
    ):
        assert step in said, step
    assert "Une piste donne son compromis" in said
    assert "affaan-m/ECC" in said


def test_the_documentation_assistant_maps_what_a_reader_finds() -> None:
    # LEKA-447: gstack's document-generate and document-release, ECC's ADRs
    # and living docs, rewritten for what LEKA sees — a coverage map by the
    # reader's need, the document against the model, one source per fact.
    said = {d.key: d for d in catalogue()}["documentation-assistant"].instructions or ""
    assert "## Sa méthode" in said
    for step in (
        "La carte de couverture",
        "Le document contre le modèle",
        "Un fait, une source",
        "Les décisions",
        "Le brouillon, un lecteur à la fois",
    ):
        assert step in said, step
    assert "garrytan/gstack" in said and "affaan-m/ECC" in said


def test_the_test_analysis_plans_by_behaviour() -> None:
    # LEKA-447: ECC's pr-test-analyzer and test-collaboration, gstack's
    # test-audit, rewritten for what LEKA sees — the behaviour, not the file;
    # the right level; incidents as tests; what a green does not prove.
    said = {d.key: d for d in catalogue()}["test-analysis"].instructions or ""
    assert "## Sa méthode" in said
    for step in (
        "Le comportement, pas le fichier",
        "Le bon niveau",
        "Les incidents deviennent des tests",
        "L'écart, classé",
        "Ce qu'un vert ne prouve pas",
    ):
        assert step in said, step
    assert "ne dis jamais qu'un test manque" in said
    assert "affaan-m/ECC" in said and "garrytan/gstack" in said
