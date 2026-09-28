"""The SQL Server connector — a database's schemas, and their tables and
views, as its catalogue describes them (LEKA-349).

LEKA reads the catalogue — sys.schemas, sys.objects, sys.columns, the keys,
checks and indexes, what a view reads — never the rows. SQL Server shows
in its catalogue only what the account holds a permission on, and one
permission shows the structure and not the data: VIEW DEFINITION, on the
schemas to describe or on the database. With it, the tables, the views
and their definitions, the columns, keys, checks, indexes and row counts
are visible, and a SELECT is refused (tests/test_sqlserver_connector.py
runs with exactly that). Only the schemas the account holds VIEW
DEFINITION on are read — HAS_PERMS_BY_NAME, as PostgreSQL's
has_schema_privilege — and a table a foreign key points to in another
schema is named only if it is visible too.

A source is one database, as PostgreSQL's: a login is the server's, but a
user — and so its permissions — is each database's.

Safe by construction, as the other database connectors:

- the host must be a **public address** — resolved when connecting, every
  address public, and the connection made to the address checked
  (leka/connectors/network.py);
- **TLS** is required, by FreeTDS's own configuration (freetds.conf, beside
  this file): pymssql does not pass its `encryption` argument on, and with
  it alone the session went in the clear after the login — checked against
  SQL Server 2022, whose sys.dm_exec_connections said encrypt_option FALSE.
  A server that does not offer TLS is refused before the login is sent.
  The certificate is not verified, as the others';
- SQL Server has no read-only session: every session is one
  **transaction, rolled back** when it closes, so nothing written in it
  would stay — the account's permissions being the first boundary. Each
  query is bounded (15 s), each lock wait too, and in a deadlock LEKA's
  session is the one to give way.

pymssql is synchronous: a session runs on a thread of its own, and the
event loop waits for it. FreeTDS keeps some settings for the whole process
— the timeouts, the configuration file, the last error's number: so the
timeouts are always the same, and a failure to connect is read from its
messages, not its number, which may be an earlier failure's.

SQL Server 2016 and later, tested on 2022; Azure SQL Database and Managed
Instance are SQL Server, not yet tried. A SQL login: Microsoft Entra ID
sign-in is not supported.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymssql
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pymssql._mssql import MSSQLException

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
    too_many_tables,
)
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

C = Capability
NAME_MAX = 128  # sysname: a database's, a schema's, a login's
FREETDS_CONF = Path(__file__).with_name("freetds.conf")
PAGE_BYTES = 8192
# What an account may hold in the database and still only read the
# structure. The last two every user holds, through public.
STRUCTURE_ONLY = frozenset(
    {
        "CONNECT",
        "VIEW DEFINITION",
        "VIEW SECURITY DEFINITION",
        "VIEW PERFORMANCE DEFINITION",
        "VIEW ANY COLUMN ENCRYPTION KEY DEFINITION",
        "VIEW ANY COLUMN MASTER KEY DEFINITION",
    }
)

# ── the catalogue queries — reads, and only of sys and INFORMATION_SCHEMA ────
# `{in}` is a list of %s, one per schema: the values are the driver's to
# quote — N'…' — never formatted in. A comment is an extended property
# named MS_Description, as SQL Server's own tools write it.

WHO = """
SELECT SUSER_SNAME() AS login, DB_NAME() AS [database],
       CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128)) AS version,
       CAST(SERVERPROPERTY('Edition') AS nvarchar(128)) AS edition
"""

PERMISSIONS = "SELECT permission_name AS permission FROM fn_my_permissions(NULL, 'DATABASE')"

# The schemas the account may describe; the role-named ones (db_owner…)
# and SQL Server's own left out.
SCHEMAS = """
SELECT s.name AS name, USER_NAME(s.principal_id) AS owner,
       CAST(p.value AS nvarchar(4000)) AS comment,
       HAS_PERMS_BY_NAME(QUOTENAME(s.name), 'SCHEMA', 'SELECT') AS can_select
FROM sys.schemas s
LEFT JOIN sys.extended_properties p
  ON p.class = 3 AND p.major_id = s.schema_id AND p.minor_id = 0 AND p.name = 'MS_Description'
WHERE s.schema_id NOT BETWEEN 16384 AND 16399
  AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
  AND HAS_PERMS_BY_NAME(QUOTENAME(s.name), 'SCHEMA', 'VIEW DEFINITION') = 1
