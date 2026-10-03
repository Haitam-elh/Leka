"""The MongoDB connector against a real MongoDB (LEKA-349).

Each test gets two databases made for it: `billing_*`, with a validated
collection, a unique index, a compound one, and a view that looks another
collection up; and `secret_*` beside it. And an account made the way
docs/connectors/databases.md says: a role with listCollections,
listIndexes, collStats and dbStats on the billing database, and nothing
else. A listener sees every command the connector sends: none reads a
document.

The client is the real one, its addresses guarded: the tests only let the
guard accept the local server, and turn TLS off — the local server speaks
none. What the guard refuses, and a server without TLS, are tested apart.

The server: `docker compose up -d mongodb` locally, where these tests skip
without one; CI starts its own, and LEKA_REQUIRE_MONGODB_TESTS turns a skip
into a failure.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from pymongo import AsyncMongoClient, monitoring, pool_shared
from pymongo.errors import (
    ConfigurationError,
    OperationFailure,
    ServerSelectionTimeoutError,
)
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
from leka.connectors.mongodb import MongoDBConfig, MongoDBConnector, MongoDBCredentials
from leka.connectors.mongodb import connector as mongo
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
URL = os.environ.get("LEKA_MONGODB_TEST_URL", "mongodb://root:leka@127.0.0.1:27017")
# The name the config holds: a name, as a customer's would be, that the
# guard resolves — to the local server, which the tests let it accept.
ADDRESS = "mongodb://localhost:" + URL.rsplit(":", 1)[1].split("/")[0]
REQUIRED = os.environ.get("LEKA_REQUIRE_MONGODB_TESTS") == "1"
USER_NOT_FOUND, ROLE_NOT_FOUND = 11, 31  # MongoDB's codes
HOW_TO_START = (
    f"no MongoDB at {URL.rpartition('@')[2]}. Start one with `docker compose up -d mongodb`, "
    "or point LEKA_MONGODB_TEST_URL at another."
)


@dataclass(frozen=True)
class Catalogue:
    billing: str
    secret: str
    role: str
    reader: str
    password: str


class Commands(monitoring.CommandListener):
    """Every command a client sends, by name — and its first pipeline stage
    when it is an aggregate."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        name = event.command_name
        if name == "aggregate":
            [stage] = event.command["pipeline"][:1]
            name += ":" + next(iter(stage))
        self.sent.append(name)

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        pass

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        pass


def _admin() -> AsyncMongoClient[dict[str, Any]]:
    return AsyncMongoClient(URL, serverSelectionTimeoutMS=3000)


async def _drop(admin: Any, command: dict[str, str]) -> None:
    """A user or a role dropped — and one already gone let be: when the
    setup failed half-way, its failure is the one worth reading, not this.
    (On 2026-09-29 a full disk in CI failed a createUser; the dropUser
    after it said UserNotFound, and hid why.)"""
    try:
        await admin.command(command)
    except OperationFailure as error:
        if error.code not in (USER_NOT_FOUND, ROLE_NOT_FOUND):
            raise


@pytest.fixture(scope="session")
def server() -> Iterator[None]:
    async def reachable() -> bool:
        client = _admin()
        try:
            await client.admin.command("ping")
        except Exception:  # every way of not being there
            return False
        finally:
            await client.close()
        return True

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(network, "is_public", lambda address: True)
        up = asyncio.run(reachable())
    if not up:
        if REQUIRED:
            pytest.fail(HOW_TO_START)
        pytest.skip(HOW_TO_START)
    yield


@pytest.fixture
def local(monkeypatch: pytest.MonkeyPatch) -> Commands:
    """The guard, told the local server is fine; TLS off; a listener."""
    commands = Commands()
    monkeypatch.setattr(network, "is_public", lambda address: True)
    monkeypatch.setattr(mongo, "OPTIONS", {"tls": False, "event_listeners": [commands]})
    return commands


