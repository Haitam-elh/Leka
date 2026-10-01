"""The data, as normalisation writes it (LEKA-364).

From the database connectors' payloads through extraction, parsing and
normalisation: a database, its schemas and its tables, views and
collections — keyed by the server and database they were read on; the
tables a foreign key references and a view reads from; what kind of data
each column holds, by its name and its comment, never a value; a cloud
instance known by its endpoint; a data catalogue's table, one with the
database source's.

What these protect: one key per table whichever source reads it; a MySQL or
MongoDB server whose databases are schemas; a Supabase project's database,
not its pooler's; a classification said with its evidence, nothing guessed
where no column says it.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from leka.connectors import Capability, SourceKind
from leka.connectors.supabase import SupabaseConfig, SupabaseConnector, SupabaseCredentials
from leka.ingestion.extraction import ExtractedRecord
from leka.ingestion.normalisation import NormalisationFailure, NormalisedRecord, normalise
from leka.ingestion.parsing import FactType, ParsedRecord, parse
from tests.test_extraction import _extract

C = Capability
HOST = "ledger.abc.eu-west-3.rds.amazonaws.com"
SERVER = {"engine": "postgresql", "host": HOST, "port": 5432, "database": "ledger"}
DATABASE = f"db:postgresql://{HOST}:5432/ledger"
BILLING = f"{DATABASE}/billing"


def _pipeline(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> tuple[ExtractedRecord, ParsedRecord]:
    extracted = _extract(kind, capability, payload, **extra)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord), parsed
    return extracted, parsed


def _normalised(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> NormalisedRecord:
    result = normalise(*_pipeline(kind, capability, payload, **extra))
    assert isinstance(result, NormalisedRecord), result
    return result


def _edges(record: NormalisedRecord) -> set[tuple[str, str, str]]:
    return {(r.from_key, r.type, r.to_key) for r in record.relationships}


def _column(name: str, type_: str = "text", comment: str | None = None) -> dict[str, Any]:
    return {"name": name, "type": type_, "nullable": True, "comment": comment}


def _table(name: str, *columns: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "schema": "billing",
        "name": name,
        "kind": "table",
        "columns": list(columns),
        "constraints": [],
        "server": SERVER,
        **extra,
    }


def _pg(payload: dict[str, Any]) -> NormalisedRecord:
    return _normalised(
        SourceKind.POSTGRESQL,
        C.TABLES,
        payload,
        external_id=f"{payload['schema']}.{payload['name']}",
        container=payload["schema"],
    )


# ── a database, its schemas, its tables ──────────────────────────────────────


def test_a_schema_is_keyed_by_its_server_and_database() -> None:
    schema = _normalised(
        SourceKind.POSTGRESQL,
        C.SCHEMAS,
        {
            "name": "billing",
            "owner": "ledger_owner",
            "comment": "Invoices",
            "database": "ledger",
            "server": SERVER,
        },
        external_id="billing",
        container="billing",
    )

    entity = schema.entity
    assert (entity.type, entity.key, entity.name) == ("schema", BILLING, "billing")
    assert entity.attributes["owner_role"] == "ledger_owner"  # a database role, not a team
    assert entity.attributes["description"] == "Invoices"
    database = next(e for e in schema.related if e.key == DATABASE)
    assert (database.type, database.name) == ("database", "ledger")
    assert database.attributes["host"] == HOST
    edges = _edges(schema)
    assert (BILLING, "part_of", DATABASE) in edges
    # The cloud instance a client reaches there, if a source shows one.
    assert (DATABASE, "part_of", f"endpoint:{HOST}:5432") in edges


def test_a_table_is_part_of_its_schema_and_references_what_its_keys_point_at() -> None:
    invoices = _pg(
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
                    "references": {"schema": "billing", "table": "customers", "columns": ["id"]},
                },
            ],
            estimated_rows=12000000,
        )
    )

    entity = invoices.entity
    assert (entity.type, entity.key, entity.name) == (
        "data_object",
        f"{BILLING}/invoices",
        "billing.invoices",
    )
    a = entity.attributes
    assert (a["object_kind"], a["schema_name"], a["primary_key"]) == ("table", "billing", ["id"])
    assert a["estimated_rows"] == 12000000
    assert "classification" not in a  # nothing says it: nothing is guessed
    edges = _edges(invoices)
    assert (entity.key, "part_of", BILLING) in edges
    assert (entity.key, "references", f"{BILLING}/customers") in edges


def test_a_view_reads_from_its_tables() -> None:
    unpaid = _pg(
        _table(
            "unpaid",
            _column("id", "bigint"),
            kind="view",
            reads_from=["billing.invoices", "billing.customers"],
        )
    )

    assert unpaid.entity.attributes["object_kind"] == "view"
    assert {to for _, kind, to in _edges(unpaid) if kind == "reads_from"} == {
        f"{BILLING}/invoices",
        f"{BILLING}/customers",
    }


def test_a_mysql_server_s_databases_are_its_schemas() -> None:
    server = {"engine": "mysql", "host": "db.acme.io", "port": 3306, "database": None}
    orders = _normalised(
        SourceKind.MYSQL,
        C.TABLES,
        {"schema": "shop", "name": "orders", "kind": "table", "columns": [], "server": server},
        external_id="shop.orders",
        container="shop",
    )

    assert orders.entity.key == "db:mysql://db.acme.io:3306/shop/orders"
    database = next(e for e in orders.related if e.type == "database")
    assert (database.key, database.name) == ("db:mysql://db.acme.io:3306", "db.acme.io")


def test_a_mongodb_collection_is_a_data_object_of_its_database() -> None:
    server = {"engine": "mongodb", "host": "cluster0.abcd.mongodb.net", "port": None}
    users = _normalised(
        SourceKind.MONGODB,
        C.TABLES,
        {
            "schema": "app",
            "name": "users",
            "kind": "collection",
            "columns": [_column("email"), _column("passwordHash")],
            "server": server,
        },
        external_id="app.users",
        container="app",
    )

    assert users.entity.key == "db:mongodb://cluster0.abcd.mongodb.net/app/users"
    assert users.entity.attributes["object_kind"] == "collection"
    assert users.entity.attributes["data_categories"] == ["contact", "credential"]


def test_a_record_read_before_it_said_its_server_waits_for_the_next_pass() -> None:
    result = normalise(
        *_pipeline(
            SourceKind.POSTGRESQL,
            C.TABLES,
            {"schema": "billing", "name": "invoices", "kind": "table", "columns": []},
            external_id="billing.invoices",
            container="billing",
        )
    )

    assert isinstance(result, NormalisationFailure)
    assert "no server" in result.message


def test_a_supabase_project_is_its_own_database_not_its_pooler_s() -> None:
    connector = SupabaseConnector(
        SupabaseConfig(host="aws-0-eu-central-1.pooler.supabase.com"),
        SupabaseCredentials(username="leka_reader.abcdefghij", password=SecretStr("x")),
    )

    assert connector._server() == {
        "engine": "postgresql",
        "host": "db.abcdefghij.supabase.co",
        "port": 5432,
        "database": "postgres",
    }


# ── what the data is ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("column", "category"),
    [
        ("email", "contact"),
        ("customerEmail", "contact"),
        ("date_of_birth", "identity"),
        ("last_name", "identity"),
        ("shipping_address_line1", "location"),
        ("ip_address", "location"),
        ("iban", "financial"),
        ("card_number", "financial"),
        ("password_hash", "credential"),
        ("api_key", "credential"),
        ("diagnosis", "health"),
        ("created_at", None),
        ("tokens_used", None),
        ("status", None),
    ],
)
def test_a_column_s_name_says_what_it_holds(column: str, category: str | None) -> None:
    _, parsed = _pipeline(
        SourceKind.POSTGRESQL,
        C.TABLES,
        _table("t", _column(column)),
        external_id="billing.t",
        container="billing",
    )

    found = [f.value for f in parsed.facts if f.type is FactType.DATA_CATEGORY]
    assert found == ([category] if category else [])


def test_a_table_holding_personal_data_is_confidential_its_columns_said() -> None:
    customers = _pg(
        _table(
            "customers",
            _column("id", "bigint"),
            _column("email", comment="Where invoices go"),
            _column("first_name"),
            _column("plan"),
        )
    )

    a = customers.entity.attributes
    assert a["data_categories"] == ["contact", "identity"]
    assert a["column_categories"] == {"email": "contact", "first_name": "identity"}
    assert (a["personal_data"], a["classification"]) == (True, "confidential")


def test_a_credential_makes_a_table_restricted() -> None:
    accounts = _pg(_table("accounts", _column("email"), _column("password_hash")))

    a = accounts.entity.attributes
    assert a["classification"] == "restricted"
    assert a["data_categories"] == ["contact", "credential"]


def test_what_a_comment_says_is_surer_than_a_name() -> None:
    extracted, parsed = _pipeline(
        SourceKind.POSTGRESQL,
        C.TABLES,
        _table(
            "leads",
            _column("handle", comment="PII: the prospect's social account"),
            _column("score", "int"),
            comment="Restricted: marketing only",
        ),
        external_id="billing.leads",
        container="billing",
    )

    [column] = [f for f in parsed.facts if f.type is FactType.DATA_CATEGORY]
    assert (column.value, column.confidence, column.target and column.target.key) == (
        "personal",
        0.95,
        "handle",
    )
    record = normalise(extracted, parsed)
    assert isinstance(record, NormalisedRecord)
    assert record.entity.attributes["classification"] == "restricted"  # the table's comment


# ── a cloud instance, by its endpoint ────────────────────────────────────────


def test_an_rds_instance_is_also_known_by_its_endpoint() -> None:
    rds = _normalised(
        SourceKind.AWS,
        C.DB_INSTANCES,
        {
            "DBInstanceIdentifier": "ledger-prod",
            "Engine": "postgres",
            "Endpoint": {"Address": HOST, "Port": 5432},
        },
        container="eu-west-3",
        external_id="arn:aws:rds:eu-west-3:123456789012:db:ledger-prod",
    )

    assert f"endpoint:{HOST}:5432" in rds.entity.aliases


def test_an_azure_flexible_server_is_known_by_its_name_in_its_domain() -> None:
    server_id = (
        "/subscriptions/s1/resourceGroups/rg/providers/"
        "Microsoft.DBforPostgreSQL/flexibleServers/Ledger-Prod"
    )
    flexible = _normalised(
        SourceKind.AZURE,
        C.DB_INSTANCES,
        {
            "id": server_id,
            "name": "Ledger-Prod",
            "type": "Microsoft.DBforPostgreSQL/flexibleServers",
        },
        container="s1",
        external_id=server_id.lower(),
    )

    assert "endpoint:ledger-prod.postgres.database.azure.com:5432" in flexible.entity.aliases


# ── a data catalogue's table ─────────────────────────────────────────────────


def _catalogue(metadata: dict[str, Any], title: str = "invoices") -> NormalisedRecord:
    return _normalised(
        SourceKind.CUSTOM_REST,
        C.RECORDS,
        {
            "resource": "datasets",
            "entity": "data_object",
            "fields": {"id": "ds-1", "title": title, "metadata": metadata},
        },
        external_id="datasets:ds-1",
    )


def test_a_catalogue_s_table_is_keyed_as_the_database_source_s() -> None:
    dataset = _catalogue(
        {
            "engine": "Postgres",
            "host": HOST,
            "port": "5432",
            "database": "ledger",
            "schema": "billing",
            "owner": "Finance",
            "classification": "Confidentiel",
            "data_categories": "financial",
            "service": "billing-api",
            "upstream": "billing.customers",
        }
    )

    entity = dataset.entity
    assert (entity.type, entity.key) == ("data_object", f"{BILLING}/invoices")
    a = entity.attributes
    assert (a["classification"], a["classification_raw"]) == ("confidential", "Confidentiel")
    assert a["data_categories"] == ["financial"]
    assert {"engine", "host", "schema", "owner"}.isdisjoint(a)
    edges = _edges(dataset)
    assert {
        (entity.key, "owned_by", "team:finance"),
        (entity.key, "part_of", "service:billing-api"),
        (entity.key, "part_of", BILLING),
        (BILLING, "part_of", DATABASE),
        (entity.key, "reads_from", f"{BILLING}/customers"),
    } <= edges


def test_a_catalogue_that_does_not_say_where_is_its_own() -> None:
    dataset = _catalogue({"owner": "Finance"}, title="Revenue KPIs")

    assert dataset.entity.key.endswith(":data_object:datasets:ds-1")
    assert not any(kind == "part_of" for _, kind, _ in _edges(dataset))
