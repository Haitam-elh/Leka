"""The SQL Server connector against a real SQL Server (LEKA-349).

Each test gets a database made for it, `leka_*`: in schema `billing`, a
foreign key, a check, a filtered index with included columns, defaults, an
identity, a computed column, comments, a view, a table that keeps its
history, a sequence; in schema `secret`, a table. And a login made the way
docs/connectors/databases.md says: a user in that database with VIEW
DEFINITION on `billing`, and nothing else. That the connector describes
everything it should with that login — while a SELECT is refused — is the
proof that it reads the catalogue, not the rows.

The connection is the real one — TLS, then the session — to the tests'
server: only the address check is told where that server is. Whether the
session is encrypted is asked of the server itself, as an admin.

The server: `docker compose up -d sqlserver` locally — on an ARM Mac it
needs Docker with Rosetta, see docs/setup.md — where these tests skip
without one; CI starts its own, and LEKA_REQUIRE_SQLSERVER_TESTS turns a
skip into a failure.
"""

from __future__ import annotations

import os
import re
import secrets
import socket
import struct
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pymssql
import pytest
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
from leka.connectors.sqlserver import SQLServerConfig, SQLServerConnector, SQLServerCredentials
from leka.connectors.sqlserver import connector as ms
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
SERVER = urlparse(
    os.environ.get("LEKA_SQLSERVER_TEST_URL", "mssql://sa:Leka-local-1@127.0.0.1:1433")
)
PORT = SERVER.port or 1433
REQUIRED = os.environ.get("LEKA_REQUIRE_SQLSERVER_TESTS") == "1"
# Kept before any test replaces it, for the tests that need it real.
PUBLIC_ADDRESS = network.public_address
HOW_TO_START = (
    f"no SQL Server at {SERVER.hostname}:{PORT}. Start one with `docker compose up -d "
    "sqlserver`, or point LEKA_SQLSERVER_TEST_URL at another."
)


@dataclass(frozen=True)
class Catalogue:
    database: str
    reader: str
    password: str


# FreeTDS keeps one query timeout for the whole process, set by the last
# connection that gave one — pymssql leaves it as it is when given none. Each
# admin connection gives its own: what a test shortened (a query too slow,
# cut at one second) never reaches the fixtures after it.
ADMIN_TIMEOUT = 120


def _admin(database: str = "master") -> Any:
    return pymssql.connect(
        server=str(SERVER.hostname),
        port=str(PORT),
        user=SERVER.username,
        password=SERVER.password or "",
        database=database,
        autocommit=True,
        login_timeout=5,
        timeout=ADMIN_TIMEOUT,
    )


def _run(db: Any, *statements: str) -> list[dict[str, Any]]:
    """The statements, one after the other; the last one's rows."""
    cursor = db.cursor(as_dict=True)
    rows: list[dict[str, Any]] = []
    for statement in statements:
        cursor.execute(statement)
        rows = cursor.fetchall() if cursor.description else []
    return rows


