"""Databases: PostgreSQL's and MySQL's schemas, and their tables and views;
MongoDB's databases, and their collections and views (LEKA-349).

What a question about data needs: a table's name as it is written in a
query (`billing.invoices`), what it is (a table, a view…), its columns as a
reader would scan them — one line each, type, NOT NULL, key, what it points
to, its comment — and what it is tied to: the tables its foreign keys
reference and the ones a view reads from, as references. The sizes are the
catalogue's estimates, rounded by the connector.

The payloads are the ones leka/connectors/postgresql and mysql store: the
catalogue's answers, one object per schema and per table — a table's in
the same shape whichever the engine (leka/connectors/databases.py), so one
reading serves them all. A MySQL schema is a database, and has no comment;
a MongoDB collection's columns are its validator's fields, when it has one.
"""

from __future__ import annotations

from typing import Any

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction.contract import Extracted, Reference
from leka.ingestion.extraction.engine import Payload, strategy
from leka.ingestion.extraction.fields import content, number, ref, required, string, strings

C = Capability
POSTGRESQL = SourceKind.POSTGRESQL
MYSQL = SourceKind.MYSQL
MONGODB = SourceKind.MONGODB
SUPABASE = SourceKind.SUPABASE  # PostgreSQL, read by its connector


@strategy("postgresql.schemas", 1, (POSTGRESQL, C.SCHEMAS), (SUPABASE, C.SCHEMAS))
def postgresql_schema(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        content=content("description", string(p, "comment")),
        references=ref("database", "database", external_id=string(p, "database")),
        metadata={"owner": string(p, "owner"), "database": string(p, "database")},
        signals={"engine": "postgresql"},
    )


@strategy("mysql.schemas", 1, (MYSQL, C.SCHEMAS))
def mysql_schema(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        metadata={"charset": string(p, "charset"), "collation": string(p, "collation")},
        signals={"engine": "mysql"},
    )


@strategy("mongodb.schemas", 1, (MONGODB, C.SCHEMAS))
def mongodb_database(p: Payload) -> Extracted:
    return Extracted(
        title=required(p, "name"),
        metadata={
            "collections": number(p, "collections"),
            "views": number(p, "views"),
            "size_bytes": number(p, "size_bytes"),
        },
        signals={"engine": "mongodb"},
    )


@strategy("postgresql.tables", 1, (POSTGRESQL, C.TABLES), (SUPABASE, C.TABLES))
def postgresql_table(p: Payload) -> Extracted:
    return _table(p, "postgresql")


@strategy("mysql.tables", 1, (MYSQL, C.TABLES))
def mysql_table(p: Payload) -> Extracted:
    return _table(p, "mysql")


@strategy("mongodb.tables", 1, (MONGODB, C.TABLES))
def mongodb_collection(p: Payload) -> Extracted:
    return _table(p, "mongodb")


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
        },
        signals={"engine": engine, "storage_engine": string(p, "engine")},
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


def _dicts(p: Payload, key: str) -> list[dict[str, Any]]:
    value = p.get(key) if isinstance(p, dict) else None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