@pytest.fixture
async def catalogue(server: None, local: Commands) -> AsyncIterator[Catalogue]:
    suffix = secrets.token_hex(4)
    made = Catalogue(
        billing=f"billing_{suffix}",
        secret=f"secret_{suffix}",
        role=f"leka_catalogue_{suffix}",
        reader=f"leka_reader_{suffix}",
        password=secrets.token_urlsafe(24),
    )
    client = _admin()
    billing, admin = client[made.billing], client.admin
    try:
        await billing.create_collection(
            "customers",
            validator={
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": ["email"],
                    "properties": {
                        "email": {"bsonType": "string", "description": "Where invoices go"},
                        "name": {"bsonType": ["string", "null"]},
                    },
                }
            },
        )
        await billing.customers.create_index("email", unique=True)
        await billing.create_collection("invoices")
        await billing.invoices.create_index([("customer_id", 1), ("paid", -1)])
        await billing.command(
            {
                "create": "unpaid",
                "viewOn": "invoices",
                "pipeline": [
                    {"$match": {"paid": False}},
                    {
                        "$lookup": {
                            "from": "customers",
                            "localField": "customer_id",
                            "foreignField": "_id",
                            "as": "customer",
                        }
                    },
                ],
            }
        )
        await billing.customers.insert_one({"_id": 1, "email": "ada@acme.example"})
        await billing.invoices.insert_one({"_id": 1, "customer_id": 1, "paid": False})
        await client[made.secret].salaries.insert_one({"amount": 1})
        # The collections' sizes, settled: WiredTiger writes them at its
        # checkpoints — the server's own, every minute — and one landing
        # between two passes changed them, so that a pass rightly wrote the
        # table again (seen once, in a full run on 2026-10-03). A checkpoint
        # forced here: nothing moves them while a test reads. As the
        # PostgreSQL fixture's VACUUM (ANALYZE).
        await admin.command("fsync")
        await admin.command(
            {
                "createRole": made.role,
                "roles": [],
                "privileges": [
                    {
                        "resource": {"db": made.billing, "collection": ""},
                        "actions": sorted(mongo.STRUCTURE_ONLY),
                    }
                ],
            }
        )
        await admin.command(
            {
                "createUser": made.reader,
                "pwd": made.password,
                "roles": [{"role": made.role, "db": "admin"}],
            }
        )
        yield made
    finally:
        await client.drop_database(made.billing)
        await client.drop_database(made.secret)
        await _drop(admin, {"dropUser": made.reader})
        await _drop(admin, {"dropRole": made.role})
        await client.close()


def _connector(user: str, password: str, *, databases: list[str] | None = None) -> MongoDBConnector:
    return MongoDBConnector(
        MongoDBConfig(address=ADDRESS, databases=databases),
        MongoDBCredentials(username=user, password=SecretStr(password)),
    )


def _reader(made: Catalogue, **kwargs: Any) -> MongoDBConnector:
    return _connector(made.reader, made.password, **kwargs)


def _root() -> MongoDBConnector:
    user, _, rest = URL.split("://", 1)[1].partition(":")
    return _connector(user, rest.split("@", 1)[0])


async def _read(connector: MongoDBConnector, capability: Capability) -> list[RawRecord]:
    return [record async for record in connector.iter_resources(capability)]


async def _failure(connector: MongoDBConnector) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await connector.test_connection()
    return caught.value


def _payload(record: RawRecord) -> dict[str, Any]:
    return dict(record.payload)


def _by(items: list[dict[str, Any]], key: str = "name") -> dict[str, dict[str, Any]]:
    return {str(item[key]): item for item in items}


# ── the connection test ──────────────────────────────────────────────────────


async def test_an_account_with_the_four_actions_passes(catalogue: Catalogue) -> None:
    result = await _reader(catalogue, databases=[catalogue.billing]).test_connection()

    assert result.account == f"{catalogue.reader}@{ADDRESS.split('://')[1]}"
    assert set(result.capabilities) == {C.SCHEMAS, C.TABLES}
    assert str(result.metadata["version"]).split(".")[0].isdigit()
    assert result.metadata["schemas_visible"] == 1
    assert result.warnings == []


async def test_an_account_that_can_do_more_is_accepted_with_warnings(
    catalogue: Catalogue,
) -> None:
    warnings = (await _root().test_connection()).warnings

    assert len(warnings) == 2
    assert "find" in warnings[0]
    assert "plus que lire" in warnings[1]


async def test_a_database_in_scope_the_account_cannot_see_is_named(catalogue: Catalogue) -> None:
    error = await _failure(_reader(catalogue, databases=[catalogue.billing, catalogue.secret]))

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert catalogue.secret in error.diagnostic.message


async def test_a_wrong_password_is_refused_and_never_repeated(catalogue: Catalogue) -> None:
    wrong = "not-" + catalogue.password

    error = await _failure(_connector(catalogue.reader, wrong))

    assert error.diagnostic.code is DiagnosticCode.AUTH_INVALID
    assert wrong not in error.diagnostic.model_dump_json()


async def test_health_and_scope(catalogue: Catalogue) -> None:
    connector = _reader(catalogue)

    assert (await connector.check_health()).status is HealthStatus.HEALTHY
    assert [o.key for o in (await connector.list_scope()).options] == [catalogue.billing]


