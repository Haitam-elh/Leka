"""What the database connectors share (LEKA-349): PostgreSQL's and MySQL's
catalogues are read the same way, within the same bounds, and handed over
in the same shape — so one extraction reads both (extraction/data.py).

A table's payload, whichever the engine:

    schema, name, kind          "billing", "invoices", "table" | "view" | …
    comment, owner              None where the engine has none
    estimated_rows, size_bytes  the engine's estimates, rounded (below)
    definition                  a view's, when the engine shows it
    columns                     [{name, type, nullable, default, comment}]
    constraints                 [{name, type, columns, definition,
                                  references: {schema, table, columns}}]
    indexes                     [{name, definition, unique, primary}]
    reads_from                  ["schema.table", …] — what a view reads

`type` of a constraint is primary_key, unique, foreign_key or check.
"""

from __future__ import annotations

from leka.connectors import network
from leka.connectors.errors import ConnectorError, DiagnosticCode, diagnose

CONNECT_TIMEOUT = 10.0  # seconds
STATEMENT_TIMEOUT_MS = 15_000
MAX_SCOPE_OPTIONS = 1000
# A pass, all schemas together. Beyond it, the pass fails and says so: a
# list read whole and cut would mark the rest gone.
MAX_TABLES = 20_000
# A name, or a literal address (an IPv6 one in brackets or not).
HOST = r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$|^\[?[0-9A-Fa-f:.]+\]?$"


def public_host(value: str) -> str:
    """The host as typed, tidied — refused at once if it is plainly not
    public. A name is checked when connecting (network.public_address)."""
    host = value.strip().lower()
    if network.obviously_private(host):
        msg = f"{value!r} is not a public address"
        raise ValueError(msg)
    return host


def rounded(number: int | None) -> int | None:
    """12 345 678 → 12 000 000: the order of a table, not its last write.

    Row counts and sizes move with every write; kept to two significant
    figures, a pass that changed no schema changes no checksum, and writes
    nothing."""
    if not number or number < 100:
        return number
    return int(float(f"{number:.2g}"))


def schema_names(value: list[str] | None, longest: int) -> list[str] | None:
    """The scope's schemas, trimmed and once each; a name the engine could
    not have is refused."""
    if value is None:
        return None
    names = [name.strip() for name in value]
    for name in names:
        if not name or len(name) > longest or "\x00" in name:
            msg = f"{name!r} is not a schema name"
            raise ValueError(msg)
    return list(dict.fromkeys(names))


def too_many_tables() -> ConnectorError:
    most = f"{MAX_TABLES:,}".replace(",", "\u202f")  # 20 000, as French writes it
    return diagnose(
        DiagnosticCode.CONFIG_INVALID,
        message=f"Plus de {most} tables et vues dans le périmètre : choisissez les "
        "schémas à décrire.",
    )
