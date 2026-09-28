"""End to end (LEKA-349): a PostgreSQL database, from its catalogue to
extracted records.

The real connector, the real service, the real pass and the real
extraction, against the tests' server: the schema and the read-only role
tests/test_postgresql_connector.py makes. Only the connection is local —
no TLS, no address check — as in the connector's own tests.

What must hold: a role with CONNECT and USAGE, and no SELECT, is enough
for the whole path; what it cannot use is never read; a second pass over an
unchanged schema writes nothing; every record extracts.
"""

# ruff: noqa: F811 — the fixture of test_postgresql_connector is imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import select, text

from leka.connectors import Capability, Source, SourceKind, SourceService
from leka.connectors.postgresql import PostgreSQLConnector
from leka.connectors.postgresql import connector as pg
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion import sync as sync_module
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.models import SourceRecord
from leka.ingestion.sync import sync_source
from leka.platform import LocalObjectStore
from tests.test_postgresql_connector import SERVER, Catalogue, catalogue  # noqa: F401 — fixture

pytestmark = pytest.mark.integration

C = Capability


@pytest.fixture(autouse=True)
def local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """The tests' server in place of a public one; a local store; the jobs
    a pass queues captured, not queued."""

    async def open_local(self: PostgreSQLConnector) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=SERVER.hostname,
            port=SERVER.port or 5432,
            user=self.credentials.username,
            password=self.credentials.password.get_secret_value(),
            database=self.config.database,
            server_settings=pg.SESSION,
        )

    monkeypatch.setattr(PostgreSQLConnector, "_open", open_local)
    from leka.platform import storage

    monkeypatch.setattr(storage, "_store", LocalObjectStore(tmp_path))

    async def capture(job: str, *args: object, **kwargs: object) -> object:
        return object()

    monkeypatch.setattr(sync_module, "enqueue_job", capture)
    monkeypatch.setattr(pipeline_module, "enqueue_job", capture)
    yield


@pytest.fixture
async def source(catalogue: Catalogue) -> AsyncIterator[Source]:
    with system_scope():
        async with session_factory() as session:
            workspace_id: uuid.UUID = (
                await session.execute(
                    text("INSERT INTO workspaces (name, slug) VALUES ('PG', :s) RETURNING id"),
                    {"s": f"pg-{uuid.uuid4().hex[:10]}"},
                )
            ).scalar_one()
            await session.commit()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = SourceService(session, workspace_id, actor_user_id=None)
            created = await service.create(
                SourceKind.POSTGRESQL,
                "Billing",
                {"host": "db.acme.example", "database": catalogue.database},
                {"username": catalogue.reader, "password": catalogue.password},
            )
            await service.test(created)
            await service.activate(created)
            await session.commit()
            yield created
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace_id})
            await session.commit()


async def _index(source: Source) -> dict[str, SourceRecord]:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(SourceRecord).where(SourceRecord.source_id == source.id)
            )
            return {f"{row.kind}:{row.external_id}": row for row in rows.scalars()}


async def test_a_database_goes_from_its_catalogue_to_extracted_records(
    source: Source, catalogue: Catalogue
) -> None:
    b = catalogue.billing
    assert sorted(source.capabilities) == ["schemas", "tables"]

    report = await sync_source(source.workspace_id, source.id, full=True)

    assert report.status == "succeeded", report.error
    index = await _index(source)
    ours = {key for key in index if key.split(":", 1)[1].split(".")[0] == b}
    assert ours == {
        f"schemas:{b}",
        *(f"tables:{b}.{name}" for name in ("customers", "invoices", "unpaid", "totals", "events")),
    }
    assert not [key for key in index if catalogue.secret in key]

    await sync_source(source.workspace_id, source.id, full=True)

    # Unchanged, not written again. (The server's other schemas — LEKA's
    # own, here — change under the pass: the pass writes to them.)
    again = await _index(source)
    assert {k: again[k].payload_key for k in ours} == {k: index[k].payload_key for k in ours}

    extracted = await extract_source(source.workspace_id, source.id)

    # Every table read — ours, and LEKA's own schema beside them, a real
    # one — extracts.
    assert extracted["extracted"] == len(index) > len(ours)
    assert extracted["failed"] == 0
