"""The Oracle connector — a database's schemas, and their tables and views,
as its catalogue describes them (LEKA-349).

In Oracle a schema is a user: `BILLING` owns its tables. LEKA reads the
ALL_* views of the catalogue — ALL_TABLES, ALL_VIEWS, ALL_TAB_COLS, the
constraints, the indexes — never the rows.

Oracle shows in its ALL_* views only what the account holds a privilege
on — the boundary is the server's own, as MySQL's. And, as MySQL's, one
object privilege shows the structure and not the data: REFERENCES. With
it, on a table or a view, the table, its columns, keys, checks, indexes,
comment and row count are visible — a view with its definition — and a
SELECT is refused, ORA-41900 (tests/test_oracle_connector.py runs with
exactly that). It is granted object by object: a table created later is
not seen until it is granted too. What a view reads Oracle shows only to
its owner (ALL_DEPENDENCIES): LEKA does not guess it from the text.

Safe by construction, as the other database connectors:

- the host must be a **public address** — resolved when connecting, every
  address public, and the connection made to the address checked
  (leka/connectors/network.py);
- **TLS** is required: the connection is TCPS, and the session's own
  NETWORK_PROTOCOL is checked once connected, whatever the driver did.
  The certificate is not verified, as the others'. Oracle's native network
  encryption is not TLS, and python-oracledb's thin mode does not speak
  it: a server that offers only that is refused;
- every session is **read-only** (SET TRANSACTION READ ONLY — the one
  transaction all its reads are in, rolled back at the end), each call
  bounded (15 s).

python-oracledb in thin mode: pure Python, no Oracle client to install.
Oracle Database 19c and later — tested on 26ai — self-hosted or managed.
"""

from __future__ import annotations

import re
import ssl
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import oracledb
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
NAME_MAX = 128  # an Oracle identifier, since 12.2
SERVICE = r"^[A-Za-z0-9][A-Za-z0-9_.$#-]{0,254}$"
# What an account may hold and still only read the structure. INHERIT
# PRIVILEGES on itself every user is given.
STRUCTURE_ONLY = frozenset({"CREATE SESSION", "REFERENCES", "INHERIT PRIVILEGES"})
READS_ROWS = frozenset(
    {"SELECT", "READ", "SELECT ANY TABLE", "READ ANY TABLE", "SELECT ANY DICTIONARY"}
)

# ── the catalogue queries — reads, and only of the catalogue ─────────────────
# `{in}` is a list of binds, one per schema, and `{limit}` the next: the
# values are the driver's to send, never formatted in. A LONG column — a
# view's text, a default — cannot be in a UNION: tables and views are asked
# apart.

WHO = """
SELECT SYS_CONTEXT('USERENV', 'SESSION_USER') AS login,
       SYS_CONTEXT('USERENV', 'DB_NAME') AS database_name,
       (SELECT MAX(version_full) FROM product_component_version) AS version
FROM dual
"""

PROTOCOL = "SELECT SYS_CONTEXT('USERENV', 'NETWORK_PROTOCOL') AS protocol FROM dual"

PRIVILEGES = """
SELECT privilege FROM session_privs
UNION SELECT privilege FROM user_tab_privs WHERE grantee = USER
UNION SELECT privilege FROM role_tab_privs
"""

# The users that own a table or a view the account may see; Oracle's own
# (SYS, SYSTEM, MDSYS…) left out.
SCHEMAS = """
SELECT u.username AS name
FROM all_users u
WHERE u.oracle_maintained = 'N'
  AND EXISTS (SELECT 1 FROM all_objects o
              WHERE o.owner = u.username AND o.object_type IN ('TABLE', 'VIEW'))
ORDER BY u.username
"""

