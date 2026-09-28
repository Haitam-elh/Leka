"""The PostgreSQL connector — a database's schemas, tables and views, as its
catalogue describes them (LEKA-349).

LEKA reads the **catalogue**, never the rows: pg_namespace, pg_class,
pg_attribute, pg_constraint, pg_index, the dependencies of views. The role
LEKA connects as needs CONNECT on the database and USAGE on the schemas to
describe — no SELECT on any table. Only the schemas it has USAGE on are
seen: that is the boundary.

Safe by construction:

- the host must be a **public address** — resolved when connecting, every
  address public, and the connection made to the address checked
  (leka/connectors/network.py), so a name cannot lead LEKA's server into
  its own network;
- **TLS** is required: a server that does not offer it is refused. The
  server's certificate is not verified — libpq's sslmode=require;
- every session is **read-only** (default_transaction_read_only) with a
  statement timeout, whatever the role could do.

test_connection: who am I, on which server, may I do more than read (a
warning: LEKA only reads), which schemas can I describe, are the ones in
scope among them, and can I list their tables.

check_health: a connection and SELECT 1.

list_scope: the schemas the role has USAGE on.

iter_resources: schemas, and tables — tables, partitioned tables, views,
materialized views, foreign tables — with their columns, keys, foreign keys,
indexes, and what a view reads from. The catalogue has no "changed since":
both come whole each pass, and the sync keeps what did not change.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import asyncpg
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

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
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose
from leka.connectors.models import HealthStatus, SourceKind
from leka.connectors.registry import register_connector
from leka.connectors.schemas import RawRecord

C = Capability
CONNECT_TIMEOUT = 10.0  # seconds
STATEMENT_TIMEOUT_MS = 15_000
MAX_SCOPE_OPTIONS = 1000
# A pass, all schemas together. Beyond it, the pass fails and says so: a
# list read whole and cut would mark the rest gone.
MAX_TABLES = 20_000
HOST = r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$|^\[?[0-9A-Fa-f:.]+\]?$"
IDENTIFIER_MAX = 63  # PostgreSQL's NAMEDATALEN - 1

# ── the catalogue queries — reads, and only of the catalogue ────────────────

WHO = """
SELECT current_user AS "user", current_database() AS database,
       current_setting('server_version') AS version,
       r.rolsuper AS superuser, r.rolcreaterole AS create_role, r.rolcreatedb AS create_db
FROM pg_roles r WHERE r.rolname = current_user
"""

SCHEMAS = """
SELECT n.nspname AS name, pg_get_userbyid(n.nspowner) AS owner,
       obj_description(n.oid, 'pg_namespace') AS comment
FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname !~ '^pg_(toast|temp)'
  AND has_schema_privilege(n.oid, 'USAGE')
ORDER BY n.nspname
"""

TABLES = """
SELECT c.oid, n.nspname AS schema, c.relname AS name,
       CASE c.relkind WHEN 'r' THEN 'table' WHEN 'p' THEN 'partitioned_table'
                      WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized_view'
                      WHEN 'f' THEN 'foreign_table' END AS kind,
       pg_get_userbyid(c.relowner) AS owner,
       obj_description(c.oid, 'pg_class') AS comment,
       CASE WHEN c.reltuples >= 0 THEN c.reltuples::bigint END AS estimated_rows,
       CASE WHEN c.relkind IN ('r', 'p', 'm') THEN pg_total_relation_size(c.oid) END AS size_bytes,
       CASE WHEN c.relkind IN ('v', 'm') THEN pg_get_viewdef(c.oid) END AS definition
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND NOT c.relispartition
  AND n.nspname = ANY($1::text[])
ORDER BY n.nspname, c.relname
LIMIT $2
"""

COLUMNS = """
SELECT a.attrelid AS table_oid, a.attname AS name,
       format_type(a.atttypid, a.atttypmod) AS type, NOT a.attnotnull AS nullable,
       pg_get_expr(d.adbin, d.adrelid) AS "default",
       col_description(a.attrelid, a.attnum) AS comment
