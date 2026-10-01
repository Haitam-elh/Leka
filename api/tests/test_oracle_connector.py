"""The Oracle connector against a real Oracle (LEKA-349).

Each test gets its own schemas — Oracle users — `BILLING_*`: a foreign key,
a check, a descending index, defaults, an identity, a virtual column,
comments, a view, a materialized view, a partitioned table, a sequence; and
`SECRET_*` beside it. And an account made the way
docs/connectors/databases.md says: REFERENCES on each table and view of
BILLING_*, and nothing else. That the connector describes everything it
should with that account — while a SELECT is refused — is the proof that
it reads the catalogue, not the rows.

The connection is the real one — TCPS, then the session made read-only —
to the tests' server, on 2484: tests/oracle/tcps.sh sets TLS up there. Only
the address check is told where that server is. The admin connects over
plain TCP (1521), the tests' own business.

The server: `docker compose up -d oracle` locally, where these tests skip
without one; CI starts its own, and LEKA_REQUIRE_ORACLE_TESTS turns a skip
into a failure.
"""

from __future__ import annotations

import os
import re
import secrets
import ssl
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import oracledb
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
from leka.connectors.oracle import OracleConfig, OracleConnector, OracleCredentials
from leka.connectors.oracle import connector as ora
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
    os.environ.get("LEKA_ORACLE_TEST_URL", "oracle://system:Leka-local-1@127.0.0.1:1521/FREEPDB1")
)
ADMIN_PORT = SERVER.port or 1521
TLS_PORT = 2484  # tests/oracle/tcps.sh's
SERVICE = SERVER.path.lstrip("/") or "FREEPDB1"
REQUIRED = os.environ.get("LEKA_REQUIRE_ORACLE_TESTS") == "1"
# Kept before any test replaces it, for the tests that need it real.
PUBLIC_ADDRESS = network.public_address
HOW_TO_START = (
    f"no Oracle at {SERVER.hostname}:{ADMIN_PORT}. Start one with `docker compose up -d "
    "oracle`, or point LEKA_ORACLE_TEST_URL at another."
)


@dataclass(frozen=True)
class Catalogue:
    billing: str
    secret: str
    reader: str
    password: str


def _admin() -> Any:
    return oracledb.connect(
        user=SERVER.username,
        password=SERVER.password,
        host=SERVER.hostname,
        port=ADMIN_PORT,
        service_name=SERVICE,
        tcp_connect_timeout=5,
        retry_count=0,
    )


