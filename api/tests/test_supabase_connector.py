"""The Supabase connector: PostgreSQL's, under Supabase's name (LEKA-349).

What is Supabase's own is tested here — the name, the defaults, the
settings. What it reads and how is the PostgreSQL connector's, tested in
tests/test_postgresql_connector.py; one pass here, against the same real
server and the same read-only role, shows the Supabase source goes the
same way, to the same extraction.
"""

# ruff: noqa: F811 — the fixture of test_postgresql_connector is imported to be requested by name.
from __future__ import annotations

import uuid

import asyncpg
import pytest
from pydantic import SecretStr, ValidationError

from leka.connectors import Capability, ConnectorCategory, SourceKind, manifests
from leka.connectors.supabase import SupabaseConfig, SupabaseConnector, SupabaseCredentials
from leka.ingestion.extraction import ExtractedRecord, extract
from tests.test_postgresql_connector import SERVER, Catalogue, catalogue  # noqa: F401 — fixture

pytestmark = pytest.mark.integration

C = Capability
POOLER = "aws-0-eu-west-3.pooler.supabase.com"


def test_its_name_and_defaults_are_supabase_s() -> None:
    manifest = next(m for m in manifests() if m.display_name == "Supabase")
    config = SupabaseConfig(host=POOLER)

    assert manifest.key is SourceKind.SUPABASE
    assert manifest.category is ConnectorCategory.DATA
    assert manifest.capabilities == manifest.listed_whole == {C.SCHEMAS, C.TABLES}
    assert (config.host, config.port, config.database) == (POOLER, 5432, "postgres")


@pytest.mark.parametrize("host", ["10.0.0.5", "127.0.0.1", "[::1]", "db.x.supabase.co/x"])
def test_a_host_that_cannot_work_is_refused(host: str) -> None:
    with pytest.raises(ValidationError):
        SupabaseConfig(host=host)


async def test_a_project_is_read_and_extracted_as_postgresql_is(catalogue: Catalogue) -> None:
    connector = SupabaseConnector(
        SupabaseConfig(host=POOLER, database=catalogue.database, schemas=[catalogue.billing]),
        SupabaseCredentials(username=catalogue.reader, password=SecretStr(catalogue.password)),
    )

    async def local() -> asyncpg.Connection:
        return await asyncpg.connect(
            host=SERVER.hostname,
            port=SERVER.port or 5432,
            user=catalogue.reader,
            password=catalogue.password,
            database=catalogue.database,
        )

    connector._open = local  # type: ignore[method-assign]

    tested = await connector.test_connection()
    records = [r async for r in connector.iter_resources(C.TABLES)]

    assert tested.account == f"{catalogue.reader}@{POOLER}"
    invoices = next(r for r in records if r.external_id == f"{catalogue.billing}.invoices")
    found = extract(invoices, source_id=uuid.uuid4(), source_kind=SourceKind.SUPABASE)
    assert isinstance(found, ExtractedRecord)
    assert found.extractor == "postgresql.tables"
    assert found.metadata["primary_key"] == ["id"]
