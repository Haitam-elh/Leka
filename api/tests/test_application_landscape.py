"""An application landscape, modelled from five tools (LEKA-362).

Acme's billing, as its tools see it — vendor payloads through the whole
pipeline: extraction, parsing, normalisation, stored as normalisation
leaves them, then entity resolution, enrichment and the company model's
build, then the API.

    PagerDuty   Billing API (Payments' team), which depends on Ledger;
                Ledger; the business service Online shop, Billing API's
    Datadog     the catalog: billing-api — team payments, application
                Billing, tier 1, in production; ledger — deprecated, tier
                2, part of the Billing system, depending on postgres-ledger
    AWS         billing-api's instances, one in production, one in
                staging, tagged with its application; Ledger's database, in
                production
    GitHub      the acme/billing-api repository
    a CMDB      a custom source: Billing API — "high", Payments', in
                production and staging; a sandbox, in staging, on Ledger

What these protect: one service per real one, whatever tool names it, with
every source it came from and what the tools disagree on, every value kept;
its application, team, criticality, stage and environments; relationships
true in some environments only kept apart; dependencies queried both ways,
in one environment or all; members read the landscape — never another
workspace's.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.connectors import Capability, SourceKind
from leka.db import session_factory, workspace_scope
from leka.ingestion.enrichment.job import enrich_workspace
from leka.ingestion.normalisation import NormalisedRecord, normalise
from leka.ingestion.parsing import ParsedRecord, parse
from leka.ingestion.resolution.job import resolve_workspace
from leka.knowledge import Entity, Relationship
from leka.knowledge.job import build_workspace
from tests.conftest import FakeIdentity
from tests.test_datadog_resources import BILLING_V22
from tests.test_enrichment_job import NOW, _normalised
from tests.test_extraction import _extract
from tests.test_pagerduty_connector import ONLINE_SHOP
from tests.test_resolution_job import _source
from tests.test_sources_api import FAKE_KEY, _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/knowledge"
ARN = "arn:aws:ec2:eu-west-3:123456789012"
C = Capability

BILLING = "service:billing-api"
LEDGER = "service:ledger"
POSTGRES = "service:postgres-ledger"
SANDBOX = "service:billing-sandbox"
APP = "application:billing"
SHOP = "application:online-shop"
PRODUCTION = "environment:production"
STAGING = "environment:staging"

LEDGER_V3: dict[str, Any] = {
    "id": "d-ledger",
    "attributes": {
        "schema": {
            "apiVersion": "v3",
            "kind": "service",
            "metadata": {"name": "ledger", "owner": "finance-platform"},
            "spec": {
                "lifecycle": "deprecated",
                "tier": "2",
                "dependsOn": ["service:postgres-ledger"],
                "componentOf": ["system:billing"],
            },
        }
    },
}


def _record(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> NormalisedRecord:
    extracted = _extract(kind, capability, payload, **extra)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)
    result = normalise(extracted, parsed)
    assert isinstance(result, NormalisedRecord), result
    return result


async def _store(
    workspace: uuid.UUID,
    source: uuid.UUID,
    record: NormalisedRecord,
    *,
    external_id: str | None = None,
) -> None:
    """A record as normalisation leaves it in `normalised_records`, from the
    workspace's own source."""

    def ours(model: Any) -> dict[str, Any]:
        dumped: dict[str, Any] = model.model_dump(mode="json")
        dumped["source_id"] = str(source)
        return dumped

    await _normalised(
        workspace,
        source,
        ours(record.entity),
        *[ours(e) for e in record.related],
        relationships=tuple(ours(r) for r in record.relationships),
        external_id=external_id,
    )


def _custom(title: str, metadata: dict[str, Any]) -> NormalisedRecord:
    return _record(
        SourceKind.CUSTOM_REST,
        C.RECORDS,
        {
            "resource": "services",
            "entity": "service",
            "fields": {"id": title, "title": title, "metadata": metadata},
        },
        external_id=f"services:{title}",
    )