@pytest.fixture(scope="session")
def server() -> Iterator[None]:
    try:
        _admin().close()
    except Exception:  # every way of not being there
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
def catalogue(server: None) -> Iterator[Catalogue]:
    suffix = secrets.token_hex(4)
    made = Catalogue(
        database=f"leka_{suffix}",
        reader=f"leka_reader_{suffix}",
        password=secrets.token_urlsafe(24) + "aA1!",
    )
    master = _admin()
    # Names made above, not input: formatting them in is safe.
    _run(
        master,
        f"CREATE DATABASE {made.database}",
        f"CREATE LOGIN {made.reader} WITH PASSWORD = '{made.password}', CHECK_POLICY = OFF",
    )
    db = _admin(made.database)
    _run(
        db,
        "CREATE SCHEMA billing",
        "CREATE SCHEMA secret",
        "CREATE TABLE secret.salaries (id int PRIMARY KEY, amount int)",
        """CREATE TABLE billing.customers (
            id bigint IDENTITY(1, 1) PRIMARY KEY,
            email nvarchar(200) NOT NULL CONSTRAINT customers_email UNIQUE,
            created_at datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME(),
            plan_name varchar(20) DEFAULT 'free',
            note nvarchar(max),
            domain AS SUBSTRING(email, CHARINDEX('@', email) + 1, 200)
        )""",
        """CREATE TABLE billing.invoices (
            id bigint PRIMARY KEY,
            customer_id bigint NOT NULL,
            amount decimal(12, 2) CONSTRAINT invoices_amount CHECK (amount >= 0),
            paid bit NOT NULL DEFAULT 0,
            CONSTRAINT invoices_customer FOREIGN KEY (customer_id)
                REFERENCES billing.customers (id) ON DELETE CASCADE
        )""",
        "CREATE INDEX invoices_unpaid ON billing.invoices (customer_id DESC, id) "
        "INCLUDE (amount) WHERE paid = 0",
        # Points into `secret`, which the login may not see.
        """CREATE TABLE billing.payouts (
            id int PRIMARY KEY,
            salary_id int CONSTRAINT payouts_salary REFERENCES secret.salaries (id)
        )""",
        """CREATE TABLE billing.prices (
            id int PRIMARY KEY, amount int,
            valid_from datetime2 GENERATED ALWAYS AS ROW START,
            valid_to datetime2 GENERATED ALWAYS AS ROW END,
            PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
        ) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = billing.prices_history))""",
        "CREATE SEQUENCE billing.invoice_numbers START WITH 1",
        "CREATE VIEW billing.unpaid AS SELECT i.id, c.email FROM billing.invoices i "
        "JOIN billing.customers c ON c.id = i.customer_id WHERE i.paid = 0",
        "EXEC sp_addextendedproperty 'MS_Description', 'Money', 'SCHEMA', 'billing'",
        "EXEC sp_addextendedproperty 'MS_Description', 'Who pays', 'SCHEMA', 'billing', "
        "'TABLE', 'customers'",
        "EXEC sp_addextendedproperty 'MS_Description', 'Where invoices go', 'SCHEMA', "
        "'billing', 'TABLE', 'customers', 'COLUMN', 'email'",
        "INSERT INTO billing.customers (email) VALUES ('ada@acme.example')",
        "INSERT INTO billing.invoices VALUES (1, 1, 1200.00, 0)",
        "INSERT INTO secret.salaries VALUES (1, 99000)",
        f"CREATE USER {made.reader} FOR LOGIN {made.reader}",
        f"GRANT VIEW DEFINITION ON SCHEMA::billing TO {made.reader}",
    )
    db.close()
    master.close()
    try:
        yield made
    finally:
        # A connection of its own: it sets the timeout the test may have cut.
        with closing(_admin()) as admin:
            _run(
                admin,
                f"ALTER DATABASE {made.database} SET SINGLE_USER WITH ROLLBACK IMMEDIATE",
                f"DROP DATABASE {made.database}",
                f"DROP LOGIN {made.reader}",
            )


def _connector(
    made: Catalogue,
    user: str | None = None,
    password: str | None = None,
    *,
    schemas: list[str] | None = None,
    database: str | None = None,
    port: int = PORT,
) -> SQLServerConnector:
    return SQLServerConnector(
        SQLServerConfig(host=HOST, port=port, database=database or made.database, schemas=schemas),
        SQLServerCredentials(
            username=user or made.reader, password=SecretStr(password or made.password)
        ),
    )


def _admin_connector(made: Catalogue, **kwargs: Any) -> SQLServerConnector:
    return _connector(made, str(SERVER.username), SERVER.password or "", **kwargs)


async def _read(connector: SQLServerConnector, capability: Capability) -> list[RawRecord]:
    return [record async for record in connector.iter_resources(capability)]


async def _failure(connector: SQLServerConnector) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()
    return caught.value


def _payloads(records: list[RawRecord]) -> dict[str, dict[str, Any]]:
    return {r.external_id: dict(r.payload) for r in records}


def _by(items: list[dict[str, Any]], key: str = "name") -> dict[str, dict[str, Any]]:
    return {str(item[key]): item for item in items}


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_login_with_view_definition_alone_passes(catalogue: Catalogue) -> None:
    result = await _connector(catalogue, schemas=["billing"]).test_connection()

    assert result.account == f"{catalogue.reader}@{HOST}"
    assert set(result.capabilities) == {C.SCHEMAS, C.TABLES}
    assert str(result.metadata["version"]).split(".")[0].isdigit()
    assert result.metadata["database"] == catalogue.database
    assert result.metadata["schemas_visible"] == 1
    assert result.warnings == []


