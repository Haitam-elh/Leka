"""The MySQL connector — a server's databases, and their tables and views,
as its catalogue describes them (LEKA-349).

In MySQL a schema is a database: `billing` is both, and LEKA calls it a
schema, as PostgreSQL does. LEKA reads information_schema, never the rows.

MySQL shows in information_schema only what the account holds a privilege
on — the boundary is the server's own. So the account needs a privilege
that reveals the structure and not the data: REFERENCES on the databases
to describe. With it, columns, keys, checks and indexes are visible, and a
SELECT is refused (tests/test_mysql_connector.py runs with exactly that).
A view's definition, and the tables it reads, MySQL shows only to an
account that may SELECT from the view — and so read its rows: LEKA reads
them when the admin granted that, and otherwise describes a view by its
name and columns.

Safe by construction, as the PostgreSQL connector:

- the host must be a **public address** — resolved when connecting, every
  address public, and the connection made to the address checked
  (leka/connectors/network.py);
- **TLS** is required: the driver refuses a server without it, and the
  session's cipher is checked once connected, whatever the driver did. The
  certificate is not verified — as PostgreSQL's sslmode=require;
- every session is **read-only** (SET SESSION TRANSACTION READ ONLY), each
  SELECT bounded by MAX_EXECUTION_TIME.

MySQL 8.0 and later — Aurora MySQL 3, Percona Server, the managed ones.
MariaDB speaks another dialect of information_schema: its connector
(leka/connectors/mariadb) is this one with MariaDB's queries and settings,
the class attributes below. Pointed at the other engine's server, each
says so rather than fail on a setting it does not know.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar

import asyncmy
from asyncmy.cursors import DictCursor
from asyncmy.errors import MySQLError
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
IDENTIFIER_MAX = 64  # a MySQL database's or table's name
USER_MAX = 32  # a MySQL account's name
# What an account may hold and still only read the structure: REFERENCES
# shows it; SHOW VIEW alone shows nothing more; USAGE is no privilege.
STRUCTURE_ONLY = frozenset({"USAGE", "REFERENCES", "SHOW VIEW"})

# ── the catalogue queries — reads, and only of information_schema ────────────
# `{in}` is a list of %s, one per schema: the values are the driver's to
# escape, never formatted in.

WHO = "SELECT CURRENT_USER() AS account, VERSION() AS version"

VERSION = "SELECT VERSION() AS version"

PRIVILEGES = """
SELECT PRIVILEGE_TYPE AS privilege FROM information_schema.USER_PRIVILEGES WHERE GRANTEE = %s
UNION SELECT PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES WHERE GRANTEE = %s
UNION SELECT PRIVILEGE_TYPE FROM information_schema.TABLE_PRIVILEGES WHERE GRANTEE = %s
"""

SCHEMAS = """
SELECT SCHEMA_NAME AS name, DEFAULT_CHARACTER_SET_NAME AS charset,
       DEFAULT_COLLATION_NAME AS collation
FROM information_schema.SCHEMATA
WHERE SCHEMA_NAME NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
ORDER BY SCHEMA_NAME
"""

TABLES = """
SELECT TABLE_SCHEMA AS `schema`, TABLE_NAME AS name, TABLE_TYPE AS kind, ENGINE AS engine,
       TABLE_ROWS AS estimated_rows, DATA_LENGTH + INDEX_LENGTH AS size_bytes,
       TABLE_COMMENT AS comment
FROM information_schema.TABLES
WHERE TABLE_SCHEMA IN ({in}) AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
ORDER BY TABLE_SCHEMA, TABLE_NAME
LIMIT %s
"""

COLUMNS = """
SELECT TABLE_SCHEMA AS `schema`, TABLE_NAME AS `table`, COLUMN_NAME AS name,
       COLUMN_TYPE AS type, IS_NULLABLE = 'YES' AS nullable, COLUMN_DEFAULT AS `default`,
       COLUMN_COMMENT AS comment
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA IN ({in})
ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
"""

CONSTRAINTS = """
SELECT TABLE_SCHEMA AS `schema`, TABLE_NAME AS `table`, CONSTRAINT_NAME AS name,
       CONSTRAINT_TYPE AS type