# A materialized view's rows live in a table of its name: that table is
# the materialized view. Dropped, nested, secondary and overflow tables
# are Oracle's own.
TABLES = """
SELECT t.owner AS schema_name, t.table_name AS name,
       CASE WHEN m.mview_name IS NOT NULL THEN 'materialized_view'
            WHEN x.table_name IS NOT NULL THEN 'external_table'
            WHEN t.partitioned = 'YES' THEN 'partitioned_table'
            WHEN t.temporary = 'Y' THEN 'temporary_table'
            ELSE 'table' END AS kind,
       c.comments AS comment_text, t.num_rows AS estimated_rows
FROM all_tables t
LEFT JOIN all_mviews m ON m.owner = t.owner AND m.container_name = t.table_name
LEFT JOIN all_external_tables x ON x.owner = t.owner AND x.table_name = t.table_name
LEFT JOIN all_tab_comments c ON c.owner = t.owner AND c.table_name = t.table_name
WHERE t.owner IN ({in}) AND t.dropped = 'NO' AND t.secondary = 'N' AND t.nested = 'NO'
  AND (t.iot_type IS NULL OR t.iot_type = 'IOT')
ORDER BY t.owner, t.table_name
FETCH FIRST {limit} ROWS ONLY
"""

VIEWS = """
SELECT v.owner AS schema_name, v.view_name AS name, c.comments AS comment_text,
       v.text AS definition
FROM all_views v
LEFT JOIN all_tab_comments c ON c.owner = v.owner AND c.table_name = v.view_name
WHERE v.owner IN ({in})
ORDER BY v.owner, v.view_name
FETCH FIRST {limit} ROWS ONLY
"""

MATERIALIZED = """
SELECT owner AS schema_name, mview_name AS name, query AS definition
FROM all_mviews
WHERE owner IN ({in})
"""

COLUMNS = """
SELECT c.owner AS schema_name, c.table_name, c.column_name AS name, c.data_type,
       c.char_length, c.char_used, c.data_length, c.data_precision, c.data_scale,
       c.nullable, c.data_default AS default_value, c.identity_column, c.virtual_column,
       m.comments AS comment_text
FROM all_tab_cols c
LEFT JOIN all_col_comments m
  ON m.owner = c.owner AND m.table_name = c.table_name AND m.column_name = c.column_name
WHERE c.owner IN ({in}) AND c.hidden_column = 'NO'
ORDER BY c.owner, c.table_name, c.column_id
"""

IDENTITIES = """
SELECT owner AS schema_name, table_name, column_name AS name, generation_type
FROM all_tab_identity_cols
WHERE owner IN ({in})
"""

# A foreign key's target is its referenced constraint's table, and must be
# visible too: one the account holds no privilege on is not named, and the
# key not read.
CONSTRAINTS = """
SELECT c.owner AS schema_name, c.table_name, c.constraint_name AS name,
       c.constraint_type AS type, c.search_condition_vc AS condition,
       c.delete_rule, k.column_name AS column_name,
       r.owner AS ref_schema, r.table_name AS ref_table, rk.column_name AS ref_column
FROM all_constraints c
JOIN all_cons_columns k ON k.owner = c.owner AND k.constraint_name = c.constraint_name
LEFT JOIN all_constraints r ON r.owner = c.r_owner AND r.constraint_name = c.r_constraint_name
LEFT JOIN all_cons_columns rk
  ON rk.owner = r.owner AND rk.constraint_name = r.constraint_name AND rk.position = k.position
WHERE c.owner IN ({in}) AND c.constraint_type IN ('P', 'U', 'R', 'C')
ORDER BY c.owner, c.table_name, c.constraint_name, k.position, k.column_name
"""

# An index on an expression — and a descending one, which Oracle keeps as
# one — names a hidden column; its expression is in ALL_IND_EXPRESSIONS.
INDEXES = """
SELECT i.table_owner AS schema_name, i.table_name, i.index_name AS name, i.index_type,
       i.uniqueness, p.constraint_name AS primary_key, k.column_name, k.descend,
       e.column_expression AS expression
FROM all_indexes i
JOIN all_ind_columns k ON k.index_owner = i.owner AND k.index_name = i.index_name
LEFT JOIN all_ind_expressions e
  ON e.index_owner = i.owner AND e.index_name = i.index_name
 AND e.column_position = k.column_position
LEFT JOIN all_constraints p
  ON p.owner = i.table_owner AND p.table_name = i.table_name AND p.index_name = i.index_name
 AND p.constraint_type = 'P'
WHERE i.table_owner IN ({in}) AND i.index_type <> 'LOB'
ORDER BY i.table_owner, i.table_name, i.index_name, k.column_position
"""