# ── what is read ─────────────────────────────────────────────────────────────


async def test_databases_are_read_as_schemas(catalogue: Catalogue) -> None:
    [database] = await _read(_reader(catalogue), C.SCHEMAS)

    assert (database.external_id, database.container) == (catalogue.billing, catalogue.billing)
    assert (database.payload["collections"], database.payload["views"]) == (2, 1)


async def test_collections_are_described_and_no_document_is_read(
    catalogue: Catalogue, local: Commands
) -> None:
    b = catalogue.billing

    records = await _read(_reader(catalogue), C.TABLES)

    found = {r.external_id: _payload(r) for r in records}
    assert set(found) == {f"{b}.customers", f"{b}.invoices", f"{b}.unpaid"}
    customers = found[f"{b}.customers"]
    assert customers["kind"] == "collection"
    assert customers["columns"] == [
        {
            "name": "email",
            "type": "string",
            "nullable": False,
            "default": None,
            "comment": "Where invoices go",
        },
        {"name": "name", "type": "string|null", "nullable": True, "default": None, "comment": None},
    ]
    assert {c["type"]: c["columns"] for c in customers["constraints"]} == {
        "primary_key": ["_id"],
        "unique": ["email"],
    }
    assert _by(customers["indexes"])["email_1"]["definition"] == "UNIQUE INDEX email_1 (email ASC)"
    assert customers["estimated_rows"] == 1
    assert _by(found[f"{b}.invoices"]["indexes"])["customer_id_1_paid_-1"]["definition"] == (
        "INDEX customer_id_1_paid_-1 (customer_id ASC, paid DESC)"
    )
    unpaid = found[f"{b}.unpaid"]
    assert unpaid["kind"] == "view"
    assert "$lookup" in str(unpaid["definition"])
    assert unpaid["reads_from"] == [f"{b}.invoices", f"{b}.customers"]
    assert "ada@acme.example" not in str(found)
    # What was sent: the catalogue's commands, and no read of a document.
    assert "find" not in local.sent
    assert {name for name in local.sent if name.startswith("aggregate")} == {"aggregate:$collStats"}
    assert set(local.sent) <= {
        "listDatabases",
        "listCollections",
        "listIndexes",
        "aggregate:$collStats",
        "dbStats",
        "endSessions",
        "saslStart",  # signing in
        "saslContinue",
    }


async def test_the_account_cannot_read_a_document(catalogue: Catalogue) -> None:
    host = URL.rpartition("@")[2]
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        f"mongodb://{catalogue.reader}:{catalogue.password}@{host}"
    )
    try:
        with pytest.raises(OperationFailure) as refused:
            await client[catalogue.billing].customers.find_one()
    finally:
        await client.close()

    assert refused.value.code == mongo.UNAUTHORIZED


async def test_more_collections_than_a_pass_reads_is_a_failure_not_a_cut(
    catalogue: Catalogue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mongo, "MAX_TABLES", 2)

    with pytest.raises(ConnectorError) as caught:
        await _read(_reader(catalogue), C.TABLES)

    assert caught.value.diagnostic.code is DiagnosticCode.CONFIG_INVALID


# ── the guard, and TLS ───────────────────────────────────────────────────────


