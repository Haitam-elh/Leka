"""Incidents, changes and deployments, modelled from five sources (LEKA-367).

Acme's operations, as its tools see them — the connectors' payloads through
the whole pipeline: extraction, parsing, normalisation, stored as
normalisation leaves them, then entity resolution, enrichment and the
company model's build, then the API.

    GitHub          acme/billing-api; its deployments: v1.4.0 to production
                    on 28 September at 11:30 — done at 11:40 — by Sara, and
                    v1.3.9 to staging the day before
    PagerDuty       the service Billing API; the incident Q1 on it, opened
                    at noon, acknowledged at 12:05, resolved at 13:00; a
                    change event on it at 10:00
    Jira            the change request CHG-3, and the incident OPS-7 it is
                    said to have caused
    a catalogue     a custom source: the application Billing platform,
                    holding Billing API; the service Checkout, depending on it
    a business system  a custom source: the capability Invoicing, which the
                    Billing platform supports

What these protect: incidents, changes and deployments, each with when it
happened, its states and the dates its sources give — their origin the
source's; what each touched and shipped; what caused an incident — said,
or suspected, with why; what changed before it, and what it reaches, up to
the business; a thing's timeline; members read it, never another
workspace's.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.connectors import Capability, SourceKind
from leka.db import session_factory, workspace_scope
from leka.ingestion.enrichment.job import enrich_workspace
from leka.ingestion.normalisation import NormalisedRecord
from leka.ingestion.resolution.job import resolve_workspace
from leka.knowledge import Entity
from leka.knowledge.job import build_workspace
from tests.conftest import FakeIdentity
from tests.test_application_landscape import _edge, _entity, _record, _store
from tests.test_enrichment_job import NOW
from tests.test_resolution_job import _source
from tests.test_sources_api import FAKE_KEY, _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/knowledge"
C = Capability
SITE = "acme.atlassian.net"
REPO = "github.com/acme/billing-api"
RELEASE = f"{REPO}/deployments/42"
STAGING = f"{REPO}/deployments/41"
BILLING = "service:billing-api"
CHECKOUT = "service:checkout"
PLATFORM = "application:billing-platform"
INVOICING = "capability:invoicing"
INCIDENT = "incident:pagerduty:Q1"
FLAG = "change:pagerduty:PCE1"
CHANGE = f"{SITE}/CHG-3"
JIRA_INCIDENT = f"{SITE}/OPS-7"
SARA = "person:github.com:sara"
SHA = "a" * 40


def _deployment(
    number: int, ref: str, environment: str, created: str, done: str
) -> NormalisedRecord:
    return _record(
        SourceKind.GITHUB,
        C.DEPLOYMENTS,
        {
            "url": f"https://api.github.com/repos/acme/billing-api/deployments/{number}",
            "id": number,
            "node_id": f"DE_{number}",
            "sha": SHA,
            "ref": ref,
            "environment": environment,
            "creator": {"login": "sara"},
            "created_at": created,
            "updated_at": done,
            "statuses": [
                {"state": "success", "created_at": done},
                {"state": "in_progress", "created_at": created},
            ],
        },
        external_id=f"DE_{number}",
        container="acme/billing-api",
    )


def _jira(key: str, kind: str, created: str, **fields: Any) -> NormalisedRecord:
    return _record(
        SourceKind.JIRA,
        C.ISSUES,
        {
            "key": key,
            "self": f"https://{SITE}/rest/api/3/issue/{key}",
            "fields": {
                "summary": f"{kind} {key}",
                "issuetype": {"name": kind},
                "status": {"name": "Done", "statusCategory": {"key": "done"}},
                "created": created,
                "updated": created,
                **fields,
            },
        },
        external_id=key,
        container=key.split("-")[0],
    )


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


async def _operations(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    """The five sources, normalised, stored, resolved, enriched, built: the
    model's ids, by key."""
    github, pagerduty, jira, catalogue, business = [
        await _source(workspace, name)
        for name in ("GitHub", "PagerDuty", "Jira", "Catalogue", "Business")
    ]
    records = [
        (
            github,
            _record(
                SourceKind.GITHUB,
                C.REPOSITORIES,
                {"full_name": "acme/billing-api", "owner": {"login": "acme"}},
            ),
        ),
        (
            github,
            _deployment(42, "v1.4.0", "production", "2026-09-28T11:30:00Z", "2026-09-28T11:40:00Z"),
        ),
        (
            github,
            _deployment(41, "v1.3.9", "staging", "2026-09-27T15:00:00Z", "2026-09-27T15:05:00Z"),
        ),
        (
            pagerduty,
            _record(
                SourceKind.PAGERDUTY,
                C.SERVICES,
                {"id": "PBILL01", "name": "Billing API", "status": "active"},
            ),
        ),
        (
            pagerduty,
            _record(
                SourceKind.PAGERDUTY,
                C.INCIDENTS,
                {
                    "id": "Q1",
                    "title": "Invoices fail to send",
                    "html_url": "https://acme.pagerduty.com/incidents/Q1",
                    "status": "resolved",
                    "urgency": "high",
                    "incident_number": 42,
                    "created_at": "2026-09-28T12:00:00Z",
                    "updated_at": "2026-09-28T13:00:00Z",
                    "resolved_at": "2026-09-28T13:00:00Z",
                    "acknowledgements": [{"at": "2026-09-28T12:05:00Z"}],
                    "service": {"id": "PBILL01", "summary": "Billing API"},
                },
                external_id="Q1",
                container="PBILL01",
            ),
        ),
        (
            pagerduty,
            _record(
                SourceKind.PAGERDUTY,
                C.CHANGES,
                {
                    "id": "PCE1",
                    "summary": "Feature flag flipped",
                    "timestamp": "2026-09-28T10:00:00Z",
                    "services": [{"id": "PBILL01", "summary": "Billing API"}],
                },
                external_id="PCE1",
                container="PBILL01",
            ),
        ),
        (jira, _jira("CHG-3", "Normal change", "2026-09-26T09:00:00.000+0000")),
        (
            jira,
            _jira(
                "OPS-7",
                "Incident",
                "2026-09-27T08:00:00.000+0000",
                issuelinks=[
                    {
                        "type": {"name": "Causes", "inward": "is caused by"},
                        "inwardIssue": {"key": "CHG-3"},
                    }
                ],
            ),
        ),
        (
            catalogue,
            _declared("application", "a-1", "Billing platform", {"services": "Billing API"}),
        ),
        (catalogue, _declared("service", "s-1", "Checkout", {"depends_on": "Billing API"})),
        (
            business,
            _declared(
                "business_capability", "c-1", "Invoicing", {"applications": "Billing platform"}
            ),
        ),
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


# ── the model ────────────────────────────────────────────────────────────────


async def test_each_event_says_when_it_happened_and_its_dates_are_its_source_s(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _operations(workspace)

    incident = await _entity(workspace, ids[INCIDENT])
    assert incident.occurred_at == datetime(2026, 9, 28, 12, tzinfo=UTC)
    a = incident.attributes
    assert (a["acknowledged_at"], a["resolved_at"], a["time_to_acknowledge_minutes"]) == (
        "2026-09-28T12:05:00Z",
        "2026-09-28T13:00:00Z",
        5,
    )
    origins = incident.provenance["attributes"]
    assert isinstance(origins, dict)
    assert origins["resolved_at"] == {"origin": "source", "rule": "record"}
    deployment = await _entity(workspace, ids[RELEASE])
    # Done at 11:40: when it happened.
    assert deployment.occurred_at == datetime(2026, 9, 28, 11, 40, tzinfo=UTC)
    assert deployment.attributes["state"] == "succeeded"


async def test_what_each_touched_shipped_and_caused(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _operations(workspace)

    for a, kind, b in (
        (RELEASE, "part_of", REPO),
        (RELEASE, "deployed_to", "environment:production"),
        (FLAG, "affects", BILLING),
        (INCIDENT, "affects", BILLING),
        (JIRA_INCIDENT, "caused_by", CHANGE),
    ):
        edge = await _edge(workspace, ids[a], kind, ids[b])
        assert edge.origin == "stated", (a, kind, b)
    suspected = await _edge(workspace, ids[INCIDENT], "caused_by", ids[RELEASE])
    assert (suspected.origin, suspected.rule, suspected.confidence) == (
        "inferred",
        "preceded",
        0.7,
    )
    flag = await _edge(workspace, ids[INCIDENT], "caused_by", ids[FLAG])
    assert flag.confidence == 0.6


# ── the API ──────────────────────────────────────────────────────────────────


async def test_members_read_the_incidents_the_latest_first(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _operations(acme["acme"])
    _as(identity, acme, "member")

    async def keys(**params: str) -> list[str]:
        response = await client.get(f"{API}/incidents", params=params)
        assert response.status_code == 200, response.text
        return [row["key"] for row in response.json()["data"]]

    rows = (await client.get(f"{API}/incidents")).json()["data"]
    assert [row["key"] for row in rows] == [INCIDENT, JIRA_INCIDENT]
    q1 = rows[0]
    assert (q1["state"], q1["urgency"], q1["time_to_acknowledge_minutes"]) == ("closed", "high", 5)
    assert q1["url"] == "https://acme.pagerduty.com/incidents/Q1"
    assert [s["key"] for s in q1["affects"]] == [BILLING]
    assert [c["key"] for c in q1["causes"]] == [RELEASE, FLAG]
    assert await keys(service_id=str(ids[BILLING])) == [INCIDENT]
    assert await keys(cause_id=str(ids[CHANGE])) == [JIRA_INCIDENT]
    assert await keys(since="2026-09-28T00:00:00Z") == [INCIDENT]

    detail = (await client.get(f"{API}/incidents/{ids[INCIDENT]}")).json()
    said = [(s["step"], s["at"]) for s in detail["timeline"] if s["origin"] == "source"]
    assert said == [
        ("opened", "2026-09-28T12:00:00Z"),
        ("acknowledged", "2026-09-28T12:05:00Z"),
        ("resolved", "2026-09-28T13:00:00Z"),
    ]
    assert [s["state"] for s in detail["timeline"] if s["origin"] == "model"] == ["closed"]
    assert [(c["entity"]["key"], c["rule"]) for c in detail["suspected_causes"]] == [
        (RELEASE, "preceded"),
        (FLAG, "preceded"),
    ]
    before = {(e["entity"]["key"], e["kind"]) for e in detail["changed_before"]}
    assert before == {(RELEASE, "deployment"), (FLAG, "change"), (STAGING, "deployment")}
    impact = detail["impact"]
    assert [a["key"] for a in impact["affected"]] == [BILLING]
    assert [d["key"] for d in impact["dependents"]] == [CHECKOUT]
    assert [a["key"] for a in impact["applications"]] == [PLATFORM]
    [capability] = impact["capabilities"]
    assert (capability["entity"]["key"], capability["path"]) == (INVOICING, "contained")
    assert (await client.get(f"{API}/incidents/{ids[CHANGE]}")).status_code == 404


async def test_members_read_the_deployments_and_the_changes(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _operations(acme["acme"])
    _as(identity, acme, "member")

    rows = (await client.get(f"{API}/deployments")).json()["data"]
    assert [row["key"] for row in rows] == [RELEASE, STAGING]
    release = rows[0]
    assert (release["environment"], release["state"], release["duration_minutes"]) == (
        "production",
        "succeeded",
        10,
    )
    assert (release["repository"]["key"], release["deployer"]["key"]) == (REPO, SARA)
    assert [s["key"] for s in release["services"]] == [BILLING]
    assert release["incident_count"] == 1
    staging = await client.get(f"{API}/deployments", params={"environment": "staging"})
    assert [row["key"] for row in staging.json()["data"]] == [STAGING]
    of_billing = await client.get(f"{API}/deployments", params={"service_id": str(ids[BILLING])})
    assert len(of_billing.json()["data"]) == 2

    detail = (await client.get(f"{API}/deployments/{ids[RELEASE]}")).json()
    assert [(s["state"], s["at"]) for s in detail["status_history"]] == [
        ("in_progress", "2026-09-28T11:30:00Z"),
        ("succeeded", "2026-09-28T11:40:00Z"),
    ]
    assert [e["key"] for e in detail["environments"]] == ["environment:production"]
    assert [i["entity"]["key"] for i in detail["incidents"]] == [INCIDENT]

    changes = (await client.get(f"{API}/changes")).json()["data"]
    assert [row["key"] for row in changes] == [FLAG, CHANGE]
    assert (changes[1]["change_type"], changes[1]["state"]) == ("normal", "completed")
    jira = (await client.get(f"{API}/changes/{ids[CHANGE]}")).json()
    assert [(i["entity"]["key"], i["origin"]) for i in jira["incidents"]] == [
        (JIRA_INCIDENT, "stated")
    ]


async def test_a_thing_s_timeline_and_the_workspace_s(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _operations(acme["acme"])
    _as(identity, acme, "member")

    window = {"since": "2026-09-27T00:00:00Z", "until": "2026-09-29T00:00:00Z"}
    around = (
        await client.get(f"{API}/timeline", params={"entity_id": str(ids[BILLING]), **window})
    ).json()
    assert [(e["kind"], e["entity"]["key"]) for e in around["events"]] == [
        ("incident_resolved", INCIDENT),
        ("incident_opened", INCIDENT),
        ("deployment", RELEASE),
        ("change", FLAG),
        ("deployment", STAGING),
    ]
    deployed = next(e for e in around["events"] if e["entity"]["key"] == RELEASE)
    # Of its repository.
    assert (deployed["via"]["key"], deployed["environment"]) == (REPO, "production")

    everywhere = await client.get(f"{API}/timeline", params={"kinds": "incident", **window})
    assert [e["entity"]["key"] for e in everywhere.json()["events"]] == [
        INCIDENT,
        INCIDENT,
        JIRA_INCIDENT,
    ]
    backwards = await client.get(
        f"{API}/timeline", params={"since": "2026-09-29T00:00:00Z", "until": "2026-09-27T00:00:00Z"}
    )
    assert backwards.status_code == 422
    nowhere = await client.get(f"{API}/timeline", params={"entity_id": str(uuid.uuid4())})
    assert nowhere.status_code == 404


async def test_another_workspace_s_operations_are_not_found(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _operations(acme["acme"])
    _as(identity, acme, "other_admin")  # Globex's

    for path in (
        f"/incidents/{ids[INCIDENT]}",
        f"/deployments/{ids[RELEASE]}",
        f"/changes/{ids[CHANGE]}",
    ):
        assert (await client.get(f"{API}{path}")).status_code == 404, path
    for path in ("/incidents", "/deployments", "/changes"):
        assert (await client.get(f"{API}{path}")).json()["data"] == [], path
    window = {"since": "2026-09-01T00:00:00Z", "until": "2026-09-30T00:00:00Z"}
    assert (await client.get(f"{API}/timeline", params=window)).json()["events"] == []
