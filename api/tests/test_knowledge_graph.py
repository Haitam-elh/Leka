"""The knowledge graph, explored (LEKA-369): search, walks, paths, views.

Acme's sources, through the whole pipeline — normalisation's records,
resolution, enrichment, the model's build:

    PagerDuty      the service Billing API — a monitoring source watches it
    a catalogue    Checkout, of the application Shop, depends on Billing
                   API; Billing API, of the application Billing platform;
                   both owned by the team Payments
    an HR system   the team Équipe Données under Engineering; Nora — in
                   Payments, reporting to Sara
    a business system  the capability Invoicing, supported by the Billing
                   platform

What these protect: search finds a thing by its name or its other words,
whatever their accents, case and punctuation, the very name first, where
each is and what the ones found say of one another; a walk reaches what it
should, so far and no further, through the relationships asked; the
shortest ways between two things, none past the depth asked; each
landscape draws its rows, boxes, states and lines, says its coverage and
its sources; all of it read by members, never another workspace's.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from leka.connectors import Capability, SourceKind, SourceService
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity
from tests.test_application_landscape import _record, _store
from tests.test_relationships_engine import _build, _declared
from tests.test_resolution_job import _source
from tests.test_sources_api import FAKE_KEY, _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/knowledge"
BILLING = "service:billing-api"
CHECKOUT = "service:checkout"
PLATFORM = "application:billing-platform"
SHOP = "application:shop"
PAYMENTS = "team:payments"
DATA = "team:equipe-donnees"
ENGINEERING = "team:engineering"
NORA = "person:email:nora@acme.io"
INVOICING = "capability:invoicing"


async def _pagerduty(workspace_id: uuid.UUID) -> uuid.UUID:
    """A PagerDuty source: a monitoring source, which says a service is
    watched."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            created = await SourceService(session, workspace_id, actor_user_id=None).create(
                SourceKind.PAGERDUTY, "PagerDuty", {}, {"api_key": FAKE_KEY}
            )
            await session.commit()
            return created.id


