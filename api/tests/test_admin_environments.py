"""Environments & integrations in LEKA ADMIN (LEKA-555): every organisation's
sources, reads and what they found; one environment whole; its map.

What these protect:
- Across LEKA: sources counted by how they stand (failing, degraded, not read
  for three hours, disabled), the services found, the reads of the last 24
  hours, each connector LEKA CORE has with who uses it; demonstrations left
  out.
- One row per organisation, its state the worst of its sources'.
- One environment: its sources' diagnostics typed and scanned for secrets,
  its reads, what was found, how sure LEKA is of what ties it together —
  confirmed, supposed, unknown — and the latest changes; never a credential
  nor a source's settings; the reading kept in the admin trail.
- Its map: only the relationships the data holds, each confirmed or supposed
  as its origin says — never a supposed one as certain — what says it
  scanned for secrets, what is tied to nothing said so, the sources it was
  read from verified or not.
- A source in error is read without failing the list (a diagnostic, not a
  string).
"""

# ruff: noqa: F811 — the admin world's fixtures are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from leka.admin import AdminAuditEvent, AdminRole
from leka.connectors import HealthStatus, Source, SourceKind, SourceStatus, SyncStatus, manifests
from leka.db import session_factory, system_scope
from leka.ingestion import SyncRun
from leka.knowledge import (
    Entity,
    EntityType,
    ModelRun,
    Relationship,
    RelationshipChange,
    RelationshipIssue,
    RelationshipType,
)
from tests.test_admin_api import API, NOW, SUPER, World, as_, world  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

OPS = AdminRole.OPERATIONS
# What must never come out: a token in a vendor's error, a password in a
# repository's configuration, a source's settings.
TOKEN = "ghp_" + "a" * 36
PASSWORD = "hunter2-very-secret"
SETTING = "https://internal-only.acme.example"


def _source(world: World, kind: SourceKind, name: str, **said: Any) -> Source:
    values: dict[str, Any] = {
        "workspace_id": world.alpha,
        "id": uuid.uuid4(),
        "kind": kind,
        "name": name,
        "status": SourceStatus.ACTIVE,
        "config": {"base_url": SETTING},
        "health_status": HealthStatus.HEALTHY,
        "sync_status": SyncStatus.IDLE,
        "last_synced_at": NOW - timedelta(minutes=30),
    }
    return Source(**(values | said))


def _entity(
    world: World, type_: EntityType, name: str, source: Source, **attributes: object
) -> Entity:
    return Entity(
        workspace_id=world.alpha,
        id=uuid.uuid4(),
        type=type_,
        key=f"{type_.value}:{name}:{world.marker}",
        name=name,
        attributes=attributes,
        provenance={"sources": [{"source_id": str(source.id), "key": name, "kind": "x"}]},
        first_seen_at=NOW - timedelta(days=3),
        last_seen_at=NOW - timedelta(minutes=30),
    )


async def _bare(world: World) -> None:
    """Alpha without the source the admin world gave it: its environment is
    then only what a test says."""
    with system_scope():
        async with session_factory() as session:
            await session.execute(delete(Source).where(Source.workspace_id == world.alpha))
            await session.commit()


