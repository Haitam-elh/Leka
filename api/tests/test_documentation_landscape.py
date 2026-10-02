"""Documentation and business knowledge, modelled from five sources (LEKA-366).

Acme's documentation and how its business runs, as its tools see them — the
connectors' payloads through the whole pipeline: extraction, parsing,
normalisation, stored as normalisation leaves them, then entity
resolution, enrichment and the company model's build, then the API.

    Confluence        the space Payments; its pages: the Billing API
                      runbook (last week; it links the code and names
                      PAY-42), Ledger notes under it (in May), the
                      Invoicing architecture (two years old)
    GitHub            acme/billing-api
    PagerDuty         the service Billing API, Payments'
    a catalogue       a custom source: the application Billing platform,
                      Billing API's; the table billing.invoices of the
                      ledger database, Billing API's
    a business system a custom source: the capabilities Finance and
                      Invoicing under it — supported by Billing platform,
                      using billing.invoices, Sara's and Payments' — the
                      process Order to cash, realizing Invoicing, and its
                      activities: Approve invoice, then Send invoice,
                      supported by Billing API

What these protect: a space and its documents, how fresh each is, whose,
what each describes — said or inferred, with its rule; what the
documentation covers and what it misses; capabilities and processes, the
technology and the data they rely on; what a table or a service means to
the business; members read it, never another workspace's.
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
SPACE = f"{SITE}/wiki/spaces/PAY"
RUNBOOK = f"{SITE}/wiki/pages/1001"
NOTES = f"{SITE}/wiki/pages/1002"
ARCHITECTURE = f"{SITE}/wiki/pages/1003"
REPO = "github.com/acme/billing-api"
BILLING = "service:billing-api"
PLATFORM = "application:billing-platform"
PAYMENTS = "team:payments"
SARA = "person:email:sara@acme.io"
WRITER = f"person:{SITE}:u-sara"
EDITOR = f"person:{SITE}:u-bob"
FINANCE = "capability:finance"
INVOICING = "capability:invoicing"
ORDER_TO_CASH = "process:order-to-cash"
APPROVE = "process:order-to-cash/approve-invoice"
SEND = "process:order-to-cash/send-invoice"
INVOICES = "db:postgresql://ledger.internal:5432/ledger/billing/invoices"


def _page(
    number: int, title: str, changed: str, body: str, parent: str = "999"
) -> NormalisedRecord:
    return _record(
        SourceKind.CONFLUENCE,
        C.PAGES,
        {
            "id": str(number),
            "title": title,
            "spaceId": "7",
            "parentId": parent,
            "authorId": "u-sara",
            "version": {"number": 2, "createdAt": changed, "authorId": "u-bob"},
            "body": {"storage": {"value": body}},
            "web_url": f"https://{SITE}/wiki/spaces/PAY/pages/{number}/x",
        },
        external_id=str(number),
        container="PAY",
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


async def _knowledge(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    """The five sources, normalised, stored, resolved, enriched, built: the
    model's ids, by key."""
    confluence, github, pagerduty, catalogue, business = [
        await _source(workspace, name)
        for name in ("Confluence", "GitHub", "PagerDuty", "Catalogue", "Business")
    ]
    records = [
        (
            confluence,
            _record(
                SourceKind.CONFLUENCE,
                C.SPACES,
                {
                    "id": "7",
                    "key": "PAY",
                    "name": "Payments",
                    "type": "global",
                    "status": "current",
                    "web_url": f"https://{SITE}/wiki/spaces/PAY",
                },
                external_id="7",
                container=None,
            ),
        ),
        (
            confluence,
            _page(
                1001,
                "Billing API runbook",
                "2026-09-20T10:00:00Z",
                '<p>Restart it: <a href="https://github.com/acme/billing-api/tree/main">the '
                "code</a>. Known: PAY-42.</p>",
            ),
        ),
        (
            confluence,
            _page(1002, "Ledger notes", "2026-05-01T10:00:00Z", "<p>Notes</p>", parent="1001"),
        ),
        (
            confluence,
            _page(1003, "Invoicing architecture", "2024-06-01T10:00:00Z", "<p>Old</p>"),
        ),
        (
            github,
            _record(
                SourceKind.GITHUB,
                C.REPOSITORIES,
                {"full_name": "acme/billing-api", "owner": {"login": "acme"}, "language": "Python"},
            ),
        ),
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
                },
            ),
        ),
        (
            catalogue,
            _declared("application", "a-1", "Billing platform", {"services": "Billing API"}),
        ),
        (
            catalogue,
            _declared(
                "data_object",
                "t-1",
                "billing.invoices",
                {
                    "engine": "postgres",
                    "host": "ledger.internal",
                    "port": 5432,
                    "database": "ledger",
                    "schema": "billing",
                    "table": "invoices",
                    "service": "Billing API",
                },
            ),
        ),
        (business, _declared("business_capability", "c-1", "Finance", {"level": "1"})),
        (
            business,
            _declared(
                "business_capability",
                "c-2",
                "Invoicing",
                {
                    "parent": "Finance",
                    "level": "2",
                    "applications": "Billing platform",
                    "data": "billing.invoices",
                    "owner": "sara@acme.io",
                    "team": "Payments",
                    "criticality": "high",
                },
            ),
        ),
        (
            business,
            _declared(
                "business_process",
                "p-1",
                "Order to cash",
                {"capabilities": "Invoicing", "team": "Payments", "type": "process"},
            ),
        ),
        (
            business,
            _declared(
                "business_process",
                "p-2",
                "Send invoice",
                {"parent": "Order to cash", "step": 2, "services": "Billing API"},
            ),
        ),
        (
            business,
            _declared(
                "business_process", "p-3", "Approve invoice", {"parent": "Order to cash", "step": 1}
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


async def test_a_space_and_its_documents_how_fresh_whose(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _knowledge(workspace)

    space = await _entity(workspace, ids[SPACE])
    assert (space.type.value, space.attributes["url"]) == (
        "knowledge_space",
        f"https://{SITE}/wiki/spaces/PAY",
    )
    owned = await _edge(workspace, ids[SPACE], "owned_by", ids[PAYMENTS])
    assert (owned.origin, owned.rule) == ("inferred", "same_name")
    runbook = await _entity(workspace, ids[RUNBOOK])
    assert (runbook.attributes["freshness"], runbook.attributes["document_kind"]) == (
        "fresh",
        "page",
    )
    assert runbook.provenance["attributes"]["freshness"]["rule"] == "freshness"  # type: ignore[index]
    assert (await _entity(workspace, ids[ARCHITECTURE])).attributes["freshness"] == "stale"
    for a, kind, b in (
        (RUNBOOK, "part_of", SPACE),
        (NOTES, "child_of", RUNBOOK),
        (RUNBOOK, "authored_by", WRITER),
        (RUNBOOK, "mentions", REPO),
    ):
        edge = await _edge(workspace, ids[a], kind, ids[b])
        assert edge.origin == "stated", (a, kind, b)
    inherited = await _edge(workspace, ids[RUNBOOK], "owned_by", ids[PAYMENTS])
    assert inherited.rule == "inherited"


async def test_what_a_document_describes_said_or_inferred(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _knowledge(workspace)

    service = await _edge(workspace, ids[RUNBOOK], "describes", ids[BILLING])
    assert (service.origin, service.rule, service.confidence) == (
        "inferred",
        "named_in_title",
        0.6,
    )
    await _edge(workspace, ids[ARCHITECTURE], "describes", ids[INVOICING])


async def test_capabilities_processes_and_what_they_rely_on(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _knowledge(workspace)

    for a, kind, b in (
        (INVOICING, "child_of", FINANCE),
        (INVOICING, "supported_by", PLATFORM),
        (INVOICING, "owned_by", SARA),
        (INVOICING, "owned_by", PAYMENTS),
        (ORDER_TO_CASH, "realizes", INVOICING),
        (SEND, "part_of", ORDER_TO_CASH),
        (SEND, "supported_by", BILLING),
    ):
        edge = await _edge(workspace, ids[a], kind, ids[b])
        assert edge.origin == "stated", (a, kind, b)
    data = await _edge(workspace, ids[INVOICING], "uses", ids[INVOICES])
    assert (data.origin, data.rule) == ("inferred", "named")
    invoicing = await _entity(workspace, ids[INVOICING])
    assert (invoicing.type.value, invoicing.attributes["level"]) == ("business_capability", 2)
    # Where the business knowledge came from: the source and the record.
    sources = invoicing.provenance["sources"]
    assert isinstance(sources, list)
    [source] = sources
    assert source["key"] == INVOICING
    stated = await _edge(workspace, ids[INVOICING], "child_of", ids[FINANCE])
    assert stated.provenance[0]["source_id"] == source["source_id"]


# ── the API ──────────────────────────────────────────────────────────────────


async def test_members_read_the_documents(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _knowledge(acme["acme"])
    _as(identity, acme, "member")

    async def keys(**params: str | int) -> list[str]:
        response = await client.get(f"{API}/documents", params={"limit": 100, **params})
        assert response.status_code == 200, response.text
        return [row["key"] for row in response.json()["data"]]

    rows = {
        row["key"]: row
        for row in (await client.get(f"{API}/documents", params={"limit": 100})).json()["data"]
    }
    runbook = rows[RUNBOOK]
    assert (runbook["space"]["key"], runbook["freshness"], runbook["tools"]) == (
        SPACE,
        "fresh",
        ["confluence"],
    )
    assert runbook["url"] == f"https://{SITE}/wiki/spaces/PAY/pages/1001/x"
    assert [a["key"] for a in runbook["authors"]] == [WRITER]
    assert runbook["last_editor"]["key"] == EDITOR
    assert [o["key"] for o in runbook["owners"]] == [PAYMENTS]
    assert BILLING in [d["key"] for d in runbook["describes"]]
    assert await keys(freshness="stale") == [ARCHITECTURE]
    assert await keys(about_id=str(ids[BILLING])) == [RUNBOOK]
    assert sorted(await keys(space_id=str(ids[SPACE]))) == [RUNBOOK, NOTES, ARCHITECTURE]
    assert await keys(q="ledger") == [NOTES]

    detail = (await client.get(f"{API}/documents/{ids[NOTES]}")).json()
    assert [a["key"] for a in detail["ancestors"]] == [RUNBOOK]
    runbook_detail = (await client.get(f"{API}/documents/{ids[RUNBOOK]}")).json()
    assert [c["key"] for c in runbook_detail["children"]] == [NOTES]
    assert REPO in [m["entity"]["key"] for m in runbook_detail["mentions"]]
    [said] = [d for d in runbook_detail["descriptions"] if d["entity"]["key"] == BILLING]
    assert (said["origin"], said["rule"]) == ("inferred", "named_in_title")
    assert (await client.get(f"{API}/documents/{ids[SPACE]}")).status_code == 404
    # Mon environnement: the service's sheet lists its documentation.
    sheet = await client.get(f"/api/v1/ingestion/enrichment/environment/{ids[BILLING]}")
    assert RUNBOOK in [d["key"] for d in sheet.json()["documents"]]


async def test_members_read_the_spaces_and_the_coverage(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _knowledge(acme["acme"])
    _as(identity, acme, "member")

    [space] = (await client.get(f"{API}/knowledge-spaces")).json()["data"]
    assert (space["key"], space["space_kind"], space["document_count"]) == (SPACE, "space", 3)
    assert space["freshness"] == {"fresh": 1, "aging": 1, "stale": 1}
    assert [o["key"] for o in space["owners"]] == [PAYMENTS]
    # Sara wrote it all; Bob edited it all, less weighed.
    assert [m["key"] for m in space["maintainers"]] == [WRITER, EDITOR]
    detail = (await client.get(f"{API}/knowledge-spaces/{ids[SPACE]}")).json()
    assert [d["key"] for d in detail["recent"]] == [RUNBOOK, NOTES, ARCHITECTURE]
    assert [d["key"] for d in detail["stalest"]] == [ARCHITECTURE]

    coverage = (await client.get(f"{API}/documentation/coverage")).json()
    assert (coverage["documents"], coverage["spaces"]) == (3, 1)
    assert coverage["freshness"] == {"fresh": 1, "aging": 1, "stale": 1}
    by_type = {row["type"]: row for row in coverage["coverage"]}
    assert (by_type["service"]["total"], by_type["service"]["documented"]) == (1, 1)
    assert by_type["business_capability"] == {
        "type": "business_capability",
        "total": 2,
        "documented": 1,
        "fresh": 0,
    }

    async def gaps(**params: str) -> list[str]:
        response = await client.get(f"{API}/documentation/gaps", params={"order": "asc", **params})
        assert response.status_code == 200, response.text
        return [row["entity"]["key"] for row in response.json()["data"]]

    assert await gaps(type="business_capability") == [FINANCE]
    stale = (
        await client.get(
            f"{API}/documentation/gaps", params={"type": "business_capability", "stale": "true"}
        )
    ).json()["data"]
    assert [(g["entity"]["key"], g["documents"], g["criticality"]) for g in stale] == [
        (INVOICING, 1, "high")
    ]
    assert await gaps(type="business_process") == [APPROVE, ORDER_TO_CASH, SEND]
    assert (
        await client.get(f"{API}/documentation/gaps", params={"type": "person"})
    ).status_code == 422


async def test_members_read_the_business(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _knowledge(acme["acme"])
    _as(identity, acme, "member")

    top = (await client.get(f"{API}/business-capabilities", params={"top": "true"})).json()
    assert [row["key"] for row in top["data"]] == [FINANCE]
    rows = {
        row["key"]: row for row in (await client.get(f"{API}/business-capabilities")).json()["data"]
    }
    invoicing = rows[INVOICING]
    assert (invoicing["parent"]["key"], invoicing["process_count"], invoicing["data_count"]) == (
        FINANCE,
        1,
        1,
    )
    assert [s["key"] for s in invoicing["supported_by"]] == [PLATFORM]
    assert {o["key"] for o in invoicing["owners"]} == {SARA, PAYMENTS}
    assert rows[FINANCE]["part_count"] == 1

    detail = (await client.get(f"{API}/business-capabilities/{ids[INVOICING]}")).json()
    assert [p["key"] for p in detail["processes"]] == [ORDER_TO_CASH]
    # Through its application, the service.
    assert [s["key"] for s in detail["services"]] == [BILLING]
    [data] = detail["data"]
    assert (data["entity"]["key"], data["rule"]) == (INVOICES, "named")
    assert [d["entity"]["key"] for d in detail["documentation"]] == [ARCHITECTURE]
    assert [a["key"] for a in detail["ancestors"]] == [FINANCE]

    realizing = await client.get(
        f"{API}/business-processes", params={"capability_id": str(ids[INVOICING])}
    )
    assert [row["key"] for row in realizing.json()["data"]] == [ORDER_TO_CASH]
    process = (await client.get(f"{API}/business-processes/{ids[ORDER_TO_CASH]}")).json()
    assert [(p["entity"]["key"], p["step"]) for p in process["parts"]] == [(APPROVE, 1), (SEND, 2)]
    assert [s["key"] for s in process["parts"][1]["supported_by"]] == [BILLING]
    assert [c["key"] for c in process["capabilities"]] == [INVOICING]
    supported = await client.get(
        f"{API}/business-processes", params={"application_id": str(ids[BILLING])}
    )
    assert [row["key"] for row in supported.json()["data"]] == [SEND]
    wrong = await client.get(f"{API}/business-processes/{ids[INVOICING]}")
    assert wrong.status_code == 404


async def test_what_a_table_and_a_service_mean_to_the_business(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _knowledge(acme["acme"])
    _as(identity, acme, "member")

    table = (await client.get(f"{API}/entities/{ids[INVOICES]}/business")).json()
    [capability] = table["capabilities"]
    assert (capability["entity"]["key"], capability["relation"], capability["path"]) == (
        INVOICING,
        "uses",
        "direct",
    )
    # Its service supports Send invoice.
    [activity] = table["processes"]
    assert (activity["entity"]["key"], activity["path"], activity["via"]["key"]) == (
        SEND,
        "contained",
        BILLING,
    )
    service = (await client.get(f"{API}/entities/{ids[BILLING]}/business")).json()
    assert [(p["entity"]["key"], p["path"]) for p in service["processes"]] == [(SEND, "direct")]
    [through] = service["capabilities"]
    assert (through["entity"]["key"], through["path"], through["via"]["key"]) == (
        INVOICING,
        "contained",
        PLATFORM,
    )


async def test_another_workspace_s_knowledge_is_not_found(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _knowledge(acme["acme"])
    _as(identity, acme, "other_admin")  # Globex's

    for path in (
        f"/documents/{ids[RUNBOOK]}",
        f"/knowledge-spaces/{ids[SPACE]}",
        f"/business-capabilities/{ids[INVOICING]}",
        f"/business-processes/{ids[ORDER_TO_CASH]}",
        f"/entities/{ids[BILLING]}/business",
    ):
        assert (await client.get(f"{API}{path}")).status_code == 404, path
    for path in ("/documents", "/knowledge-spaces", "/business-capabilities"):
        assert (await client.get(f"{API}{path}")).json()["data"] == [], path
    coverage = (await client.get(f"{API}/documentation/coverage")).json()
    assert (coverage["documents"], coverage["spaces"]) == (0, 0)