def _instance(name: str, tags: dict[str, str]) -> NormalisedRecord:
    return _record(
        SourceKind.AWS,
        C.INSTANCES,
        {"InstanceId": name, "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]},
        container="eu-west-3",
        external_id=f"{ARN}:instance/{name}",
    )


async def _landscape(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    """The five tools, normalised, stored, resolved, enriched, built: the
    model's ids, by key."""
    pagerduty, datadog, aws, github, cmdb = [
        await _source(workspace, name) for name in ("PagerDuty", "Datadog", "AWS", "GitHub", "CMDB")
    ]
    records = [
        (
            pagerduty,
            _record(
                SourceKind.PAGERDUTY,
                C.SERVICES,
                {
                    "id": "PBILL01",
                    "name": "Billing API",
                    "status": "active",
                    "teams": [{"summary": "Payments"}],
                    "dependencies": [{"id": "PLEDG01", "name": "Ledger", "type": "technical"}],
                },
            ),
        ),
        (
            pagerduty,
            _record(
                SourceKind.PAGERDUTY,
                C.SERVICES,
                {"id": "PLEDG01", "name": "Ledger", "status": "active", "dependencies": []},
            ),
        ),
        (
            pagerduty,
            _record(
                SourceKind.PAGERDUTY,
                C.SERVICES,
                {
                    **ONLINE_SHOP,
                    "dependencies": [{"id": "PBILL01", "name": "Billing API", "type": "technical"}],
                },
            ),
        ),
        (datadog, _record(SourceKind.DATADOG, C.SERVICES, BILLING_V22)),
        (datadog, _record(SourceKind.DATADOG, C.SERVICES, LEDGER_V3)),
        (
            aws,
            _instance(
                "i-prod",
                {"service": "billing-api", "application": "Billing", "env": "prod"},
            ),
        ),
        (aws, _instance("i-staging", {"service": "billing-api", "env": "staging"})),
        (
            aws,
            _record(
                SourceKind.AWS,
                C.DB_INSTANCES,
                {
                    "DBInstanceIdentifier": "ledger-prod",
                    "Engine": "postgres",
                    "TagList": [
                        {"Key": "service", "Value": "ledger"},
                        {"Key": "env", "Value": "production"},
                    ],
                },
                container="eu-west-3",
                external_id=f"{ARN}:db:ledger-prod",
            ),
        ),
        (
            github,
            _record(
                SourceKind.GITHUB,
                C.REPOSITORIES,
                {"full_name": "acme/billing-api", "owner": {"login": "acme"}},
            ),
        ),
        (
            cmdb,
            _custom(
                "Billing API",
                {"criticality": "high", "owner": "Payments", "environments": "prod, staging"},
            ),
        ),
        (cmdb, _custom("Billing sandbox", {"environments": "staging", "dependencies": "ledger"})),
    ]
    for source, record in records:
        await _store(workspace, source, record)
    await resolve_workspace(workspace)
    await enrich_workspace(workspace, now=NOW)
    await build_workspace(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            rows = await session.execute(select(Entity.key, Entity.id))
            return dict(rows.tuples().all())


async def _entity(workspace: uuid.UUID, entity_id: uuid.UUID) -> Entity:
    with workspace_scope(workspace):
        async with session_factory() as session:
            found = await session.get(Entity, entity_id)
            assert found is not None
            return found


async def _edge(workspace: uuid.UUID, a: uuid.UUID, kind: str, b: uuid.UUID) -> Relationship:
    with workspace_scope(workspace):
        async with session_factory() as session:
            found = await session.scalar(
                select(Relationship).where(
                    Relationship.from_entity_id == a,
                    Relationship.to_entity_id == b,
                    Relationship.type == kind,
                )
            )
            assert found is not None, (a, kind, b)
            return found


# ── the model ────────────────────────────────────────────────────────────────


async def test_one_service_per_real_one_whatever_tool_names_it(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    billing = await _entity(workspace, ids[BILLING])
    # PagerDuty, Datadog, AWS's tags and the CMDB: one service, four sources.
    assert len({s["source_id"] for s in billing.provenance["sources"]}) == 4  # type: ignore[attr-defined]
    assert billing.type.value == "service"
    # The tools disagree on how critical it is: both values kept, with who
    # said each; the one chosen is on LEKA's scale.
    [conflict] = [
        c
        for c in billing.provenance["conflicts"]  # type: ignore[attr-defined]
        if c["attribute"] == "criticality"
    ]
    assert {v["value"] for v in conflict["values"]} == {"critical", "high"}
    assert billing.attributes["criticality"] == conflict["chosen"]
    assert billing.provenance["attributes"]["criticality"]["disputed"] is True  # type: ignore[index]
    assert billing.attributes["stage"] == "production"
    assert billing.attributes["environments"] == ["production", "staging"]


async def test_applications_teams_and_dependencies_are_relationships(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    for a, kind, b in (
        (BILLING, "part_of", APP),
        (BILLING, "part_of", SHOP),
        (LEDGER, "part_of", APP),
        (BILLING, "depends_on", LEDGER),
        (LEDGER, "depends_on", POSTGRES),
        (SANDBOX, "depends_on", LEDGER),
        (BILLING, "runs_in", PRODUCTION),
        (BILLING, "runs_in", STAGING),
        (LEDGER, "runs_in", PRODUCTION),
    ):
        await _edge(workspace, ids[a], kind, ids[b])
    ledger = await _entity(workspace, ids[LEDGER])
    assert (ledger.attributes["stage"], ledger.attributes["criticality"]) == ("deprecated", "high")
    application = await _entity(workspace, ids[APP])
    # As critical as its most critical service, inferred and said so.
    assert application.attributes["criticality"] in ("critical", "high")
    assert application.provenance["attributes"]["criticality"]["origin"] == "enrichment"  # type: ignore[index]


async def test_relationships_true_in_one_environment_stay_apart(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)
    instances = {key: ids[key] for key in ids if key.startswith("aws:") and "instance" in key}
    prod = next(i for k, i in instances.items() if k.endswith("i-prod"))
    staging = next(i for k, i in instances.items() if k.endswith("i-staging"))

    assert (await _edge(workspace, prod, "part_of", ids[BILLING])).attributes == {
        "environments": ["production"]
    }
    assert (await _edge(workspace, staging, "part_of", ids[BILLING])).attributes == {
        "environments": ["staging"]
    }
    # Ledger is seen in production only: Billing API's dependency on it is
    # production's; the sandbox's joins its staging to Ledger's production.
    assert (await _edge(workspace, ids[BILLING], "depends_on", ids[LEDGER])).attributes == {
        "environments": ["production"]
    }
    assert (await _edge(workspace, ids[SANDBOX], "depends_on", ids[LEDGER])).attributes == {
        "environments": ["production", "staging"]
    }


# ── the API ──────────────────────────────────────────────────────────────────


async def test_members_read_the_services_and_filter_them(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "member")

    async def names(**params: str | int) -> list[str]:
        response = await client.get(f"{API}/services", params={"limit": 100, **params})
        assert response.status_code == 200, response.text
        return [row["key"] for row in response.json()["data"]]

    every = (await client.get(f"{API}/services", params={"limit": 100})).json()["data"]
    billing = next(row for row in every if row["key"] == BILLING)
    assert [a["key"] for a in billing["applications"]] == [APP, SHOP]
    assert [o["key"] for o in billing["owners"]] == ["team:payments"]
    assert billing["environments"] == ["production", "staging"]
    assert billing["stage"] == "production"
    assert billing["criticality"]["level"] in ("critical", "high")
    assert billing["criticality"]["origin"] == "source"
    assert (billing["dependencies"], billing["dependents"]) == (1, 0)
    assert await names(stage="deprecated") == [LEDGER]
    assert set(await names(environment="staging")) == {BILLING, SANDBOX}
    assert set(await names(application_id=str(ids[APP]))) == {BILLING, LEDGER}
    assert await names(team_id=str(ids["team:payments"])) == [BILLING]
    assert await names(q="sandbox") == [SANDBOX]


async def test_applications_say_how_many_services_they_hold(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "member")

    listed = (await client.get(f"{API}/applications")).json()["data"]
    detail = (await client.get(f"{API}/applications/{ids[APP]}")).json()

    counts = {row["key"]: row["services"] for row in listed}
    assert counts == {APP: 2, SHOP: 1}
    assert {p["entity"]["key"] for p in detail["parts"]} >= {BILLING, LEDGER}
    assert detail["criticality"]["origin"] == "enrichment"
    wrong = await client.get(f"{API}/services/{ids[APP]}")
    assert wrong.status_code == 404  # an application is not a service


async def test_a_service_s_detail_says_what_it_is_made_of_where(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "member")

    detail = (await client.get(f"{API}/services/{ids[BILLING]}")).json()

    parts = {p["entity"]["key"]: p["environments"] for p in detail["parts"]}
    assert parts[f"aws:{ARN}:instance/i-prod"] == ["production"]
    assert parts[f"aws:{ARN}:instance/i-staging"] == ["staging"]
    assert "github.com/acme/billing-api" in parts
    assert [(d["entity"]["key"], d["environments"]) for d in detail["depends_on"]] == [
        (LEDGER, ["production"])
    ]
    assert detail["depended_on_by"] == []
    assert detail["provenance"]["conflicts"]


async def test_dependencies_are_walked_both_ways_in_one_environment_or_all(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "member")

    async def walk(entity: str, **params: str | int) -> dict[str, int]:
        response = await client.get(f"{API}/entities/{ids[entity]}/dependencies", params=params)
        assert response.status_code == 200, response.text
        return {n["entity"]["key"]: n["depth"] for n in response.json()["nodes"]}

    assert await walk(BILLING) == {LEDGER: 1, POSTGRES: 2}
    assert await walk(BILLING, depth=1) == {LEDGER: 1}
    # In staging, nothing Billing API depends on is known to run there.
    assert await walk(BILLING, environment="staging") == {}
    # What a failure of Ledger reaches — in staging, the sandbox alone.
    assert await walk(LEDGER, direction="upstream") == {BILLING: 1, SANDBOX: 1}
    assert await walk(LEDGER, direction="upstream", environment="staging") == {SANDBOX: 1}
    whole = (await client.get(f"{API}/entities/{ids[BILLING]}/dependencies")).json()
    # Ledger runs in production only: what it is on, it is on there.
    assert [(r["type"], r["attributes"]) for r in whole["relationships"]] == [
        ("depends_on", {"environments": ["production"]})
    ] * 2
    assert whole["truncated"] is False


async def test_another_workspace_s_landscape_is_not_found(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "other_admin")  # Globex's

    for path in (
        f"/services/{ids[BILLING]}",
        f"/applications/{ids[APP]}",
        f"/entities/{ids[BILLING]}/dependencies",
    ):
        assert (await client.get(f"{API}{path}")).status_code == 404, path
    assert (await client.get(f"{API}/services")).json()["data"] == []
    assert (await client.get(f"{API}/applications")).json()["data"] == []