async def test_a_login_that_can_do_more_than_read_is_accepted_with_warnings(
    catalogue: Catalogue,
) -> None:
    result = await _admin_connector(catalogue, schemas=["billing"]).test_connection()

    assert len(result.warnings) == 2
    assert "SELECT" in result.warnings[0]
    assert "plus que lire" in result.warnings[1]


async def test_select_on_a_schema_in_scope_is_a_warning(catalogue: Catalogue) -> None:
    db = _admin(catalogue.database)
    _run(db, f"GRANT SELECT ON SCHEMA::billing TO {catalogue.reader}")
    db.close()

    warnings = (await _connector(catalogue).test_connection()).warnings

    assert ["SELECT" in w for w in warnings] == [True]


async def test_a_schema_in_scope_the_login_cannot_see_is_named(catalogue: Catalogue) -> None:
    error = await _failure(_connector(catalogue, schemas=["billing", "secret"]))

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert "secret" in error.diagnostic.message
    assert "billing" not in error.diagnostic.message


async def test_view_definition_on_the_database_shows_every_schema(catalogue: Catalogue) -> None:
    db = _admin(catalogue.database)
    _run(db, f"GRANT VIEW DEFINITION TO {catalogue.reader}")
    db.close()

    listing = await _connector(catalogue).list_scope()

    assert {"billing", "dbo", "secret"} <= {option.key for option in listing.options}
    assert not {"sys", "INFORMATION_SCHEMA", "guest", "db_owner"} & {
        option.key for option in listing.options
    }


async def test_a_wrong_password_is_refused_and_never_repeated(catalogue: Catalogue) -> None:
    wrong = "not-" + catalogue.password

    error = await _failure(_connector(catalogue, password=wrong))

    assert error.diagnostic.code is DiagnosticCode.AUTH_INVALID
    assert wrong not in error.diagnostic.model_dump_json()


async def test_a_database_the_login_has_no_user_in_is_refused(catalogue: Catalogue) -> None:
    error = await _failure(_connector(catalogue, database="master_of_nothing"))

    assert error.diagnostic.code is DiagnosticCode.AUTH_INVALID
    assert "base" in error.diagnostic.message


async def test_no_server_on_the_port_is_unreachable(catalogue: Catalogue) -> None:
    error = await _failure(_connector(catalogue, port=1))

    assert error.diagnostic.code is DiagnosticCode.NETWORK_UNREACHABLE


async def test_health_is_a_connection_that_answers(catalogue: Catalogue) -> None:
    assert (await _connector(catalogue).check_health()).status is HealthStatus.HEALTHY


async def test_the_scope_offers_what_the_login_may_see(catalogue: Catalogue) -> None:
    listing = await _connector(catalogue).list_scope()

    assert [option.key for option in listing.options] == ["billing"]


# ── what is read ─────────────────────────────────────────────────────────────


async def test_schemas_are_read_with_their_database(catalogue: Catalogue) -> None:
    [schema] = await _read(_connector(catalogue), C.SCHEMAS)

    assert (schema.external_id, schema.container) == ("billing", "billing")
    assert schema.payload == {
        "name": "billing",
        "owner": "dbo",
        "comment": "Money",
        "database": catalogue.database,
        # Where it was read (LEKA-364).
        "server": {
            "engine": "sqlserver",
            "host": HOST,
            "port": PORT,
            "database": catalogue.database,
        },
    }


