"""Databases: PostgreSQL's, MySQL's, MariaDB's, SQL Server's and Oracle's
schemas, and their tables and views; MongoDB's databases, and their
collections and views (LEKA-349).

What a question about data needs: a table's name as it is written in a
query (`billing.invoices`), what it is (a table, a view…), its columns as a
reader would scan them — one line each, type, NOT NULL, key, what it points
to, its comment — and what it is tied to: the tables its foreign keys
reference and the ones a view reads from, as references. The sizes are the
catalogue's estimates, rounded by the connector. Its structure, as metadata
(version 3, 2026-10-22: the database review): each column's type
("name type"), each foreign key ("customer_id → billing.customers(id)"),
each index as the engine would create it — what a review of the schema
reads, never a row.

The payloads are the ones the database connectors store: the catalogue's
answers, one object per schema and per table — a table's in the same shape
whichever the engine (leka/connectors/databases.py), so one reading serves
them all. A MySQL or MariaDB schema is a database, and has no comment; a
MongoDB collection's columns are its validator's fields, when it has one.

Where each was read — the server's engine, host, port and database
(LEKA-364) — comes out as signals and metadata: what makes a table one
thing whichever source reads it.
"""

from __future__ import annotations

from typing import Any

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction.contract import Extracted, Reference
from leka.ingestion.extraction.engine import Payload, strategy
from leka.ingestion.extraction.fields import content, number, ref, required, string, strings

# A table's structure kept, at most: its columns' types, its keys, its indexes.
MOST_COLUMNS = 500
MOST_INDEXES = 100

C = Capability
POSTGRESQL = SourceKind.POSTGRESQL
MYSQL = SourceKind.MYSQL
MARIADB = SourceKind.MARIADB
SQLSERVER = SourceKind.SQLSERVER
ORACLE = SourceKind.ORACLE
MONGODB = SourceKind.MONGODB
SUPABASE = SourceKind.SUPABASE  # PostgreSQL, read by its connector


@strategy("postgresql.schemas", 2, (POSTGRESQL, C.SCHEMAS), (SUPABASE, C.SCHEMAS))
def postgresql_schema(p: Payload) -> Extracted:
    return _schema(p, "postgresql")


@strategy("sqlserver.schemas", 2, (SQLSERVER, C.SCHEMAS))
def sqlserver_schema(p: Payload) -> Extracted:
    return _schema(p, "sqlserver")


@strategy("oracle.schemas", 2, (ORACLE, C.SCHEMAS))
def oracle_schema(p: Payload) -> Extracted:
    return _schema(p, "oracle")


@strategy("mysql.schemas", 2, (MYSQL, C.SCHEMAS))
def mysql_schema(p: Payload) -> Extracted:
    return _database(p, "mysql")


@strategy("mariadb.schemas", 2, (MARIADB, C.SCHEMAS))
def mariadb_schema(p: Payload) -> Extracted:
    return _database(p, "mariadb")


@strategy("mongodb.schemas", 2, (MONGODB, C.SCHEMAS))
def mongodb_database(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        metadata={
            "collections": number(p, "collections"),
            "views": number(p, "views"),
            "size_bytes": number(p, "size_bytes"),
            **_where(p)[0],
        },
        signals={"engine": "mongodb", **_where(p)[1]},
    )


@strategy("postgresql.tables", 3, (POSTGRESQL, C.TABLES), (SUPABASE, C.TABLES))
def postgresql_table(p: Payload) -> Extracted:
    return _table(p, "postgresql")


@strategy("mysql.tables", 3, (MYSQL, C.TABLES))
def mysql_table(p: Payload) -> Extracted:
    return _table(p, "mysql")


@strategy("mariadb.tables", 3, (MARIADB, C.TABLES))
def mariadb_table(p: Payload) -> Extracted:
    return _table(p, "mariadb")


@strategy("sqlserver.tables", 3, (SQLSERVER, C.TABLES))
def sqlserver_table(p: Payload) -> Extracted:
    return _table(p, "sqlserver")


@strategy("oracle.tables", 3, (ORACLE, C.TABLES))
def oracle_table(p: Payload) -> Extracted:
    return _table(p, "oracle")


@strategy("mongodb.tables", 2, (MONGODB, C.TABLES))
def mongodb_collection(p: Payload) -> Extracted:
    return _table(p, "mongodb")


def _schema(p: Payload, engine: str) -> Extracted:
    """A schema inside a database — PostgreSQL's, SQL Server's, Oracle's: its
    name, owner, comment, and the database it is in."""
    return Extracted(
        title=required(p, "name"),
        content=content("description", string(p, "comment")),
        references=ref("database", "database", external_id=string(p, "database")),
        # The server's database, as its tables say it — else the schema's.
        metadata={
            "owner": string(p, "owner"),
            "database": string(p, "server", "database") or string(p, "database"),
        },
        signals={"engine": engine, **_where(p)[1]},
    )