QUERIES = (
    WHO,
    PROTOCOL,
    PRIVILEGES,
    SCHEMAS,
    TABLES,
    VIEWS,
    MATERIALIZED,
    COLUMNS,
    IDENTITIES,
    CONSTRAINTS,
    INDEXES,
)
KEY_KINDS = {"P": ("primary_key", "PRIMARY KEY"), "U": ("unique", "UNIQUE")}
# A NOT NULL is a check to Oracle, written so; LEKA reads it as nullable.
NOT_NULL = re.compile(r'^"[^"]+" IS NOT NULL$')
CHARACTERS = frozenset({"VARCHAR2", "CHAR", "NVARCHAR2", "NCHAR"})

# Oracle's error codes, and python-oracledb's, for the diagnostics.
REFUSED = frozenset({"ORA-01017", "ORA-28000", "ORA-28001"})
UNKNOWN_SERVICE = frozenset({"DPY-6001", "ORA-12514"})
DENIED = frozenset({"ORA-41900", "ORA-01031", "ORA-00942", "ORA-01045"})
CALL_TIMEOUT = "DPY-4024"


class OracleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(
        min_length=1,
        max_length=253,
        pattern=HOST,
        description="The server's name or address — public, reachable from LEKA's server.",
    )
    port: int = Field(default=2484, ge=1, le=65535, description="The server's TLS (TCPS) port.")
    service_name: str = Field(
        min_length=1,
        max_length=255,
        pattern=SERVICE,
        description="The database's service: ORCLPDB1, or a pluggable database's.",
    )
    schemas: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCOPE_OPTIONS,
        description="The schemas — users — to describe, as Oracle writes them: BILLING. "
        "Empty: every one the account may see.",
    )

    @field_validator("host")
    @classmethod
    def _not_obviously_private(cls, value: str) -> str:
        return public_host(value)

    @field_validator("schemas")
    @classmethod
    def _names(cls, value: list[str] | None) -> list[str] | None:
        return schema_names(value, NAME_MAX)


class OracleCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # First: the stored hint is taken from the first field — the user's
    # name, which says nothing of the password.
    username: str = Field(min_length=1, max_length=NAME_MAX, description="The user.")
    password: SecretStr = Field(
        min_length=1,
        max_length=1024,
        description="Its password.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )


class NoTlsError(ConnectionError):
    """Connected, and the session is not TCPS."""


@register_connector
class OracleConnector(Connector[OracleConfig, OracleCredentials]):
    manifest = ConnectorManifest(
        key=SourceKind.ORACLE,
        display_name="Oracle",
        category=ConnectorCategory.DATA,
        auth_type="token",
        config_schema=OracleConfig,
        credentials_schema=OracleCredentials,
        capabilities=frozenset({C.SCHEMAS, C.TABLES}),
        # The catalogue has no "changed since": both come whole each pass.
        listed_whole=frozenset({C.SCHEMAS, C.TABLES}),
    )

    # ── the contract ─────────────────────────────────────────────────────────

    async def test_connection(self) -> ConnectionTestResult:
        async with self._session() as db:
            [who] = await _fetch(db, WHO)
            privileges = {str(row["privilege"]) for row in await _fetch(db, PRIVILEGES)}
            schemas = [str(row["name"]) for row in await _fetch(db, SCHEMAS)]
            self._require_scope(schemas)
            in_scope = self._in_scope(schemas)
            if in_scope:
                await _fetch(db, _in(TABLES, in_scope), *in_scope, 1)
        warnings: list[str] = []
        if privileges & READS_ROWS:
            warnings.append(
                "Ce compte peut lire les lignes (SELECT, READ). LEKA n'en a pas besoin : "
                "REFERENCES sur les tables et vues à décrire suffit."
            )
        beyond = sorted(privileges - STRUCTURE_ONLY - READS_ROWS)
        if beyond:
            named = ", ".join(beyond[:6]) + ("…" if len(beyond) > 6 else "")
            warnings.append(
                f"Ce compte peut plus que lire ({named}). LEKA ne lit que le catalogue : "
                "REFERENCES sur les tables et vues à décrire suffit."
            )
        if not schemas:
            warnings.append(
                "Aucun schéma n'est visible : donnez à ce compte REFERENCES sur les tables et "
                "vues à décrire."
            )
        return ConnectionTestResult(
            account=f"{who['login']}@{self.config.host}",
            metadata={
                "version": str(who["version"]),
                "database": str(who["database_name"]),
                "schemas_visible": len(schemas),
            },
            capabilities=[C.SCHEMAS, C.TABLES],
            warnings=warnings,
        )

    async def check_health(self) -> HealthResult:
        async with self._session() as db:
            await _fetch(db, "SELECT 1 AS ok FROM dual")
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
            msg = f"Oracle does not read {capability}"
            raise ValueError(msg)
        fetched = datetime.now(UTC)
        async with self._session() as db:
            wanted = self._in_scope([str(row["name"]) for row in await _fetch(db, SCHEMAS)])
            if capability is C.SCHEMAS:
                [who] = await _fetch(db, WHO)
                for name in wanted:
                    payload = {
                        "name": name,
                        "owner": name,  # a schema is its user
                        "comment": None,
                        "database": who["database_name"],
                        "server": self._server(),
                    }
                    # Its own container, as a repository is: the scope
                    # rules keep or leave a schema and its tables alike.
                    yield _record(C.SCHEMAS, payload, name, name, fetched)
                return
            for table in await self._tables(db, wanted):
                external_id = f"{table['schema']}.{table['name']}"
                payload = {**table, "server": self._server()}
                yield _record(C.TABLES, payload, external_id, str(table["schema"]), fetched)

    def _server(self) -> dict[str, object]:
        """Where its catalogue is read: the service it connects to — case-
        insensitive, as Oracle's names are (leka/connectors/databases.py)."""
        service = self.config.service_name.strip().lower()
        return server("oracle", self.config.host, self.config.port, service)

    # ── inside ───────────────────────────────────────────────────────────────

    async def _open(self) -> Any:
        """A TCPS connection to the address checked. Replaced in the tests,
        which skip the address check."""
        address = await network.public_address(self.config.host, self.config.port)
        context = ssl.create_default_context()
        context.check_hostname = False  # encrypted, not verified — as the others
        context.verify_mode = ssl.CERT_NONE
        return await oracledb.connect_async(
            user=self.credentials.username,
            password=self.credentials.password.get_secret_value(),
            host=address,
            port=self.config.port,
            service_name=self.config.service_name,
            protocol="tcps",
            ssl_context=context,
            ssl_server_dn_match=False,
            tcp_connect_timeout=CONNECT_TIMEOUT,
            retry_count=0,
            program="LEKA",
        )

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[Any]:
        """A read-only, encrypted session for one call, rolled back and
        closed after it; every failure a diagnostic."""
        try:
            db = await self._open()
        except Exception as error:
            raise self._diagnose(error) from error
        try:
            try:
                db.call_timeout = STATEMENT_TIMEOUT_MS
                [session] = await _fetch(db, PROTOCOL)
                if str(session["protocol"]).lower() != "tcps":
                    raise NoTlsError(f"the session is {session['protocol']}, not tcps")
                await _fetch(db, "SET TRANSACTION READ ONLY")
                yield db
            except ConnectorError:
                raise
            except (oracledb.Error, OSError) as error:
                raise self._diagnose(error) from error
        finally:
            with suppress(oracledb.Error, OSError):
                await db.rollback()
            with suppress(oracledb.Error, OSError):
                await db.close()

    async def _tables(self, db: Any, schemas: list[str]) -> list[dict[str, Any]]:
        """Every table and view of these schemas, with what the catalogue
        says of each — asked for all of them at once, not one by one."""
        if not schemas:
            return []
        rows = await _fetch(db, _in(TABLES, schemas), *schemas, MAX_TABLES + 1)
        views = await _fetch(db, _in(VIEWS, schemas), *schemas, MAX_TABLES + 1)
        if len(rows) + len(views) > MAX_TABLES:
            raise too_many_tables()
        tables: dict[tuple[str, str], dict[str, Any]] = {}
        for row in [*rows, *({**view, "kind": "view"} for view in views)]:
            schema, name = str(row["schema_name"]), str(row["name"])
            tables[(schema, name)] = {
                "schema": schema,
                "name": name,
                "kind": row["kind"],
                "owner": schema,
                "comment": row["comment_text"],
                "estimated_rows": rounded(row.get("estimated_rows")),
                "size_bytes": None,  # a segment's size is DBA_SEGMENTS', not the account's
                "definition": row.get("definition"),
                "columns": [],
                "constraints": [],
                "indexes": [],
                "reads_from": [],
            }

        def table_of(row: dict[str, Any]) -> dict[str, Any] | None:
            return tables.get((str(row["schema_name"]), str(row["table_name"])))

        args = tuple(schemas)
        for row in await _fetch(db, _in(MATERIALIZED, schemas), *args):
            if (view := tables.get((str(row["schema_name"]), str(row["name"])))) is not None:
                view["definition"] = row["definition"]
        identities = {
            (str(row["schema_name"]), str(row["table_name"]), str(row["name"])): str(
                row["generation_type"]
            )
            for row in await _fetch(db, _in(IDENTITIES, schemas), *args)
        }
        for row in await _fetch(db, _in(COLUMNS, schemas), *args):
            if (table := table_of(row)) is not None:
                key = (str(row["schema_name"]), str(row["table_name"]), str(row["name"]))
                table["columns"].append(
                    {
                        "name": row["name"],
                        "type": _type(row),
                        "nullable": row["nullable"] == "Y",
                        "default": _default(row, identities.get(key)),
                        "comment": row["comment_text"],
                    }
                )
        for rows_of_one in _grouped(await _fetch(db, _in(CONSTRAINTS, schemas), *args)):
            if (table := table_of(rows_of_one[0])) is not None and (
                constraint := _constraint(rows_of_one)
            ) is not None:
                table["constraints"].append(constraint)
        for rows_of_one in _grouped(await _fetch(db, _in(INDEXES, schemas), *args)):
            if (table := table_of(rows_of_one[0])) is not None:
                table["indexes"].append(_index(rows_of_one))
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
                message="Ce compte ne voit aucune table ni vue de ces schémas (pas de "
                f"REFERENCES) : {named}.",
            )

    def _diagnose(self, error: BaseException) -> ConnectorError:
        """What went wrong, in the admin's words, the password never in it.
        python-oracledb wraps the cause — a refused TLS handshake, a
        timeout — in its own error: the whole chain is read."""
        secrets = [self.credentials.password.get_secret_value()]
        detail = f"{type(error).__name__}: {error}"
        chain = list(_chain(error))
        codes = {code for e in chain if (code := _code(e))}
        if isinstance(error, network.PrivateAddressError):
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Cet hôte ne mène pas à une adresse publique.",
                detail=detail,
                secrets=secrets,
            )
        if isinstance(error, NoTlsError) or any(
            isinstance(e, ssl.SSLError | ConnectionResetError) for e in chain
        ):
            return diagnose(
                DiagnosticCode.CONFIG_INVALID,
                message="Le serveur n'accepte pas de connexion chiffrée (TCPS) sur ce port : "
                "LEKA l'exige.",
                detail=detail,
                secrets=secrets,
            )
        if CALL_TIMEOUT in codes or any(isinstance(e, TimeoutError) for e in chain):
            return diagnose(DiagnosticCode.TIMEOUT, detail=detail, secrets=secrets)
        if codes & REFUSED:
            return diagnose(
                DiagnosticCode.AUTH_INVALID,
                message="Oracle refuse ce compte ou ce mot de passe.",
                detail=detail,
                secrets=secrets,
            )
        if codes & UNKNOWN_SERVICE:
            return diagnose(
                DiagnosticCode.NOT_FOUND,
                message="Ce service n'est pas connu du serveur : vérifiez son nom.",
                detail=detail,
                secrets=secrets,
            )
        if codes & DENIED:
            return diagnose(DiagnosticCode.PERMISSION_DENIED, detail=detail, secrets=secrets)
        if any(isinstance(e, OSError) for e in chain):
            return diagnose(DiagnosticCode.NETWORK_UNREACHABLE, detail=detail, secrets=secrets)
        if isinstance(error, oracledb.Error):
            return diagnose(DiagnosticCode.PROVIDER_ERROR, detail=detail, secrets=secrets)
        return diagnose(DiagnosticCode.UNKNOWN, detail=detail, secrets=secrets)