async def test_tables_are_described_while_their_rows_are_refused(catalogue: Catalogue) -> None:
    tables = _payloads(await _read(_connector(catalogue), C.TABLES))

    # The sequence is not a table LEKA reads; `secret` is not seen at all.
    assert set(tables) == {
        f"billing.{name}"
        for name in ("customers", "invoices", "payouts", "prices", "prices_history", "unpaid")
    }
    customers, invoices = tables["billing.customers"], tables["billing.invoices"]
    assert (customers["kind"], customers["owner"], customers["comment"]) == (
        "table",
        "dbo",
        "Who pays",
    )
    assert customers["estimated_rows"] == 1
    assert customers["size_bytes"] > 0
    columns = _by(customers["columns"])
    assert columns["email"] == {
        "name": "email",
        "type": "nvarchar(200)",
        "nullable": False,
        "default": None,
        "comment": "Where invoices go",
    }
    assert {name: (c["type"], c["default"]) for name, c in columns.items()} == {
        "id": ("bigint", "IDENTITY(1,1)"),
        "email": ("nvarchar(200)", None),
        "created_at": ("datetime2(3)", "sysutcdatetime()"),
        "plan_name": ("varchar(20)", "'free'"),
        "note": ("nvarchar(max)", None),
        "domain": ("nvarchar(200)", "AS substring([email],charindex('@',[email])+(1),(200))"),
    }
    assert _by(invoices["columns"])["amount"]["type"] == "decimal(12,2)"
    constraints = {c["type"]: c for c in invoices["constraints"]}
    assert constraints["primary_key"]["columns"] == ["id"]
    assert constraints["foreign_key"]["references"] == {
        "schema": "billing",
        "table": "customers",
        "columns": ["id"],
    }
    assert constraints["foreign_key"]["definition"] == (
        "FOREIGN KEY (customer_id) REFERENCES billing.customers(id) ON DELETE CASCADE"
    )
    assert constraints["check"] == {
        "name": "invoices_amount",
        "type": "check",
        "columns": ["amount"],
        "definition": "CHECK ([amount]>=(0))",
    }
    assert {c["type"] for c in customers["constraints"]} == {"primary_key", "unique"}
    assert _by(invoices["indexes"])["invoices_unpaid"] == {
        "name": "invoices_unpaid",
        "definition": "CREATE NONCLUSTERED INDEX invoices_unpaid ON billing.invoices "
        "(customer_id DESC, id) INCLUDE (amount) WHERE ([paid]=(0))",
        "unique": False,
        "primary": False,
    }
    # A key to a table in a schema the login may not see is not read.
    assert [c["type"] for c in tables["billing.payouts"]["constraints"]] == ["primary_key"]
    prices = tables["billing.prices"]
    assert prices["kind"] == "system_versioned_table"
    assert tables["billing.prices_history"]["kind"] == "history_table"
    assert _by(prices["columns"])["valid_from"]["default"] == "GENERATED ALWAYS AS ROW START"
    # A view: its definition and what it reads, with VIEW DEFINITION alone.
    unpaid = tables["billing.unpaid"]
    assert unpaid["kind"] == "view"
    assert "WHERE i.paid = 0" in str(unpaid["definition"])
    assert unpaid["reads_from"] == ["billing.customers", "billing.invoices"]
    assert (unpaid["estimated_rows"], unpaid["size_bytes"]) == (None, None)
    assert "secret" not in str(tables)
    assert "ada@acme.example" not in str(tables)

    reader = pymssql.connect(
        server=str(SERVER.hostname),
        port=str(PORT),
        user=catalogue.reader,
        password=catalogue.password,
        database=catalogue.database,
    )
    try:  # and the login cannot read a row
        with pytest.raises(pymssql.OperationalError) as refused:
            _run(reader, "SELECT * FROM billing.customers")
        assert refused.value.args[0] == 229
    finally:
        reader.close()


async def test_a_schema_named_beyond_ascii_is_read(catalogue: Catalogue) -> None:
    db = _admin(catalogue.database)
    _run(
        db,
        "EXEC(N'CREATE SCHEMA [ventes_été]')",
        "CREATE TABLE [ventes_été].commandes (id int PRIMARY KEY)",
        f"GRANT VIEW DEFINITION ON SCHEMA::[ventes_été] TO {catalogue.reader}",
    )
    db.close()
    connector = _connector(catalogue, schemas=["ventes_été"])

    assert (await connector.test_connection()).warnings == []
    assert set(_payloads(await _read(connector, C.TABLES))) == {"ventes_été.commandes"}


# ── the session ──────────────────────────────────────────────────────────────


