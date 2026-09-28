"""The PostgreSQL connector against a real PostgreSQL — the tests' own (LEKA-349).

Each test gets two schemas made for it: `billing_*`, with a foreign key, a
check, an index, a view, a materialized view, a partitioned table and
comments; and `secret_*`, a table beside it. And a role made the way
docs/connectors/databases.md says: CONNECT on the database, USAGE on the
billing schema, and not one SELECT. That the connector describes everything
it should with that role is the proof that it reads the catalogue, not the
rows.

The connection itself is replaced — the tests' server is local and speaks no
TLS, and the real one would refuse both. What the real one does is tested
apart: an address that is not public, a server without TLS.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import asyncpg
import pytest
from pydantic import SecretStr, ValidationError

from leka.connectors import (
    Capability,
    ConnectorCategory,
    ConnectorError,
    DiagnosticCode,
    HealthStatus,
    RawRecord,
    manifests,
    network,
)
from leka.connectors.postgresql import (
    PostgreSQLConfig,
    PostgreSQLConnector,
    PostgreSQLCredentials,
)
from leka.connectors.postgresql import connector as pg

pytestmark = pytest.mark.integration

C = Capability
HOST = "db.acme.example"
SERVER = urlparse(os.environ["LEKA_DATABASE_URL"].replace("+asyncpg", ""))


@dataclass(frozen=True)
class Catalogue:
    database: str
    billing: str
    secret: str
    reader: str
    password: str


def _admin() -> dict[str, Any]:
    return {
        "host": SERVER.hostname,
        "port": SERVER.port or 5432,
        "user": SERVER.username,
        "password": SERVER.password,
        "database": SERVER.path.lstrip("/"),
    }


@pytest.fixture
async def catalogue() -> AsyncIterator[Catalogue]:
    suffix = secrets.token_hex(4)
    made = Catalogue(
        database=SERVER.path.lstrip("/"),
        billing=f"billing_{suffix}",
        secret=f"secret_{suffix}",
        reader=f"leka_reader_{suffix}",
        password=secrets.token_urlsafe(24),
    )
    b = made.billing
    admin = await asyncpg.connect(**_admin())
    try:
        # Names made above, not input: formatting them in is safe.
        await admin.execute(f"""
            CREATE SCHEMA {b};
            COMMENT ON SCHEMA {b} IS 'Invoices, and who pays them';
            CREATE TABLE {b}.customers (
                id bigint PRIMARY KEY,
                email text NOT NULL UNIQUE,
                created_at timestamptz DEFAULT now()
            );
            COMMENT ON TABLE {b}.customers IS 'Who pays';
            COMMENT ON COLUMN {b}.customers.email IS 'Where invoices go';
            CREATE TABLE {b}.invoices (
                id bigint PRIMARY KEY,
                customer_id bigint NOT NULL REFERENCES {b}.customers (id),
                amount numeric(12, 2) CHECK (amount >= 0),
                paid boolean NOT NULL DEFAULT false
            );
            CREATE INDEX invoices_customer ON {b}.invoices (customer_id);
            CREATE VIEW {b}.unpaid AS
                SELECT i.id, c.email FROM {b}.invoices i
                JOIN {b}.customers c ON c.id = i.customer_id WHERE NOT i.paid;
            CREATE MATERIALIZED VIEW {b}.totals AS
                SELECT customer_id, sum(amount) AS total FROM {b}.invoices GROUP BY customer_id;
            CREATE TABLE {b}.events (id bigint, at date NOT NULL) PARTITION BY RANGE (at);
            CREATE TABLE {b}.events_2026 PARTITION OF {b}.events
                FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
            INSERT INTO {b}.customers VALUES (1, 'ada@acme.example');
            INSERT INTO {b}.invoices VALUES (1, 1, 1200.00, false);
            CREATE SCHEMA {made.secret};
            CREATE TABLE {made.secret}.salaries (id int, amount int);
            CREATE ROLE {made.reader} LOGIN PASSWORD '{made.password}';
            GRANT CONNECT ON DATABASE {made.database} TO {made.reader};
            GRANT USAGE ON SCHEMA {b} TO {made.reader};
        """)  # noqa: S608
        yield made
    finally:
        await admin.execute(f"""
            DROP SCHEMA IF EXISTS {b} CASCADE;
            DROP SCHEMA IF EXISTS {made.secret} CASCADE;
            DROP OWNED BY {made.reader};
            DROP ROLE IF EXISTS {made.reader};
        """)
        await admin.close()


def _connector(
    user: str, password: str, *, schemas: list[str] | None = None, database: str | None = None
) -> PostgreSQLConnector:
    config = PostgreSQLConfig(
        host=HOST, database=database or SERVER.path.lstrip("/"), schemas=schemas
    )
    credentials = PostgreSQLCredentials(username=user, password=SecretStr(password))
    connector = PostgreSQLConnector(config, credentials)

    async def local() -> asyncpg.Connection:
        # What _open does, to the tests' server: no TLS, no address check.
        return await asyncpg.connect(
            host=SERVER.hostname,
            port=SERVER.port or 5432,
            user=user,
            password=password,
            database=config.database,
            server_settings=pg.SESSION,
        )

    connector._open = local  # type: ignore[method-assign]
    return connector


def _reader(made: Catalogue, **kwargs: Any) -> PostgreSQLConnector:
    return _connector(made.reader, made.password, **kwargs)


def _superuser(**kwargs: Any) -> PostgreSQLConnector:
    return _connector(str(SERVER.username), str(SERVER.password), **kwargs)


async def _read(connector: PostgreSQLConnector, capability: Capability) -> list[RawRecord]:
    return [record async for record in connector.iter_resources(capability)]


async def _failure(connector: PostgreSQLConnector) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()
    return caught.value


def _payload(record: RawRecord) -> dict[str, Any]:
    return dict(record.payload)


def _by(items: list[dict[str, Any]], key: str = "name") -> dict[str, dict[str, Any]]:
    return {str(item[key]): item for item in items}


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_role_with_usage_alone_passes_and_reads_both(catalogue: Catalogue) -> None:
    result = await _reader(catalogue, schemas=[catalogue.billing]).test_connection()

    assert result.account == f"{catalogue.reader}@{HOST}"
    assert set(result.capabilities) == {C.SCHEMAS, C.TABLES}
    assert result.metadata["database"] == catalogue.database
    assert str(result.metadata["version"]).split(".")[0].isdigit()
    assert result.warnings == []


async def test_a_role_that_can_do_more_than_read_is_accepted_with_a_warning() -> None:
    result = await _superuser(schemas=["public"]).test_connection()

    assert len(result.warnings) == 1
    assert "plus que lire" in result.warnings[0]


async def test_a_schema_in_scope_the_role_cannot_use_is_named(catalogue: Catalogue) -> None:
    connector = _reader(catalogue, schemas=[catalogue.billing, catalogue.secret])

    error = await _failure(connector)

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert catalogue.secret in error.diagnostic.message
    assert catalogue.billing not in error.diagnostic.message


async def test_a_wrong_password_is_refused_and_never_repeated(catalogue: Catalogue) -> None:
    wrong = "not-" + catalogue.password

    error = await _failure(_connector(catalogue.reader, wrong))

    assert error.diagnostic.code is DiagnosticCode.AUTH_INVALID
    assert wrong not in error.diagnostic.model_dump_json()


async def test_a_database_that_is_not_there_is_named(catalogue: Catalogue) -> None:
    error = await _failure(_reader(catalogue, database=f"nothing_{catalogue.billing}"))

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert "base" in error.diagnostic.message


async def test_health_is_a_connection_that_answers(catalogue: Catalogue) -> None:
    health = await _reader(catalogue).check_health()

    assert health.status is HealthStatus.HEALTHY


# ── the scope ────────────────────────────────────────────────────────────────


async def test_the_scope_offers_the_schemas_the_role_may_use(catalogue: Catalogue) -> None:
    listing = await _reader(catalogue).list_scope()

    offered = {option.key: option for option in listing.options}
    assert offered[catalogue.billing].description == "Invoices, and who pays them"
    assert catalogue.secret not in offered
    assert not {"pg_catalog", "information_schema", "pg_toast"} & offered.keys()
    assert listing.truncated is False


# ── what is read ─────────────────────────────────────────────────────────────


async def test_schemas_are_read_with_their_database(catalogue: Catalogue) -> None:
    records = await _read(_reader(catalogue, schemas=[catalogue.billing]), C.SCHEMAS)

    assert [r.external_id for r in records] == [catalogue.billing]
    [schema] = records
    assert schema.container == catalogue.billing  # its own, for the scope rules
    assert schema.payload["comment"] == "Invoices, and who pays them"
    assert schema.payload["database"] == catalogue.database
    assert schema.payload["owner"] == SERVER.username


async def test_without_a_scope_every_usable_schema_is_read_and_no_other(
    catalogue: Catalogue,
) -> None:
    records = await _read(_reader(catalogue), C.SCHEMAS)

    read = {r.external_id for r in records}
    assert catalogue.billing in read
    assert catalogue.secret not in read


async def test_tables_and_views_are_described_without_a_row_read(catalogue: Catalogue) -> None:
    b = catalogue.billing

    records = await _read(_reader(catalogue, schemas=[b]), C.TABLES)

    tables = {r.external_id: _payload(r) for r in records}
    assert set(tables) == {
        f"{b}.{name}" for name in ("customers", "invoices", "unpaid", "totals", "events")
    }
    kinds = {r.payload["name"]: r.payload["kind"] for r in records}
    assert kinds == {
        "customers": "table",
        "invoices": "table",
        "unpaid": "view",
        "totals": "materialized_view",
        "events": "partitioned_table",
    }
    assert all(r.container == b for r in records)
    assert all(isinstance(r.fetched_at, datetime) and r.updated_at is None for r in records)

    customers = tables[f"{b}.customers"]
    assert customers["comment"] == "Who pays"
    columns = _by(customers["columns"])
    assert list(columns) == ["id", "email", "created_at"]
    assert columns["email"] == {
        "name": "email",
        "type": "text",
        "nullable": False,
        "default": None,
        "comment": "Where invoices go",
    }
    assert columns["created_at"]["type"] == "timestamp with time zone"
    assert columns["created_at"]["default"] == "now()"
    constraints = {c["type"]: c for c in customers["constraints"]}
    assert constraints["primary_key"]["columns"] == ["id"]
    assert constraints["unique"]["columns"] == ["email"]

    invoices = tables[f"{b}.invoices"]
    assert _by(invoices["columns"])["amount"]["type"] == "numeric(12,2)"
    by_type = {c["type"]: c for c in invoices["constraints"]}
    assert by_type["foreign_key"]["columns"] == ["customer_id"]
    assert by_type["foreign_key"]["references"] == {
        "schema": b,
        "table": "customers",
        "columns": ["id"],
    }
    assert "amount >= " in by_type["check"]["definition"]
    indexes = _by(invoices["indexes"])
    assert indexes["invoices_customer"]["unique"] is False
    assert indexes["invoices_pkey"]["primary"] is True

    unpaid = tables[f"{b}.unpaid"]
    assert sorted(unpaid["reads_from"]) == [f"{b}.customers", f"{b}.invoices"]
    assert "NOT i.paid" in str(unpaid["definition"])
    assert unpaid["size_bytes"] is None
    assert tables[f"{b}.totals"]["reads_from"] == [f"{b}.invoices"]
    assert "oid" not in customers
    # No value of a row is in what was read.
    assert "ada@acme.example" not in str([r.payload for r in records])


async def test_more_tables_than_a_pass_reads_is_a_failure_not_a_cut(
    catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pg, "MAX_TABLES", 4)

    with pytest.raises(ConnectorError) as caught:
        await _read(_reader(catalogue, schemas=[catalogue.billing]), C.TABLES)

    assert caught.value.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "choisissez les schémas" in caught.value.diagnostic.message


async def test_the_session_writes_nothing_even_as_a_superuser(catalogue: Catalogue) -> None:
    connector = _superuser(schemas=[catalogue.billing])

    with pytest.raises(ConnectorError) as caught:
        async with connector._session() as db:
            await db.execute(f"CREATE TABLE {catalogue.billing}.written (id int)")

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert "read-only" in str(caught.value.diagnostic.detail)


def test_the_queries_read_the_catalogue_and_nothing_else() -> None:
    relations = set()
    for query in pg.QUERIES:
        relations |= set(re.findall(r"\b(?:FROM|JOIN)\s+([a-z_]+)", query))
    assert relations - {"unnest"} <= {
        "pg_roles",
        "pg_namespace",
        "pg_class",
        "pg_attribute",
        "pg_attrdef",
        "pg_constraint",
        "pg_index",
        "pg_rewrite",
        "pg_depend",
    }


async def test_a_capability_it_does_not_read_is_refused(catalogue: Catalogue) -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _read(_reader(catalogue), C.ISSUES)


# ── the real connection ──────────────────────────────────────────────────────


async def test_an_address_that_is_not_public_is_refused_before_any_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve(host: str, port: int) -> list[str]:
        return ["10.0.0.5"]

    real = network.public_address

    async def public_address(host: str, port: int) -> str:
        return await real(host, port, resolve=resolve)

    monkeypatch.setattr(network, "public_address", public_address)
    connector = PostgreSQLConnector(
        PostgreSQLConfig(host=HOST, database="app"),
        PostgreSQLCredentials(username="leka", password=SecretStr("not-tried")),
    )

    error = await _failure(connector)

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "adresse publique" in error.diagnostic.message


async def test_a_server_without_tls_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = await asyncpg.connect(**_admin())
    try:
        if await admin.fetchval("SHOW ssl") == "on":
            pytest.skip("this server speaks TLS")
    finally:
        await admin.close()

    async def public_address(host: str, port: int) -> str:
        return str(SERVER.hostname)

    monkeypatch.setattr(network, "public_address", public_address)
    connector = PostgreSQLConnector(
        PostgreSQLConfig(host=HOST, port=SERVER.port or 5432, database=_admin()["database"]),
        PostgreSQLCredentials(
            username=str(SERVER.username), password=SecretStr(str(SERVER.password))
        ),
    )

    error = await _failure(connector)

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "TLS" in error.diagnostic.message


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (network.PrivateAddressError("10.0.0.5"), DiagnosticCode.CONFIG_INVALID),
        (
            asyncpg.InvalidPasswordError("password authentication failed"),
            DiagnosticCode.AUTH_INVALID,
        ),
        (
            asyncpg.InvalidAuthorizationSpecificationError("no pg_hba.conf entry"),
            DiagnosticCode.AUTH_INVALID,
        ),
        (asyncpg.InvalidCatalogNameError("database does not exist"), DiagnosticCode.NOT_FOUND),
        (asyncpg.InsufficientPrivilegeError("permission denied"), DiagnosticCode.PERMISSION_DENIED),
        (asyncpg.QueryCanceledError("statement timeout"), DiagnosticCode.TIMEOUT),
        (TimeoutError(), DiagnosticCode.TIMEOUT),
        (ConnectionError("server rejected SSL upgrade"), DiagnosticCode.CONFIG_INVALID),
        (ConnectionRefusedError(61, "Connection refused"), DiagnosticCode.NETWORK_UNREACHABLE),
        (OSError(8, "nodename nor servname provided"), DiagnosticCode.NETWORK_UNREACHABLE),
        (asyncpg.DataError("invalid input"), DiagnosticCode.PROVIDER_ERROR),
        (RuntimeError("?"), DiagnosticCode.UNKNOWN),
    ],
)
def test_each_failure_has_its_diagnostic(error: Exception, code: DiagnosticCode) -> None:
    secret = "s3cr3t-" + secrets.token_hex(8)
    connector = PostgreSQLConnector(
        PostgreSQLConfig(host=HOST, database="app"),
        PostgreSQLCredentials(username="leka", password=SecretStr(secret)),
    )

    diagnostic = connector._diagnose(type(error)(f"{error} {secret}")).diagnostic

    assert diagnostic.code is code
    assert secret not in diagnostic.model_dump_json()


# ── the settings ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [
        {"host": "10.0.0.5", "database": "app"},
        {"host": "127.0.0.1", "database": "app"},
        {"host": "[::1]", "database": "app"},
        {"host": "169.254.169.254", "database": "app"},
        {"host": "db.acme.example/app", "database": "app"},
        {"host": "db.acme.example", "database": "app", "port": 0},
        {"host": "db.acme.example", "database": ""},
        {"host": "db.acme.example", "database": "app", "schemas": [""]},
        {"host": "db.acme.example", "database": "app", "schemas": []},
        {"host": "db.acme.example", "database": "app", "sslmode": "disable"},
    ],
)
def test_settings_that_cannot_work_are_refused(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PostgreSQLConfig.model_validate(config)


def test_settings_are_tidied() -> None:
    config = PostgreSQLConfig.model_validate(
        {"host": "DB.Acme.Example", "database": "app", "schemas": [" billing", "billing", "ops"]}
    )

    assert config.host == "db.acme.example"
    assert config.port == 5432
    assert config.schemas == ["billing", "ops"]


def test_the_hint_names_the_role_and_the_password_never_shows() -> None:
    credentials = PostgreSQLCredentials(username="leka_reader", password=SecretStr("hunter2"))

    assert next(iter(credentials.model_dump())) == "username"
    assert "hunter2" not in repr(credentials)


def test_the_manifest() -> None:
    manifest = next(m for m in manifests() if m.display_name == "PostgreSQL")

    assert manifest.category is ConnectorCategory.DATA
    assert manifest.capabilities == {C.SCHEMAS, C.TABLES}
    assert manifest.listed_whole == {C.SCHEMAS, C.TABLES}


@pytest.mark.parametrize(
    ("number", "rounded"),
    [(None, None), (0, 0), (42, 42), (8192, 8200), (12_345_678, 12_000_000), (99_999, 100_000)],
)
def test_estimates_keep_two_figures(number: int | None, rounded: int | None) -> None:
    assert pg._rounded(number) == rounded
