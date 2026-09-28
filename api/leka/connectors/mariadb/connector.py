"""The MariaDB connector — a server's databases, and their tables and views,
as its catalogue describes them (LEKA-349).

The MySQL connector, with MariaDB's dialect. What holds for MySQL holds
here, checked against MariaDB 10.6, 10.11 and 11.8: information_schema
shows only what the account holds a privilege on, REFERENCES shows the
structure and a SELECT is refused, a view's definition needs SELECT on the
view; a public address, TLS required and checked, a read-only session. The
tests of it are tests/test_mariadb_connector.py.

What MariaDB says otherwise, and so the attributes replaced:

- a query is bounded by `max_statement_time`, in seconds — MariaDB has no
  MAX_EXECUTION_TIME — and one too slow is error 1969;
- a table that keeps its history (WITH SYSTEM VERSIONING) is its own kind
  of table; a sequence, which MariaDB lists among the tables, is not read,
  as PostgreSQL's are not;
- STATISTICS has no EXPRESSION: an index's parts are its columns;
- a check is named within its table, not its database — a check written on
  a column takes the column's name, so two tables may each have one called
  `amount` — and CHECK_CONSTRAINTS says which table;
- a column's default is written as SQL: 'none' quoted, current_timestamp(),
  and NULL when there is none — read as no default;
- there is no VIEW_TABLE_USAGE: what a view reads is read from its
  definition, which MariaDB writes back normalised — every table after a
  `from` or a `join`, as `schema`.`table`.
"""

from __future__ import annotations

import re
from typing import Any

from leka.connectors.base import Capability, ConnectorCategory, ConnectorManifest
from leka.connectors.databases import STATEMENT_TIMEOUT_MS
from leka.connectors.models import SourceKind
from leka.connectors.mysql import connector as my
from leka.connectors.mysql.connector import MySQLConfig, MySQLConnector, MySQLCredentials
from leka.connectors.registry import register_connector

C = Capability

TABLES = """
SELECT TABLE_SCHEMA AS `schema`, TABLE_NAME AS name, TABLE_TYPE AS kind, ENGINE AS engine,
       TABLE_ROWS AS estimated_rows, DATA_LENGTH + INDEX_LENGTH AS size_bytes,
       TABLE_COMMENT AS comment
FROM information_schema.TABLES
WHERE TABLE_SCHEMA IN ({in}) AND TABLE_TYPE IN ('BASE TABLE', 'SYSTEM VERSIONED', 'VIEW')
ORDER BY TABLE_SCHEMA, TABLE_NAME
LIMIT %s
"""

# The clause in parentheses, as MySQL writes it: CHECK (`amount` >= 0).
CHECKS = """
SELECT CONSTRAINT_SCHEMA AS `schema`, TABLE_NAME AS `table`, CONSTRAINT_NAME AS name,
       CONCAT('(', CHECK_CLAUSE, ')') AS clause
FROM information_schema.CHECK_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA IN ({in})
"""

INDEXES = """
SELECT TABLE_SCHEMA AS `schema`, TABLE_NAME AS `table`, INDEX_NAME AS name,
       NON_UNIQUE = 0 AS `unique`, COLUMN_NAME AS part, INDEX_TYPE AS method
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA IN ({in})
ORDER BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
"""

QUERIES = (
    my.WHO,
    my.VERSION,
    my.PRIVILEGES,
    my.SCHEMAS,
    TABLES,
    my.COLUMNS,
    my.CONSTRAINTS,
    my.KEY_COLUMNS,
    CHECKS,
    INDEXES,
    my.VIEWS,
)
KINDS = {**my.KINDS, "SYSTEM VERSIONED": "system_versioned_table"}
SESSION = (
    "SET SESSION TRANSACTION READ ONLY",
    f"SET SESSION max_statement_time = {STATEMENT_TIMEOUT_MS // 1000}",
)
TOO_SLOW = 1969  # max_statement_time exceeded

# A literal, quoted as MariaDB writes one back: '' or \' inside.
LITERAL = re.compile(r"'(?:[^'\\]|\\.|'')*'")
# A table read: after `from` or a `join` — straight_join and left join
# included — past any opening parentheses, `schema`.`table`, a ` inside a
# name doubled. A column is never written so after either word.
READ = re.compile(r"(?:\bfrom|join)\s+[(\s]*`((?:[^`]|``)+)`\.`((?:[^`]|``)+)`", re.IGNORECASE)


def reads_from(definition: str) -> list[str]:
    """The tables and views a view's definition reads, each once, sorted —
    as MySQL's VIEW_TABLE_USAGE hands them. What a literal says is not
    read: `where note = 'from `a`.`b`'` names no table."""
    code = LITERAL.sub("''", definition)
    names = {
        f"{schema.replace('``', '`')}.{table.replace('``', '`')}"
        for schema, table in READ.findall(code)
    }
    return sorted(names)


class MariaDBConfig(MySQLConfig):
    pass


class MariaDBCredentials(MySQLCredentials):
    pass


@register_connector
class MariaDBConnector(MySQLConnector):
    manifest = ConnectorManifest(
        key=SourceKind.MARIADB,
        display_name="MariaDB",
        category=ConnectorCategory.DATA,
        auth_type="token",
        config_schema=MariaDBConfig,
        credentials_schema=MariaDBCredentials,
        capabilities=frozenset({C.SCHEMAS, C.TABLES}),
        listed_whole=frozenset({C.SCHEMAS, C.TABLES}),
    )

    session = SESSION
    tables_query = TABLES
    checks_query = CHECKS
    indexes_query = INDEXES
    kinds = KINDS
    too_slow = TOO_SLOW

    async def _view_sources(
        self, db: Any, schemas: list[str], tables: dict[tuple[str, str], dict[str, Any]]
    ) -> None:
        """Each view's `reads_from`, from its definition: there when the
        account may SELECT from the view, as MySQL's."""
        for table in tables.values():
            if table["kind"] == "view" and table["definition"]:
                table["reads_from"] = reads_from(str(table["definition"]))

    def _default(self, value: object) -> object:
        return None if value == "NULL" else value

    def _other_engine(self, version: str) -> str | None:
        return None if "MariaDB" in version else "MySQL"