FROM information_schema.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA IN ({in})
ORDER BY TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME
"""

KEY_COLUMNS = """
SELECT TABLE_SCHEMA AS `schema`, TABLE_NAME AS `table`, CONSTRAINT_NAME AS name,
       COLUMN_NAME AS `column`, REFERENCED_TABLE_SCHEMA AS ref_schema,
       REFERENCED_TABLE_NAME AS ref_table, REFERENCED_COLUMN_NAME AS ref_column
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA IN ({in})
ORDER BY TABLE_SCHEMA, TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION
"""

# A check's table is in TABLE_CONSTRAINTS: MySQL names a check once in its
# database, so the two meet on the name.
CHECKS = """
SELECT c.CONSTRAINT_SCHEMA AS `schema`, t.TABLE_NAME AS `table`, c.CONSTRAINT_NAME AS name,
       c.CHECK_CLAUSE AS clause
FROM information_schema.CHECK_CONSTRAINTS c
JOIN information_schema.TABLE_CONSTRAINTS t
  ON t.CONSTRAINT_SCHEMA = c.CONSTRAINT_SCHEMA AND t.CONSTRAINT_NAME = c.CONSTRAINT_NAME
 AND t.CONSTRAINT_TYPE = 'CHECK'
WHERE c.CONSTRAINT_SCHEMA IN ({in})
"""

INDEXES = """
SELECT TABLE_SCHEMA AS `schema`, TABLE_NAME AS `table`, INDEX_NAME AS name,
       NON_UNIQUE = 0 AS `unique`, COALESCE(COLUMN_NAME, EXPRESSION) AS part,
       INDEX_TYPE AS method
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA IN ({in})
ORDER BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
"""

VIEWS = """
SELECT TABLE_SCHEMA AS `schema`, TABLE_NAME AS name, VIEW_DEFINITION AS definition
FROM information_schema.VIEWS
WHERE TABLE_SCHEMA IN ({in})
"""

VIEW_SOURCES = """
SELECT VIEW_SCHEMA AS `schema`, VIEW_NAME AS name, TABLE_SCHEMA AS ref_schema,
       TABLE_NAME AS ref_table