async def _fetch(db: Any, query: str, *args: object) -> list[dict[str, Any]]:
    """The rows, each a dict of lower-case names — Oracle's are upper."""
    cursor = db.cursor()
    try:
        await cursor.execute(query, list(args) if args else None)
        if cursor.description is None:
            return []
        names = [str(column[0]).lower() for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in await cursor.fetchall()]
    finally:
        cursor.close()


def _in(query: str, schemas: Sequence[str]) -> str:
    """The query with one bind per schema, then one for the limit — the
    values sent apart, never formatted in."""
    binds = ", ".join(f":{position}" for position in range(1, len(schemas) + 1))
    return query.replace("{in}", binds).replace("{limit}", f":{len(schemas) + 1}")


def _chain(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _code(error: BaseException) -> str | None:
    """ORA-01017, DPY-6001: what python-oracledb says an error is."""
    first = error.args[0] if error.args else None
    code = getattr(first, "full_code", None)
    return str(code) if code else None


def _type(row: dict[str, Any]) -> str:
    """A column's type as Oracle writes it: VARCHAR2(200), VARCHAR2(200 CHAR),
    NUMBER(12,2), NUMBER, TIMESTAMP(3) — the last as the catalogue has it."""
    name = str(row["data_type"])
    precision, scale = row["data_precision"], row["data_scale"]
    if name in CHARACTERS:
        unit = " CHAR" if row["char_used"] == "C" and not name.startswith("N") else ""
        return f"{name}({row['char_length']}{unit})"
    if name == "NUMBER":
        if precision is None:
            return "NUMBER" if scale is None else f"NUMBER(*,{scale})"
        return f"NUMBER({precision})" if not scale else f"NUMBER({precision},{scale})"
    if name == "FLOAT" and precision is not None:
        return f"FLOAT({precision})"
    if name in ("RAW", "UROWID"):
        return f"{name}({row['data_length']})"
    return name


def _default(row: dict[str, Any], identity: str | None) -> str | None:
    """What fills a column when nothing is written to it: its identity, its
    expression when virtual, its default."""
    if row["identity_column"] == "YES":
        return f"GENERATED {identity or 'ALWAYS'} AS IDENTITY"
    written = str(row["default_value"]).strip() if row["default_value"] is not None else None
    if row["virtual_column"] == "YES":
        return f"AS ({written})"
    return written or None


def _grouped(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Rows of one constraint or index together, as the queries order them."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["schema_name"]), str(row["table_name"]), str(row["name"]))
        groups.setdefault(key, []).append(row)
    return list(groups.values())


def _constraint(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A constraint in the shape the other engines' come in — or None: a
    NOT NULL, which the column says, or a foreign key to a table the
    account may not see."""
    first = rows[0]
    kind = str(first["type"])
    columns = [str(row["column_name"]) for row in rows]
    listed = ", ".join(columns)
    if kind in KEY_KINDS:
        name, written = KEY_KINDS[kind]
        return {
            "name": first["name"],
            "type": name,
            "columns": columns,
            "definition": f"{written} ({listed})",
        }
    if kind == "C":
        condition = str(first["condition"] or "")
        if not condition or NOT_NULL.fullmatch(condition):
            return None
        return {
            "name": first["name"],
            "type": "check",
            "columns": columns,
            "definition": f"CHECK ({condition})",
        }
    if first["ref_table"] is None:
        return None
    referenced = [str(row["ref_column"]) for row in rows]
    target = f"{first['ref_schema']}.{first['ref_table']}"
    on_delete = (
        "" if first["delete_rule"] in (None, "NO ACTION") else f" ON DELETE {first['delete_rule']}"
    )
    return {
        "name": first["name"],
        "type": "foreign_key",
        "columns": columns,
        "references": {
            "schema": first["ref_schema"],
            "table": first["ref_table"],
            "columns": referenced,
        },
        "definition": f"FOREIGN KEY ({listed}) REFERENCES {target}({', '.join(referenced)})"
        + on_delete,
    }


def _index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """An index as Oracle would create it: its columns — or expressions —
    in order, descending where they are."""
    first = rows[0]
    parts = [
        str(row["expression"] or row["column_name"]) + (" DESC" if row["descend"] == "DESC" else "")
        for row in rows
    ]
    unique = first["uniqueness"] == "UNIQUE"
    kind = (
        "UNIQUE " if unique else "BITMAP " if str(first["index_type"]).startswith("BITMAP") else ""
    )
    return {
        "name": first["name"],
        "definition": f"CREATE {kind}INDEX {first['name']} ON "
        f"{first['schema_name']}.{first['table_name']} ({', '.join(parts)})",
        "unique": unique,
        "primary": first["primary_key"] is not None,
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