def _run(db: Any, *statements: str) -> list[tuple[Any, ...]]:
    """The statements, one after the other; the last one's rows."""
    cursor = db.cursor()
    rows: list[tuple[Any, ...]] = []
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
    suffix = secrets.token_hex(4).upper()
    made = Catalogue(
        billing=f"BILLING_{suffix}",
        secret=f"SECRET_{suffix}",
        reader=f"LEKA_READER_{suffix}",
        password="Pw-" + secrets.token_hex(12),
    )
    b, s, reader = made.billing, made.secret, made.reader
    admin = _admin()
    # Names made above, not input: formatting them in is safe.
    _run(
        admin,
        f"CREATE USER {b} NO AUTHENTICATION QUOTA UNLIMITED ON users",
        f"CREATE USER {s} NO AUTHENTICATION QUOTA UNLIMITED ON users",
        # What a materialized view's owner needs; the account gets none of it.
        f"GRANT CREATE TABLE, CREATE MATERIALIZED VIEW TO {b}",
        f"CREATE TABLE {s}.salaries (id NUMBER PRIMARY KEY, amount NUMBER)",
        f"GRANT REFERENCES ON {s}.salaries TO {b}",
        f"""CREATE TABLE {b}.customers (
            id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            email VARCHAR2(200) NOT NULL CONSTRAINT customers_email UNIQUE,
            name NVARCHAR2(100),
            created_at TIMESTAMP(3) DEFAULT SYSTIMESTAMP NOT NULL,
            plan_name VARCHAR2(20 CHAR) DEFAULT 'free',
            domain GENERATED ALWAYS AS (SUBSTR(email, INSTR(email, '@') + 1)) VIRTUAL
        )""",
        f"""CREATE TABLE {b}.invoices (
            id NUMBER(19) PRIMARY KEY,
            customer_id NUMBER NOT NULL,
            amount NUMBER(12, 2) CONSTRAINT invoices_amount CHECK (amount >= 0),
            paid NUMBER(1) DEFAULT 0 NOT NULL,
            CONSTRAINT invoices_customer FOREIGN KEY (customer_id)
                REFERENCES {b}.customers (id) ON DELETE CASCADE
        )""",
        f"CREATE INDEX {b}.invoices_unpaid ON {b}.invoices (customer_id DESC, id)",
        # Points into the other schema, which the account may not see.
        f"""CREATE TABLE {b}.payouts (
            id NUMBER PRIMARY KEY,
            salary_id NUMBER CONSTRAINT payouts_salary REFERENCES {s}.salaries (id)
        )""",
        f"""CREATE TABLE {b}.events (id NUMBER, happened DATE)
            PARTITION BY RANGE (happened) INTERVAL (NUMTOYMINTERVAL(1, 'MONTH'))
            (PARTITION before_2026 VALUES LESS THAN (DATE '2026-01-01'))""",
        f"CREATE SEQUENCE {b}.invoice_numbers",
        f"""CREATE VIEW {b}.unpaid AS SELECT i.id, c.email FROM {b}.invoices i
            JOIN {b}.customers c ON c.id = i.customer_id WHERE i.paid = 0""",  # noqa: S608
        f"""CREATE MATERIALIZED VIEW {b}.totals AS
            SELECT customer_id, SUM(amount) AS total FROM {b}.invoices GROUP BY customer_id""",  # noqa: S608
        f"COMMENT ON TABLE {b}.customers IS 'Who pays'",
        f"COMMENT ON COLUMN {b}.customers.email IS 'Where invoices go'",
        f"INSERT INTO {b}.customers (email) VALUES ('ada@acme.example')",  # noqa: S608
        f"INSERT INTO {b}.invoices VALUES (1, 1, 1200, 0)",  # noqa: S608
        "COMMIT",
        f"BEGIN DBMS_STATS.GATHER_SCHEMA_STATS('{b}'); END;",
        f'CREATE USER {reader} IDENTIFIED BY "{made.password}"',
        f"GRANT CREATE SESSION TO {reader}",
        *(
            f"GRANT REFERENCES ON {b}.{name} TO {reader}"
            for name in ("customers", "invoices", "payouts", "events", "unpaid", "totals")
        ),
    )
    try:
        yield made
    finally:
        _run(
            admin,
            f"DROP USER {reader} CASCADE",
            f"DROP USER {b} CASCADE",
            f"DROP USER {s} CASCADE",
        )
        admin.close()


def _connector(
    made: Catalogue,
    user: str | None = None,
    password: str | None = None,
    *,
    schemas: list[str] | None = None,
    port: int = TLS_PORT,
    service: str = SERVICE,
) -> OracleConnector:
    return OracleConnector(
        OracleConfig(host=HOST, port=port, service_name=service, schemas=schemas),
        OracleCredentials(
            username=user or made.reader, password=SecretStr(password or made.password)
        ),
    )


def _system(made: Catalogue, **kwargs: Any) -> OracleConnector:
    return _connector(made, str(SERVER.username), SERVER.password or "", **kwargs)


async def _read(connector: OracleConnector, capability: Capability) -> list[RawRecord]:
    return [record async for record in connector.iter_resources(capability)]


async def _failure(connector: OracleConnector) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()
    return caught.value


def _payloads(records: list[RawRecord]) -> dict[str, dict[str, Any]]:
    return {r.external_id: dict(r.payload) for r in records}


def _by(items: list[dict[str, Any]], key: str = "name") -> dict[str, dict[str, Any]]:
    return {str(item[key]): item for item in items}


# ── the connection test ──────────────────────────────────────────────────────


async def test_an_account_with_references_alone_passes(catalogue: Catalogue) -> None:
    result = await _connector(catalogue, schemas=[catalogue.billing]).test_connection()

    assert result.account == f"{catalogue.reader}@{HOST}"
    assert set(result.capabilities) == {C.SCHEMAS, C.TABLES}
    assert str(result.metadata["version"]).split(".")[0].isdigit()
    assert result.metadata["database"] == SERVICE
    assert result.metadata["schemas_visible"] == 1
    assert result.warnings == []


async def test_an_account_that_can_do_more_than_read_is_accepted_with_warnings(
    catalogue: Catalogue,
) -> None:
    result = await _system(catalogue, schemas=[catalogue.billing]).test_connection()

    assert len(result.warnings) == 2
    assert "SELECT" in result.warnings[0]
    assert "plus que lire" in result.warnings[1]


