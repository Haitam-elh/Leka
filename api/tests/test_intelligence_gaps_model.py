"""Knowledge gaps, end to end (LEKA-379): what the model holds, the
findings, the API.

A small company in the model, written as a build writes it. GitHub, AWS
and Confluence are connected — Confluence last read five days ago — and no
monitoring, no database source. payment-api — critical, in production,
deployed five hours ago — runs on ecs-prod, its code in acme/payments,
part of checkout, owned by Nadia, described only by a runbook unchanged
since February. auth-service runs there too, its code in acme/auth, a
fresh guide describing it, no application holding it. user-service runs
nowhere known, its code unknown, depends on payment-api; a removed page
once described it. ledger is dormant, and payment-api still relies on it.
orphan-worker is tied to nothing. postgres-prod keeps payment-api's data,
its tables unread.

What these protect: what the model holds around each thing — how
critical, how many documents describe it, how many fresh, when the latest
changed, whether the business holds it — counting no removed document;
the analyses find each gap of each family, and only those, told apart by
code, a per-thing gap only where its family is connected, the rest as
coverage; a gap on what a current change touched weighs more; the API
serves them by category, the most pressing first, a stale source as its
own subject, with what shows it and where it was read — to a member,
never to another workspace.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.connectors.models import Source, SourceKind, SourceStatus
from leka.db import session_factory, workspace_scope
from leka.intelligence import ANALYZERS, Finding
from leka.intelligence.job import analyse_workspace
from leka.knowledge import (
    Entity,
    EntityType,
    GraphRepository,
    GraphService,
    Lifecycle,
    Relationship,
    RelationshipType,
)
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/intelligence"
NOW = datetime.now(UTC).replace(microsecond=0)
FEBRUARY = "2026-02-05T16:46:39+00:00"


async def _company(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    with workspace_scope(workspace):
        async with session_factory() as session:
            for kind, name, read in (
                (SourceKind.GITHUB, "GitHub", timedelta(hours=1)),
                (SourceKind.AWS, "AWS", timedelta(hours=1)),
                (SourceKind.CONFLUENCE, "Confluence", timedelta(days=5)),
            ):
                source = Source(
                    workspace_id=workspace,
                    kind=kind,
                    name=name,
                    status=SourceStatus.ACTIVE,
                    config={},
                    last_synced_at=NOW - read,
                )
                session.add(source)
                ids[name] = source.id = uuid.uuid4()
            await session.flush()

            def thing(
                name: str,
                type_: EntityType,
                source: str,
                *,
                at: datetime | None = None,
                lifecycle: Lifecycle = Lifecycle.ACTIVE,
                **attributes: object,
            ) -> None:
                row = Entity(
                    workspace_id=workspace,
                    type=type_,
                    key=f"{type_.value}:{name}",
                    name=name,
                    attributes=attributes,
                    provenance={
                        "sources": [{"source_id": str(ids[source]), "key": name, "kind": "id"}]
                    },
                    lifecycle=lifecycle,
                    removed_at=NOW if lifecycle is Lifecycle.REMOVED else None,
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

            thing(
                "payment-api",
                EntityType.SERVICE,
                "GitHub",
                criticality="critical",
                environment="production",
            )
            thing("auth-service", EntityType.SERVICE, "GitHub")
            thing("user-service", EntityType.SERVICE, "GitHub")
            thing("ledger", EntityType.SERVICE, "GitHub", lifecycle=Lifecycle.DORMANT)
            thing("orphan-worker", EntityType.SERVICE, "GitHub")
            thing("checkout", EntityType.APPLICATION, "GitHub")
            thing("acme/payments", EntityType.REPOSITORY, "GitHub")
            thing("acme/auth", EntityType.REPOSITORY, "GitHub")
            thing("postgres-prod", EntityType.DATABASE, "AWS")
            thing("ecs-prod", EntityType.INFRA_RESOURCE, "AWS")
            thing("nadia", EntityType.PERSON, "GitHub")
            thing(
                "Payment runbook",
                EntityType.DOCUMENT,
                "Confluence",
                freshness="stale",
                last_activity_at=FEBRUARY,
            )
            thing("Auth guide", EntityType.DOCUMENT, "Confluence", freshness="fresh")
            thing(
                "Users page",
                EntityType.DOCUMENT,
                "Confluence",
                lifecycle=Lifecycle.REMOVED,
                freshness="fresh",
            )
            thing(
                "payments v4.1.0",
                EntityType.DEPLOYMENT,
                "GitHub",
                at=NOW - timedelta(hours=5),
                state="succeeded",
                environment="production",
            )
            await session.flush()
            tie("payment-api", RelationshipType.DEPLOYED_TO, "ecs-prod")
            tie("auth-service", RelationshipType.DEPLOYED_TO, "ecs-prod")
            tie("acme/payments", RelationshipType.PART_OF, "payment-api")
            tie("acme/auth", RelationshipType.PART_OF, "auth-service")
            tie("payment-api", RelationshipType.PART_OF, "checkout")
            tie("payment-api", RelationshipType.DEPENDS_ON, "auth-service")
            tie("payment-api", RelationshipType.DEPENDS_ON, "ledger")
            tie("payment-api", RelationshipType.DEPENDS_ON, "postgres-prod")
            tie("user-service", RelationshipType.DEPENDS_ON, "payment-api")
            tie("nadia", RelationshipType.OWNS, "payment-api")
            tie("Payment runbook", RelationshipType.DESCRIBES, "payment-api")
            tie("Auth guide", RelationshipType.DESCRIBES, "auth-service")
            tie("Users page", RelationshipType.DESCRIBES, "user-service")
            tie("payments v4.1.0", RelationshipType.PART_OF, "payment-api")
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


async def _analysed(workspace: uuid.UUID) -> None:
    await analyse_workspace(workspace, trigger="model", analyzers=ANALYZERS)


async def test_what_the_model_holds_around_each_thing(
    acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID]
) -> None:
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            graph = GraphService(GraphRepository(session, acme["acme"]))
            held = await graph.standing(
                [company[name] for name in ("payment-api", "auth-service", "user-service")]
            )
            documents = await graph.documents()

    payment, auth, users = (
        held[company[name]] for name in ("payment-api", "auth-service", "user-service")
    )
    assert (payment.criticality, payment.documents, payment.fresh_documents) == ("critical", 1, 0)
    assert payment.last_documented_at == FEBRUARY
    assert payment.business is True
    assert (auth.documents, auth.fresh_documents, auth.business) == (1, 1, False)
    # The page that described it is removed: nothing does now.
    assert (users.documents, users.business) == (0, False)
    assert documents == 2


async def test_each_gap_is_found_told_apart_and_only_those(
    acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID]
) -> None:
    await _analysed(acme["acme"])

    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            found = (
                (await session.execute(select(Finding).where(Finding.category == "gaps")))
                .scalars()
                .all()
            )
    said = {(f.code, f.subject_name) for f in found}
    assert said == {
        # The runbook is all that describes payment-api, and it is stale.
        ("gap.stale_documentation", "payment-api"),
        ("gap.missing_entity.runtime", "user-service"),
        ("gap.missing_entity.code", "user-service"),
        ("gap.missing_relationship.business", "user-service"),
        ("gap.missing_documentation", "user-service"),
        ("gap.missing_relationship.business", "auth-service"),
        ("gap.missing_documentation", "postgres-prod"),
        ("gap.missing_documentation", "checkout"),
        # Tied to nothing: that, and its documentation, nothing more.
        ("gap.missing_relationship.isolated", "orphan-worker"),
        ("gap.missing_documentation", "orphan-worker"),
        # Dormant, still relied on: the one question asked of it.
        ("gap.stale_knowledge.dormant", "ledger"),
        ("gap.stale_source", "Confluence"),
        # Not connected: said once, never per thing.
        ("gap.coverage.monitoring", "monitoring"),
        ("gap.coverage.data", "data"),
    }
    # Each family under its own code, each finding its own key.
    assert len({f.key for f in found}) == len(found)
    assert {f.analyzer for f in found} == {
        "gaps_entities",
        "gaps_relationships",
        "gaps_documentation",
        "gaps_staleness",
        "gaps_coverage",
    }
    by = {(f.code, f.subject_name): f for f in found}
    # Critical, in production, relied on, deployed five hours ago: first.
    stale = by[("gap.stale_documentation", "payment-api")]
    assert stale.severity == "high"
    assert stale.params["signals"] == ["relied_on", "critical", "production", "changing"]
    assert stale.rank == max(f.rank for f in found)
    assert stale.subject_id == company["payment-api"]


async def test_the_api_serves_gaps_most_pressing_first_with_what_shows_them(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    company: dict[str, uuid.UUID],
) -> None:
    await _analysed(acme["acme"])

    catalogue = {a["name"]: a for a in await _get(client, "/analyzers")}
    assert {name for name, a in catalogue.items() if a["category"] == "gaps"} == {
        "gaps_entities",
        "gaps_relationships",
        "gaps_documentation",
        "gaps_staleness",
        "gaps_coverage",
    }
    assert catalogue["gaps_coverage"]["reads"] == ["model"]

    gaps = (await _get(client, "/findings", category="gaps", limit=100))["data"]
    assert len(gaps) == 14
    ranks = [f["rank"] for f in gaps]
    assert ranks == sorted(ranks, reverse=True)
    assert (gaps[0]["code"], gaps[0]["subject"]["name"]) == (
        "gap.stale_documentation",
        "payment-api",
    )

    # A stale source: its own subject, what shows it, where it was read.
    stale = (
        await _get(
            client, "/findings", analyzer="gaps_staleness", subject=str(company["Confluence"])
        )
    )["data"]
    [source] = stale
    assert source["subject"] == {
        "type": "source",
        "id": str(company["Confluence"]),
        "name": "Confluence",
        "kind": "confluence",
    }
    detail = await _get(client, f"/findings/{source['id']}")
    assert detail["evidence"][0]["kind"] == "source"
    assert detail["evidence"][0]["id"] == str(company["Confluence"])
    assert detail["provenance"]["analyzer"] == "gaps_staleness"
    assert detail["provenance"]["sources"] == ["confluence"]
    assert detail["params"]["status"] == "active"

    # A coverage gap: about a family, no entity.
    [monitoring] = [f for f in gaps if f["code"] == "gap.coverage.monitoring"]
    assert monitoring["subject"] == {
        "type": "coverage",
        "id": None,
        "name": "monitoring",
        "kind": "monitoring",
    }
    assert monitoring["params"]["count"] == 4

    _as(identity, acme, "other_admin")
    assert (await _get(client, "/findings", category="gaps"))["data"] == []
    assert (await client.get(f"{API}/findings/{source['id']}")).status_code == 404