async def test_the_session_keeps_nothing_it_wrote_even_as_sa(catalogue: Catalogue) -> None:
    async with _admin_connector(catalogue)._session() as db:
        await db.fetch("INSERT INTO billing.customers (email) VALUES ('mallory@acme.example')")
        await db.fetch("CREATE TABLE billing.planted (id int)")
        [row] = await db.fetch("SELECT COUNT(*) AS n FROM billing.customers")
        assert row["n"] == 2  # written, inside the transaction

    admin = _admin(catalogue.database)
    [kept] = _run(admin, "SELECT COUNT(*) AS n FROM billing.customers")
    [planted] = _run(admin, "SELECT OBJECT_ID('billing.planted') AS id")
    admin.close()
    assert (kept["n"], planted["id"]) == (1, None)  # rolled back when it closed


async def test_the_session_is_encrypted_named_and_bounded(catalogue: Catalogue) -> None:
    async with _connector(catalogue)._session() as db:
        [me] = await db.fetch("SELECT @@SPID AS spid, @@LOCK_TIMEOUT AS lock_timeout")
        admin = _admin()
        [seen] = _run(
            admin,
            f"""SELECT c.encrypt_option, s.program_name FROM sys.dm_exec_connections c
                JOIN sys.dm_exec_sessions s ON s.session_id = c.session_id
                WHERE c.session_id = {int(me["spid"])}""",  # noqa: S608
        )
        admin.close()

    assert (seen["encrypt_option"], seen["program_name"]) == ("TRUE", "LEKA")
    assert me["lock_timeout"] == 15_000