async def test_a_schema_in_scope_the_account_cannot_see_is_named(catalogue: Catalogue) -> None:
    error = await _failure(_connector(catalogue, schemas=[catalogue.billing, catalogue.secret]))

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert catalogue.secret in error.diagnostic.message
    assert catalogue.billing not in error.diagnostic.message


async def test_a_wrong_password_is_refused_and_never_repeated(catalogue: Catalogue) -> None:
    wrong = "not-" + catalogue.password

    error = await _failure(_connector(catalogue, password=wrong))

    assert error.diagnostic.code is DiagnosticCode.AUTH_INVALID
    assert wrong not in error.diagnostic.model_dump_json()


async def test_an_unknown_service_is_named(catalogue: Catalogue) -> None:
    error = await _failure(_connector(catalogue, service="NOWHERE"))

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert "service" in error.diagnostic.message


async def test_a_port_without_tls_is_refused(catalogue: Catalogue) -> None:
    error = await _failure(_connector(catalogue, port=ADMIN_PORT))  # plain TCP there

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "TCPS" in error.diagnostic.message


async def test_a_session_that_is_not_tls_is_refused(catalogue: Catalogue) -> None:
    connector = _connector(catalogue)

    async def in_the_clear() -> Any:
        return await oracledb.connect_async(
            user=catalogue.reader,
            password=catalogue.password,
            host=SERVER.hostname,
            port=ADMIN_PORT,
            service_name=SERVICE,
        )

    connector._open = in_the_clear  # type: ignore[method-assign]

    error = await _failure(connector)

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "TCPS" in error.diagnostic.message


async def test_no_server_on_the_port_is_unreachable(catalogue: Catalogue) -> None:
    error = await _failure(_connector(catalogue, port=1))

    assert error.diagnostic.code is DiagnosticCode.NETWORK_UNREACHABLE


async def test_health_is_a_connection_that_answers(catalogue: Catalogue) -> None:
    assert (await _connector(catalogue).check_health()).status is HealthStatus.HEALTHY


async def test_the_scope_offers_what_the_account_may_see(catalogue: Catalogue) -> None:
    listing = await _connector(catalogue).list_scope()

    assert [option.key for option in listing.options] == [catalogue.billing]


# ── what is read ─────────────────────────────────────────────────────────────


async def test_schemas_are_read_with_their_database(catalogue: Catalogue) -> None:
    [schema] = await _read(_connector(catalogue), C.SCHEMAS)

    assert (schema.external_id, schema.container) == (catalogue.billing, catalogue.billing)
    assert schema.payload == {
        "name": catalogue.billing,
        "owner": catalogue.billing,
        "comment": None,
        "database": SERVICE,
        # Where it was read (LEKA-364): the service, as Oracle's names are,
        # case-insensitive.
        "server": {
            "engine": "oracle",
            "host": HOST,
            "port": TLS_PORT,
            "database": SERVICE.lower(),
        },
    }