FROM information_schema.VIEW_TABLE_USAGE
WHERE VIEW_SCHEMA IN ({in})
ORDER BY VIEW_SCHEMA, VIEW_NAME, TABLE_SCHEMA, TABLE_NAME
"""

CIPHER = "SHOW SESSION STATUS LIKE 'Ssl_cipher'"

QUERIES = (
    WHO,
    VERSION,
    PRIVILEGES,
    SCHEMAS,
    TABLES,
    COLUMNS,
    CONSTRAINTS,
    KEY_COLUMNS,
    CHECKS,
    INDEXES,
    VIEWS,
    VIEW_SOURCES,
)
KINDS = {"BASE TABLE": "table", "VIEW": "view"}
CONSTRAINT_KINDS = {
    "PRIMARY KEY": "primary_key",
    "UNIQUE": "unique",
    "FOREIGN KEY": "foreign_key",
    "CHECK": "check",
}
# Every session: read-only whatever the account may do, each SELECT bounded.
SESSION = (
    "SET SESSION TRANSACTION READ ONLY",
    f"SET SESSION MAX_EXECUTION_TIME = {STATEMENT_TIMEOUT_MS}",
)

# MySQL's error numbers, for the diagnostics.
ACCESS_DENIED = 1045
DATABASE_ACCESS_DENIED = 1044
COMMAND_DENIED = (1142, 1143, 1227)
TOO_SLOW = 3024
UNREACHABLE = (2002, 2003, 2005, 2006, 2013)


class MySQLConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(
        min_length=1,
        max_length=253,
        pattern=HOST,
        description="The server's name or address — public, reachable from LEKA's server.",
    )
    port: int = Field(default=3306, ge=1, le=65535, description="The server's port.")
    schemas: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="The databases to describe. Empty: every one the account may see.",
    )

    @field_validator("host")
    @classmethod
    def _not_obviously_private(cls, value: str) -> str:
        return public_host(value)

    @field_validator("schemas")
    @classmethod
    def _names(cls, value: list[str] | None) -> list[str] | None:
        return schema_names(value, IDENTIFIER_MAX)


class MySQLCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field — the account's
    # name, which says nothing of the password.
    username: str = Field(min_length=1, max_length=USER_MAX, description="The account.")
    password: SecretStr = Field(
        min_length=1,
        max_length=1024,
        description="Its password.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


class NoTlsError(ConnectionError):
    """Connected, and the session is not encrypted."""


class OtherEngineError(ConnectionError):
    """Connected, to the other engine's server: MariaDB's for the MySQL
    connector, or the reverse."""

    def __init__(self, engine: str, version: str) -> None:
        super().__init__(engine, version)
        self.engine = engine
        self.version = version


@register_connector
class MySQLConnector(Connector[MySQLConfig, MySQLCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.MYSQL,
        display_name="MySQL",
        category=ConnectorCategory.DATA,
        auth_type="token",
        config_schema=MySQLConfig,
        credentials_schema=MySQLCredentials,
        capabilities=frozenset({C.SCHEMAS, C.TABLES}),
        # The catalogue has no "changed since": both come whole each pass.
        listed_whole=frozenset({C.SCHEMAS, C.TABLES}),
    )

    # MySQL's dialect. MariaDB's connector replaces these, and the methods
    # that say what a default is, what a view reads, which engine is not
    # this one's; the rest — the privileges, the boundary, the payload — is
    # the same.
    session: ClassVar[tuple[str, ...]] = SESSION
    tables_query: ClassVar[str] = TABLES
    checks_query: ClassVar[str] = CHECKS
    indexes_query: ClassVar[str] = INDEXES
    kinds: ClassVar[Mapping[str, str]] = KINDS
    too_slow: ClassVar[int] = TOO_SLOW

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._session() as db:
            [who] = await _fetch(db, WHO)
            account = str(who["account"])
            grantee = _grantee(account)
            privileges = {
                str(row["privilege"])
                for row in await _fetch(db, PRIVILEGES, grantee, grantee, grantee)
            }
            schemas = [str(row["name"]) for row in await _fetch(db, SCHEMAS)]
            self._require_scope(schemas)
            in_scope = self._in_scope(schemas)
            if in_scope:
                await _fetch(db, _in(self.tables_query, in_scope), *in_scope, 1)
        warnings: list[str] = []
        if "SELECT" in privileges:
            warnings.append(
                "Ce compte peut lire les lignes (SELECT). LEKA n'en a pas besoin : REFERENCES "
                "sur les bases à décrire suffit — SELECT ne sert qu'à lire la définition des "
                "vues."
            )
        beyond = sorted(privileges - STRUCTURE_ONLY - {"SELECT"})
        if beyond:
            named = ", ".join(beyond[:6]) + ("…" if len(beyond) > 6 else "")
            warnings.append(
                f"Ce compte peut plus que lire ({named}). LEKA ne lit que le catalogue : "
                "REFERENCES sur les bases à décrire suffit."
            )
        if not schemas:
            warnings.append(
                "Aucune base n'est visible : donnez à ce compte REFERENCES sur les bases à décrire."
            )
        return ConnectionTestResult(
            account=f"{account.rsplit('@', 1)[0]}@{self.config.host}",
            metadata={"version": str(who["version"]), "schemas_visible": len(schemas)},
            capabilities=[C.SCHEMAS, C.TABLES],
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._session() as db:
            await _fetch(db, "SELECT 1 AS ok")
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def list_scope(self) -> ScopeListing:
        async with self._session() as db:
            rows = await _fetch(db, SCHEMAS)
        options = [
            ScopeOption(key=str(row["name"]), name=str(row["name"]))
            for row in rows[:MAX_SCOPE_OPTIONS]
        ]
        return ScopeListing(options=options, truncated=len(rows) > MAX_SCOPE_OPTIONS)

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        if capability not in self.manifest.capabilities:
            msg = f"{self.manifest.display_name} does not read {capability}"
            raise ValueError(msg)
        fetched = datetime.now(UTC)
        async with self._session() as db:
            rows = await _fetch(db, SCHEMAS)
            wanted = self._in_scope([str(row["name"]) for row in rows])
            if capability is C.SCHEMAS:
                for row in rows:
                    name = str(row["name"])
                    if name in wanted:
                        # Its own container, as a repository is: the scope
                        # rules keep or leave a database and its tables alike.
                        payload = {**dict(row), "server": self._server()}
                        yield _record(C.SCHEMAS, payload, name, name, fetched)
                return
            for table in await self._tables(db, wanted):
                external_id = f"{table['schema']}.{table['name']}"
                payload = {**table, "server": self._server()}
                yield _record(C.TABLES, payload, external_id, str(table["schema"]), fetched)

    def _server(self) -> dict[str, object]:
        """Where its catalogue is read: a server, whose databases are its
        schemas (leka/connectors/databases.py)."""
        engine = self.manifest.key.value  # mysql, or mariadb
        return server(engine, self.config.host, self.config.port, None)

    # ── inside ───────────────────────────────────────────────────────────────

    async def _open(self) -> Any:
        """A connection to the address checked, over TLS, then made
        read-only. Replaced in the tests, which skip the address check."""
        address = await network.public_address(self.config.host, self.config.port)
        context = ssl.create_default_context()
        context.check_hostname = False  # encrypted, not verified — as sslmode=require
        context.verify_mode = ssl.CERT_NONE
        return await asyncmy.connect(
            host=address,
            port=self.config.port,
            user=self.credentials.username,
            password=self.credentials.password.get_secret_value(),
            ssl=context,
            connect_timeout=CONNECT_TIMEOUT,
            # MAX_EXECUTION_TIME first; this if the network hangs.
            read_timeout=STATEMENT_TIMEOUT_MS / 1000 + CONNECT_TIMEOUT,
            program_name="LEKA",
            autocommit=True,
        )

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[Any]:
        """A read-only, encrypted session for one call, closed after it;
        every failure a diagnostic."""
        try:
            db = await self._open()
        except Exception as error:
            raise self._diagnose(error) from error
        try:
            try:
                [cipher] = await _fetch(db, CIPHER)
                if not cipher.get("Value"):
                    raise NoTlsError("the session is not encrypted")
                [server] = await _fetch(db, VERSION)
                version = str(server["version"])
                if (other := self._other_engine(version)) is not None:
                    raise OtherEngineError(other, version)
                for statement in self.session:
                    await _fetch(db, statement)
                yield db
            except ConnectorError:
                raise
            except (MySQLError, OSError) as error:
                raise self._diagnose(error) from error
        finally:
            db.close()

    async def _tables(self, db: Any, schemas: list[str]) -> list[dict[str, Any]]:
        """Every table and view of these databases, with what the catalogue
        says of each — asked for all of them at once, not one by one."""
        if not schemas:
            return []
        rows = await _fetch(db, _in(self.tables_query, schemas), *schemas, MAX_TABLES + 1)
        if len(rows) > MAX_TABLES:
            raise too_many_tables()
        tables: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            kind = self.kinds[str(row["kind"])]
            comment = row["comment"] or None
            tables[(str(row["schema"]), str(row["name"]))] = {
                "schema": row["schema"],
                "name": row["name"],
                "kind": kind,
                "owner": None,  # MySQL has no owner; a view has a definer
                "engine": row["engine"],
                # MySQL writes "VIEW" as a view's comment.
                "comment": None if kind == "view" and comment == "VIEW" else comment,
                "estimated_rows": rounded(_int(row["estimated_rows"])),
                "size_bytes": rounded(_int(row["size_bytes"])),
                "definition": None,
                "columns": [],
                "constraints": [],
                "indexes": [],
                "reads_from": [],
            }

        def table_of(row: dict[str, Any]) -> dict[str, Any] | None:
            return tables.get((str(row["schema"]), str(row["table"])))

        args = tuple(schemas)
        for row in await _fetch(db, _in(COLUMNS, schemas), *args):
            if (table := table_of(row)) is not None:
                table["columns"].append(
                    {
                        "name": row["name"],
                        "type": row["type"],
                        "nullable": bool(row["nullable"]),
                        "default": self._default(row["default"]),
                        "comment": row["comment"] or None,
                    }
                )
        checks = {
            (str(row["schema"]), str(row["table"]), str(row["name"])): str(row["clause"])
            for row in await _fetch(db, _in(self.checks_query, schemas), *args)
        }
        keys: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in await _fetch(db, _in(KEY_COLUMNS, schemas), *args):
            keys.setdefault((str(row["schema"]), str(row["table"]), str(row["name"])), []).append(
                row
            )
        for row in await _fetch(db, _in(CONSTRAINTS, schemas), *args):
            if (table := table_of(row)) is not None:
                key = (str(row["schema"]), str(row["table"]), str(row["name"]))
                table["constraints"].append(
                    _constraint(key[2], str(row["type"]), keys.get(key, []), checks.get(key))
                )
        indexes: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in await _fetch(db, _in(self.indexes_query, schemas), *args):
            key = (str(row["schema"]), str(row["table"]), str(row["name"]))
            index = indexes.setdefault(
                key,
                {
                    "name": row["name"],
                    "unique": bool(row["unique"]),
                    "primary": row["name"] == "PRIMARY",
                    "method": row["method"],
                    "parts": [],
                },
            )
            index["parts"].append(str(row["part"]))
        for (schema, table_name, _), index in indexes.items():
            if (table := tables.get((schema, table_name))) is not None:
                table["indexes"].append(_index(index))
        for row in await _fetch(db, _in(VIEWS, schemas), *args):
            view = tables.get((str(row["schema"]), str(row["name"])))
            if view is not None:
                view["definition"] = row["definition"] or None  # empty without SELECT
        await self._view_sources(db, schemas, tables)
        return list(tables.values())

    # ── what the dialects say otherwise ──────────────────────────────────────

    async def _view_sources(
        self, db: Any, schemas: list[str], tables: dict[tuple[str, str], dict[str, Any]]
    ) -> None:
        """Each view's `reads_from`: VIEW_TABLE_USAGE's rows, which MySQL
        shows for a view the account may SELECT from, as its definition."""
        for row in await _fetch(db, _in(VIEW_SOURCES, schemas), *schemas):
            view = tables.get((str(row["schema"]), str(row["name"])))
            if view is not None:
                view["reads_from"].append(f"{row['ref_schema']}.{row['ref_table']}")

    def _default(self, value: object) -> object:
        """A column's default as the catalogue writes it: MySQL's is the
        value, a string unquoted, and None when there is none."""
        return value

    def _other_engine(self, version: str) -> str | None:
        """The engine this server is, when it is not this connector's: every
        MariaDB writes its name in its version, 11.8.2-MariaDB-log."""
        return "MariaDB" if "MariaDB" in version else None

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
                message=f"Ce compte ne voit pas ces bases (aucun privilège) : {named}.",
            )

    def _diagnose(self, error: BaseException) -> ConnectorError:
        """What went wrong, in the admin's words, the password never in it."""
        secrets = [self.credentials.password.get_secret_value()]
        detail = f"{type(error).__name__}: {error}"
        code = error.args[0] if isinstance(error, MySQLError) and error.args else None
        if isinstance(error, network.PrivateAddressError):
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Cet hôte ne mène pas à une adresse publique.",
                detail=detail,
                secrets=secrets,
            )
        if isinstance(error, OtherEngineError):
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message=f"Ce serveur est {error.engine} ({error.version}) : ajoutez-le avec "
                f"le connecteur {error.engine}.",
                detail=detail,
                secrets=secrets,
            )
        if isinstance(error, NoTlsError | ssl.SSLError) or "SSL" in str(error):
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Le serveur n'accepte pas de connexion chiffrée (TLS) : LEKA l'exige.",
                detail=detail,
                secrets=secrets,
            )
        if code == ACCESS_DENIED:
            return diagnose(
                DiagnosticCode.AUTH_INVALID,
                message=f"{self.manifest.display_name} refuse ce compte ou ce mot de passe.",
                detail=detail,
                secrets=secrets,
            )
        if code == DATABASE_ACCESS_DENIED or code in COMMAND_DENIED:
            return diagnose(DiagnosticCode.PERMISSION_DENIED, detail=detail, secrets=secrets)
        if code == self.too_slow or isinstance(error, TimeoutError):
            return diagnose(DiagnosticCode.TIMEOUT, detail=detail, secrets=secrets)
        if code in UNREACHABLE or isinstance(error, OSError):
            return diagnose(DiagnosticCode.NETWORK_UNREACHABLE, detail=detail, secrets=secrets)
        if isinstance(error, MySQLError):
            return diagnose(DiagnosticCode.PROVIDER_ERROR, detail=detail, secrets=secrets)
        return diagnose(DiagnosticCode.UNKNOWN, detail=detail, secrets=secrets)