async def _environment(world: World) -> dict[str, Any]:
    """Alpha: GitHub read half an hour ago, AWS failing, Jira not read for
    five hours, Slack disabled; a service depending on its database, as
    the code says, and run by an instance, as a rule supposes; a service
    tied to nothing."""
    github = _source(world, SourceKind.GITHUB, "GitHub Acme")
    aws = _source(
        world,
        SourceKind.AWS,
        "AWS production",
        status=SourceStatus.ERROR,
        health_status=HealthStatus.UNHEALTHY,
        sync_status=SyncStatus.FAILED,
        last_error={
            "code": "AUTH_EXPIRED",
            "retryable": False,
            "message": f"The key expired (it was {TOKEN}).",
            "remediation": "Give LEKA a new access key.",
            "provider_status": 403,
            "detail": None,
        },
    )
    jira = _source(world, SourceKind.JIRA, "Jira", last_synced_at=NOW - timedelta(hours=5))
    slack = _source(world, SourceKind.SLACK, "Slack", status=SourceStatus.DISABLED)
    await _bare(world)
    with system_scope():
        async with session_factory() as session:
            session.add_all([github, aws, jira, slack])
            await session.flush()
            checkout = _entity(
                world, EntityType.SERVICE, "checkout", github, environment="production"
            )
            orders = _entity(world, EntityType.DATABASE, "orders-db", github)
            lonely = _entity(world, EntityType.SERVICE, "lonely", github)
            instance = _entity(world, EntityType.INFRA_RESOURCE, "i-0abc", aws)
            session.add_all([checkout, orders, lonely, instance])
            await session.flush()
            session.add_all(
                [
                    Relationship(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        from_entity_id=checkout.id,
                        to_entity_id=orders.id,
                        type=RelationshipType.DEPENDS_ON,
                        origin="stated",
                        rule="stated",
                        confidence=1.0,
                        provenance=[
                            {
                                "source_id": str(github.id),
                                "evidence": "stores: deploy/app.yml:12 — DATABASE_URL="
                                f"postgres://app:{PASSWORD}@db/orders",
                            }
                        ],
                        first_seen_at=NOW - timedelta(days=2),
                    ),
                    Relationship(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        from_entity_id=checkout.id,
                        to_entity_id=instance.id,
                        type=RelationshipType.DEPLOYED_TO,
                        origin="inferred",
                        rule="deployed_together",
                        confidence=0.6,
                        provenance=[],
                        first_seen_at=NOW - timedelta(days=1),
                    ),
                    RelationshipChange(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        from_entity_id=checkout.id,
                        to_entity_id=orders.id,
                        type="depends_on",
                        change="added",
                        before=None,
                        after={"origin": "stated", "rule": "stated", "confidence": 1.0},
                        recorded_at=NOW - timedelta(days=2),
                    ),
                    RelationshipIssue(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        from_entity_id=checkout.id,
                        to_entity_id=instance.id,
                        type="deployed_to",
                        issue="end_refused",
                        severity="warning",
                        origin="inferred",
                        rule="deployed_together",
                        confidence=0.6,
                    ),
                    SyncRun(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        source_id=github.id,
                        trigger="schedule",
                        full_read=False,
                        status="succeeded",
                        started_at=NOW - timedelta(minutes=31),
                        finished_at=NOW - timedelta(minutes=30),
                        records=120,
                    ),
                    SyncRun(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        source_id=aws.id,
                        trigger="schedule",
                        full_read=False,
                        status="failed",
                        started_at=NOW - timedelta(minutes=20),
                        finished_at=NOW - timedelta(minutes=19),
                        records=0,
                        error={
                            "code": "AUTH_EXPIRED",
                            "retryable": False,
                            "message": f"Denied: password={PASSWORD}",
                            "remediation": "Renew it.",
                        },
                    ),
                    ModelRun(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        status="succeeded",
                        started_at=NOW - timedelta(minutes=12),
                        finished_at=NOW - timedelta(minutes=10),
                        model_version=1,
                    ),
                ]
            )
            await session.commit()
    return {
        "github": github,
        "aws": aws,
        "jira": jira,
        "checkout": checkout,
        "orders": orders,
        "lonely": lonely,
        "instance": instance,
    }


def _never_secret(text: str) -> None:
    for said in (TOKEN, PASSWORD, SETTING, "base_url", "credential"):
        assert said not in text, said