async def test_tables_are_described_while_their_rows_are_refused(catalogue: Catalogue) -> None:
    b = catalogue.billing

    tables = _payloads(await _read(_connector(catalogue), C.TABLES))

    # The sequence is not read; the other schema is not seen at all.
    assert set(tables) == {
        f"{b}.{name}" for name in ("CUSTOMERS", "INVOICES", "PAYOUTS", "EVENTS", "UNPAID", "TOTALS")
    }
    customers, invoices = tables[f"{b}.CUSTOMERS"], tables[f"{b}.INVOICES"]
    assert (customers["kind"], customers["owner"], customers["comment"]) == ("table", b, "Who pays")
    assert customers["estimated_rows"] == 1
    columns = _by(customers["columns"])
    assert columns["EMAIL"] == {
        "name": "EMAIL",
        "type": "VARCHAR2(200)",
        "nullable": False,
        "default": None,
        "comment": "Where invoices go",
    }
    assert {name: (c["type"], c["default"]) for name, c in columns.items()} == {
        "ID": ("NUMBER", "GENERATED ALWAYS AS IDENTITY"),
        "EMAIL": ("VARCHAR2(200)", None),
        "NAME": ("NVARCHAR2(100)", None),
        "CREATED_AT": ("TIMESTAMP(3)", "SYSTIMESTAMP"),
        "PLAN_NAME": ("VARCHAR2(20 CHAR)", "'free'"),
        "DOMAIN": ("VARCHAR2(800)", """AS (SUBSTR("EMAIL",INSTR("EMAIL",'@')+1))"""),
    }
    assert _by(invoices["columns"])["AMOUNT"]["type"] == "NUMBER(12,2)"
    constraints = {c["type"]: c for c in invoices["constraints"]}
    # A NOT NULL is the column's, not a check.
    assert sorted(constraints) == ["check", "foreign_key", "primary_key"]
    assert constraints["primary_key"]["columns"] == ["ID"]
    assert constraints["foreign_key"]["references"] == {
        "schema": b,
        "table": "CUSTOMERS",
        "columns": ["ID"],
    }
    assert constraints["foreign_key"]["definition"] == (
        f"FOREIGN KEY (CUSTOMER_ID) REFERENCES {b}.CUSTOMERS(ID) ON DELETE CASCADE"
    )
    assert constraints["check"] == {
        "name": "INVOICES_AMOUNT",
        "type": "check",
        "columns": ["AMOUNT"],
        "definition": "CHECK (amount >= 0)",
    }
    assert {c["type"] for c in customers["constraints"]} == {"primary_key", "unique"}
    unpaid_index = _by(invoices["indexes"])["INVOICES_UNPAID"]
    assert unpaid_index["definition"] == (
        f'CREATE INDEX INVOICES_UNPAID ON {b}.INVOICES ("CUSTOMER_ID" DESC, ID)'
    )
    assert [i["primary"] for i in invoices["indexes"]].count(True) == 1
    # A key to a table in a schema the account may not see is not read.
    assert [c["type"] for c in tables[f"{b}.PAYOUTS"]["constraints"]] == ["primary_key"]
    assert tables[f"{b}.EVENTS"]["kind"] == "partitioned_table"
    totals = tables[f"{b}.TOTALS"]
    assert totals["kind"] == "materialized_view"
    assert "SUM(amount)" in str(totals["definition"])
    # A view: its definition, with REFERENCES alone.
    unpaid = tables[f"{b}.UNPAID"]
    assert unpaid["kind"] == "view"
    assert "WHERE i.paid = 0" in str(unpaid["definition"])
    assert catalogue.secret not in str(tables)
    assert "ada@acme.example" not in str(tables)

    reader = oracledb.connect(
        user=catalogue.reader,
        password=catalogue.password,
        host=SERVER.hostname,
        port=ADMIN_PORT,
        service_name=SERVICE,
    )
    try:  # and the account cannot read a row
        with pytest.raises(oracledb.DatabaseError, match="ORA-41900"):
            _run(reader, f"SELECT * FROM {b}.customers")  # noqa: S608
    finally:
        reader.close()


async def test_a_table_is_seen_once_it_is_granted(catalogue: Catalogue) -> None:
    b = catalogue.billing
    admin = _admin()
    _run(admin, f"CREATE TABLE {b}.refunds (id NUMBER PRIMARY KEY)")

    before = set(_payloads(await _read(_connector(catalogue), C.TABLES)))
    _run(admin, f"GRANT REFERENCES ON {b}.refunds TO {catalogue.reader}")
    after = set(_payloads(await _read(_connector(catalogue), C.TABLES)))
    admin.close()

    assert f"{b}.REFUNDS" not in before
    assert after - before == {f"{b}.REFUNDS"}


# ── the session ──────────────────────────────────────────────────────────────


async def test_the_session_writes_nothing_even_as_system(catalogue: Catalogue) -> None:
    connector = _system(catalogue)

    with pytest.raises(ConnectorError) as caught:
        async with connector._session() as db:
            written = f"INSERT INTO {catalogue.billing}.customers (email) VALUES ('x')"  # noqa: S608
            await ora._fetch(db, written)

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert "ORA-01456" in str(caught.value.diagnostic.detail)  # a READ ONLY transaction


async def test_the_session_is_tls_named_and_bounded(catalogue: Catalogue) -> None:
    async with _connector(catalogue)._session() as db:
        [me] = await ora._fetch(
            db,
            "SELECT SYS_CONTEXT('USERENV', 'NETWORK_PROTOCOL') AS protocol, "
            "SYS_CONTEXT('USERENV', 'SID') AS sid FROM dual",
        )
        admin = _admin()
        [(program,)] = _run(admin, f"SELECT program FROM v$session WHERE sid = {int(me['sid'])}")  # noqa: S608
        admin.close()
        bound = db.call_timeout

    assert (me["protocol"], program, bound) == ("tcps", "LEKA", 15_000)