ORDER BY s.name
"""

TABLES = """
SELECT s.name AS [schema], o.name AS name, o.type AS type, t.temporal_type AS temporal,
       t.is_external AS [external], USER_NAME(COALESCE(o.principal_id, s.principal_id)) AS owner,
       CAST(p.value AS nvarchar(4000)) AS comment, m.definition AS definition,
       (SELECT SUM(r.rows) FROM sys.partitions r
        WHERE r.object_id = o.object_id AND r.index_id IN (0, 1)) AS estimated_rows,
       (SELECT SUM(a.total_pages) FROM sys.partitions r
        JOIN sys.allocation_units a ON a.container_id = r.partition_id
        WHERE r.object_id = o.object_id) AS pages
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
LEFT JOIN sys.tables t ON t.object_id = o.object_id
LEFT JOIN sys.sql_modules m ON m.object_id = o.object_id
LEFT JOIN sys.extended_properties p
  ON p.class = 1 AND p.major_id = o.object_id AND p.minor_id = 0 AND p.name = 'MS_Description'
WHERE s.name IN ({in}) AND o.type IN ('U', 'V') AND o.is_ms_shipped = 0
ORDER BY s.name, o.name
OFFSET 0 ROWS FETCH NEXT %s ROWS ONLY
"""

COLUMNS = """
SELECT s.name AS [schema], o.name AS [table], c.name AS name,
       TYPE_NAME(c.user_type_id) AS type, TYPE_NAME(c.system_type_id) AS base_type,
       c.max_length AS length, c.precision AS [precision], c.scale AS scale,
       c.is_nullable AS nullable, d.definition AS [default], k.definition AS computed,
       CAST(i.seed_value AS nvarchar(40)) AS seed,
       CAST(i.increment_value AS nvarchar(40)) AS increment,
       c.generated_always_type AS generated, CAST(p.value AS nvarchar(4000)) AS comment
FROM sys.columns c
JOIN sys.objects o ON o.object_id = c.object_id
JOIN sys.schemas s ON s.schema_id = o.schema_id
LEFT JOIN sys.default_constraints d ON d.object_id = c.default_object_id
LEFT JOIN sys.computed_columns k ON k.object_id = c.object_id AND k.column_id = c.column_id
LEFT JOIN sys.identity_columns i ON i.object_id = c.object_id AND i.column_id = c.column_id
LEFT JOIN sys.extended_properties p
  ON p.class = 1 AND p.major_id = c.object_id AND p.minor_id = c.column_id
 AND p.name = 'MS_Description'
WHERE s.name IN ({in}) AND o.type IN ('U', 'V') AND o.is_ms_shipped = 0
ORDER BY s.name, o.name, c.column_id
"""

KEYS = """
SELECT s.name AS [schema], o.name AS [table], k.name AS name, k.type AS type,
       COL_NAME(ic.object_id, ic.column_id) AS [column]
FROM sys.key_constraints k
JOIN sys.objects o ON o.object_id = k.parent_object_id
JOIN sys.schemas s ON s.schema_id = o.schema_id
JOIN sys.index_columns ic
  ON ic.object_id = k.parent_object_id AND ic.index_id = k.unique_index_id AND ic.key_ordinal > 0
WHERE s.name IN ({in})
ORDER BY s.name, o.name, k.name, ic.key_ordinal
"""

# The table a foreign key points to must be visible too: one in a schema
# the account may not see is not named, and the key not read.
FOREIGN_KEYS = """
SELECT s.name AS [schema], o.name AS [table], f.name AS name,
       COL_NAME(fc.parent_object_id, fc.parent_column_id) AS [column],
       rs.name AS ref_schema, ro.name AS ref_table,
       COL_NAME(fc.referenced_object_id, fc.referenced_column_id) AS ref_column,
       f.delete_referential_action_desc AS on_delete
FROM sys.foreign_keys f
JOIN sys.objects o ON o.object_id = f.parent_object_id
JOIN sys.schemas s ON s.schema_id = o.schema_id
JOIN sys.objects ro ON ro.object_id = f.referenced_object_id
JOIN sys.schemas rs ON rs.schema_id = ro.schema_id
JOIN sys.foreign_key_columns fc ON fc.constraint_object_id = f.object_id
WHERE s.name IN ({in})
ORDER BY s.name, o.name, f.name, fc.constraint_column_id
"""

CHECKS = """
SELECT s.name AS [schema], o.name AS [table], k.name AS name, k.definition AS definition,
       COL_NAME(k.parent_object_id, k.parent_column_id) AS [column]