FROM pg_attribute a
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attrelid = ANY($1::oid[]) AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attrelid, a.attnum
"""

CONSTRAINTS = """
SELECT k.conrelid AS table_oid, k.conname AS name, k.contype::text AS type,
       pg_get_constraintdef(k.oid) AS definition,
       ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY u(num, i)
             JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = u.num
             ORDER BY u.i) AS columns,
       rn.nspname AS ref_schema, rc.relname AS ref_table,
       ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY u(num, i)
             JOIN pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = u.num
             ORDER BY u.i) AS ref_columns
FROM pg_constraint k
LEFT JOIN pg_class rc ON rc.oid = k.confrelid
LEFT JOIN pg_namespace rn ON rn.oid = rc.relnamespace
WHERE k.conrelid = ANY($1::oid[]) AND k.contype IN ('p', 'u', 'f', 'c')
ORDER BY k.conrelid, k.conname
"""

INDEXES = """
SELECT i.indrelid AS table_oid, ic.relname AS name, pg_get_indexdef(i.indexrelid) AS definition,
       i.indisunique AS "unique", i.indisprimary AS "primary"
FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid
WHERE i.indrelid = ANY($1::oid[])
ORDER BY i.indrelid, ic.relname
"""

VIEW_SOURCES = """
SELECT DISTINCT r.ev_class AS table_oid, rn.nspname AS schema, rc.relname AS name
FROM pg_rewrite r
JOIN pg_depend d ON d.objid = r.oid AND d.classid = 'pg_rewrite'::regclass
                AND d.refclassid = 'pg_class'::regclass
