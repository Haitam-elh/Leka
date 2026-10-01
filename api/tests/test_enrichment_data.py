"""Enrichment of the data (LEKA-364): what a schema, a database and the
instance serving it hold, from their tables; where they run, from the
instance.

A workspace as resolution leaves it: an RDS instance in production, the
ledger database it serves, its schema `billing` — customers (contact,
identity: confidential), secrets (credential: restricted), a plain table —
and `reporting`, which holds nothing said.

What these protect: the most sensitive classification of what it holds,
every kind of data, said as enrichment's with its rule — never over what a
source says; a database and its schemas run where the instance serving
them runs.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from leka.ingestion.enrichment import enrich
from leka.ingestion.enrichment.engine import Enrichment
from tests.test_enrichment import GITHUB, World

INSTANCE = "aws:arn:aws:rds:eu-west-3:123456789012:db:ledger-prod"
DATABASE = "db:postgresql://ledger.abc.rds.amazonaws.com:5432/ledger"
BILLING = f"{DATABASE}/billing"
REPORTING = f"{DATABASE}/reporting"


def _world() -> World:
    world = World()
    world.thing(
        INSTANCE,
        "ledger-prod",
        type="database",
        provider="aws",
        environment="production",
        environment_confidence=0.95,
    )
    world.thing("environment:production", "production", type="environment")
    world.thing(DATABASE, "ledger", type="database", engine="postgresql")
    world.thing(BILLING, "billing", type="schema")
    world.thing(REPORTING, "reporting", type="schema")
    tables: dict[str, dict[str, Any]] = {
        "customers": {
            "data_categories": ["contact", "identity"],
            "classification": "confidential",
            "personal_data": True,
        },
        "secrets": {"data_categories": ["credential"], "classification": "restricted"},
        "plans": {},
    }
    for name, attributes in tables.items():
        world.thing(f"{BILLING}/{name}", f"billing.{name}", type="data_object", **attributes)
        world.states(GITHUB, f"{BILLING}/{name}", "part_of", BILLING)
    world.thing(f"{REPORTING}/totals", "reporting.totals", type="data_object")
    world.states(GITHUB, f"{REPORTING}/totals", "part_of", REPORTING)
    world.states(GITHUB, BILLING, "part_of", DATABASE)
    world.states(GITHUB, REPORTING, "part_of", DATABASE)
    world.states(GITHUB, DATABASE, "part_of", INSTANCE)
    return world


def _facts(enrichment: Enrichment, world: World, key: str) -> dict[str, tuple[object, str]]:
    return {
        f.attribute: (f.value, f.rule) for f in enrichment.facts if f.entity_id == world.id(key)
    }


def test_a_schema_holds_what_its_tables_hold_the_most_sensitive_first() -> None:
    world = _world()

    facts = _facts(enrich(world.snapshot()), world, BILLING)

    assert facts["classification"] == ("restricted", "objects")
    assert facts["data_categories"] == (["contact", "credential", "identity"], "objects")
    assert facts["personal_data"] == (True, "objects")


def test_a_database_and_its_instance_hold_what_their_schemas_hold() -> None:
    world = _world()

    enrichment = enrich(world.snapshot())

    assert _facts(enrichment, world, DATABASE)["classification"] == ("restricted", "objects")
    assert _facts(enrichment, world, INSTANCE)["data_categories"][0] == [
        "contact",
        "credential",
        "identity",
    ]


def test_a_schema_that_holds_nothing_said_says_nothing() -> None:
    world = _world()

    assert _facts(enrich(world.snapshot()), world, REPORTING).keys() <= {"environment"}


def test_what_a_source_says_of_a_schema_stands() -> None:
    world = _world()
    node = world.nodes[world.id(BILLING)]
    world.nodes[node.id] = replace(node, attributes={"classification": "internal"})

    facts = _facts(enrich(world.snapshot()), world, BILLING)

    assert "classification" not in facts
    # What goes up is the most sensitive: its restricted table, not its word.
    assert _facts(enrich(world.snapshot()), world, DATABASE)["classification"][0] == "restricted"


def test_a_database_and_its_schemas_run_where_the_instance_serving_them_runs() -> None:
    world = _world()

    enrichment = enrich(world.snapshot())

    assert _facts(enrichment, world, DATABASE)["environment"] == ("production", "container")
    assert _facts(enrichment, world, BILLING)["environment"] == ("production", "container")
