"""What each person's work shows they know (LEKA-365).

A workspace as resolution leaves it: Sara authored and reviewed pull
requests in billing-api — Billing API's repository, in Python — and led an
incident on Ledger; Bob reviewed one pull request; a bot committed often.

What these protect: expertise is where a person's items are — a pull
request's repository and that repository's service, an incident's service
— with its evidence (how many items, which roles, the last); nothing below
two items; nothing of a bot, who is said to be one.
"""

from __future__ import annotations

from leka.ingestion.enrichment import enrich
from leka.ingestion.enrichment.engine import Enrichment
from tests.test_enrichment import GITHUB, PAGERDUTY, World, ago

REPO = "github.com/acme/billing-api"
BILLING = "service:billing-api"
LEDGER = "service:ledger"
SARA = "person:email:sara@acme.io"
BOB = "person:github.com:bob"
BOT = "person:github.com:dependabot[bot]"


def _world() -> World:
    world = World()
    world.thing(REPO, "acme/billing-api", type="repository", language="Python")
    world.thing(BILLING, "Billing API", type="service", sources=(PAGERDUTY,))
    world.thing(LEDGER, "Ledger", type="service", sources=(PAGERDUTY,))
    world.states(GITHUB, REPO, "part_of", BILLING)
    for person, name in ((SARA, "Sara Martin"), (BOB, "bob"), (BOT, "dependabot[bot]")):
        world.thing(person, name, type="person")
    for number in range(1, 4):
        pull = f"{REPO}#{number}"
        world.thing(pull, f"Pull {number}", type="pull_request", updated_at=ago(number))
        world.states(GITHUB, pull, "part_of", REPO)
        world.states(GITHUB, pull, "authored_by", SARA)
    world.states(GITHUB, f"{REPO}#1", "reviewed_by", BOB)
    world.thing(f"{REPO}#4", "Pull 4", type="pull_request", updated_at=ago(5))
    world.states(GITHUB, f"{REPO}#4", "part_of", REPO)
    world.states(GITHUB, f"{REPO}#4", "reviewed_by", SARA)
    for number in range(5, 9):
        commit = f"{REPO}@{number:040x}"
        world.thing(commit, f"Bump {number}", type="commit", updated_at=ago(1))
        world.states(GITHUB, commit, "part_of", REPO)
        world.states(GITHUB, commit, "authored_by", BOT)
    for number in (1, 2):
        incident = f"incident:pagerduty:Q{number}"
        world.thing(incident, f"Ledger down {number}", type="incident", sources=(PAGERDUTY,))
        world.states(PAGERDUTY, incident, "affects", LEDGER)
        world.states(PAGERDUTY, incident, "led_by", SARA)
    return world


def _facts(enrichment: Enrichment, world: World, key: str) -> dict[str, object]:
    return {f.attribute: f.value for f in enrichment.facts if f.entity_id == world.id(key)}


def _contributes(enrichment: Enrichment, world: World, key: str) -> dict[str, float]:
    keys = {node.id: node.key for node in world.nodes.values()}
    return {
        keys[e.to_id]: e.confidence
        for e in enrichment.edges
        if e.from_id == world.id(key) and e.type == "contributes_to"
    }


def test_expertise_is_where_a_person_s_work_is_with_its_evidence() -> None:
    world = _world()

    enrichment = enrich(world.snapshot())

    areas = _contributes(enrichment, world, SARA)
    # The repository, its service, and the service their incidents affect.
    assert set(areas) == {REPO, BILLING, LEDGER}
    assert areas[REPO] == max(areas.values())
    shown = _facts(enrichment, world, SARA)["expertise"]
    assert isinstance(shown, list)
    first = shown[0]
    assert (first["key"], first["items"], first["roles"]) == (
        REPO,
        4,
        {"authored": 3, "reviewed": 1},
    )
    assert first["last_at"] == ago(1)
    ledger = next(area for area in shown if area["key"] == LEDGER)
    assert ledger["roles"] == {"led": 2}


def test_the_languages_of_the_code_they_work_on() -> None:
    world = _world()

    assert _facts(enrich(world.snapshot()), world, SARA)["languages"] == ["python"]


def test_one_item_is_not_expertise() -> None:
    world = _world()

    enrichment = enrich(world.snapshot())

    assert _contributes(enrichment, world, BOB) == {}
    assert "expertise" not in _facts(enrichment, world, BOB)


def test_a_bot_has_no_expertise_and_is_said_to_be_one() -> None:
    world = _world()

    enrichment = enrich(world.snapshot())

    assert _contributes(enrichment, world, BOT) == {}
    facts = _facts(enrichment, world, BOT)
    assert facts["bot"] is True
    assert "expertise" not in facts