JOIN pg_class rc ON rc.oid = d.refobjid
JOIN pg_namespace rn ON rn.oid = rc.relnamespace
WHERE r.ev_class = ANY($1::oid[]) AND rc.oid <> r.ev_class
ORDER BY 1, 2, 3
"""

QUERIES = (WHO, SCHEMAS, TABLES, COLUMNS, CONSTRAINTS, INDEXES, VIEW_SOURCES)
CONSTRAINT_KINDS = {"p": "primary_key", "u": "unique", "f": "foreign_key", "c": "check"}


class PostgreSQLConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(
        min_length=1,
        max_length=253,
        pattern=HOST,
        description="The server's name or address — public, reachable from LEKA's server.",
    )
    port: int = Field(default=5432, ge=1, le=65535, description="The server's port.")
    database: str = Field(
        min_length=1, max_length=IDENTIFIER_MAX, description="The database to describe."
    )
    schemas: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="The schemas to describe. Empty: every schema the role may use.",
    )

    @field_validator("host")
    @classmethod
    def _not_obviously_private(cls, value: str) -> str:
        host = value.strip().lower()
        if network.obviously_private(host):
            msg = f"{value!r} is not a public address"
            raise ValueError(msg)
        return host

    @field_validator("schemas")
    @classmethod
    def _names(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        names = [schema.strip() for schema in value]
        for name in names:
            if not name or len(name) > IDENTIFIER_MAX or "\x00" in name:
                msg = f"{name!r} is not a schema name"
                raise ValueError(msg)
        return list(dict.fromkeys(names))


class PostgreSQLCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field — the role's
    # name, which says nothing of the password.
    username: str = Field(min_length=1, max_length=IDENTIFIER_MAX, description="The role.")
    password: SecretStr = Field(
        min_length=1,
        max_length=1024,
        description="Its password.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


# Every session: named, read-only whatever the role may do, and bounded.
SESSION = {
    "application_name": "LEKA",
    "default_transaction_read_only": "on",
    "statement_timeout": str(STATEMENT_TIMEOUT_MS),
}


@register_connector
class PostgreSQLConnector(Connector[PostgreSQLConfig, PostgreSQLCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.POSTGRESQL,
        display_name="PostgreSQL",
        category=ConnectorCategory.DATA,
        auth_type="token",
        config_schema=PostgreSQLConfig,
        credentials_schema=PostgreSQLCredentials,
        capabilities=frozenset({C.SCHEMAS, C.TABLES}),
        # The catalogue has no "changed since": both come whole each pass.
        listed_whole=frozenset({C.SCHEMAS, C.TABLES}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._session() as db:
            who = await db.fetchrow(WHO)
            schemas = [row["name"] for row in await db.fetch(SCHEMAS)]
            self._require_scope(schemas)
            # The catalogue asks no privilege on a table: if this reads, the
            # sync will.
            await db.fetch(TABLES, self._in_scope(schemas), 1)
        warnings: list[str] = []
        if who and (who["superuser"] or who["create_role"] or who["create_db"]):
            warnings.append(
                "Ce rôle peut plus que lire (superutilisateur, ou création de rôles ou de "
                "bases). LEKA ne fait que lire le catalogue : un rôle avec CONNECT et USAGE "
                "suffit."
            )
        if not schemas:
            warnings.append(
                "Aucun schéma n'est visible : donnez à ce rôle USAGE sur les schémas à décrire."
            )
        return ConnectionTestResult(
            account=f"{who['user']}@{self.config.host}" if who else self.config.host,
            metadata={
                "database": who["database"] if who else self.config.database,
                "version": who["version"] if who else None,
                "schemas_visible": len(schemas),
            },
            capabilities=[C.SCHEMAS, C.TABLES],
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._session() as db:
            await db.fetchval("SELECT 1")
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        async with self._session() as db:
            rows = await db.fetch(SCHEMAS)
        options = [
            ScopeOption(
                key=row["name"],
                name=row["name"],
                description=row["comment"],
            )
            for row in rows[:MAX_SCOPE_OPTIONS]
        ]
        return ScopeListing(options=options, truncated=len(rows) > MAX_SCOPE_OPTIONS)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"PostgreSQL does not read {capability}"
            raise ValueError(msg)
        fetched = datetime.now(UTC)
        async with self._session() as db:
            rows = await db.fetch(SCHEMAS)
            wanted = set(self._in_scope([row["name"] for row in rows]))
            if capability is C.SCHEMAS:
                for row in rows:
                    if row["name"] in wanted:
                        payload = {**dict(row), "database": self.config.database}
                        # Its own container, as a repository is: the scope
                        # rules keep or leave a schema and its tables alike.
                        name = str(row["name"])
                        yield _record(C.SCHEMAS, payload, name, name, fetched)
                return
            for table in await self._tables(db, sorted(wanted)):
                external_id = f"{table['schema']}.{table['name']}"
                yield _record(C.TABLES, table, external_id, str(table["schema"]), fetched)

    # ── inside ───────────────────────────────────────────────────────────────

    async def _open(self) -> asyncpg.Connection:
        """A connection to the address checked — not to the name, which could
        resolve elsewhere a moment later — over TLS, read-only. Replaced in
        the tests, which talk to a local server without TLS."""
        address = await network.public_address(self.config.host, self.config.port)
        context = ssl.create_default_context()
        context.check_hostname = False  # sslmode=require: encrypted, not verified
        context.verify_mode = ssl.CERT_NONE
        connection: asyncpg.Connection = await asyncpg.connect(
            host=address,
            port=self.config.port,
            user=self.credentials.username,
            password=self.credentials.password.get_secret_value(),
            database=self.config.database,
            ssl=context,
            timeout=CONNECT_TIMEOUT,
            # The server's statement_timeout first; this if the network hangs.
            command_timeout=STATEMENT_TIMEOUT_MS / 1000 + CONNECT_TIMEOUT,
            server_settings=SESSION,
        )
        return connection

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[asyncpg.Connection]:
        """A read-only session for one call, closed after it; every failure
        a diagnostic."""
        try:
            db = await self._open()
        except Exception as error:
            raise self._diagnose(error) from error
        try:
            yield db
        except ConnectorError:
            raise
        except (TimeoutError, asyncpg.PostgresError, OSError) as error:
            raise self._diagnose(error) from error
        finally:
            await db.close()

    async def _tables(self, db: asyncpg.Connection, schemas: list[str]) -> list[dict[str, Any]]:
        """Every table and view of these schemas, with what the catalogue
        says of each — asked for all of them at once, not one by one."""
        tables = [dict(row) for row in await db.fetch(TABLES, schemas, MAX_TABLES + 1)]
        if len(tables) > MAX_TABLES:
            most = f"{MAX_TABLES:,}".replace(",", "\u202f")  # 20 000, as French writes it
            raise diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message=f"Plus de {most} tables et vues dans le périmètre : choisissez les "
                "schémas à décrire.",
            )
        oids = [table["oid"] for table in tables]
        by_oid: dict[int, dict[str, Any]] = {}
        for table in tables:
            table.update(columns=[], constraints=[], indexes=[], reads_from=[])
            by_oid[table["oid"]] = table
        for row in await db.fetch(COLUMNS, oids):
            by_oid[row["table_oid"]]["columns"].append(_without(row, "table_oid"))
        for row in await db.fetch(CONSTRAINTS, oids):
            by_oid[row["table_oid"]]["constraints"].append(_constraint(row))
        for row in await db.fetch(INDEXES, oids):
            by_oid[row["table_oid"]]["indexes"].append(_without(row, "table_oid"))
        for row in await db.fetch(VIEW_SOURCES, oids):
            by_oid[row["table_oid"]]["reads_from"].append(f"{row['schema']}.{row['name']}")
        for table in tables:
            del table["oid"]  # the server's, not stable across a dump and restore
            # Estimates that move with every write, kept to two significant
            # figures: a pass that changed no schema changes no checksum.
            table["estimated_rows"] = _rounded(table["estimated_rows"])
            table["size_bytes"] = _rounded(table["size_bytes"])
        return tables

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
                message=f"Ce rôle ne peut pas utiliser ces schémas (USAGE) : {named}.",
            )

    def _diagnose(self, error: BaseException) -> ConnectorError:
        """What went wrong, in the admin's words, the password never in it."""
        secrets = [self.credentials.password.get_secret_value()]
        detail = f"{type(error).__name__}: {error}"
        if isinstance(error, network.PrivateAddressError):
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Cet hôte ne mène pas à une adresse publique.",
                detail=detail,
                secrets=secrets,
            )
        if isinstance(
            error,
            asyncpg.InvalidPasswordError | asyncpg.InvalidAuthorizationSpecificationError,
        ):
            return diagnose(
                DiagnosticCode.AUTH_INVALID,
                message="PostgreSQL refuse ce rôle ou ce mot de passe.",
                detail=detail,
                secrets=secrets,
            )
        if isinstance(error, asyncpg.InvalidCatalogNameError):
            return diagnose(
                DiagnosticCode.NOT_FOUND,
                message="Cette base n'existe pas sur ce serveur.",
                detail=detail,
                secrets=secrets,
            )
        if isinstance(error, asyncpg.InsufficientPrivilegeError):
            return diagnose(DiagnosticCode.PERMISSION_DENIED, detail=detail, secrets=secrets)
        if isinstance(error, asyncpg.QueryCanceledError | TimeoutError):
            return diagnose(DiagnosticCode.TIMEOUT, detail=detail, secrets=secrets)
        if isinstance(error, ssl.SSLError) or "SSL" in str(error):
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Le serveur n'accepte pas de connexion chiffrée (TLS) : LEKA l'exige.",
                detail=detail,
                secrets=secrets,
            )
        if isinstance(error, OSError | ConnectionError):
            return diagnose(DiagnosticCode.NETWORK_UNREACHABLE, detail=detail, secrets=secrets)
        if isinstance(error, asyncpg.PostgresError):
            return diagnose(DiagnosticCode.PROVIDER_ERROR, detail=detail, secrets=secrets)
        return diagnose(DiagnosticCode.UNKNOWN, detail=detail, secrets=secrets)


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


def _without(row: Any, *names: str) -> dict[str, Any]:
    return {k: v for k, v in dict(row).items() if k not in names}


def _constraint(row: Any) -> dict[str, Any]:
    found: dict[str, Any] = {
        "name": row["name"],
        "type": CONSTRAINT_KINDS.get(row["type"], row["type"]),
        "columns": list(row["columns"] or []),
        "definition": row["definition"],
    }
    if row["type"] == "f":
        found["references"] = {
            "schema": row["ref_schema"],
            "table": row["ref_table"],
            "columns": list(row["ref_columns"] or []),
        }
    return found


def _rounded(number: int | None) -> int | None:
    """12 345 678 → 12 000 000: the order of a table, not its last write."""
    if not number or number < 100:
        return number
    return int(float(f"{number:.2g}"))
