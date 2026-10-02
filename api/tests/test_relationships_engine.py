"""The relationships of a company model, checked and kept in time (LEKA-368).

Acme's sources, through the whole pipeline — normalisation's records,
resolution, enrichment, the model's build — twice:

    PagerDuty      the service Billing API
    a catalogue    a custom source: Checkout depends on Billing API, and
                   Billing API on Checkout; the application Billing
                   platform, holding Billing API
    an HR system   a custom source: the team Data under Engineering, and
                   Engineering under Data; Nora, who reports to Sara
    Microsoft 365  Nora, who reports to Karim
    a business system  the capability Invoicing, supported by the platform

then Checkout's record goes, and the teams Platform and Mobile, under
Engineering, come — and the model is built again.

What these protect: dependency graphs built from processed evidence, each
relationship with its provenance and confidence; loops and two managers
found and said, never silently kept; what appeared, changed and went
between two builds, recorded — when each relationship first appeared,
kept; the contracts read from the registry; a dependency walk through the
relationships asked; members read it, never another workspace's.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.connectors import Capability, SourceKind
from leka.db import session_factory, workspace_scope
from leka.ingestion.enrichment.job import enrich_workspace
from leka.ingestion.normalisation import NormalisedRecord
from leka.ingestion.resolution.job import resolve_workspace
from leka.knowledge import Entity
from leka.knowledge.job import build_workspace
from tests.conftest import FakeIdentity
from tests.test_application_landscape import _record, _store
from tests.test_enrichment_job import NOW
from tests.test_resolution_job import _source
from tests.test_sources_api import FAKE_KEY, _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/knowledge"
C = Capability
BILLING = "service:billing-api"
CHECKOUT = "service:checkout"
PLATFORM_APP = "application:billing-platform"
DATA = "team:data"
ENGINEERING = "team:engineering"
PLATFORM = "team:platform"
NORA = "person:email:nora@acme.io"
SARA = "person:email:sara@acme.io"
KARIM = "person:email:karim@acme.io"
INVOICING = "capability:invoicing"


def _declared(
    entity: str, record_id: str, title: str, metadata: dict[str, Any]
) -> NormalisedRecord:
    return _record(
        SourceKind.CUSTOM_REST,
        C.RECORDS,
        {
            "resource": f"{entity}s",
            "entity": entity,
            "fields": {"id": record_id, "title": title, "metadata": metadata},
        },
        external_id=f"{entity}s:{record_id}",
        container=None,
    )


async def _build(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    await resolve_workspace(workspace)
    await enrich_workspace(workspace, now=NOW)
    await build_workspace(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            rows = await session.execute(select(Entity.key, Entity.id))
            return dict(rows.tuples().all())


async def _first(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    pagerduty, catalogue, hr, microsoft, business = [
        await _source(workspace, name)
        for name in ("PagerDuty", "Catalogue", "HR", "Microsoft 365", "Business")
    ]
    records = [
        (
            pagerduty,
            _record(
                SourceKind.PAGERDUTY,
                C.SERVICES,
                {"id": "PBILL01", "name": "Billing API", "status": "active"},
            ),
        ),
        (catalogue, _declared("service", "s-1", "Checkout", {"depends_on": "Billing API"})),
        (catalogue, _declared("service", "s-2", "Billing API", {"depends_on": "Checkout"})),
        (
            catalogue,
            _declared("application", "a-1", "Billing platform", {"services": "Billing API"}),
        ),
        (hr, _declared("team", "t-1", "Data", {"parent": "Engineering"})),
        (hr, _declared("team", "t-2", "Engineering", {"parent": "Data"})),
        (
            hr,
            _declared(
                "person", "p-1", "Nora Diallo", {"email": "nora@acme.io", "manager": "sara@acme.io"}
            ),
        ),
        (
            microsoft,
            _record(
                SourceKind.MICROSOFT_365,
                C.PEOPLE,
                {
                    "id": "u-nora",
                    "displayName": "Nora Diallo",
                    "mail": "nora@acme.io",
                    "manager": {"id": "u-karim", "mail": "karim@acme.io"},
                },
                external_id="u-nora",
                container=None,
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


async def _second(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    """Checkout's record goes; the team Platform, under Engineering, comes."""
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM normalised_records WHERE entity_key = :k"), {"k": CHECKOUT}
            )
            await session.commit()
    hr = await _source(workspace, "HR, again")
    # Two: resolution sees what normalisation made by how many and the
    # latest — one gone and one come, at the tests' one date, is no news.
    for record_id, name in (("t-3", "Platform"), ("t-4", "Mobile")):
        await _store(workspace, hr, _declared("team", record_id, name, {"parent": "Engineering"}))
    return await _build(workspace)