FROM sys.check_constraints k
JOIN sys.objects o ON o.object_id = k.parent_object_id
JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE s.name IN ({in})
ORDER BY s.name, o.name, k.name
"""

INDEXES = """
SELECT s.name AS [schema], o.name AS [table], i.name AS name, i.type_desc AS type,
       i.is_unique AS [unique], i.is_primary_key AS [primary], i.filter_definition AS filter,
       COL_NAME(ic.object_id, ic.column_id) AS [column], ic.is_descending_key AS descending,
       ic.is_included_column AS included
FROM sys.indexes i
JOIN sys.objects o ON o.object_id = i.object_id
JOIN sys.schemas s ON s.schema_id = o.schema_id
LEFT JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
WHERE s.name IN ({in}) AND o.type IN ('U', 'V') AND o.is_ms_shipped = 0
  AND i.type > 0 AND i.is_hypothetical = 0
ORDER BY s.name, o.name, i.name, ic.is_included_column, ic.key_ordinal, ic.index_column_id
"""

VIEW_SOURCES = """
SELECT VIEW_SCHEMA AS [schema], VIEW_NAME AS name, TABLE_SCHEMA AS ref_schema,
       TABLE_NAME AS ref_table
FROM INFORMATION_SCHEMA.VIEW_TABLE_USAGE
WHERE VIEW_SCHEMA IN ({in})
ORDER BY VIEW_SCHEMA, VIEW_NAME, TABLE_SCHEMA, TABLE_NAME
"""

QUERIES = (
    WHO,
    PERMISSIONS,
    SCHEMAS,
    TABLES,
    COLUMNS,
    KEYS,
    FOREIGN_KEYS,
    CHECKS,
    INDEXES,
    VIEW_SOURCES,
)
# Every session, after the transaction pymssql opens: a lock waited for no
# longer than a query, and LEKA's session the deadlock's victim.
SESSION = f"SET LOCK_TIMEOUT {STATEMENT_TIMEOUT_MS}; SET DEADLOCK_PRIORITY LOW"
TEMPORAL_KINDS = {1: "history_table", 2: "system_versioned_table"}
GENERATED = {1: "GENERATED ALWAYS AS ROW START", 2: "GENERATED ALWAYS AS ROW END"}
KEY_KINDS = {"PK": ("primary_key", "PRIMARY KEY"), "UQ": ("unique", "UNIQUE")}
# A length in characters, a length in bytes, a precision and scale, a
# fractional second's digits: how SQL Server writes each type.
CHARACTERS = frozenset({"nchar", "nvarchar"})
LENGTHS = frozenset({"char", "varchar", "binary", "varbinary"})
PRECISE = frozenset({"decimal", "numeric"})
FRACTIONS = frozenset({"datetime2", "datetimeoffset", "time"})

# SQL Server's error numbers, once connected; FreeTDS's, in the messages.
PERMISSION_NUMBERS = (229, 230, 262, 297, 300)
LOCK_TIMEOUT = 1222
# pymssql raises two families: DB-API's, and its inner layer's own, which a
# dead connection's rollback raises and DB-API's do not include.
DRIVER_ERRORS = (pymssql.Error, MSSQLException)
DBLIB = re.compile(r"DB-Lib error message (\d+)")
UNREACHABLE, CONNECTION_FAILED, SERVER_MESSAGE, TIMED_OUT = "20009", "20002", "20018", "20003"


class SQLServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(
        min_length=1,
        max_length=253,
        pattern=HOST,
        description="The server's name or address — public, reachable from LEKA's server.",
    )
    port: int = Field(default=1433, ge=1, le=65535, description="The server's port.")
    database: str = Field(
        min_length=1, max_length=NAME_MAX, description="The database to describe."
    )
    schemas: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="The schemas to describe. Empty: every one the account may see.",
    )

    @field_validator("host")
    @classmethod
    def _not_obviously_private(cls, value: str) -> str:
        return public_host(value)

    @field_validator("database")
    @classmethod
    def _database(cls, value: str) -> str:
        name = value.strip()
        if not name or "\x00" in name:
            msg = f"{value!r} is not a database name"
            raise ValueError(msg)
        return name

    @field_validator("schemas")
    @classmethod
    def _names(cls, value: list[str] | None) -> list[str] | None:
        return schema_names(value, NAME_MAX)


class SQLServerCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field — the login's
    # name, which says nothing of the password.
    username: str = Field(min_length=1, max_length=NAME_MAX, description="The SQL login.")
    password: SecretStr = Field(
        min_length=1,
        max_length=1024,
        description="Its password.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


class Session:
    """A connection, and the one thread it is used on: pymssql's calls
    block, and FreeTDS's connection is not to be passed between threads."""

    def __init__(self, connection: Any, thread: ThreadPoolExecutor) -> None:
        self.connection = connection
        self._thread = thread

    async def run[T](self, call: Callable[..., T], *args: object) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._thread, call, *args)

    async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
        return await self.run(_fetch, self.connection, query, args)


