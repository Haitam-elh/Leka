"""PostgreSQL's schemas and tables, extracted for what comes after
(LEKA-349 → LEKA-354).

End to end: the payloads are the connector's own, read from the tests'
server — the schema tests/test_postgresql_connector.py makes, with a
foreign key, a check, a view — by a role that may read no row. What
matters: the name as a query writes it, the columns as a reader scans them,
and the tables a table is tied to as references.
"""

# ruff: noqa: F811 — the fixture of test_postgresql_connector is imported to be requested by name.
from __future__ import annotations

import pytest

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction import ExtractedRecord, FailureCode
from tests.test_extraction import _extract, _failure
from tests.test_postgresql_connector import (  # noqa: F401 — fixture
    Catalogue,
    _read,
    _reader,
    catalogue,
)

pytestmark = pytest.mark.integration

C = Capability
PG = SourceKind.POSTGRESQL


async def _tables(made: Catalogue) -> dict[str, ExtractedRecord]:
    records = await _read(_reader(made, schemas=[made.billing]), C.TABLES)
    found = {}
    for record in records:
        extracted = _extract(
            PG,
            C.TABLES,
            dict(record.payload),
            external_id=record.external_id,
            container=record.container,
        )
        found[extracted.title or ""] = extracted
    return found


async def test_a_schema_says_its_database_and_what_it_is_for(catalogue: Catalogue) -> None:
    [record] = await _read(_reader(catalogue, schemas=[catalogue.billing]), C.SCHEMAS)

    schema = _extract(PG, C.SCHEMAS, dict(record.payload), external_id=record.external_id)

    assert schema.title == catalogue.billing
    assert schema.content[0].text == "Invoices, and who pays them"
    assert [(r.role, r.kind, r.external_id) for r in schema.references] == [
        ("database", "database", catalogue.database)
    ]
    assert schema.extractor == "postgresql.schemas"


async def test_a_table_reads_as_its_columns_its_keys_and_what_it_points_to(
    catalogue: Catalogue,
) -> None:
    b = catalogue.billing

    tables = await _tables(catalogue)

    invoices = tables[f"{b}.invoices"]
    columns = next(c for c in invoices.content if c.role == "columns").text.splitlines()
    assert columns[0] == "id bigint NOT NULL PRIMARY KEY"
    assert columns[1] == f"customer_id bigint NOT NULL → {b}.customers(id)"
    assert columns[2] == "amount numeric(12,2)"
    assert columns[4].startswith("CHECK ((amount >= ")
    assert [(r.role, r.external_id) for r in invoices.references] == [
        ("schema", b),
        ("references", f"{b}.customers"),
    ]
    assert invoices.metadata["kind"] == "table"
    assert invoices.metadata["primary_key"] == ["id"]
    assert invoices.metadata["columns"] == ["id", "customer_id", "amount", "paid"]
    # Where it was read (LEKA-364): what makes it one table whichever
    # source reads it.
    assert invoices.signals == {"engine": "postgresql", "host": "db.acme.example", "port": 5432}
    assert invoices.metadata["database"] == catalogue.database
    assert invoices.provenance.container == b

    customers = tables[f"{b}.customers"]
    assert customers.content[0].text == "Who pays"
    assert "email text NOT NULL UNIQUE — Where invoices go" in customers.content[1].text


async def test_a_view_says_what_it_reads_and_how(catalogue: Catalogue) -> None:
    b = catalogue.billing

    unpaid = (await _tables(catalogue))[f"{b}.unpaid"]

    assert unpaid.metadata["kind"] == "view"
    assert "size_bytes" not in unpaid.metadata
    assert "NOT i.paid" in next(c for c in unpaid.content if c.role == "definition").text
    assert sorted(r.external_id or "" for r in unpaid.references if r.role == "reads") == [
        f"{b}.customers",
        f"{b}.invoices",
    ]


def test_a_table_without_its_schema_is_malformed() -> None:
    failure = _failure(PG, C.TABLES, {"name": "invoices", "columns": []})

    assert failure.code is FailureCode.MALFORMED
    assert "schema" in failure.message


def test_a_composite_key_is_listed_after_the_columns() -> None:
    payload = {
        "schema": "ops",
        "name": "shifts",
        "kind": "table",
        "columns": [
            {"name": "team", "type": "text", "nullable": False},
            {"name": "day", "type": "date", "nullable": False},
        ],
        "constraints": [
            {
                "type": "primary_key",
                "columns": ["team", "day"],
                "definition": "PRIMARY KEY (team, day)",
            }
        ],
    }

    shifts = _extract(PG, C.TABLES, payload)

    assert shifts.content[0].text.splitlines() == [
        "team text NOT NULL",
        "day date NOT NULL",
        "PRIMARY KEY (team, day)",
    ]
    assert shifts.metadata["primary_key"] == ["team", "day"]