async def test_the_graph_its_issues_and_its_history(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    ids = await _first(workspace)
    between = datetime.now(UTC)
    _as(identity, acme, "member")

    async def page(path: str, **params: str) -> list[dict[str, Any]]:
        response = await client.get(f"{API}{path}", params={"limit": 100, **params})
        assert response.status_code == 200, response.text
        data: list[dict[str, Any]] = response.json()["data"]
        return data

    depends = await page("/relationships", type="depends_on")
    pairs = {(r["from_entity"]["key"], r["to_entity"]["key"]) for r in depends}
    assert pairs == {(CHECKOUT, BILLING), (BILLING, CHECKOUT)}
    assert all(r["origin"] == "stated" and r["confidence"] == 1.0 for r in depends)
    assert all(r["provenance"] and r["first_seen_at"] for r in depends)

    issues = {(i["type"], i["issue"]) for i in await page("/relationships/issues")}
    assert issues == {
        ("depends_on", "cycle"),
        ("child_of", "cycle"),
        ("reports_to", "several_targets"),
    }
    [two] = await page("/relationships/issues", issue="several_targets")
    assert two["from_entity"]["key"] == NORA
    assert set(two["detail"]["targets"]) == {str(ids[SARA]), str(ids[KARIM])}
    assert await page("/relationships/issues", severity="error") == []

    ids = await _second(workspace)

    went = await page("/relationships/changes", change="removed", type="depends_on")
    assert [(c["from_entity"]["key"], c["to_entity"]["key"]) for c in went] == [(CHECKOUT, BILLING)]
    assert went[0]["before"]["origin"] == "stated"
    came = await page("/relationships/changes", change="added", since=between.isoformat())
    assert (PLATFORM, ENGINEERING) in {
        (c["from_entity"]["key"], c["to_entity"]["key"]) for c in came
    }
    # Its loop gone, the dependency is no longer said.
    issues = {(i["type"], i["issue"]) for i in await page("/relationships/issues")}
    assert ("depends_on", "cycle") not in issues
    kept = await page("/relationships", type="child_of", entity_id=str(ids[ENGINEERING]))
    data = next(r for r in kept if r["from_entity"]["key"] == DATA)
    assert datetime.fromisoformat(data["first_seen_at"]) < between
    platform = next(r for r in kept if r["from_entity"]["key"] == PLATFORM)
    assert datetime.fromisoformat(platform["first_seen_at"]) >= between


async def test_the_contracts_and_a_walk_through_the_relationships_asked(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _first(acme["acme"])
    _as(identity, acme, "member")

    registry = (await client.get(f"{API}/registry")).json()
    depends = next(r for r in registry["relationships"] if r["type"] == "depends_on")
    assert (depends["meaning"], depends["dependency"], depends["acyclic"]) == (
        "depends on",
        True,
        False,
    )
    assert set(depends["sources"]) == {"service", "application", "infra_resource", "database"}
    reports = next(r for r in registry["relationships"] if r["type"] == "reports_to")
    assert (reports["single"], reports["acyclic"], reports["targets"]) == (True, True, ["person"])

    walked = await client.get(
        f"{API}/entities/{ids[INVOICING]}/dependencies", params={"through": "supported_by"}
    )
    assert [n["entity"]["key"] for n in walked.json()["nodes"]] == [PLATFORM_APP]
    plain = await client.get(f"{API}/entities/{ids[INVOICING]}/dependencies")
    assert plain.json()["nodes"] == []
    wrong = await client.get(
        f"{API}/entities/{ids[INVOICING]}/dependencies", params={"through": "part_of"}
    )
    assert wrong.status_code == 422


async def test_another_workspace_s_relationships_are_not_seen(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await _first(acme["acme"])
    _as(identity, acme, "other_admin")  # Globex's

    for path in ("/relationships", "/relationships/changes", "/relationships/issues"):
        response = await client.get(f"{API}{path}")
        assert response.status_code == 200, path
        assert response.json()["data"] == [], path
