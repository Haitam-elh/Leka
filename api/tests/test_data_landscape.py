"""A data landscape, modelled from five sources (LEKA-364).

Acme's data, as its tools see it — the connectors' payloads through the
whole pipeline: extraction, parsing, normalisation, stored as normalisation
leaves them, then entity resolution, enrichment and the company model's
build, then the API.

    AWS             the RDS instance `ledger-prod`, Billing API's, in
                    production — its endpoint
    PostgreSQL      the ledger database on that endpoint: its schema
                    `billing` — customers (email, names), invoices (a
                    foreign key to customers), credentials (password
                    hashes), the view `unpaid` reading both
    PostgreSQL (2)  a second source on the same database, its scope the
                    `billing` schema alone: customers again
    MySQL           a server's `shop` database and its `orders` table
    a catalogue     a custom source: invoices, by its server, database and
                    schema — Finance's, confidential, of Billing API — and
                    a dataset it knows of no database

What these protect: one entity per table, schema and database whichever
source reads it, every source kept; the database part of the instance at
its endpoint; foreign keys and what views read, walked as lineage both
ways; what each table holds and how sensitive, up to its schema, its
database and the instance; members read the data — never another
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
HOST = "ledger-prod.abc.eu-west-3.rds.amazonaws.com"
RDS_ARN = "arn:aws:rds:eu-west-3:123456789012:db:ledger-prod"
SERVER = {"engine": "postgresql", "host": HOST, "port": 5432, "database": "ledger"}
MYSQL = {"engine": "mysql", "host": "shop.acme.io", "port": 3306, "database": None}

INSTANCE = f"aws:{RDS_ARN}"
DATABASE = f"db:postgresql://{HOST}:5432/ledger"
BILLING = f"{DATABASE}/billing"
CUSTOMERS = f"{BILLING}/customers"
INVOICES = f"{BILLING}/invoices"
CREDENTIALS = f"{BILLING}/credentials"
UNPAID = f"{BILLING}/unpaid"
SHOP_SERVER = "db:mysql://shop.acme.io:3306"
ORDERS = f"{SHOP_SERVER}/shop/orders"
BILLING_API = "service:billing-api"


def _column(name: str, type_: str = "text", comment: str | None = None) -> dict[str, Any]:
    return {"name": name, "type": type_, "nullable": True, "comment": comment}


def _table(
    name: str, *columns: dict[str, Any], server: dict[str, Any] = SERVER, **extra: Any
) -> dict[str, Any]:
    return {
        "schema": extra.pop("schema", "billing"),
        "name": name,
        "kind": "table",
        "columns": list(columns),
        "constraints": [],
        "server": server,
        **extra,
    }


def _read(kind: SourceKind, capability: Capability, payload: dict[str, Any]) -> NormalisedRecord:
    name = payload["name"]
    schema = payload.get("schema")
    return _record(
        kind,
        capability,
        payload,
        external_id=f"{schema}.{name}" if schema else name,
        container=schema or name,
    )


def _customers() -> dict[str, Any]:
    return _table(
        "customers",
        _column("id", "bigint"),
        _column("email", comment="Where invoices go"),
        _column("first_name"),
        constraints=[{"type": "primary_key", "columns": ["id"]}],
        comment="Who pays",
    )


async def _landscape(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    """The five sources, normalised, stored, resolved, enriched, built: the
    model's ids, by key."""
    aws, postgresql, scoped, mysql, catalogue = [
        await _source(workspace, name)
        for name in ("AWS", "PostgreSQL", "PostgreSQL billing", "MySQL", "Catalogue")
    ]
    records = [
        (
            aws,
            _record(
                SourceKind.AWS,
                C.DB_INSTANCES,
                {
                    "DBInstanceIdentifier": "ledger-prod",
                    "DBInstanceStatus": "available",
                    "Engine": "postgres",
                    "Endpoint": {"Address": HOST, "Port": 5432},
                    "TagList": [
                        {"Key": "service", "Value": "billing-api"},
                        {"Key": "env", "Value": "production"},
                    ],
                },
                container="eu-west-3",
                external_id=RDS_ARN,
            ),
        ),
        (
            postgresql,
            _read(
                SourceKind.POSTGRESQL,
                C.SCHEMAS,
                {
                    "name": "billing",
                    "owner": "ledger",
                    "comment": "Invoices",
                    "database": "ledger",
                    "server": SERVER,
                },
            ),
        ),
        (postgresql, _read(SourceKind.POSTGRESQL, C.TABLES, _customers())),
        (
            postgresql,
            _read(
                SourceKind.POSTGRESQL,
                C.TABLES,
                _table(
                    "invoices",
                    _column("id", "bigint"),
                    _column("customer_id", "bigint"),
                    _column("amount", "numeric(12,2)"),
                    constraints=[
                        {"type": "primary_key", "columns": ["id"]},
                        {
                            "type": "foreign_key",
                            "columns": ["customer_id"],
                            "references": {
                                "schema": "billing",
                                "table": "customers",
                                "columns": ["id"],
                            },
                        },
                    ],
                    estimated_rows=12000000,
                ),
            ),
        ),
        (
            postgresql,
            _read(
                SourceKind.POSTGRESQL,
                C.TABLES,
                _table("credentials", _column("customer_id", "bigint"), _column("password_hash")),
            ),
        ),
        (
            postgresql,
            _read(
                SourceKind.POSTGRESQL,
                C.TABLES,
                _table(
                    "unpaid",
                    _column("id", "bigint"),
                    kind="view",
                    reads_from=["billing.invoices", "billing.customers"],
                ),
            ),
        ),
        (scoped, _read(SourceKind.POSTGRESQL, C.TABLES, _customers())),
        (
            mysql,
            _read(
                SourceKind.MYSQL,
                C.SCHEMAS,
                {"name": "shop", "charset": "utf8mb4", "server": MYSQL},
            ),
        ),
        (
            mysql,
            _read(
                SourceKind.MYSQL,
                C.TABLES,
                _table(
                    "orders",
                    _column("id", "bigint"),
                    _column("shipping_address"),
                    schema="shop",
                    server=MYSQL,
                ),
            ),
        ),
        (
            catalogue,
            _record(
                SourceKind.CUSTOM_REST,
                C.RECORDS,
                {
                    "resource": "datasets",
                    "entity": "data_object",
                    "fields": {
                        "id": "ds-1",
                        "title": "invoices",
                        "metadata": {
                            "engine": "postgres",
                            "host": HOST,
                            "port": 5432,
                            "database": "ledger",
                            "schema": "billing",
                            "owner": "Finance",
                            "classification": "confidential",
                            "data_categories": "financial",
                            "service": "billing-api",
                        },
                    },
                },
                external_id="datasets:ds-1",
            ),
        ),
        (
            catalogue,
            _record(
                SourceKind.CUSTOM_REST,
                C.RECORDS,
                {
                    "resource": "datasets",
                    "entity": "data_object",
                    "fields": {"id": "ds-2", "title": "Revenue KPIs", "metadata": {}},
                },
                external_id="datasets:ds-2",
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


def _sources(entity: Entity) -> set[str]:
    return {str(s["source_id"]) for s in entity.provenance["sources"]}  # type: ignore[attr-defined]


def _origin(entity: Entity, attribute: str) -> dict[str, Any]:
    found: dict[str, Any] = entity.provenance["attributes"][attribute]  # type: ignore[index]
    return found


# ── the model ────────────────────────────────────────────────────────────────


async def test_every_database_schema_and_table_is_one_entity_of_its_kind(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    kinds = {
        key: (await _entity(workspace, ids[key])).type.value
        for key in (INSTANCE, DATABASE, BILLING, CUSTOMERS, UNPAID, SHOP_SERVER, ORDERS)
    }
    assert kinds == {
        INSTANCE: "database",
        DATABASE: "database",
        BILLING: "schema",
        CUSTOMERS: "data_object",
        UNPAID: "data_object",
        SHOP_SERVER: "database",
        ORDERS: "data_object",
    }
    # Two PostgreSQL sources read customers: one entity, both kept.
    assert len(_sources(await _entity(workspace, ids[CUSTOMERS]))) == 2
    # The catalogue names invoices by where it is: one entity with the
    # database source's, its owner and service beside.
    invoices = await _entity(workspace, ids[INVOICES])
    assert len(_sources(invoices)) == 2
    assert invoices.attributes["estimated_rows"] == 12000000
    await _edge(workspace, ids[INVOICES], "owned_by", ids["team:finance"])
    await _edge(workspace, ids[INVOICES], "part_of", ids[BILLING_API])
    # One it knows of no database is its own.
    assert any(key.endswith(":data_object:datasets:ds-2") for key in ids)


async def test_the_hierarchy_up_to_the_instance_serving_it(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    for a, kind, b in (
        (CUSTOMERS, "part_of", BILLING),
        (BILLING, "part_of", DATABASE),
        (ORDERS, "part_of", f"{SHOP_SERVER}/shop"),
        (f"{SHOP_SERVER}/shop", "part_of", SHOP_SERVER),
    ):
        await _edge(workspace, ids[a], kind, ids[b])
    hosted = await _edge(workspace, ids[DATABASE], "part_of", ids[INSTANCE])
    assert hosted.cross_source is True  # the PostgreSQL source's and AWS's
    # Where it runs: the instance's environment, said as enrichment's.
    database = await _entity(workspace, ids[DATABASE])
    assert database.attributes["environment"] == "production"
    assert _origin(database, "environment")["rule"] == "container"


async def test_foreign_keys_and_views_are_relationships(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    await _edge(workspace, ids[INVOICES], "references", ids[CUSTOMERS])
    await _edge(workspace, ids[UNPAID], "reads_from", ids[INVOICES])
    await _edge(workspace, ids[UNPAID], "reads_from", ids[CUSTOMERS])


async def test_what_the_data_is_goes_up_to_what_holds_it(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    ids = await _landscape(workspace)

    customers = await _entity(workspace, ids[CUSTOMERS])
    assert (customers.attributes["classification"], customers.attributes["personal_data"]) == (
        "confidential",
        True,
    )
    assert customers.attributes["column_categories"] == {
        "email": "contact",
        "first_name": "identity",
    }
    assert (await _entity(workspace, ids[CREDENTIALS])).attributes["classification"] == "restricted"
    for key in (BILLING, DATABASE, INSTANCE):
        holder = await _entity(workspace, ids[key])
        assert holder.attributes["classification"] == "restricted", key
        assert _origin(holder, "classification")["origin"] == "enrichment"
        categories = holder.attributes["data_categories"]
        assert isinstance(categories, list) and "credential" in categories
    orders = await _entity(workspace, ids[ORDERS])
    assert orders.attributes["data_categories"] == ["location"]


# ── the API ──────────────────────────────────────────────────────────────────


async def test_members_read_the_databases_and_their_schemas(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "member")

    listed = {
        row["key"]: row
        for row in (await client.get(f"{API}/databases", params={"limit": 100})).json()["data"]
    }
    ledger = listed[DATABASE]
    assert (ledger["engine"], ledger["host"], ledger["port"], ledger["database_name"]) == (
        "postgresql",
        HOST,
        5432,
        "ledger",
    )
    assert ledger["instance"]["key"] == INSTANCE
    assert (ledger["schema_count"], ledger["object_count"]) == (1, 4)
    assert ledger["holds"]["classification"] == "restricted"
    assert ledger["holds"]["origin"] == "enrichment"
    assert listed[INSTANCE]["provider"] == "aws"
    restricted = await client.get(f"{API}/databases", params={"classification": "restricted"})
    assert {row["key"] for row in restricted.json()["data"]} == {INSTANCE, DATABASE}
    personal = await client.get(f"{API}/databases", params={"personal_data": "true"})
    assert {row["key"] for row in personal.json()["data"]} == {INSTANCE, DATABASE, SHOP_SERVER}

    detail = (await client.get(f"{API}/databases/{ids[DATABASE]}")).json()
    [billing] = detail["schemas"]
    assert (billing["key"], billing["object_count"], billing["kinds"]) == (
        BILLING,
        4,
        {"table": 3, "view": 1},
    )
    instance = (await client.get(f"{API}/databases/{ids[INSTANCE]}")).json()
    assert [d["key"] for d in instance["serves"]] == [DATABASE]
    wrong = await client.get(f"{API}/databases/{ids[BILLING]}")
    assert wrong.status_code == 404  # a schema is not a database


async def test_members_read_the_data_objects_and_filter_them(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "member")

    async def keys(**params: str | int) -> set[str]:
        response = await client.get(f"{API}/data-objects", params={"limit": 100, **params})
        assert response.status_code == 200, response.text
        return {row["key"] for row in response.json()["data"]}

    rows = {
        row["key"]: row
        for row in (await client.get(f"{API}/data-objects", params={"limit": 100})).json()["data"]
    }
    invoices = rows[INVOICES]
    assert (invoices["database"]["key"], invoices["container"]["key"]) == (DATABASE, BILLING)
    assert invoices["ties"] == {"references": 1, "referenced_by": 0, "reads_from": 0, "read_by": 1}
    assert [o["key"] for o in invoices["owners"]] == ["team:finance"]
    assert rows[CUSTOMERS]["column_count"] == 3

    assert await keys(database_id=str(ids[DATABASE])) == {CUSTOMERS, INVOICES, CREDENTIALS, UNPAID}
    assert await keys(schema_id=str(ids[f"{SHOP_SERVER}/shop"])) == {ORDERS}
    assert await keys(object_kind="view") == {UNPAID}
    assert await keys(classification="restricted") == {CREDENTIALS}
    assert await keys(category="contact") == {CUSTOMERS}
    assert CUSTOMERS in await keys(personal_data="true")
    assert INVOICES in await keys(personal_data="false")
    assert await keys(service_id=str(ids[BILLING_API])) == {INVOICES}
    assert await keys(team_id=str(ids["team:finance"])) == {INVOICES}


async def test_a_data_object_s_detail_and_its_lineage(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "member")

    customers = (await client.get(f"{API}/data-objects/{ids[CUSTOMERS]}")).json()
    assert customers["description"] == "Who pays"
    assert customers["columns"] == [
        {"name": "id", "category": None, "primary_key": True},
        {"name": "email", "category": "contact", "primary_key": False},
        {"name": "first_name", "category": "identity", "primary_key": False},
    ]
    assert [b["key"] for b in customers["referenced_by"]] == [INVOICES]
    assert [b["key"] for b in customers["read_by"]] == [UNPAID]

    async def walk(key: str, **params: str | int) -> dict[str, int]:
        response = await client.get(f"{API}/data-objects/{ids[key]}/lineage", params=params)
        assert response.status_code == 200, response.text
        return {n["entity"]["key"]: n["depth"] for n in response.json()["nodes"]}

    # What the view is made of, and what a change of customers reaches.
    assert await walk(UNPAID) == {INVOICES: 1, CUSTOMERS: 1}
    assert await walk(CUSTOMERS, direction="downstream") == {INVOICES: 1, UNPAID: 1}
    assert await walk(INVOICES, direction="upstream", depth=1) == {CUSTOMERS: 1}
    wrong = await client.get(f"{API}/data-objects/{ids[BILLING]}")
    assert wrong.status_code == 404


async def test_another_workspace_s_data_is_not_found(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _landscape(acme["acme"])
    _as(identity, acme, "other_admin")  # Globex's

    for path in (
        f"/databases/{ids[DATABASE]}",
        f"/data-objects/{ids[CUSTOMERS]}",
        f"/data-objects/{ids[CUSTOMERS]}/lineage",
    ):
        assert (await client.get(f"{API}{path}")).status_code == 404, path
    assert (await client.get(f"{API}/databases")).json()["data"] == []
    assert (await client.get(f"{API}/data-objects")).json()["data"] == []