@register_connector
class SQLServerConnector(Connector[SQLServerConfig, SQLServerCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.SQLSERVER,
        display_name="SQL Server",
        category=ConnectorCategory.DATA,
        auth_type="token",
        config_schema=SQLServerConfig,
        credentials_schema=SQLServerCredentials,
        capabilities=frozenset({C.SCHEMAS, C.TABLES}),
        # The catalogue has no "changed since": both come whole each pass.
        listed_whole=frozenset({C.SCHEMAS, C.TABLES}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._session() as db:
            [who] = await db.fetch(WHO)
            permissions = {str(row["permission"]) for row in await db.fetch(PERMISSIONS)}
            schemas = await db.fetch(SCHEMAS)
            names = [str(row["name"]) for row in schemas]
            self._require_scope(names)
            in_scope = self._in_scope(names)
            if in_scope:
                await db.fetch(_in(TABLES, in_scope), *in_scope, 1)
        readable = [str(row["name"]) for row in schemas if row["can_select"]]
        warnings: list[str] = []
        if "SELECT" in permissions or set(readable) & set(in_scope):
            warnings.append(
                "Ce compte peut lire les lignes (SELECT). LEKA n'en a pas besoin : VIEW "
                "DEFINITION sur les schémas à décrire suffit."
            )
        beyond = sorted(permissions - STRUCTURE_ONLY - {"SELECT"})
        if beyond:
            named = ", ".join(beyond[:6]) + ("…" if len(beyond) > 6 else "")
            warnings.append(
                f"Ce compte peut plus que lire ({named}). LEKA ne lit que le catalogue : "
                "VIEW DEFINITION sur les schémas à décrire suffit."
            )
        if not names:
            warnings.append(
                "Aucun schéma n'est visible : donnez à ce compte VIEW DEFINITION sur les "
                "schémas à décrire."
            )
        return ConnectionTestResult(
            account=f"{who['login']}@{self.config.host}",
            metadata={
                "version": str(who["version"]),
                "edition": str(who["edition"]),
                "database": str(who["database"]),
                "schemas_visible": len(names),
            },
            capabilities=[C.SCHEMAS, C.TABLES],
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._session() as db:
            await db.fetch("SELECT 1 AS ok")
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        async with self._session() as db:
            rows = await db.fetch(SCHEMAS)
        options = [
            ScopeOption(key=str(row["name"]), name=str(row["name"]))
            for row in rows[:MAX_SCOPE_OPTIONS]
        ]
        return ScopeListing(options=options, truncated=len(rows) > MAX_SCOPE_OPTIONS)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"SQL Server does not read {capability}"
            raise ValueError(msg)
        fetched = datetime.now(UTC)
        async with self._session() as db:
            rows = await db.fetch(SCHEMAS)
            wanted = self._in_scope([str(row["name"]) for row in rows])
            if capability is C.SCHEMAS:
                for row in rows:
                    name = str(row["name"])
                    if name in wanted:
                        payload = {
                            "name": name,
                            "owner": row["owner"],
                            "comment": row["comment"],
                            "database": self.config.database,
                        }
                        # Its own container, as a repository is: the scope
                        # rules keep or leave a schema and its tables alike.
                        yield _record(C.SCHEMAS, payload, name, name, fetched)
                return
            for table in await self._tables(db, wanted):
                external_id = f"{table['schema']}.{table['name']}"
                yield _record(C.TABLES, table, external_id, str(table["schema"]), fetched)

    # ── inside ───────────────────────────────────────────────────────────────

    def _connect(self, address: str) -> Any:
        """A connection to the address checked, encrypted by FreeTDS's
        configuration, in a transaction pymssql opens. Runs on the
        session's thread."""
        os.environ["FREETDSCONF"] = str(FREETDS_CONF)
        return pymssql.connect(
            server=address,
            port=str(self.config.port),
            user=self.credentials.username,
            password=self.credentials.password.get_secret_value(),
            database=self.config.database,
            login_timeout=int(CONNECT_TIMEOUT),
            timeout=STATEMENT_TIMEOUT_MS // 1000,
            appname="LEKA",
            read_only=True,  # ApplicationIntent=ReadOnly: a readable replica where there is one
            autocommit=False,
            tds_version="7.4",
        )

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[Session]:
        """An encrypted session for one call, rolled back and closed after
        it; every failure a diagnostic."""
        thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="leka-sqlserver")
        try:
            try:
                address = await network.public_address(self.config.host, self.config.port)
                connection = await asyncio.get_running_loop().run_in_executor(
                    thread, self._connect, address
                )
            except Exception as error:
                raise self._diagnose(error) from error
            session = Session(connection, thread)
            try:
                try:
                    await session.fetch(SESSION)
                    yield session
                except ConnectorError:
                    raise
                except (*DRIVER_ERRORS, OSError) as error:
                    raise self._diagnose(error) from error
            finally:
                await session.run(_close, connection)
        finally:
            thread.shutdown(wait=False)

    async def _tables(self, db: Session, schemas: list[str]) -> list[dict[str, Any]]:
        """Every table and view of these schemas, with what the catalogue
        says of each — asked for all of them at once, not one by one."""
        if not schemas:
            return []
        rows = await db.fetch(_in(TABLES, schemas), *schemas, MAX_TABLES + 1)
        if len(rows) > MAX_TABLES:
            raise too_many_tables()
        tables: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            is_view = str(row["type"]).strip() == "V"
            pages = _int(row["pages"])
            tables[(str(row["schema"]), str(row["name"]))] = {
                "schema": row["schema"],
                "name": row["name"],
                "kind": "view" if is_view else _table_kind(row),
                "owner": row["owner"],
                "comment": row["comment"],
                "estimated_rows": rounded(_int(row["estimated_rows"])),
                # A view has pages only when it has an index.
                "size_bytes": rounded(pages * PAGE_BYTES) if pages is not None else None,
                "definition": row["definition"] if is_view else None,
                "columns": [],
                "constraints": [],
                "indexes": [],
                "reads_from": [],
            }

        def table_of(row: dict[str, Any]) -> dict[str, Any] | None:
            return tables.get((str(row["schema"]), str(row["table"])))

        for row in await db.fetch(_in(COLUMNS, schemas), *schemas):
            if (table := table_of(row)) is not None:
                table["columns"].append(
                    {
                        "name": row["name"],
                        "type": _type(row),
                        "nullable": bool(row["nullable"]),
                        "default": _default(row),
                        "comment": row["comment"],
                    }
                )
        for constraint in _grouped(await db.fetch(_in(KEYS, schemas), *schemas)):
            if (table := table_of(constraint[0])) is not None:
                table["constraints"].append(_key(constraint))
        for constraint in _grouped(await db.fetch(_in(FOREIGN_KEYS, schemas), *schemas)):
            if (table := table_of(constraint[0])) is not None:
                table["constraints"].append(_foreign_key(constraint))
        for row in await db.fetch(_in(CHECKS, schemas), *schemas):
            if (table := table_of(row)) is not None:
                table["constraints"].append(
                    {
                        "name": row["name"],
                        "type": "check",
                        "columns": [row["column"]] if row["column"] else [],
                        "definition": f"CHECK {row['definition']}",
                    }
                )
        for index in _grouped(await db.fetch(_in(INDEXES, schemas), *schemas)):
            if (table := table_of(index[0])) is not None:
                table["indexes"].append(_index(index))
        for row in await db.fetch(_in(VIEW_SOURCES, schemas), *schemas):
            view = tables.get((str(row["schema"]), str(row["name"])))
            if view is not None:
                view["reads_from"].append(f"{row['ref_schema']}.{row['ref_table']}")
        return list(tables.values())

    def _in_scope(self, visible: list[str]) -> list[str]:
        if not self.config.schemas:
            return visible
        chosen = set(self.config.schemas)
        return [schema for schema in visible if schema in chosen]

    def _require_scope(self, visible: list[str]) -> None:
        seen = set(visible)
        missing = [schema for schema in self.config.schemas or [] if schema not in seen]
        if missing:
            named = ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
            raise diagnose(
                DiagnosticCode.NOT_FOUND,
                message=f"Ce compte ne voit pas ces schémas (pas de VIEW DEFINITION) : {named}.",
            )

    def _diagnose(self, error: BaseException) -> ConnectorError:
        """What went wrong, in the admin's words, the password never in it.

        Connecting, FreeTDS says what failed in its messages — 20009 no
        server there, 20003 too slow, 20002 the connection refused, after
        a message from the server (20018) when it refused the login; the
        error's number may be an earlier failure's. Once connected, the
        number is the server's own."""
        secrets = [self.credentials.password.get_secret_value()]
        detail = f"{type(error).__name__}: {_text(error)}"
        codes = set(DBLIB.findall(_text(error)))
        number = error.args[0] if isinstance(error, DRIVER_ERRORS) and error.args else None
        if isinstance(error, network.PrivateAddressError):
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Cet hôte ne mène pas à une adresse publique.",
                detail=detail,
                secrets=secrets,
            )
        if TIMED_OUT in codes or number == LOCK_TIMEOUT or isinstance(error, TimeoutError):
            return diagnose(DiagnosticCode.TIMEOUT, detail=detail, secrets=secrets)
        if UNREACHABLE in codes:
            return diagnose(DiagnosticCode.NETWORK_UNREACHABLE, detail=detail, secrets=secrets)
        if CONNECTION_FAILED in codes and SERVER_MESSAGE in codes:
            return diagnose(
                DiagnosticCode.AUTH_INVALID,
                message="SQL Server refuse cette connexion : le compte, son mot de passe, ou la "
                "base — qui doit exister et avoir un utilisateur pour ce compte.",
                detail=detail,
                secrets=secrets,
            )
        if CONNECTION_FAILED in codes:
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Le serveur n'accepte pas de connexion chiffrée (TLS), que LEKA exige — "
                "ou ce n'est pas un SQL Server.",
                detail=detail,
                secrets=secrets,
            )
        if number in PERMISSION_NUMBERS:
            return diagnose(DiagnosticCode.PERMISSION_DENIED, detail=detail, secrets=secrets)
        if isinstance(error, DRIVER_ERRORS):
            return diagnose(DiagnosticCode.PROVIDER_ERROR, detail=detail, secrets=secrets)
        if isinstance(error, OSError):
            return diagnose(DiagnosticCode.NETWORK_UNREACHABLE, detail=detail, secrets=secrets)
        return diagnose(DiagnosticCode.UNKNOWN, detail=detail, secrets=secrets)


def _fetch(connection: Any, query: str, args: tuple[object, ...]) -> list[dict[str, Any]]:
    cursor = connection.cursor(as_dict=True)
    try:
        cursor.execute(query, args or None)
        rows: list[dict[str, Any]] = cursor.fetchall() if cursor.description else []
        return rows
    finally:
        cursor.close()


def _close(connection: Any) -> None:
    """Whatever the session did, undone; then closed. A connection a
    timeout left dead has nothing to undo, and closes all the same."""
    for step in (connection.rollback, connection.close):
        with suppress(*DRIVER_ERRORS):
            step()


def _in(query: str, schemas: Sequence[str]) -> str:
    """The query with one placeholder per schema — the values quoted by the
    driver, never formatted in."""
    return query.replace("{in}", ", ".join(["%s"] * len(schemas)))


def _text(error: BaseException) -> str:
    """An error's words: pymssql's come as bytes, after a number."""
    return " ".join(
        part.decode(errors="replace") if isinstance(part, bytes) else str(part)
        for part in error.args
    )


def _int(value: object) -> int | None:
    """A count or a size, as the driver hands it: an int, or a Decimal."""
    return int(value) if isinstance(value, int | float | Decimal) else None


def _table_kind(row: dict[str, Any]) -> str:
    if row["external"]:
        return "external_table"
    return TEMPORAL_KINDS.get(_int(row["temporal"]) or 0, "table")


def _type(row: dict[str, Any]) -> str:
    """A column's type as SQL Server writes it: nvarchar(200), varchar(max),
    decimal(12,2), datetime2(3). An alias type is its own name."""
    name, base = str(row["type"]), str(row["base_type"])
    length = int(row["length"])
    if name != base:
        return name
    if name in CHARACTERS:
        return f"{name}(max)" if length == -1 else f"{name}({length // 2})"
    if name in LENGTHS:
        return f"{name}(max)" if length == -1 else f"{name}({length})"
    if name in PRECISE:
        return f"{name}({row['precision']},{row['scale']})"
    if name in FRACTIONS:
        return f"{name}({row['scale']})"
    return name


def _default(row: dict[str, Any]) -> str | None:
    """What fills a column when nothing is written to it: its default, its
    expression when computed, its identity, or the period it marks."""
    if row["computed"]:
        return f"AS {_unwrapped(str(row['computed']))}"
    if row["seed"] is not None:
        return f"IDENTITY({row['seed']},{row['increment']})"
    if (generated := GENERATED.get(_int(row["generated"]) or 0)) is not None:
        return generated
    return _unwrapped(str(row["default"])) if row["default"] is not None else None


def _unwrapped(expression: str) -> str:
    """((0)) → 0, ('free') → 'free': SQL Server keeps an expression in
    parentheses it adds itself. (1)+(2) keeps its own."""
    while expression.startswith("(") and expression.endswith(")") and _closes_last(expression):
        expression = expression[1:-1]
    return expression


def _closes_last(expression: str) -> bool:
    """Whether the first parenthesis closes at the last character — a
    parenthesis inside a literal counted as any other: SQL Server's own
    wrapping never has one."""
    depth = 0
    for position, character in enumerate(expression):
        depth += {"(": 1, ")": -1}.get(character, 0)
        if depth == 0:
            return position == len(expression) - 1
    return False


def _grouped(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Rows of one constraint or index together, as the queries order them."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["schema"]), str(row["table"]), str(row["name"]))
        groups.setdefault(key, []).append(row)
    return list(groups.values())


def _key(rows: list[dict[str, Any]]) -> dict[str, Any]:
    kind, written = KEY_KINDS[str(rows[0]["type"]).strip()]
    columns = [str(row["column"]) for row in rows]
    return {
        "name": rows[0]["name"],
        "type": kind,
        "columns": columns,
        "definition": f"{written} ({', '.join(columns)})",
    }


def _foreign_key(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    columns = [str(row["column"]) for row in rows]
    referenced = [str(row["ref_column"]) for row in rows]
    target = f"{first['ref_schema']}.{first['ref_table']}"
    on_delete = str(first["on_delete"]).replace("_", " ")
    return {
        "name": first["name"],
        "type": "foreign_key",
        "columns": columns,
        "references": {
            "schema": first["ref_schema"],
            "table": first["ref_table"],
            "columns": referenced,
        },
        "definition": f"FOREIGN KEY ({', '.join(columns)}) REFERENCES {target}"
        f"({', '.join(referenced)})"
        + ("" if on_delete == "NO ACTION" else f" ON DELETE {on_delete}"),
    }


def _index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """An index as SQL Server would create it: its key columns in order,
    the included ones, its filter."""
    first = rows[0]
    keys = [
        str(row["column"]) + (" DESC" if row["descending"] else "")
        for row in rows
        if row["column"] is not None and not row["included"]
    ]
    included = [str(row["column"]) for row in rows if row["column"] is not None and row["included"]]
    unique = "UNIQUE " if first["unique"] else ""
    definition = (
        f"CREATE {unique}{first['type']} INDEX {first['name']} ON "
        f"{first['schema']}.{first['table']} ({', '.join(keys)})"
    )
    if included:
        definition += f" INCLUDE ({', '.join(included)})"
    if first["filter"]:
        definition += f" WHERE {first['filter']}"
    return {
        "name": first["name"],
        "definition": definition,
        "unique": bool(first["unique"]),
        "primary": bool(first["primary"]),
    }


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
