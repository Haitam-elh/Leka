"""The MongoDB connector — a server's databases, and their collections and
views, as MongoDB describes them (LEKA-349).

LEKA reads what MongoDB says about its collections, never a document:
listDatabases, listCollections (with each collection's validator and each
view's pipeline), listIndexes, $collStats and dbStats. The account needs a
role with exactly those four actions on the databases to describe —
listCollections, listIndexes, collStats, dbStats — and not `find`
(tests/test_mongodb_connector.py runs with that role, and a find is
refused). MongoDB lists only the databases the account holds a privilege
on: the boundary is the server's own.

A collection has no declared columns: what it has is its validator. A
$jsonSchema one gives its fields — name, BSON type, required or not,
description — and those are the columns. Without one, a collection is its
name, its indexes and its size: inferring fields would mean reading
documents, and LEKA does not.

Safe by construction:

- every address the driver connects to — the seed, the hosts an SRV record
  names, the members a replica set announces — is resolved and checked
  public by the driver's own resolution, and connected to as checked
  (`guard_the_driver` below); a Unix socket is refused;
- **TLS** is required; the certificate is not verified, as the other
  database connectors;
- the account's role is the read-only boundary — the connector runs only
  commands that read, each bounded by a timeout.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from bson import json_util
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pymongo import AsyncMongoClient, pool_shared
from pymongo.errors import ConfigurationError, OperationFailure, PyMongoError

from leka.connectors import network
from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
    ScopeListing,
    ScopeOption,
)
from leka.connectors.databases import (
    CONNECT_TIMEOUT,
    HOST,
    MAX_SCOPE_OPTIONS,
    MAX_TABLES,
    STATEMENT_TIMEOUT_MS,
    public_host,
    rounded,
    schema_names,
    server,
    too_many_tables,
)
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

C = Capability
NAME_MAX = 63  # a MongoDB database's name
SYSTEM_DATABASES = frozenset({"admin", "local", "config"})
# What the role may hold and still only read the structure.
STRUCTURE_ONLY = frozenset({"listCollections", "listIndexes", "collStats", "dbStats"})
READS_DOCUMENTS = frozenset({"find", "changeStream"})
WRITES = frozenset(
    {
        "insert",
        "update",
        "remove",
        "createCollection",
        "dropCollection",
        "dropDatabase",
        "createIndex",
        "dropIndex",
        "collMod",
        "createUser",
        "grantRole",
        "createRole",
        "shutdown",
        "applicationMessage",
    }
)
# MongoDB's error codes, for the diagnostics.
UNAUTHORIZED = 13
AUTHENTICATION_FAILED = 18
TIME_LIMIT_EXCEEDED = 50
REFUSED = "is not a public address"  # PrivateAddressError's words, seen through the driver
# How the client connects: over TLS, encrypted, the certificate not
# verified. The tests replace it — their local server speaks no TLS — and
# add a listener that sees every command sent.
OPTIONS: dict[str, Any] = {
    "tls": True,
    "tlsAllowInvalidCertificates": True,
    "tlsAllowInvalidHostnames": True,
}
ADDRESS = re.compile(r"^mongodb(\+srv)?://")


class MongoDBConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = Field(
        min_length=1,
        max_length=1000,
        description=(
            "The server's address, as MongoDB writes it: mongodb+srv://cluster0.abcd.mongodb.net"
            " for Atlas, mongodb://db.acme.com:27017 otherwise — with no user or password."
        ),
    )
    auth_database: str = Field(
        default="admin",
        min_length=1,
        max_length=NAME_MAX,
        description="Where the account is defined: admin, on Atlas and most servers.",
    )
    databases: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="The databases to describe. Empty: every one the account may see.",
    )

    @field_validator("address")
    @classmethod
    def _address(cls, value: str) -> str:
        return mongodb_address(value)

    @field_validator("databases")
    @classmethod
    def _names(cls, value: list[str] | None) -> list[str] | None:
        return schema_names(value, NAME_MAX)


def mongodb_address(value: str) -> str:
    """The address, kept to its scheme and hosts: a user and password pasted
    with it are dropped — never stored in the config, they go in the
    credentials — and so are the options after `?`, which LEKA sets itself.

    mongodb+srv://ada:secret@cluster0.abcd.mongodb.net/?retryWrites=true
      → mongodb+srv://cluster0.abcd.mongodb.net
    """
    text = value.strip()
    if not ADDRESS.match(text):
        msg = "the address starts with mongodb:// or mongodb+srv://"
        raise ValueError(msg)
    srv = text.startswith("mongodb+srv://")
    netloc = urlsplit(text).netloc.rpartition("@")[2]
    hosts = [host.strip() for host in netloc.split(",") if host.strip()]
    if not hosts or (srv and len(hosts) != 1):
        msg = "mongodb+srv:// names one host; mongodb:// one or more"
        raise ValueError(msg)
    kept = []
    for host in hosts:
        name, port = _host_and_port(host)
        if srv and port:
            msg = "mongodb+srv:// takes no port"
            raise ValueError(msg)
        if port and not (port.isdigit() and 0 < int(port) < 65536):
            msg = f"{host!r}: the port is a number"
            raise ValueError(msg)
        if not re.match(HOST, name) or name.endswith(".sock"):
            msg = f"{name!r} is not a server's name or address"
            raise ValueError(msg)
        kept.append(public_host(name) + (f":{port}" if port else ""))
    return ("mongodb+srv://" if srv else "mongodb://") + ",".join(kept)


def _host_and_port(host: str) -> tuple[str, str]:
    """db.acme.com:27017 → (db.acme.com, 27017); [2001:db8::1]:27017 → the
    same, an IPv6 address in brackets as MongoDB writes it."""
    if host.startswith("["):
        name, _, rest = host.partition("]")
        if rest and not rest.startswith(":"):
            msg = f"{host!r} is not a server's name or address"
            raise ValueError(msg)
        return name + "]", rest[1:]
    if host.count(":") > 1:
        msg = "an IPv6 address is written in brackets: [2001:db8::1]:27017"
        raise ValueError(msg)
    name, _, port = host.partition(":")
    return name, port


class MongoDBCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field — the account's
    # name, which says nothing of the password.
    username: str = Field(min_length=1, max_length=256, description="The account.")
    password: SecretStr = Field(
        min_length=1,
        max_length=1024,
        description="Its password.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


# ── the guard: every address the driver connects to, checked ────────────────


def guard_the_driver() -> None:
    """Make pymongo resolve every host through a check, and refuse a socket.

    A MongoDB deployment names its own hosts — an SRV record, the members a
    replica set announces — so checking the seed is not enough: a server
    could announce 10.0.0.5, or /tmp/mongodb.sock. pymongo resolves each
    host in one function and connects to what it returned; wrapped here,
    what it connects to is what was checked. LEKA uses pymongo for nothing
    else, so the guard is the whole process's.

    Tied to pymongo's internals: if a version moves them, this raises at
    import rather than connecting unguarded, and
    test_the_driver_is_guarded fails.
    """
    internals = vars(pool_shared)  # the module's own names, private ones included
    if getattr(internals["_getaddrinfo"], "leka_guard", False):
        return
    resolve: Callable[..., Any] = internals["_getaddrinfo"]
    create: Callable[..., Any] = internals["_async_create_connection"]

    async def getaddrinfo(host: Any, port: Any, **kwargs: Any) -> Any:
        found = await resolve(host, port, **kwargs)
        addresses = [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in found]
        if not addresses or not all(network.is_public(address) for address in addresses):
            msg = f"{host} {REFUSED}"
            raise network.PrivateAddressError(msg)
        return found

    async def create_connection(address: Any, options: Any) -> Any:
        host = str(address[0])
        if host.endswith(".sock") or host.startswith("/"):
            msg = f"{host} {REFUSED}"
            raise network.PrivateAddressError(msg)
        return await create(address, options)

    getaddrinfo.leka_guard = True  # type: ignore[attr-defined]
    internals["_getaddrinfo"] = getaddrinfo
    internals["_async_create_connection"] = create_connection


guard_the_driver()


@register_connector
class MongoDBConnector(Connector[MongoDBConfig, MongoDBCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.MONGODB,
        display_name="MongoDB",
        category=ConnectorCategory.DATA,
        auth_type="token",
        config_schema=MongoDBConfig,
        credentials_schema=MongoDBCredentials,
        capabilities=frozenset({C.SCHEMAS, C.TABLES}),
        # MongoDB has no "changed since" for its catalogue: whole each pass.
        listed_whole=frozenset({C.SCHEMAS, C.TABLES}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._session() as client:
            build = await client.admin.command("buildInfo")
            status = await client.admin.command({"connectionStatus": 1, "showPrivileges": True})
            databases = await _databases(client)
            self._require_scope(databases)
            in_scope = self._in_scope(databases)
            if in_scope:
                await client[in_scope[0]].list_collection_names()
        auth = status.get("authInfo", {})
        users = auth.get("authenticatedUsers") or [{}]
        actions = {
            str(action)
            for privilege in auth.get("authenticatedUserPrivileges") or []
            for action in privilege.get("actions") or []
        }
        warnings: list[str] = []
        if actions & READS_DOCUMENTS:
            warnings.append(
                "Ce compte peut lire les documents (find). LEKA n'en a pas besoin : un rôle avec "
                "listCollections, listIndexes, collStats et dbStats suffit."
            )
        beyond = sorted(actions & WRITES)
        if beyond:
            named = ", ".join(beyond[:6]) + ("…" if len(beyond) > 6 else "")
            warnings.append(
                f"Ce compte peut plus que lire ({named}). LEKA ne lit que la description des "
                "collections : un rôle avec listCollections, listIndexes, collStats et dbStats "
                "suffit."
            )
        if not databases:
            warnings.append(
                "Aucune base n'est visible : donnez à ce compte un rôle sur les bases à décrire."
            )
        return ConnectionTestResult(
            account=f"{users[0].get('user', self.credentials.username)}@{_hosts(self.config)}",
            metadata={"version": str(build.get("version")), "schemas_visible": len(databases)},
            capabilities=[C.SCHEMAS, C.TABLES],
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._session() as client:
            await client.admin.command("ping")
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        async with self._session() as client:
            databases = await _databases(client)
        options = [ScopeOption(key=name, name=name) for name in databases[:MAX_SCOPE_OPTIONS]]
        return ScopeListing(options=options, truncated=len(databases) > MAX_SCOPE_OPTIONS)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"MongoDB does not read {capability}"
            raise ValueError(msg)
        fetched = datetime.now(UTC)
        async with self._session() as client:
            wanted = self._in_scope(await _databases(client))
            if capability is C.SCHEMAS:
                for name in wanted:
                    db = client[name]
                    stats = await db.command({"dbStats": 1})
                    # Counted here, not dbStats': it counts system.views too.
                    kinds = [
                        str(spec.get("type") or "collection")
                        async for spec in await db.list_collections()
                        if not str(spec["name"]).startswith("system.")
                    ]
                    payload = {
                        "name": name,
                        "collections": sum(kind != "view" for kind in kinds),
                        "views": kinds.count("view"),
                        "size_bytes": rounded(_int(stats.get("storageSize")) or None),
                        "server": self._server(),
                    }
                    # Its own container, as a repository is: the scope rules
                    # keep or leave a database and its collections alike.
                    yield _record(C.SCHEMAS, payload, name, name, fetched)
                return
            read = 0
            for name in wanted:
                for collection in await self._collections(client, name):
                    read += 1
                    if read > MAX_TABLES:
                        raise too_many_tables()
                    external_id = f"{name}.{collection['name']}"
                    payload = {**collection, "server": self._server()}
                    yield _record(C.TABLES, payload, external_id, name, fetched)

    def _server(self) -> dict[str, object]:
        """Where its catalogue is read: the address's hosts — a cluster, its
        databases its schemas (leka/connectors/databases.py)."""
        return server("mongodb", urlsplit(self.config.address).netloc, None, None)

    # ── inside ───────────────────────────────────────────────────────────────

    def _client(self) -> AsyncMongoClient[dict[str, Any]]:
        return AsyncMongoClient(
            self.config.address,
            username=self.credentials.username,
            password=self.credentials.password.get_secret_value(),
            authSource=self.config.auth_database,
            appname="LEKA",
            readPreference="secondaryPreferred",
            retryWrites=False,
            serverSelectionTimeoutMS=int(CONNECT_TIMEOUT * 1000),
            connectTimeoutMS=int(CONNECT_TIMEOUT * 1000),
            timeoutMS=STATEMENT_TIMEOUT_MS,
            **OPTIONS,
        )

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncMongoClient[dict[str, Any]]]:
        """A client for one call, closed after it; every failure a
        diagnostic."""
        try:
            client = self._client()
        except PyMongoError as error:
            raise self._diagnose(error) from error
        try:
            yield client
        except ConnectorError:
            raise
        except (PyMongoError, OSError) as error:
            raise self._diagnose(error) from error
        finally:
            await client.close()

    async def _collections(
        self, client: AsyncMongoClient[dict[str, Any]], database: str
    ) -> list[dict[str, Any]]:
        """Each collection and view of a database, described — asked of
        MongoDB collection by collection, as it has no other way."""
        db = client[database]
        found = []
        async for spec in await db.list_collections():
            name = str(spec["name"])
            if name.startswith("system."):
                continue
            kind = str(spec.get("type") or "collection")
            options = spec.get("options") or {}
            if "timeseries" in options:
                kind = "timeseries"
            validator = options.get("validator") or {}
            collection: dict[str, Any] = {
                "schema": database,
                "name": name,
                "kind": kind,
                "owner": None,
                "comment": None,
                "estimated_rows": None,
                "size_bytes": None,
                "definition": None,
                "columns": _columns(validator),
                "constraints": [],
                "indexes": [],
                "reads_from": [],
            }
            if kind == "view":
                pipeline = options.get("pipeline") or []
                collection["definition"] = json_util.dumps(
                    {"viewOn": options.get("viewOn"), "pipeline": pipeline}
                )
                collection["reads_from"] = _read_by(database, options.get("viewOn"), pipeline)
            else:
                indexes = [index async for index in await db[name].list_indexes()]
                collection["indexes"] = [_index(index) for index in indexes]
                collection["constraints"] = _constraints(indexes, validator)
                stats = await db[name].aggregate([{"$collStats": {"storageStats": {}}}])
                storage = [s.get("storageStats") or {} async for s in stats]  # one per shard
                collection["estimated_rows"] = rounded(sum(_int(s.get("count")) for s in storage))
                collection["size_bytes"] = rounded(
                    sum(_int(s.get("storageSize")) + _int(s.get("totalIndexSize")) for s in storage)
                )
            found.append(collection)
        return found

    def _in_scope(self, visible: list[str]) -> list[str]:
        if not self.config.databases:
            return visible
        chosen = set(self.config.databases)
        return [name for name in visible if name in chosen]

    def _require_scope(self, visible: list[str]) -> None:
        seen = set(visible)
        missing = [name for name in self.config.databases or [] if name not in seen]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Ce compte ne voit pas ces bases (aucun rôle dessus) : {named}.",
            )

    def _diagnose(self, error: BaseException) -> ConnectorError:
        """What went wrong, in the admin's words, the password never in it."""
        secrets = [self.credentials.password.get_secret_value()]
        detail = f"{type(error).__name__}: {error}"
        said = str(error)
        code = error.code if isinstance(error, OperationFailure) else None
        if isinstance(error, network.PrivateAddressError) or REFUSED in said:
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message=(
                    "Cet hôte, ou un serveur qu'il annonce, ne mène pas à une adresse publique."
                ),
                detail=detail,
                secrets=secrets,
            )
        if code == AUTHENTICATION_FAILED:
            return diagnose(
                DiagnosticCode.AUTH_INVALID,
                message="MongoDB refuse ce compte ou ce mot de passe.",
                detail=detail,
                secrets=secrets,
            )
        if code == UNAUTHORIZED:
            return diagnose(DiagnosticCode.PERMISSION_DENIED, detail=detail, secrets=secrets)
        if code == TIME_LIMIT_EXCEEDED:
            return diagnose(DiagnosticCode.TIMEOUT, detail=detail, secrets=secrets)
        if isinstance(error, OperationFailure):
            return diagnose(DiagnosticCode.PROVIDER_ERROR, detail=detail, secrets=secrets)
        if "SSL" in said or "TLS" in said:
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Le serveur n'accepte pas de connexion chiffrée (TLS) : LEKA l'exige.",
                detail=detail,
                secrets=secrets,
            )
        if isinstance(error, ConfigurationError):
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Cette adresse ne mène à aucun serveur MongoDB.",
                detail=detail,
                secrets=secrets,
            )
        if isinstance(error, PyMongoError | OSError):
            return diagnose(DiagnosticCode.NETWORK_UNREACHABLE, detail=detail, secrets=secrets)
        return diagnose(DiagnosticCode.UNKNOWN, detail=detail, secrets=secrets)