async def _fetch(db: Any, query: str, *args: object) -> list[dict[str, Any]]:
    async with db.cursor(DictCursor) as cursor:
        await cursor.execute(query, args or None)
        rows: list[dict[str, Any]] = await cursor.fetchall()
        return rows


def _in(query: str, schemas: Sequence[str]) -> str:
    """The query with one placeholder per schema — the values escaped by
    the driver, never formatted in."""
    return query.replace("{in}", ", ".join(["%s"] * len(schemas)))


def _grantee(account: str) -> str:
    """CURRENT_USER()'s 'reader@%' as information_schema writes a grantee:
    'reader'@'%'."""
    user, _, host = account.rpartition("@")
    return f"'{user}'@'{host}'"


def _int(value: object) -> int | None:
    """A count or a size, as the driver hands it: an int, or a Decimal."""
    return int(value) if isinstance(value, int | float | Decimal) else None


def _constraint(
    name: str, kind: str, columns: list[dict[str, Any]], clause: str | None
) -> dict[str, Any]:
    """A constraint in the shape PostgreSQL's come in, its definition
    written out as MySQL would."""
    names = [str(c["column"]) for c in columns]
    listed = ", ".join(names)
    found: dict[str, Any] = {
        "name": name,
        "type": CONSTRAINT_KINDS.get(kind, kind.lower()),
        "columns": names,
    }
    if kind == "CHECK":
        found["definition"] = f"CHECK {clause}" if clause else None
    elif kind == "FOREIGN KEY" and columns:
        target = columns[0]
        referenced = [str(c["ref_column"]) for c in columns]
        found["references"] = {
            "schema": target["ref_schema"],
            "table": target["ref_table"],
            "columns": referenced,
        }
        found["definition"] = (
            f"FOREIGN KEY ({listed}) REFERENCES {target['ref_schema']}.{target['ref_table']}"
            f"({', '.join(referenced)})"
        )
    else:
        found["definition"] = f"{kind} ({listed})"
    return found


def _index(index: dict[str, Any]) -> dict[str, Any]:
    unique = "UNIQUE " if index["unique"] and not index["primary"] else ""
    parts = ", ".join(index["parts"])
    return {
        "name": index["name"],
        "definition": f"{unique}INDEX {index['name']} ({parts}) USING {index['method']}",
        "unique": index["unique"],
        "primary": index["primary"],
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