async def test_environments_across_leka_counted_as_their_sources_stand(
    client: AsyncClient, world: World
) -> None:
    async def read() -> dict[str, Any]:
        response = await client.get(f"{API}/environments/overview", headers=as_(world, OPS))
        assert response.status_code == 200, response.text
        found: dict[str, Any] = response.json()
        return found

    await _bare(world)
    before = await read()
    await _environment(world)
    after = await read()
    moved = {
        key: after[key] - before[key]
        for key in (
            "organisations",
            "organisations_in_error",
            "sources",
            "active",
            "in_error",
            "degraded",
            "stale",
            "disabled",
            "services",
            "syncs",
            "syncs_failed",
        )
    }
    assert moved == {
        "organisations": 1,
        "organisations_in_error": 1,
        "sources": 3,
        "active": 2,
        "in_error": 1,
        "degraded": 0,
        "stale": 1,
        "disabled": 1,
        "services": 2,
        "syncs": 2,
        "syncs_failed": 1,
    }
    # Every connector LEKA CORE has, those used first.
    keys = [c["key"] for c in after["connectors"]]
    assert sorted(keys) == sorted(str(m.key) for m in manifests())
    github = next(c for c in after["connectors"] if c["key"] == "github")
    github_before = next(c for c in before["connectors"] if c["key"] == "github")
    assert github["sources"] - github_before["sources"] == 1
    aws = next(c for c in after["connectors"] if c["key"] == "aws")
    assert aws["in_error"] >= 1 and aws["category"] == "cloud"


async def test_one_row_per_organisation_its_state_the_worst_of_its_sources(
    client: AsyncClient, world: World
) -> None:
    await _environment(world)
    response = await client.get(
        f"{API}/environments", params={"q": f"alpha-{world.marker}"}, headers=as_(world, OPS)
    )
    assert response.status_code == 200, response.text
    [row] = response.json()["data"]
    assert row["organisation"]["id"] == str(world.alpha)
    assert (row["state"], row["sources"], row["in_error"]) == ("error", 3, 1)
    assert row["kinds"] == ["aws", "github", "jira"]
    assert (row["services"], row["entities"], row["relationships"], row["failed_syncs"]) == (
        2,
        4,
        2,
        1,
    )

    failing = await client.get(
        f"{API}/environments", params={"in_error": "true", "limit": 200}, headers=as_(world, OPS)
    )
    assert str(world.alpha) in {r["organisation"]["id"] for r in failing.json()["data"]}
    # The demonstration, never; one with nothing connected, said so.
    everyone = await client.get(
        f"{API}/environments", params={"q": world.marker, "limit": 200}, headers=as_(world, OPS)
    )
    assert str(world.demo) not in {r["organisation"]["id"] for r in everyone.json()["data"]}
    connected = await client.get(
        f"{API}/environments",
        params={"connected": "true", "q": world.marker},
        headers=as_(world, OPS),
    )
    assert [r["organisation"]["id"] for r in connected.json()["data"]] == [str(world.alpha)]


async def test_one_environment_whole_its_errors_scanned_its_relations_as_sure_as_they_are(
    client: AsyncClient, world: World
) -> None:
    await _environment(world)
    response = await client.get(f"{API}/environments/{world.alpha}", headers=as_(world, OPS))
    assert response.status_code == 200, response.text
    _never_secret(response.text)
    said = response.json()
    assert said["state"] == "error" and said["built_at"] is not None
    aws = next(s for s in said["sources"] if s["kind"] == "aws")
    assert aws["last_error"]["code"] == "AUTH_EXPIRED"
    assert aws["last_error"]["remediation"] == "Give LEKA a new access key."
    assert aws["last_error"]["provider_status"] == 403
    assert "[redacted:" in aws["last_error"]["message"]
    # The latest read first, its diagnostic said.
    assert [(r["source"]["kind"], r["status"]) for r in said["syncs"]] == [
        ("aws", "failed"),
        ("github", "succeeded"),
    ]
    assert said["syncs"][0]["error"]["code"] == "AUTH_EXPIRED"
    assert said["failed_syncs"] == 1
    assert said["entities"] == {"service": 2, "database": 1, "infra_resource": 1}
    services = {s["name"]: s for s in said["services"]}
    assert set(services) == {"checkout", "orders-db", "lonely"}
    assert services["checkout"]["environment"] == "production"
    assert [s["name"] for s in services["checkout"]["sources"]] == ["GitHub Acme"]
    assert said["relations"] == {"confirmed": 1, "supposed": 1, "unknown": 1, "issues": 1}
    [change] = said["history"]
    assert (change["from_name"], change["to_name"], change["change"], change["certainty"]) == (
        "checkout",
        "orders-db",
        "added",
        "confirmed",
    )
    async with session_factory() as session:
        kept = (
            await session.scalars(
                select(AdminAuditEvent).where(
                    AdminAuditEvent.action == "admin.viewed",
                    AdminAuditEvent.target_type == "environment",
                    AdminAuditEvent.target_id == str(world.alpha),
                )
            )
        ).all()
    assert len(kept) == 1

    missing = await client.get(f"{API}/environments/{uuid.uuid4()}", headers=as_(world, OPS))
    assert missing.status_code == 404