async def test_a_call_too_slow_is_a_timeout(
    catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ora, "STATEMENT_TIMEOUT_MS", 1000)

    with pytest.raises(ConnectorError) as caught:
        async with _system(catalogue)._session() as db:
            await ora._fetch(db, "BEGIN DBMS_SESSION.SLEEP(3); END;")

    assert caught.value.diagnostic.code is DiagnosticCode.TIMEOUT


async def test_more_tables_than_a_pass_reads_is_a_failure_not_a_cut(
    catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ora, "MAX_TABLES", 2)

    with pytest.raises(ConnectorError) as caught:
        await _read(_connector(catalogue), C.TABLES)

    assert caught.value.diagnostic.code is DiagnosticCode.CONFIG_INVALID


def test_the_queries_read_the_catalogue_and_nothing_else() -> None:
    relations = set()
    for query in ora.QUERIES:
        relations |= set(re.findall(r"\b(?:FROM|JOIN)\s+([\w.$]+)", query))
    assert relations
    catalogue = ("all_", "user_", "role_", "session_")
    assert all(
        relation.startswith(catalogue) or relation in ("dual", "product_component_version")
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


def _oracle(code: str, cause: BaseException | None = None) -> oracledb.Error:
    """An error as python-oracledb raises one: its first argument carries
    the code, the cause is chained."""
    error = oracledb.DatabaseError(SimpleNamespace(full_code=code, message=code))
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (network.PrivateAddressError("10.0.0.5"), DiagnosticCode.CONFIG_INVALID),
        (ora.NoTlsError("tcp"), DiagnosticCode.CONFIG_INVALID),
        # TCPS to a port that speaks TCP: the handshake reset (checked by hand).
        (_oracle("DPY-6005", ConnectionResetError()), DiagnosticCode.CONFIG_INVALID),
        (_oracle("DPY-6005", ssl.SSLError("wrong version")), DiagnosticCode.CONFIG_INVALID),
        (_oracle("DPY-4011", TimeoutError()), DiagnosticCode.TIMEOUT),
        (_oracle("DPY-4024"), DiagnosticCode.TIMEOUT),
        (_oracle("ORA-01017"), DiagnosticCode.AUTH_INVALID),
        (_oracle("ORA-28000"), DiagnosticCode.AUTH_INVALID),
        (_oracle("DPY-6005", _oracle("DPY-6001")), DiagnosticCode.NOT_FOUND),
        (_oracle("ORA-41900"), DiagnosticCode.PERMISSION_DENIED),
        (_oracle("ORA-01045"), DiagnosticCode.PERMISSION_DENIED),
        (
            _oracle("DPY-6005", ConnectionRefusedError(61, "refused")),
            DiagnosticCode.NETWORK_UNREACHABLE,
        ),
        (_oracle("ORA-00904"), DiagnosticCode.PROVIDER_ERROR),
        (RuntimeError("?"), DiagnosticCode.UNKNOWN),
    ],
)
def test_each_failure_has_its_diagnostic(error: Exception, code: DiagnosticCode) -> None:
    secret = "s3cr3t-" + secrets.token_hex(8)
    error.args = (*error.args, secret)
    connector = OracleConnector(
        OracleConfig(host=HOST, service_name="ORCLPDB1"),
        OracleCredentials(username="leka", password=SecretStr(secret)),
    )

    diagnostic = connector._diagnose(error).diagnostic

    assert diagnostic.code is code
    assert secret not in diagnostic.model_dump_json()


# ── what the catalogue says, written out ─────────────────────────────────────