def _database(p: Payload, engine: str) -> Extracted:
    """A MySQL or MariaDB database: a name, its character set and collation."""
    return Extracted(
        title=required(p, "name"),
        metadata={
            "charset": string(p, "charset"),
            "collation": string(p, "collation"),
            **_where(p)[0],
        },
        signals={"engine": engine, **_where(p)[1]},
    )


def _table(p: Payload, engine: str) -> Extracted:
    schema = required(p, "schema")
    columns = _dicts(p, "columns")
    constraints = _dicts(p, "constraints")
    keys = [c for c in constraints if c.get("type") == "primary_key"]
    return Extracted(
        title=f"{schema}.{required(p, 'name')}",
        content=[
            *content("description", string(p, "comment")),
            *content("columns", _columns(columns, constraints)),
            *content("definition", string(p, "definition")),
        ],
        references=[
            *ref("schema", "schema", external_id=schema),
            *_referenced(constraints),
            *(
                r
                for table in strings(p, "reads_from")
                for r in ref("reads", "table", external_id=table)
            ),
        ],
        metadata={
            "kind": string(p, "kind"),
            "schema": schema,
            "owner": string(p, "owner"),
            "columns": [str(c["name"]) for c in columns if c.get("name")],
            "primary_key": [str(c) for c in keys[0].get("columns") or []] if keys else [],
            "estimated_rows": number(p, "estimated_rows"),
            "size_bytes": number(p, "size_bytes"),
            # "name type", each column.
            "column_types": [
                f"{c['name']} {c['type']}"
                for c in columns[:MOST_COLUMNS]
                if c.get("name") and c.get("type")
            ],
            # "customer_id → billing.customers(id)", each foreign key.
            "foreign_keys": [
                f"{', '.join(str(n) for n in c.get('columns') or [])} → "
                f"{target.get('schema')}.{target.get('table')}"
                f"({', '.join(str(n) for n in target.get('columns') or [])})"
                for c in constraints
                if c.get("type") == "foreign_key"
                and isinstance(target := c.get("references"), dict)
            ][:MOST_INDEXES],
            "indexes": [
                str(i.get("definition") or f"INDEX {i.get('name')}")
                for i in _dicts(p, "indexes")
                if i.get("definition") or i.get("name")
            ][:MOST_INDEXES],
            **_where(p)[0],
        },
        signals={"engine": engine, "storage_engine": string(p, "engine"), **_where(p)[1]},
    )


def _columns(columns: list[dict[str, Any]], constraints: list[dict[str, Any]]) -> str | None:
    """A table's columns as a reader scans them, then the checks:

    id bigint NOT NULL PRIMARY KEY
    customer_id bigint NOT NULL → billing.customers(id)
    email text NOT NULL UNIQUE — Where invoices go
    CHECK ((amount >= (0)::numeric))
    """
    marks: dict[str, list[str]] = {}
    checks: list[str] = []
    for constraint in constraints:
        named = [str(c) for c in constraint.get("columns") or []]
        kind = constraint.get("type")
        if kind == "check":
            checks.append(str(constraint.get("definition") or ""))
        elif len(named) == 1 and kind in ("primary_key", "unique"):
            marks.setdefault(named[0], []).append(
                "PRIMARY KEY" if kind == "primary_key" else "UNIQUE"
            )
        elif len(named) == 1 and kind == "foreign_key":
            target = constraint.get("references") or {}
            to = f"{target.get('schema')}.{target.get('table')}"
            marks.setdefault(named[0], []).append(
                f"→ {to}({', '.join(target.get('columns') or [])})"
            )
        elif named and kind in ("primary_key", "unique", "foreign_key"):
            checks.append(str(constraint.get("definition") or ""))  # on several columns
    lines = []
    for column in columns:
        name = column.get("name")
        if not name:
            continue
        line = " ".join(
            part
            for part in (
                str(name),
                str(column.get("type") or ""),
                "" if column.get("nullable", True) else "NOT NULL",
                *marks.get(str(name), []),
            )
            if part
        )
        if column.get("comment"):
            line += f" — {column['comment']}"
        lines.append(line)
    lines += [check for check in checks if check]
    return "\n".join(lines) or None


def _referenced(constraints: list[dict[str, Any]]) -> list[Reference]:
    """The tables this one's foreign keys point to, each once."""
    found: dict[str, None] = {}
    for constraint in constraints:
        target = constraint.get("references")
        if constraint.get("type") == "foreign_key" and isinstance(target, dict):
            found[f"{target.get('schema')}.{target.get('table')}"] = None
    return [r for table in found for r in ref("references", "table", external_id=table)]


def _where(p: Payload) -> tuple[dict[str, str | None], dict[str, str | int | float | None]]:
    """Where it was read (LEKA-364): its database as metadata; the server's
    host and port as signals."""
    return (
        {"database": string(p, "server", "database")},
        {"host": string(p, "server", "host"), "port": number(p, "server", "port")},
    )


def _dicts(p: Payload, key: str) -> list[dict[str, Any]]:
    value = p.get(key) if isinstance(p, dict) else None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
