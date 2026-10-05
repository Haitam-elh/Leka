"""Change and impact, end to end (LEKA-378): footprints, findings, the API.

A small company in the model, written as a build writes it: payment-api
calls auth-service, user-service calls payment-api, checkout holds
payment-api. auth-service's code lives in acme/auth. A production
deployment in acme/auth 26 hours ago; two hours later an incident on
payment-api; another incident whose source says the deployment caused it,
two days and a half later; an older incident, before it; a staging
deployment of user-service five hours ago; a change request on
user-service ten days ago.

What these protect: a change in a repository is made to the service the
repository is part of; it reaches what depends on that, two steps, and the
application holding it; the incidents on that footprint within 48 hours
follow it, and one its source ties to it whenever it opened — never one
that opened before; the analysis makes a finding of the deployment and of
nothing else; the API lists the changes, current or history, around an
entity too, and details one, its impacts ranked, what followed and how
long after — to a member, never to another workspace.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.db import session_factory, workspace_scope
from leka.intelligence import ANALYZERS, Finding
from leka.intelligence.changes import AFTER
from leka.intelligence.job import analyse_workspace
from leka.knowledge import (
    Entity,
    EntityType,
    GraphRepository,
    GraphService,
    Relationship,
    RelationshipType,
)
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/intelligence"
NOW = datetime.now(UTC).replace(microsecond=0)


async def _company(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    with workspace_scope(workspace):
        async with session_factory() as session:

            def thing(
                name: str, type_: EntityType, *, at: datetime | None = None, **attributes: object
            ) -> None:
                row = Entity(
                    workspace_id=workspace,
                    type=type_,
                    key=f"{type_.value}:{name}",
                    name=name,
                    attributes=attributes,
                    provenance={},
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                    occurred_at=at,
                )
                session.add(row)
                ids[name] = row.id = uuid.uuid4()

            def tie(a: str, kind: RelationshipType, b: str) -> None:
                session.add(
                    Relationship(
                        workspace_id=workspace,
                        from_entity_id=ids[a],
                        to_entity_id=ids[b],
                        type=kind,
                        confidence=1.0,
                        origin="stated",
                        rule="stated",
                        provenance=[],
                    )
                )

            for name in ("auth-service", "payment-api", "user-service"):
                thing(name, EntityType.SERVICE)
            thing("checkout", EntityType.APPLICATION)
            thing("acme/auth", EntityType.REPOSITORY)
            deployed = NOW - timedelta(hours=26)
            thing(
                "auth v3.2.0",
                EntityType.DEPLOYMENT,
                at=deployed,
                state="succeeded",
                environment="production",
                ref="v3.2.0",
            )
            thing(
                "OPS-1 payment errors",
                EntityType.INCIDENT,
                at=deployed + timedelta(hours=2),
                state="open",
                severity="sev2",
            )
            thing(
                "OPS-2 login loop",
                EntityType.INCIDENT,
                at=deployed + timedelta(hours=60),
                state="open",
                severity="sev3",
            )
            thing("OPS-0 earlier", EntityType.INCIDENT, at=deployed - timedelta(hours=3))
            thing(
                "users staging",
                EntityType.DEPLOYMENT,
                at=NOW - timedelta(hours=5),
                state="succeeded",
                environment="staging",
            )
            thing(
                "CHG-12 users schema",
                EntityType.CHANGE,
                at=NOW - timedelta(days=10),
                state="completed",
            )
            await session.flush()
            tie("payment-api", RelationshipType.DEPENDS_ON, "auth-service")
            tie("user-service", RelationshipType.DEPENDS_ON, "payment-api")
            tie("payment-api", RelationshipType.PART_OF, "checkout")
            tie("acme/auth", RelationshipType.PART_OF, "auth-service")
            tie("auth v3.2.0", RelationshipType.PART_OF, "acme/auth")
            tie("OPS-1 payment errors", RelationshipType.AFFECTS, "payment-api")
            tie("OPS-0 earlier", RelationshipType.AFFECTS, "payment-api")
            tie("OPS-2 login loop", RelationshipType.CAUSED_BY, "auth v3.2.0")
            tie("users staging", RelationshipType.PART_OF, "user-service")
            tie("CHG-12 users schema", RelationshipType.AFFECTS, "user-service")
            await session.commit()
    return ids


@pytest.fixture
async def company(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids = await _company(acme["acme"])
    _as(identity, acme, "member")
    return ids


async def _get(client: AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_change_is_made_to_its_service_and_reaches_what_depends_on_it(
    acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID]
) -> None:
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            graph = GraphService(GraphRepository(session, acme["acme"]))
            found, truncated = await graph.footprints(
                since=NOW - timedelta(days=30),
                until=NOW + timedelta(minutes=1),
                limit=10,
                after=AFTER,
            )

    assert not truncated
    assert [f.change.name for f in found] == ["users staging", "auth v3.2.0", "CHG-12 users schema"]
    deployment = found[1]
    assert {(t.entity.name, t.how) for t in deployment.touched} == {
        ("acme/auth", "part_of"),
        ("auth-service", "via_repository"),
    }
    assert [(r.entity.name, r.distance, r.through.name) for r in deployment.reached] == [
        ("payment-api", 1, "auth-service"),
        ("user-service", 2, "auth-service"),
    ]
    assert [a.name for a in deployment.applications] == ["checkout"]
    # Followed within 48 hours on its footprint, or tied by its source —
    # never what opened before it.
    assert [
        (i.entity.name, i.stated, i.on.name if i.on else None) for i in deployment.incidents
    ] == [
        ("OPS-2 login loop", True, None),
        ("OPS-1 payment errors", False, "payment-api"),
    ]
    assert deployment.details == {"ref": "v3.2.0"}


async def test_the_deployment_an_incident_followed_is_a_finding_and_nothing_else_is(
    acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID]
) -> None:
    await analyse_workspace(acme["acme"], trigger="model", analyzers=ANALYZERS)

    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            found = (
                (await session.execute(select(Finding).where(Finding.analyzer == "change_impact")))
                .scalars()
                .all()
            )
    [finding] = found
    assert finding.key == f"change:{company['auth v3.2.0']}"
    assert (finding.severity, finding.subject_name, finding.subject_id) == (
        "high",
        "auth-service",
        company["auth-service"],
    )
    # The source ties OPS-2 to it: sure.
    assert finding.confidence == 1.0
    assert finding.params["incidents"] == 2
    top = finding.params["top"]
    assert isinstance(top, list)
    assert top[0] == "payment-api"


async def test_the_api_lists_changes_current_or_history_and_around_an_entity(
    client: AsyncClient, company: dict[str, uuid.UUID]
) -> None:
    timeline = await _get(client, "/changes")
    rows = {row["name"]: row for row in timeline["changes"]}

    assert list(rows) == ["users staging", "auth v3.2.0", "CHG-12 users schema"]
    assert rows["auth v3.2.0"]["current"] is True
    assert set(rows["auth v3.2.0"]["signals"]) >= {"production", "incident_after", "stated_cause"}
    assert rows["CHG-12 users schema"]["current"] is False
    assert rows["users staging"]["significance"] < rows["auth v3.2.0"]["significance"]

    # Around payment-api: what was made to it, or to what it depends on —
    # auth-service's repository included.
    around = await _get(client, "/changes", entity=str(company["payment-api"]))
    assert [row["name"] for row in around["changes"]] == ["auth v3.2.0"]

    refused = await client.get(
        f"{API}/changes",
        params={"since": NOW.isoformat(), "until": (NOW - timedelta(days=1)).isoformat()},
    )
    assert refused.status_code == 422


async def test_the_api_details_a_change_its_impacts_ranked_and_what_followed(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    company: dict[str, uuid.UUID],
) -> None:
    detail = await _get(client, f"/changes/{company['auth v3.2.0']}")

    # The incident hit payment-api: first, though one step away.
    assert [i["subject"]["name"] for i in detail["impacts"]][:2] == ["payment-api", "acme/auth"]
    assert "incident" in detail["impacts"][0]["reasons"]
    assert [a["name"] for a in detail["applications"]] == ["checkout"]
    followed = {f["subject"]["name"]: f for f in detail["followed"]}
    assert followed["OPS-1 payment errors"]["hours_after"] == 2.0
    assert followed["OPS-1 payment errors"]["on"]["name"] == "payment-api"
    assert followed["OPS-2 login loop"]["stated"] is True

    # Not a change: none. Another workspace's: none.
    assert (await client.get(f"{API}/changes/{company['payment-api']}")).status_code == 404
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/changes/{company['auth v3.2.0']}")).status_code == 404
    assert (await _get(client, "/changes"))["changes"] == []