async def _databases(client: AsyncMongoClient[dict[str, Any]]) -> list[str]:
    """The databases the account holds a privilege on — MongoDB's own list,
    without listDatabases on the whole server."""
    answer = await client.admin.command(
        {"listDatabases": 1, "nameOnly": True, "authorizedDatabases": True}
    )
    names = {str(d["name"]) for d in answer.get("databases") or []}
    return sorted(names - SYSTEM_DATABASES)


def _hosts(config: MongoDBConfig) -> str:
    return config.address.split("://", 1)[1]


def _int(value: object) -> int:
    """A count or a size as MongoDB returns it; 0 when it does not say."""
    return int(value) if isinstance(value, int | float) else 0


def _columns(validator: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A $jsonSchema validator's fields, as columns: a collection declares
    nothing else about its documents."""
    schema = validator.get("$jsonSchema") or {}
    required = set(schema.get("required") or [])
    columns = []
    for name, spec in (schema.get("properties") or {}).items():
        kind = spec.get("bsonType") or spec.get("type") or ""
        columns.append(
            {
                "name": name,
                "type": "|".join(kind) if isinstance(kind, list) else str(kind),
                "nullable": name not in required,
                "default": None,
                "comment": spec.get("description"),
            }
        )
    return columns


def _constraints(
    indexes: Sequence[Mapping[str, Any]], validator: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """_id is the key; a unique index is a unique constraint; a validator
    that is more than a $jsonSchema is a check, as written."""
    found: list[dict[str, Any]] = [
        {
            "name": "_id_",
            "type": "primary_key",
            "columns": ["_id"],
            "definition": "PRIMARY KEY (_id)",
        }
    ]
    for index in indexes:
        if index.get("unique") and index.get("name") != "_id_":
            fields = list((index.get("key") or {}).keys())
            found.append(
                {
                    "name": index["name"],
                    "type": "unique",
                    "columns": fields,
                    "definition": f"UNIQUE ({', '.join(fields)})",
                }
            )
    rest = {k: v for k, v in validator.items() if k != "$jsonSchema"}
    if rest:
        found.append(
            {
                "name": "validator",
                "type": "check",
                "columns": [],
                "definition": json_util.dumps(rest),
            }
        )
    return found


DIRECTIONS = {1: "ASC", -1: "DESC"}


def _index(index: Mapping[str, Any]) -> dict[str, Any]:
    key = index.get("key") or {}
    parts = ", ".join(f"{field} {DIRECTIONS.get(order, order)}" for field, order in key.items())
    unique = bool(index.get("unique")) or index.get("name") == "_id_"
    extra = []
    if index.get("sparse"):
        extra.append("SPARSE")
    if "expireAfterSeconds" in index:
        extra.append(f"TTL {index['expireAfterSeconds']}s")
    if "partialFilterExpression" in index:
        extra.append(f"WHERE {json_util.dumps(index['partialFilterExpression'])}")
    return {
        "name": index.get("name"),
        "definition": " ".join(
            [f"{'UNIQUE ' if unique else ''}INDEX {index.get('name')} ({parts})", *extra]
        ),
        "unique": unique,
        "primary": index.get("name") == "_id_",
    }


def _read_by(database: str, view_on: object, pipeline: list[Any]) -> list[str]:
    """What a view reads: the collection it is on, and the ones its
    pipeline looks up or unions with."""
    found = [str(view_on)] if view_on else []
    for stage in pipeline:
        if not isinstance(stage, dict):
            continue
        for operator in ("$lookup", "$graphLookup"):
            source = (stage.get(operator) or {}).get("from")
            if isinstance(source, str):
                found.append(source)
        union = stage.get("$unionWith")
        if isinstance(union, str):
            found.append(union)
        elif isinstance(union, dict) and isinstance(union.get("coll"), str):
            found.append(union["coll"])
    return [f"{database}.{name}" for name in dict.fromkeys(found)]


def _record(
    capability: Capability,
    payload: dict[str, Any],
    external_id: str,
    container: str,
    fetched: datetime,
) -> RawRecord:
    return RawRecord(
        kind=capability,
        external_id=external_id,
        container=container,
        payload=payload,
        updated_at=None,
        fetched_at=fetched,
    )