def _server_without_tls() -> tuple[int, dict[str, bytes]]:
    """A server that answers the prelogin with ENCRYPT_NOT_SUP, and keeps
    what the client sends after it."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    seen: dict[str, bytes] = {}

    def serve() -> None:
        client, _ = listener.accept()
        with client, listener:
            seen["prelogin"] = client.recv(4096)
            options = (
                b"\x00" + struct.pack(">HH", 11, 6) + b"\x01" + struct.pack(">HH", 17, 1) + b"\xff"
            )
            body = options + bytes([16, 0, 0x10, 0xC7, 0, 0]) + b"\x02"  # ENCRYPT_NOT_SUP
            header = b"\x04\x01" + struct.pack(">H", 8 + len(body)) + b"\x00\x00\x01\x00"
            client.sendall(header + body)
            client.settimeout(5)
            try:
                seen["after"] = client.recv(4096)
            except OSError:
                seen["after"] = b""

    threading.Thread(target=serve, daemon=True).start()
    return listener.getsockname()[1], seen


async def test_a_server_without_tls_is_refused_before_the_login_is_sent(
    catalogue: Catalogue,
) -> None:
    port, seen = _server_without_tls()

    error = await _failure(_connector(catalogue, port=port))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "TLS" in error.diagnostic.message
    assert seen["prelogin"][0] == 0x12  # a prelogin, which asked for encryption…
    assert seen.get("after", b"") == b""  # …and no login, so no password, after it


async def test_a_query_too_slow_is_a_timeout(
    catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ms, "STATEMENT_TIMEOUT_MS", 1000)

    with pytest.raises(ConnectorError) as caught:
        async with _connector(catalogue)._session() as db:
            await db.fetch("WAITFOR DELAY '00:00:03'")

    assert caught.value.diagnostic.code is DiagnosticCode.TIMEOUT


async def test_a_timeout_a_test_shortens_does_not_outlive_it(
    catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FreeTDS keeps one query timeout for the whole process, set by the last
    # connection that gave one: a fixture after a test that shortened it must
    # not inherit it (CI, 2026-10-02: a CREATE DATABASE cut at one second).
    monkeypatch.setattr(ms, "STATEMENT_TIMEOUT_MS", 1000)
    async with _connector(catalogue)._session() as db:
        await db.fetch("SELECT 1 AS one")

    with closing(_admin()) as admin:
        _run(admin, "WAITFOR DELAY '00:00:02'")


async def test_more_tables_than_a_pass_reads_is_a_failure_not_a_cut(
    catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ms, "MAX_TABLES", 2)

    with pytest.raises(ConnectorError) as caught:
        await _read(_connector(catalogue), C.TABLES)

    assert caught.value.diagnostic.code is DiagnosticCode.CONFIG_INVALID


def test_the_queries_read_the_catalogue_and_nothing_else() -> None:
    relations = set()
    for query in ms.QUERIES:
        relations |= set(re.findall(r"\b(?:FROM|JOIN)\s+([\w.]+)", query))
    assert relations
    assert all(
        relation.startswith(("sys.", "INFORMATION_SCHEMA.")) or relation == "fn_my_permissions"
        for relation in relations
    )


async def test_an_address_that_is_not_public_is_refused(
    catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolve(host: str, port: int) -> list[str]:
        return ["10.0.0.5"]

    async def public_address(host: str, port: int) -> str:
        return await PUBLIC_ADDRESS(host, port, resolve=resolve)

    monkeypatch.setattr(network, "public_address", public_address)

    error = await _failure(_connector(catalogue))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "adresse publique" in error.diagnostic.message


def _dblib(*codes: int) -> bytes:
    return b"".join(f"DB-Lib error message {code}, severity 9:\n…\n".encode() for code in codes)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (network.PrivateAddressError("10.0.0.5"), DiagnosticCode.CONFIG_INVALID),
        # Connecting: what FreeTDS said, whatever the number — an earlier
        # failure's, as a refused port shows (18456 there, checked by hand).
        (pymssql.OperationalError(18456, _dblib(20009)), DiagnosticCode.NETWORK_UNREACHABLE),
        (pymssql.OperationalError(18456, _dblib(20018, 20002)), DiagnosticCode.AUTH_INVALID),
        (pymssql.OperationalError(18456, _dblib(20002)), DiagnosticCode.CONFIG_INVALID),
        (pymssql.OperationalError(20047, _dblib(20003, 20047)), DiagnosticCode.TIMEOUT),
        # Connected: the server's own number.
        (pymssql.OperationalError(1222, b"Lock request time out"), DiagnosticCode.TIMEOUT),
        (pymssql.OperationalError(229, _dblib(20018)), DiagnosticCode.PERMISSION_DENIED),
        (pymssql.OperationalError(208, _dblib(20018)), DiagnosticCode.PROVIDER_ERROR),
        (TimeoutError(), DiagnosticCode.TIMEOUT),
        (ConnectionRefusedError(61, "Connection refused"), DiagnosticCode.NETWORK_UNREACHABLE),
        (RuntimeError("?"), DiagnosticCode.UNKNOWN),
    ],
)
def test_each_failure_has_its_diagnostic(error: Exception, code: DiagnosticCode) -> None:
    secret = "s3cr3t-" + secrets.token_hex(8)
    error.args = (*error.args, secret)
    connector = SQLServerConnector(
        SQLServerConfig(host=HOST, database="app"),
        SQLServerCredentials(username="leka", password=SecretStr(secret)),
    )

    diagnostic = connector._diagnose(error).diagnostic

    assert diagnostic.code is code
    assert secret not in diagnostic.model_dump_json()


# ── what the catalogue says, written out ─────────────────────────────────────


@pytest.mark.parametrize(
    ("column", "written"),
    [
        ({"type": "nvarchar", "base_type": "nvarchar", "length": 400}, "nvarchar(200)"),
        ({"type": "nvarchar", "base_type": "nvarchar", "length": -1}, "nvarchar(max)"),
        ({"type": "varbinary", "base_type": "varbinary", "length": 16}, "varbinary(16)"),
        (
            {"type": "numeric", "base_type": "numeric", "length": 9, "precision": 9, "scale": 0},
            "numeric(9,0)",
        ),
        ({"type": "time", "base_type": "time", "length": 5, "scale": 0}, "time(0)"),
        ({"type": "int", "base_type": "int", "length": 4}, "int"),
        ({"type": "email", "base_type": "nvarchar", "length": 400}, "email"),  # an alias type
        ({"type": "sysname", "base_type": "nvarchar", "length": 256}, "sysname"),
    ],
)
def test_a_type_is_written_as_sql_server_writes_it(column: dict[str, Any], written: str) -> None:
    assert ms._type({"precision": 0, "scale": 0, **column}) == written


@pytest.mark.parametrize(
    ("expression", "unwrapped"),
    [
        ("((0))", "0"),
        ("('free')", "'free'"),
        ("(sysutcdatetime())", "sysutcdatetime()"),
        ("((1)+(2))", "(1)+(2)"),
        ("(1)+(2)", "(1)+(2)"),
        ("0", "0"),
    ],
)
def test_the_parentheses_sql_server_adds_are_taken_off(expression: str, unwrapped: str) -> None:
    assert ms._unwrapped(expression) == unwrapped


# ── the settings ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [
        {"host": "10.0.0.5", "database": "app"},
        {"host": "[::1]", "database": "app"},
        {"host": "db.acme.example\\SQLEXPRESS", "database": "app"},
        {"host": "db.acme.example", "port": 70000, "database": "app"},
        {"host": "db.acme.example"},
        {"host": "db.acme.example", "database": " "},
        {"host": "db.acme.example", "database": "app", "schemas": []},
        {"host": "db.acme.example", "database": "app", "schemas": ["x" * 129]},
    ],
)
def test_settings_that_cannot_work_are_refused(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SQLServerConfig.model_validate(config)


def test_the_hint_names_the_login_and_the_manifest_its_category() -> None:
    credentials = SQLServerCredentials(username="leka_reader", password=SecretStr("hunter2"))
    manifest = next(m for m in manifests() if m.display_name == "SQL Server")

    assert next(iter(credentials.model_dump())) == "username"
    assert "hunter2" not in repr(credentials)
    assert SQLServerConfig(host="db.acme.example", database="app").port == 1433
    assert manifest.key is SourceKind.SQLSERVER
    assert manifest.category is ConnectorCategory.DATA
    assert manifest.listed_whole == manifest.capabilities == {C.SCHEMAS, C.TABLES}
    assert ms.FREETDS_CONF.is_file()
    assert "encryption = require" in ms.FREETDS_CONF.read_text()


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
                    text(
                        "INSERT INTO workspaces (name, slug) VALUES ('SQL Server', :s) RETURNING id"
                    ),
                    {"s": f"sqlserver-{uuid.uuid4().hex[:10]}"},
                )
            ).scalar_one()
            await session.commit()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = SourceService(session, workspace_id, actor_user_id=None)
            created = await service.create(
                SourceKind.SQLSERVER,
                "Billing",
                {"host": HOST, "port": PORT, "database": catalogue.database},
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
    assert sorted(source.capabilities) == ["schemas", "tables"]

    report = await sync_source(source.workspace_id, source.id, full=True)

    assert report.status == "succeeded", report.error
    index = await _index(source)
    tables = ("customers", "invoices", "payouts", "prices", "prices_history", "unpaid")
    assert set(index) == {"schemas:billing", *(f"tables:billing.{name}" for name in tables)}

    await sync_source(source.workspace_id, source.id, full=True)

    assert {k: r.payload_key for k, r in (await _index(source)).items()} == {
        k: r.payload_key for k, r in index.items()
    }  # unchanged, not written again
    extracted = await extract_source(source.workspace_id, source.id)
    assert (extracted["extracted"], extracted["failed"]) == (7, 0)


async def test_a_table_extracts_as_the_others_do_under_its_own_engine(
    catalogue: Catalogue,
) -> None:
    [record] = [
        r
        for r in await _read(_connector(catalogue), C.TABLES)
        if r.external_id == "billing.invoices"
    ]

    found = extract(record, source_id=uuid.uuid4(), source_kind=SourceKind.SQLSERVER)

    assert isinstance(found, ExtractedRecord)
    assert found.title == "billing.invoices"
    columns = found.content[0].text.splitlines()
    assert columns[:2] == [
        "id bigint NOT NULL PRIMARY KEY",
        "customer_id bigint NOT NULL → billing.customers(id)",
    ]
    assert "CHECK ([amount]>=(0))" in columns
    assert [(r.role, r.external_id) for r in found.references] == [
        ("schema", "billing"),
        ("references", "billing.customers"),
    ]
    assert found.signals == {"engine": "sqlserver", "host": HOST, "port": PORT}
    assert found.metadata["database"] == catalogue.database