async def test_the_map_only_what_the_data_holds_never_a_supposition_as_certain(
    client: AsyncClient, world: World
) -> None:
    await _environment(world)
    response = await client.get(f"{API}/environments/{world.alpha}/map", headers=as_(world, SUPER))
    assert response.status_code == 200, response.text
    _never_secret(response.text)
    said = response.json()
    nodes = {n["name"]: n for n in said["nodes"]}
    assert {"checkout", "orders-db", "lonely"} <= set(nodes)
    by_ends = {(link["from_id"], link["to_id"]): link for link in said["links"]}
    stated = by_ends[(nodes["checkout"]["id"], nodes["orders-db"]["id"])]
    assert (stated["certainty"], stated["origin"], stated["sources"]) == (
        "confirmed",
        "stated",
        ["github"],
    )
    assert stated["evidence"] is not None and "[redacted:" in stated["evidence"]
    supposed = [link for link in said["links"] if link["origin"] == "inferred"]
    assert supposed and all(link["certainty"] == "supposed" for link in supposed)
    assert all(
        link["certainty"] == "confirmed"
        for link in said["links"]
        if link["origin"] in ("stated", "accepted")
    )
    # Tied to nothing: what it relies on is unknown, said so.
    assert nodes["lonely"]["linked"] is False
    assert said["confirmed"] == sum(1 for link in said["links"] if link["certainty"] == "confirmed")
    sources = {s["name"]: s for s in said["sources"]}
    # Where it was read from: verified when active, healthy and read once.
    assert {name: s["verified"] for name, s in sources.items()} == {
        "GitHub Acme": True,
        "AWS production": False,
        "Jira": True,
        "Slack": False,
    }
    assert said["unverified"] == 2
    assert sources["GitHub Acme"]["entities"] == 3
    assert {n["name"]: (n["column"], n["linked"]) for n in said["nodes"]} == {
        "checkout": ("services", True),
        "lonely": ("services", False),
        "orders-db": ("data", True),
        "i-0abc": ("cloud", True),
    }
    assert sorted((link["origin"], link["certainty"]) for link in said["links"]) == [
        ("inferred", "supposed"),
        ("stated", "confirmed"),
    ]
    assert (said["confirmed"], said["supposed"], said["unknown"]) == (1, 1, 1)


async def test_a_source_in_error_is_listed_its_diagnostic_typed(
    client: AsyncClient, world: World
) -> None:
    await _environment(world)
    response = await client.get(
        f"{API}/sources",
        params={"organisation_id": str(world.alpha), "in_error": "true"},
        headers=as_(world, OPS),
    )
    assert response.status_code == 200, response.text
    _never_secret(response.text)
    [failing] = response.json()["data"]
    assert (failing["kind"], failing["last_error"]["code"]) == ("aws", "AUTH_EXPIRED")


async def test_environments_are_refused_to_who_does_not_read_them(
    client: AsyncClient, world: World
) -> None:
    for path in (
        "/environments/overview",
        "/environments",
        f"/environments/{world.alpha}",
        f"/environments/{world.alpha}/map",
        f"/environments/{world.alpha}/syncs",
    ):
        refused = await client.get(f"{API}{path}", headers=as_(world, AdminRole.FINANCE))
        assert refused.status_code == 403, path


async def test_an_environment_s_reads_page_by_page_those_that_failed(
    client: AsyncClient, world: World
) -> None:
    await _environment(world)
    failed = await client.get(
        f"{API}/environments/{world.alpha}/syncs",
        params={"status": "failed"},
        headers=as_(world, OPS),
    )
    assert failed.status_code == 200, failed.text
    _never_secret(failed.text)
    assert [(r["source"]["name"], r["status"]) for r in failed.json()["data"]] == [
        ("AWS production", "failed")
    ]