async def test_the_driver_is_guarded(server: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """No leave for the local server: the guard refuses it, as it would a
    name leading into LEKA's own network, or a host a replica set
    announced."""
    monkeypatch.setattr(mongo, "OPTIONS", {"tls": False})
    monkeypatch.setattr(mongo, "CONNECT_TIMEOUT", 2.0)

    error = await _failure(_connector("leka", "not-tried"))

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "adresse publique" in error.diagnostic.message


async def test_the_driver_is_refused_a_socket() -> None:
    connect = vars(pool_shared)["_async_create_connection"]

    with pytest.raises(network.PrivateAddressError):
        await connect(("/run/mongodb-27017.sock", 0), None)


async def test_a_server_without_tls_is_refused(
    server: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(network, "is_public", lambda address: True)
    monkeypatch.setattr(mongo, "CONNECT_TIMEOUT", 2.0)

    error = await _failure(_root())

    assert error.diagnostic.code is DiagnosticCode.CONFIG_INVALID
    assert "TLS" in error.diagnostic.message


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (network.PrivateAddressError("10.0.0.5"), DiagnosticCode.CONFIG_INVALID),
        (
            ServerSelectionTimeoutError(f"db:27017: db {mongo.REFUSED}"),
            DiagnosticCode.CONFIG_INVALID,
        ),
        (
            ServerSelectionTimeoutError("db:27017: SSL handshake failed: [SSL] record layer"),
            DiagnosticCode.CONFIG_INVALID,
        ),
        (OperationFailure("Authentication failed.", code=18), DiagnosticCode.AUTH_INVALID),
        (OperationFailure("not authorized", code=13), DiagnosticCode.PERMISSION_DENIED),
        (OperationFailure("operation exceeded time limit", code=50), DiagnosticCode.TIMEOUT),
        (OperationFailure("something else", code=2), DiagnosticCode.PROVIDER_ERROR),
        (ConfigurationError("The DNS query name does not exist"), DiagnosticCode.CONFIG_INVALID),
        (
            ServerSelectionTimeoutError("db:27017: connection refused"),
            DiagnosticCode.NETWORK_UNREACHABLE,
        ),
        (ConnectionRefusedError(61, "Connection refused"), DiagnosticCode.NETWORK_UNREACHABLE),
        (RuntimeError("?"), DiagnosticCode.UNKNOWN),
    ],
)
def test_each_failure_has_its_diagnostic(error: Exception, code: DiagnosticCode) -> None:
    secret = "s3cr3t-" + secrets.token_hex(8)
    error.args = (*error.args, secret)
    connector = MongoDBConnector(
        MongoDBConfig(address="mongodb+srv://cluster0.abcd.mongodb.net"),
        MongoDBCredentials(username="leka", password=SecretStr(secret)),
    )

    diagnostic = connector._diagnose(error).diagnostic

    assert diagnostic.code is code
    assert secret not in diagnostic.model_dump_json()


# ── the settings ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("typed", "kept"),
    [
        (
            "mongodb+srv://ada:<db_password>@Cluster0.abcd.mongodb.net/?retryWrites=true&w=majority",
            "mongodb+srv://cluster0.abcd.mongodb.net",
        ),
        (
            "mongodb://db1.acme.com:27017,db2.acme.com:27018/app",
            "mongodb://db1.acme.com:27017,db2.acme.com:27018",
        ),
        ("mongodb://[2606:4700:4700::1111]:27017", "mongodb://[2606:4700:4700::1111]:27017"),
    ],
)
def test_the_address_is_kept_to_its_hosts(typed: str, kept: str) -> None:
    assert MongoDBConfig(address=typed).address == kept


@pytest.mark.parametrize(
    "address",
    [
        "https://cluster0.abcd.mongodb.net",
        "mongodb+srv://cluster0.abcd.mongodb.net:27017",
        "mongodb+srv://a.acme.com,b.acme.com",
        "mongodb://10.0.0.5:27017",
        "mongodb://[::1]:27017",
        "mongodb://%2Ftmp%2Fmongodb-27017.sock",
        "mongodb://mongo.sock",
        "mongodb://2001:db8::1:27017",
        "mongodb://db.acme.com:0",
    ],
)
def test_addresses_that_cannot_work_are_refused(address: str) -> None:
    with pytest.raises(ValidationError):
        MongoDBConfig(address=address)


def test_the_hint_names_the_account_and_the_manifest_its_category() -> None:
    credentials = MongoDBCredentials(username="leka_reader", password=SecretStr("hunter2"))
    manifest = next(m for m in manifests() if m.display_name == "MongoDB")

    assert next(iter(credentials.model_dump())) == "username"
    assert "hunter2" not in repr(credentials)
    assert MongoDBConfig(address="mongodb://db.acme.com").auth_database == "admin"
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
                    text("INSERT INTO workspaces (name, slug) VALUES ('Mongo', :s) RETURNING id"),
                    {"s": f"mongo-{uuid.uuid4().hex[:10]}"},
                )
            ).scalar_one()
            await session.commit()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = SourceService(session, workspace_id, actor_user_id=None)
            created = await service.create(
                SourceKind.MONGODB,
                "Billing",
                {"address": ADDRESS},
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


async def test_a_collection_extracts_as_a_table_does(catalogue: Catalogue) -> None:
    b = catalogue.billing
    [record] = [
        r for r in await _read(_reader(catalogue), C.TABLES) if r.external_id == f"{b}.customers"
    ]

    found = extract(record, source_id=uuid.uuid4(), source_kind=SourceKind.MONGODB)

    assert isinstance(found, ExtractedRecord)
    assert found.title == f"{b}.customers"
    assert found.content[0].text.splitlines() == [
        "email string NOT NULL UNIQUE — Where invoices go",
        "name string|null",
    ]
    assert found.metadata["primary_key"] == ["_id"]
    # Where it was read: the address's hosts (LEKA-364).
    assert found.signals == {"engine": "mongodb", "host": "localhost:27017"}