async def _acme(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    pagerduty = await _pagerduty(workspace)
    catalogue, hr, business = [
        await _source(workspace, name) for name in ("Catalogue", "HR", "Business")
    ]
    records = [
        (
            pagerduty,
            _record(
                SourceKind.PAGERDUTY,
                Capability.SERVICES,
                {"id": "PBILL01", "name": "Billing API", "status": "active"},
            ),
        ),
        (
            catalogue,
            _declared(
                "service",
                "s-1",
                "Checkout",
                {"depends_on": "Billing API", "team": "Payments", "application": "Shop"},
            ),
        ),
        (
            catalogue,
            _declared(
                "service",
                "s-2",
                "Billing API",
                {"team": "Payments", "application": "Billing platform"},
            ),
        ),
        (hr, _declared("team", "t-1", "Équipe Données", {"parent": "Engineering"})),
        (
            hr,
            _declared(
                "person",
                "p-1",
                "Nora Diallo",
                {"email": "nora@acme.io", "manager": "sara@acme.io", "team": "Payments"},
            ),
        ),
        (
            business,
            _declared(
                "business_capability", "c-1", "Invoicing", {"applications": "Billing platform"}
            ),
        ),
    ]
    for source, record in records:
        await _store(workspace, source, record)
    return await _build(workspace)


@pytest.fixture
async def graph(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids = await _acme(acme["acme"])
    _as(identity, acme, "member")
    return ids


async def _get(client: AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_search_finds_by_name_and_words_the_best_first(
    client: AsyncClient, graph: dict[str, uuid.UUID]
) -> None:
    found = await _get(client, "/search", q="billing")
    keys = [hit["entity"]["key"] for hit in found["entities"]]
    assert set(keys[:2]) == {BILLING, PLATFORM}
    billing = next(hit for hit in found["entities"] if hit["entity"]["key"] == BILLING)
    assert billing["sources"] == ["pagerduty", "slack"]
    assert billing["holder"]["key"] == PLATFORM
    # What the two found say of each other.
    said = {
        (r["from_entity"]["key"], r["type"], r["to_entity"]["key"]) for r in found["relationships"]
    }
    assert (BILLING, "part_of", PLATFORM) in said

    # Accents and case are nothing; each word a prefix; an address a word.
    [team] = (await _get(client, "/search", q="equipe DONN"))["entities"]
    assert team["entity"]["key"] == DATA
    [nora] = (await _get(client, "/search", q="nora", type="person"))["entities"]
    assert (nora["entity"]["key"], nora["holder"]["key"]) == (NORA, PAYMENTS)
    exact = await _get(client, "/search", q="Checkout")
    assert exact["entities"][0]["entity"]["key"] == CHECKOUT
    # The very name first, however it is written: its case changes are not
    # where a word breaks, but where it may.
    for typed in ("Billing API", "billing-api", "BillingApi", "billi api"):
        hits = (await _get(client, "/search", q=typed))["entities"]
        assert hits[0]["entity"]["key"] == BILLING, typed

    assert (await _get(client, "/search", q="--- !"))["entities"] == []
    assert (await _get(client, "/search", q="billing", type="team"))["entities"] == []


async def test_a_walk_reaches_so_far_through_what_is_asked(
    client: AsyncClient, graph: dict[str, uuid.UUID]
) -> None:
    async def walk(**params: Any) -> dict[str, int]:
        found = await _get(client, "/graph", root=str(graph[CHECKOUT]), **params)
        assert found["nodes"][0]["entity"]["key"] == CHECKOUT
        return {n["entity"]["key"]: n["depth"] for n in found["nodes"]}

    assert await walk(relationship="depends_on", direction="outgoing") == {CHECKOUT: 0, BILLING: 1}
    assert await walk(relationship="depends_on", direction="incoming") == {CHECKOUT: 0}
    around = await walk(depth=2)
    assert {BILLING: 1, PAYMENTS: 1, SHOP: 1, PLATFORM: 2, NORA: 2}.items() <= around.items()
    assert await walk(depth=2, entity_type=["service", "application"]) == {
        CHECKOUT: 0,
        BILLING: 1,
        SHOP: 1,
        PLATFORM: 2,
    }

    found = await _get(client, "/graph", root=str(graph[CHECKOUT]), depth=4, limit=3)
    assert (len(found["nodes"]), found["truncated"]) == (3, True)
    # The relationships among what was reached, whichever way they point.
    found = await _get(client, "/graph", root=str(graph[BILLING]), relationship="depends_on")
    assert [(r["type"], r["to_entity_id"]) for r in found["relationships"]] == [
        ("depends_on", str(graph[BILLING]))
    ]

    missing = await client.get(f"{API}/graph", params={"root": str(uuid.uuid4())})
    assert missing.status_code == 404
    too_deep = await client.get(f"{API}/graph", params={"root": str(graph[CHECKOUT]), "depth": 5})
    assert too_deep.status_code == 422


async def test_the_shortest_ways_between_two_things(
    client: AsyncClient, graph: dict[str, uuid.UUID]
) -> None:
    found = await _get(
        client, "/graph/paths", **{"from": str(graph[NORA]), "to": str(graph[BILLING])}
    )
    assert found["length"] == 2
    [way] = found["paths"]
    assert [e["key"] for e in way["entities"]] == [NORA, PAYMENTS, BILLING]
    assert [r["type"] for r in way["relationships"]] == ["member_of", "owned_by"]

    # Nora → Payments ← Billing API → Billing platform ← Invoicing.
    far = await _get(
        client, "/graph/paths", **{"from": str(graph[NORA]), "to": str(graph[INVOICING])}
    )
    assert far["length"] == 4
    assert all(len(p["entities"]) == 5 for p in far["paths"])
    short = await _get(
        client,
        "/graph/paths",
        **{"from": str(graph[NORA]), "to": str(graph[INVOICING]), "max_depth": 2},
    )
    assert (short["length"], short["paths"]) == (None, [])
    only = await _get(
        client,
        "/graph/paths",
        **{"from": str(graph[NORA]), "to": str(graph[BILLING]), "relationship": "depends_on"},
    )
    assert only["length"] is None

    same = await _get(client, "/graph/paths", **{"from": str(graph[NORA]), "to": str(graph[NORA])})
    assert same["length"] == 0


async def test_the_landscapes_rows_states_lines_coverage_and_sources(
    client: AsyncClient, graph: dict[str, uuid.UUID]
) -> None:
    company = await _get(client, "/views/company")
    layers = {layer["name"]: layer for layer in company["layers"]}
    assert list(layers) == ["users", "applications", "services", "data", "infrastructure"]
    assert (layers["users"]["types"], layers["users"]["total"]) == ([], 0)
    assert (layers["applications"]["types"], layers["applications"]["total"]) == (
        ["application"],
        2,
    )
    boxes = {node["key"]: node for node in company["nodes"]}
    assert boxes[BILLING]["status"] == "operational"  # PagerDuty watches it
    assert boxes[CHECKOUT]["status"] == "unmonitored"
    assert boxes[CHECKOUT]["team"]["key"] == PAYMENTS
    lines = {(line["from_id"], line["to_id"], line["type"]) for line in company["edges"]}
    assert (str(graph[CHECKOUT]), str(graph[SHOP]), "part_of") in lines
    assert (str(graph[CHECKOUT]), str(graph[BILLING]), "depends_on") in lines
    assert company["built_at"] is not None

    known = {row["type"]: row for row in company["coverage"]}
    assert known["service"] == {
        "type": "service",
        "total": 2,
        "owned": 2,
        "documented": 0,
        "corroborated": 1,
        "connected": 2,
    }
    kinds = {source["kind"] for source in company["sources"]}
    assert kinds == {"pagerduty", "slack"}

    organisation = await _get(client, "/views/organisation")
    known = {row["type"]: row for row in organisation["coverage"]}
    assert known["person"]["owned"] is None and known["person"]["documented"] is None
    names = {node["name"] for node in organisation["nodes"]}
    assert {"Payments", "Équipe Données", "Engineering", "Nora Diallo"} <= names

    domains = await _get(client, "/views/domains")
    rows = {layer["name"]: layer["total"] for layer in domains["layers"]}
    # Only the applications the business relies on: not Shop.
    assert (rows["capabilities"], rows["applications"]) == (1, 1)

    unknown = await client.get(f"{API}/views/everything")
    assert unknown.status_code == 422


async def test_the_coverage_of_every_kind(client: AsyncClient, graph: dict[str, uuid.UUID]) -> None:
    found = await _get(client, "/coverage")
    kinds = {row["type"]: row["total"] for row in found["kinds"]}
    assert {"service": 2, "application": 2, "business_capability": 1}.items() <= kinds.items()
    assert {source["kind"] for source in found["sources"]} == {"pagerduty", "slack"}


async def test_another_workspace_s_graph_is_not_seen(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _acme(acme["acme"])
    _as(identity, acme, "other_admin")  # Globex's

    assert (await _get(client, "/search", q="billing"))["entities"] == []
    walked = await client.get(f"{API}/graph", params={"root": str(ids[CHECKOUT])})
    assert walked.status_code == 404
    ways = await client.get(
        f"{API}/graph/paths", params={"from": str(ids[NORA]), "to": str(ids[BILLING])}
    )
    assert ways.status_code == 404
    company = await _get(client, "/views/company")
    assert (company["nodes"], company["coverage"], company["sources"]) == ([], [], [])