@pytest.mark.parametrize(
    ("column", "written"),
    [
        ({"data_type": "VARCHAR2", "char_length": 200, "char_used": "B"}, "VARCHAR2(200)"),
        ({"data_type": "VARCHAR2", "char_length": 20, "char_used": "C"}, "VARCHAR2(20 CHAR)"),
        ({"data_type": "NVARCHAR2", "char_length": 100, "char_used": "C"}, "NVARCHAR2(100)"),
        ({"data_type": "NUMBER"}, "NUMBER"),
        ({"data_type": "NUMBER", "data_precision": 19, "data_scale": 0}, "NUMBER(19)"),
        ({"data_type": "NUMBER", "data_precision": 12, "data_scale": 2}, "NUMBER(12,2)"),
        ({"data_type": "NUMBER", "data_scale": 0}, "NUMBER(*,0)"),
        ({"data_type": "FLOAT", "data_precision": 126}, "FLOAT(126)"),
        ({"data_type": "RAW", "data_length": 16}, "RAW(16)"),
        ({"data_type": "TIMESTAMP(6) WITH TIME ZONE"}, "TIMESTAMP(6) WITH TIME ZONE"),
        ({"data_type": "CLOB"}, "CLOB"),
    ],
)
def test_a_type_is_written_as_oracle_writes_it(column: dict[str, Any], written: str) -> None:
    empty = {"char_length": 0, "char_used": None, "data_length": 0}
    assert ora._type({**empty, "data_precision": None, "data_scale": None, **column}) == written


# ── the settings ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [
        {"host": "10.0.0.5", "service_name": "ORCLPDB1"},
        {"host": "[::1]", "service_name": "ORCLPDB1"},
        {"host": "db.acme.example", "port": 70000, "service_name": "ORCLPDB1"},
        {"host": "db.acme.example"},
        {"host": "db.acme.example", "service_name": "ORCL PDB"},
        {"host": "db.acme.example", "service_name": "(DESCRIPTION=(ADDRESS=…))"},
        {"host": "db.acme.example", "service_name": "ORCLPDB1", "schemas": []},
        {"host": "db.acme.example", "service_name": "ORCLPDB1", "schemas": ["X" * 129]},
    ],
)
def test_settings_that_cannot_work_are_refused(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        OracleConfig.model_validate(config)


def test_the_hint_names_the_account_and_the_manifest_its_category() -> None:
    credentials = OracleCredentials(username="LEKA_READER", password=SecretStr("hunter2"))
    manifest = next(m for m in manifests() if m.display_name == "Oracle")

    assert next(iter(credentials.model_dump())) == "username"
    assert "hunter2" not in repr(credentials)
    assert OracleConfig(host="db.acme.example", service_name="ORCLPDB1").port == 2484
    assert manifest.key is SourceKind.ORACLE
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
                    text("INSERT INTO workspaces (name, slug) VALUES ('Oracle', :s) RETURNING id"),
                    {"s": f"oracle-{uuid.uuid4().hex[:10]}"},
                )
            ).scalar_one()
            await session.commit()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = SourceService(session, workspace_id, actor_user_id=None)
            created = await service.create(
                SourceKind.ORACLE,
                "Billing",
                {"host": HOST, "port": TLS_PORT, "service_name": SERVICE},
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
    tables = ("CUSTOMERS", "INVOICES", "PAYOUTS", "EVENTS", "UNPAID", "TOTALS")
    assert set(index) == {f"schemas:{b}", *(f"tables:{b}.{name}" for name in tables)}

    await sync_source(source.workspace_id, source.id, full=True)

    assert {k: r.payload_key for k, r in (await _index(source)).items()} == {
        k: r.payload_key for k, r in index.items()
    }  # unchanged, not written again
    extracted = await extract_source(source.workspace_id, source.id)
    assert (extracted["extracted"], extracted["failed"]) == (7, 0)


async def test_a_table_extracts_as_the_others_do_under_its_own_engine(
    catalogue: Catalogue,
) -> None:
    b = catalogue.billing
    [record] = [
        r for r in await _read(_connector(catalogue), C.TABLES) if r.external_id == f"{b}.INVOICES"
    ]

    found = extract(record, source_id=uuid.uuid4(), source_kind=SourceKind.ORACLE)

    assert isinstance(found, ExtractedRecord)
    assert found.title == f"{b}.INVOICES"
    columns = found.content[0].text.splitlines()
    assert columns[:2] == [
        "ID NUMBER(19) NOT NULL PRIMARY KEY",
        f"CUSTOMER_ID NUMBER NOT NULL → {b}.CUSTOMERS(ID)",
    ]
    assert "CHECK (amount >= 0)" in columns
    assert [(r.role, r.external_id) for r in found.references] == [
        ("schema", b),
        ("references", f"{b}.CUSTOMERS"),
    ]
    assert found.signals == {"engine": "oracle", "host": HOST, "port": TLS_PORT}
    assert found.metadata["database"] == SERVICE.lower()
