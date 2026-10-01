"""The MySQL connector against a real MySQL (LEKA-349).

Each test gets two databases made for it: `billing_*`, with a foreign key, a
check, a composite index, a view and comments; and `secret_*` beside it.
And an account made the way docs/connectors/databases.md says: REFERENCES
on the billing database, and nothing else. That the connector describes
everything it should with that account — while a SELECT is refused — is the
proof that it reads the catalogue, not the rows.

The connection is the real one — TLS, then the session made read-only — to
the tests' server: only the address check is told where that server is.

The server: `docker compose up -d mysql` locally, where these tests skip
without one; CI starts its own, and LEKA_REQUIRE_MYSQL_TESTS turns a skip
into a failure. A test that quietly stops running is worse than none.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import ssl
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncmy
import pytest
from asyncmy.errors import OperationalError, ProgrammingError
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, text

from leka.connectors import (
    Capability,
    ConnectorCategory,
    ConnectorError,
    DiagnosticCode,
    HealthStatus,
    RawRecord,
    Source,
    SourceKind,
    SourceService,
    manifests,
    network,
)
from leka.connectors.mariadb import MariaDBConfig, MariaDBConnector, MariaDBCredentials
from leka.connectors.mysql import MySQLConfig, MySQLConnector, MySQLCredentials
from leka.connectors.mysql import connector as my
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion import sync as sync_module
from leka.ingestion.extraction import ExtractedRecord, extract
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.models import SourceRecord
from leka.ingestion.sync import sync_source
from leka.platform import LocalObjectStore

pytestmark = pytest.mark.integration

C = Capability
HOST = "db.acme.example"
SERVER = urlparse(os.environ.get("LEKA_MYSQL_TEST_URL", "mysql://root:leka@127.0.0.1:3306"))
PORT = SERVER.port or 3306
REQUIRED = os.environ.get("LEKA_REQUIRE_MYSQL_TESTS") == "1"
# Kept before any test replaces it, for the one test that needs it real.
PUBLIC_ADDRESS = network.public_address
HOW_TO_START = (
    f"no MySQL at {SERVER.hostname}:{PORT}. Start one with `docker compose up -d mysql`, "
    "or point LEKA_MYSQL_TEST_URL at another."
)


@dataclass(frozen=True)
class Catalogue:
    billing: str
    secret: str
    reader: str
    password: str


async def _admin() -> Any:
    return await asyncmy.connect(
        host=SERVER.hostname,
        port=PORT,
        user=SERVER.username,
        password=SERVER.password or "",
        autocommit=True,
        connect_timeout=3,
    )


async def _run(db: Any, *statements: str) -> None:
    async with db.cursor() as cursor:
        for statement in statements:
            await cursor.execute(statement)


@pytest.fixture(scope="session")
def server() -> Iterator[None]:
    async def reachable() -> bool:
        try:
            db = await _admin()
        except Exception:  # every way of not being there
            return False
        db.close()
        return True

    if not asyncio.run(reachable()):
        if REQUIRED:
            pytest.fail(HOW_TO_START)
        pytest.skip(HOW_TO_START)
    yield


@pytest.fixture(autouse=True)
def the_tests_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """The address check, told where the tests' server is. Everything after
    it — TLS, the session — is the real thing."""

    async def public_address(host: str, port: int) -> str:
        return str(SERVER.hostname)

    monkeypatch.setattr(network, "public_address", public_address)


@pytest.fixture
async def catalogue(server: None) -> AsyncIterator[Catalogue]:
    suffix = secrets.token_hex(4)
    made = Catalogue(
        billing=f"billing_{suffix}",
        secret=f"secret_{suffix}",
        reader=f"leka_reader_{suffix}",
        password=secrets.token_urlsafe(24),
    )
    b, reader = made.billing, made.reader
    admin = await _admin()
    try:
        # Names made above, not input: formatting them in is safe.
        await _run(
            admin,
            f"CREATE DATABASE {b}",
            f"""CREATE TABLE {b}.customers (
                id bigint PRIMARY KEY,
                email varchar(200) NOT NULL UNIQUE COMMENT 'Where invoices go',
                created_at timestamp DEFAULT CURRENT_TIMESTAMP
            ) COMMENT 'Who pays'""",
            f"""CREATE TABLE {b}.invoices (
                id bigint PRIMARY KEY,
                customer_id bigint NOT NULL,
                amount decimal(12, 2) CHECK (amount >= 0),
                paid boolean NOT NULL DEFAULT false,
                CONSTRAINT invoices_customer FOREIGN KEY (customer_id)
                    REFERENCES {b}.customers (id),
                INDEX invoices_unpaid (paid, customer_id)
            )""",
            f"""CREATE VIEW {b}.unpaid AS SELECT i.id, c.email FROM {b}.invoices i
                JOIN {b}.customers c ON c.id = i.customer_id WHERE NOT i.paid""",  # noqa: S608
            f"INSERT INTO {b}.customers (id, email) VALUES (1, 'ada@acme.example')",  # noqa: S608
            f"INSERT INTO {b}.invoices VALUES (1, 1, 1200.00, false)",  # noqa: S608
            f"CREATE DATABASE {made.secret}",
            f"CREATE TABLE {made.secret}.salaries (id int, amount int)",
            f"CREATE USER '{reader}'@'%' IDENTIFIED BY '{made.password}'",
            f"GRANT REFERENCES ON {b}.* TO '{reader}'@'%'",
        )
        yield made
    finally:
        await _run(
            admin,
            f"DROP DATABASE IF EXISTS {b}",
            f"DROP DATABASE IF EXISTS {made.secret}",
            f"DROP USER IF EXISTS '{reader}'@'%'",
        )
        admin.close()


def _connector(user: str, password: str, *, schemas: list[str] | None = None) -> MySQLConnector:
    return MySQLConnector(
        MySQLConfig(host=HOST, port=PORT, schemas=schemas),
        MySQLCredentials(username=user, password=SecretStr(password)),
    )


def _reader(made: Catalogue, **kwargs: Any) -> MySQLConnector:
    return _connector(made.reader, made.password, **kwargs)


def _root(**kwargs: Any) -> MySQLConnector:
    return _connector(str(SERVER.username), SERVER.password or "", **kwargs)


async def _read(connector: MySQLConnector, capability: Capability) -> list[RawRecord]:
    return [record async for record in connector.iter_resources(capability)]


async def _failure(connector: MySQLConnector) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()
    return caught.value


def _payloads(records: list[RawRecord]) -> dict[str, dict[str, Any]]:
    return {r.external_id: dict(r.payload) for r in records}


def _by(items: list[dict[str, Any]], key: str = "name") -> dict[str, dict[str, Any]]:
    return {str(item[key]): item for item in items}


# ── the connection test ──────────────────────────────────────────────────────


async def test_an_account_with_references_alone_passes(catalogue: Catalogue) -> None:
    result = await _reader(catalogue, schemas=[catalogue.billing]).test_connection()

    assert result.account == f"{catalogue.reader}@{HOST}"
    assert set(result.capabilities) == {C.SCHEMAS, C.TABLES}
    assert str(result.metadata["version"]).split(".")[0].isdigit()
    assert result.metadata["schemas_visible"] == 1
    assert result.warnings == []


async def test_an_account_that_can_do_more_than_read_is_accepted_with_warnings(
    catalogue: Catalogue,
) -> None:
    result = await _root(schemas=[catalogue.billing]).test_connection()

    assert len(result.warnings) == 2
    assert "SELECT" in result.warnings[0]
    assert "plus que lire" in result.warnings[1]


async def test_a_database_in_scope_the_account_cannot_see_is_named(catalogue: Catalogue) -> None:
    error = await _failure(_reader(catalogue, schemas=[catalogue.billing, catalogue.secret]))

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert catalogue.secret in error.diagnostic.message
    assert catalogue.billing not in error.diagnostic.message


async def test_a_wrong_password_is_refused_and_never_repeated(catalogue: Catalogue) -> None:
    wrong = "not-" + catalogue.password

    error = await _failure(_connector(catalogue.reader, wrong))

    assert error.diagnostic.code is DiagnosticCode.AUTH_INVALID
    assert wrong not in error.diagnostic.model_dump_json()


async def test_the_mariadb_connector_pointed_at_mysql_says_so(catalogue: Catalogue) -> None:
    mariadb = MariaDBConnector(
        MariaDBConfig(host=HOST, port=PORT),
        MariaDBCredentials(username=catalogue.reader, password=SecretStr(catalogue.password)),
    )

    error = await _failure(mariadb)

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "connecteur MySQL" in error.diagnostic.message


async def test_health_is_a_connection_that_answers(catalogue: Catalogue) -> None:
    assert (await _reader(catalogue).check_health()).status is HealthStatus.HEALTHY


async def test_the_scope_offers_what_the_account_may_see(catalogue: Catalogue) -> None:
    listing = await _reader(catalogue).list_scope()

    assert [option.key for option in listing.options] == [catalogue.billing]


# ── what is read ─────────────────────────────────────────────────────────────


async def test_databases_are_read_as_schemas(catalogue: Catalogue) -> None:
    records = await _read(_reader(catalogue), C.SCHEMAS)

    [schema] = records
    assert (schema.external_id, schema.container) == (catalogue.billing, catalogue.billing)
    assert schema.payload["charset"] == "utf8mb4"


async def test_tables_are_described_while_their_rows_are_refused(catalogue: Catalogue) -> None:
    b = catalogue.billing

    tables = _payloads(await _read(_reader(catalogue), C.TABLES))

    assert set(tables) == {f"{b}.customers", f"{b}.invoices", f"{b}.unpaid"}
    customers, invoices = tables[f"{b}.customers"], tables[f"{b}.invoices"]
    assert (customers["kind"], customers["engine"], customers["comment"]) == (
        "table",
        "InnoDB",
        "Who pays",
    )
    assert _by(customers["columns"])["email"] == {
        "name": "email",
        "type": "varchar(200)",
        "nullable": False,
        "default": None,
        "comment": "Where invoices go",
    }
    assert _by(invoices["columns"])["amount"]["type"] == "decimal(12,2)"
    constraints = {c["type"]: c for c in invoices["constraints"]}
    assert constraints["primary_key"]["columns"] == ["id"]
    assert constraints["foreign_key"]["references"] == {
        "schema": b,
        "table": "customers",
        "columns": ["id"],
    }
    assert constraints["check"]["definition"] == "CHECK (`amount` >= 0)"
    assert {c["type"] for c in customers["constraints"]} == {"primary_key", "unique"}
    indexes = _by(invoices["indexes"])
    assert indexes["invoices_unpaid"]["definition"] == (
        "INDEX invoices_unpaid (paid, customer_id) USING BTREE"
    )
    assert indexes["PRIMARY"]["primary"] is True
    # Without SELECT on it, a view is its name and columns: MySQL shows no
    # more, and LEKA asks no more.
    unpaid = tables[f"{b}.unpaid"]
    assert (unpaid["kind"], unpaid["comment"], unpaid["definition"]) == ("view", None, None)
    assert unpaid["reads_from"] == []
    assert "ada@acme.example" not in str(tables)

    with pytest.raises(OperationalError):  # and the account cannot read a row
        reader = await asyncmy.connect(
            host=SERVER.hostname, port=PORT, user=catalogue.reader, password=catalogue.password
        )
        try:
            await _run(reader, f"SELECT * FROM {b}.customers")  # noqa: S608
        finally:
            reader.close()


async def test_a_view_the_admin_let_it_select_says_what_it_reads(catalogue: Catalogue) -> None:
    b = catalogue.billing
    admin = await _admin()
    await _run(admin, f"GRANT SELECT, SHOW VIEW ON {b}.unpaid TO '{catalogue.reader}'@'%'")
    admin.close()

    unpaid = _payloads(await _read(_reader(catalogue), C.TABLES))[f"{b}.unpaid"]

    assert "`paid`" in str(unpaid["definition"])
    assert sorted(unpaid["reads_from"]) == [f"{b}.customers", f"{b}.invoices"]
    warnings = (await _reader(catalogue).test_connection()).warnings
    assert ["SELECT" in w for w in warnings] == [True]


async def test_the_session_writes_nothing_even_as_root(catalogue: Catalogue) -> None:
    connector = _root()

    with pytest.raises(ConnectorError) as caught:
        async with connector._session() as db:
            written = f"INSERT INTO {catalogue.billing}.customers (id, email) VALUES (2, 'x')"  # noqa: S608
            await _run(db, written)

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert "READ ONLY" in str(caught.value.diagnostic.detail)


async def test_a_session_that_is_not_encrypted_is_refused(catalogue: Catalogue) -> None:
    connector = _reader(catalogue)

    async def in_the_clear() -> Any:
        return await asyncmy.connect(
            host=SERVER.hostname, port=PORT, user=catalogue.reader, password=catalogue.password
        )

    connector._open = in_the_clear  # type: ignore[method-assign]

    error = await _failure(connector)

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "TLS" in error.diagnostic.message


async def test_more_tables_than_a_pass_reads_is_a_failure_not_a_cut(
    catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(my, "MAX_TABLES", 2)

    with pytest.raises(ConnectorError) as caught:
        await _read(_reader(catalogue), C.TABLES)

    assert caught.value.diagnostic.code is DiagnosticCode.CONFIG_INVALID


def test_the_queries_read_information_schema_and_nothing_else() -> None:
    relations = set()
    for query in my.QUERIES:
        relations |= set(re.findall(r"\b(?:FROM|JOIN)\s+([\w.]+)", query))
    assert relations
    assert all(relation.startswith("information_schema.") for relation in relations)


async def test_an_address_that_is_not_public_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(host: str, port: int) -> list[str]:
        return ["10.0.0.5"]

    async def public_address(host: str, port: int) -> str:
        return await PUBLIC_ADDRESS(host, port, resolve=resolve)

    monkeypatch.setattr(network, "public_address", public_address)

    error = await _failure(_connector("leka", "not-tried"))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "adresse publique" in error.diagnostic.message


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (network.PrivateAddressError("10.0.0.5"), DiagnosticCode.CONFIG_INVALID),
        (my.NoTlsError("not encrypted"), DiagnosticCode.CONFIG_INVALID),
        (my.OtherEngineError("MariaDB", "11.8.2-MariaDB"), DiagnosticCode.CONFIG_INVALID),
        (ssl.SSLError("wrong version number"), DiagnosticCode.CONFIG_INVALID),
        # What the driver says to a server without TLS (checked by hand
        # against one started with --tls-version=''): a 2003, read as TLS.
        (
            OperationalError(2003, "Can't connect ([SSL: WRONG_VERSION_NUMBER] wrong version)"),
            DiagnosticCode.CONFIG_INVALID,
        ),
        (OperationalError(1045, "Access denied"), DiagnosticCode.AUTH_INVALID),
        (OperationalError(1044, "Access denied to database"), DiagnosticCode.PERMISSION_DENIED),
        (ProgrammingError(1142, "SELECT command denied"), DiagnosticCode.PERMISSION_DENIED),
        (OperationalError(3024, "maximum statement execution time"), DiagnosticCode.TIMEOUT),
        (TimeoutError(), DiagnosticCode.TIMEOUT),
        (OperationalError(2003, "Can't connect"), DiagnosticCode.NETWORK_UNREACHABLE),
        (ConnectionRefusedError(61, "Connection refused"), DiagnosticCode.NETWORK_UNREACHABLE),
        (ProgrammingError(1064, "syntax"), DiagnosticCode.PROVIDER_ERROR),
        (RuntimeError("?"), DiagnosticCode.UNKNOWN),
    ],
)
def test_each_failure_has_its_diagnostic(error: Exception, code: DiagnosticCode) -> None:
    secret = "s3cr3t-" + secrets.token_hex(8)
    error.args = (*error.args, secret)
    connector = MySQLConnector(
        MySQLConfig(host=HOST),
        MySQLCredentials(username="leka", password=SecretStr(secret)),
    )

    diagnostic = connector._diagnose(error).diagnostic

    assert diagnostic.code is code
    assert secret not in diagnostic.model_dump_json()


# ── the settings ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [
        {"host": "10.0.0.5"},
        {"host": "[::1]"},
        {"host": "db.acme.example:3306"},
        {"host": "db.acme.example", "port": 70000},
        {"host": "db.acme.example", "schemas": []},
        {"host": "db.acme.example", "schemas": ["x" * 65]},
        {"host": "db.acme.example", "database": "app"},
    ],
)
def test_settings_that_cannot_work_are_refused(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MySQLConfig.model_validate(config)


def test_the_hint_names_the_account_and_the_manifest_its_category() -> None:
    credentials = MySQLCredentials(username="leka_reader", password=SecretStr("hunter2"))
    manifest = next(m for m in manifests() if m.display_name == "MySQL")

    assert next(iter(credentials.model_dump())) == "username"
    assert "hunter2" not in repr(credentials)
    assert MySQLConfig(host="db.acme.example").port == 3306
    assert manifest.category is ConnectorCategory.DATA
    assert manifest.listed_whole == manifest.capabilities == {C.SCHEMAS, C.TABLES}


# ── end to end: a source, a pass, extraction ─────────────────────────────────


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from leka.platform import storage

    monkeypatch.setattr(storage, "_store", LocalObjectStore(tmp_path))

    async def capture(job: str, *args: object, **kwargs: object) -> object:
        return object()

    monkeypatch.setattr(sync_module, "enqueue_job", capture)
    monkeypatch.setattr(pipeline_module, "enqueue_job", capture)


@pytest.fixture
async def source(catalogue: Catalogue, pipeline: None) -> AsyncIterator[Source]:
    with system_scope():
        async with session_factory() as session:
            workspace_id: uuid.UUID = (
                await session.execute(
                    text("INSERT INTO workspaces (name, slug) VALUES ('MySQL', :s) RETURNING id"),
                    {"s": f"mysql-{uuid.uuid4().hex[:10]}"},
                )
            ).scalar_one()
            await session.commit()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = SourceService(session, workspace_id, actor_user_id=None)
            created = await service.create(
                SourceKind.MYSQL,
                "Billing",
                {"host": HOST, "port": PORT},
                {"username": catalogue.reader, "password": catalogue.password},
            )
            await service.test(created)
            await service.activate(created)
            await session.commit()
            yield created
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace_id})
            await session.commit()


async def _index(source: Source) -> dict[str, SourceRecord]:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(SourceRecord).where(SourceRecord.source_id == source.id)
            )
            return {f"{row.kind}:{row.external_id}": row for row in rows.scalars()}


async def test_a_database_goes_from_its_catalogue_to_extracted_records(
    source: Source, catalogue: Catalogue
) -> None:
    b = catalogue.billing
    assert sorted(source.capabilities) == ["schemas", "tables"]

    report = await sync_source(source.workspace_id, source.id, full=True)

    assert report.status == "succeeded", report.error
    index = await _index(source)
    assert set(index) == {
        f"schemas:{b}",
        *(f"tables:{b}.{name}" for name in ("customers", "invoices", "unpaid")),
    }

    await sync_source(source.workspace_id, source.id, full=True)

    assert {k: r.payload_key for k, r in (await _index(source)).items()} == {
        k: r.payload_key for k, r in index.items()
    }  # unchanged, not written again
    extracted = await extract_source(source.workspace_id, source.id)
    assert (extracted["extracted"], extracted["failed"]) == (4, 0)


async def test_a_table_extracts_as_postgresql_s_do(catalogue: Catalogue) -> None:
    b = catalogue.billing
    [record] = [
        r for r in await _read(_reader(catalogue), C.TABLES) if r.external_id == f"{b}.invoices"
    ]

    found = extract(record, source_id=uuid.uuid4(), source_kind=SourceKind.MYSQL)

    assert isinstance(found, ExtractedRecord)
    assert found.title == f"{b}.invoices"
    columns = found.content[0].text.splitlines()
    assert columns[:2] == [
        "id bigint NOT NULL PRIMARY KEY",
        f"customer_id bigint NOT NULL → {b}.customers(id)",
    ]
    assert "CHECK (`amount` >= 0)" in columns
    assert [(r.role, r.external_id) for r in found.references] == [
        ("schema", b),
        ("references", f"{b}.customers"),
    ]
    assert found.signals == {
        "engine": "mysql",
        "storage_engine": "InnoDB",
        "host": "db.acme.example",
        "port": 3306,
    }
