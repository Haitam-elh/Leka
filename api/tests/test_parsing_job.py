"""The parsing job (LEKA-355): after the extraction, what it says needs it.

The fake source of test_sync.py, a pass, the extraction, then the job —
against the test database. The fake connector's commits get a strategy that
writes "fix: commit <n>" with "Fixes PAY-<n>" in their message, so each
parses into a change type and a reference; its issues have no strategy, stay
`unsupported`, and are never parsed.
"""

# ruff: noqa: F811 — the fixtures of test_sync are imported to be requested by name.
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select, text

from leka.connectors import Capability, Source, SourceKind
from leka.db import session_factory, workspace_scope
from leka.ingestion import ExtractedRecordRow, ParsedRecordRow, ParseStatus
from leka.ingestion import sync as sync_module
from leka.ingestion.extraction import Content, Extracted, MalformedPayloadError
from leka.ingestion.extraction import engine as engine_module
from leka.ingestion.extraction import job as extraction_job
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.parsing import job as parsing_job
from leka.ingestion.parsing.job import PARSE_JOB, parse_source
from tests import test_sync as sync_tests
from tests.test_sync import _index, _sync, fake, source  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

queued: list[str] = []


def _commit(payload: dict[str, Any], *, broken: int | None = None) -> Extracted:
    if payload["n"] == broken:
        raise MalformedPayloadError("missing field 'title'")
    return Extracted(
        title=f"fix: commit {payload['n']}",
        content=[Content(role="message", format="text", text=f"Fixes PAY-{payload['n']}")],
    )


def _strategy(monkeypatch: pytest.MonkeyPatch, version: int, broken: int | None = None) -> None:
    monkeypatch.setitem(
        engine_module._STRATEGIES,
        (SourceKind.SLACK, Capability.COMMITS),
        engine_module.Strategy(
            "fake.commits", version, lambda r: _commit(r.payload, broken=broken)
        ),
    )


@pytest.fixture(autouse=True)
def pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """A strategy for the fake commits; what the jobs queue, captured."""
    _strategy(monkeypatch, 1)
    queued.clear()

    async def capture(job: str, *args: object, **kwargs: object) -> object:
        queued.append(job)
        return object()

    monkeypatch.setattr(extraction_job, "enqueue_job", capture)
    monkeypatch.setattr(parsing_job, "enqueue_job", capture)


async def _extracted(source: Source, **records: int) -> None:
    sync_tests.SCRIPT.records = {Capability(k): n for k, n in records.items()}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)


async def _rows(source: Source) -> dict[str, ParsedRecordRow]:
    """The parse rows, by the external id of their record."""
    ids = {row.id: external_id for external_id, row in (await _index(source)).items()}
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(ParsedRecordRow, ExtractedRecordRow.source_record_id)
                .join(
                    ExtractedRecordRow, ExtractedRecordRow.id == ParsedRecordRow.extracted_record_id
                )
                .where(ParsedRecordRow.source_id == source.id)
            )
            return {ids[record_id]: row for row, record_id in rows.all()}


async def test_the_extraction_queues_the_parsing(source: Source) -> None:
    await _extracted(source, commits=2)

    assert PARSE_JOB in queued


async def test_every_extracted_record_is_parsed_and_the_rest_is_not(source: Source) -> None:
    await _extracted(source, commits=2, issues=1)

    result = await parse_source(source.workspace_id, source.id)

    assert (result["parsed"], result["failed"]) == (2, 0)  # the issue was never extracted
    row = (await _rows(source))["commits-1"]
    assert (row.status, row.parser_version, row.extractor_version) == (ParseStatus.PARSED, 1, 1)
    assert row.result is not None
    facts = row.result["facts"]
    assert isinstance(facts, list)
    assert any(f["type"] == "change_type" and f["value"] == "fix" for f in facts)
    assert any(f["type"] == "references" and f["target"]["key"] == "PAY-1" for f in facts)


async def test_a_second_run_finds_nothing_to_do(source: Source) -> None:
    await _extracted(source, commits=2)
    await parse_source(source.workspace_id, source.id)

    assert await parse_source(source.workspace_id, source.id) == {
        "parsed": 0,
        "failed": 0,
        "forgotten": 0,
    }


async def test_a_record_extracted_again_is_parsed_again(source: Source) -> None:
    await _extracted(source, commits=2)
    await parse_source(source.workspace_id, source.id)
    sync_tests.SCRIPT.edited = {0}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)

    assert (await parse_source(source.workspace_id, source.id))["parsed"] == 1


async def test_a_new_parser_version_parses_everything_again(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _extracted(source, commits=2)
    await parse_source(source.workspace_id, source.id)
    monkeypatch.setattr(parsing_job, "PARSER_VERSION", 2)

    assert (await parse_source(source.workspace_id, source.id))["parsed"] == 2
    assert {row.parser_version for row in (await _rows(source)).values()} == {2}


async def test_only_parsing_to_do_is_queued_by_the_pass(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _extracted(source, commits=2)
    await parse_source(source.workspace_id, source.id)
    sync_tests.queued_purges.clear()
    monkeypatch.setattr(sync_module, "PARSER_VERSION", 2)

    await _sync(source)

    jobs = [job for job, _ in sync_tests.queued_purges]
    assert PARSE_JOB in jobs
    assert extraction_job.EXTRACT_JOB not in jobs


async def test_an_extraction_that_now_fails_loses_its_parse(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _extracted(source, commits=2)
    await parse_source(source.workspace_id, source.id)
    _strategy(monkeypatch, 2, broken=0)
    await extract_source(source.workspace_id, source.id)

    result = await parse_source(source.workspace_id, source.id)

    assert result["forgotten"] == 1
    assert set(await _rows(source)) == {"commits-1"}


async def test_a_record_deleted_at_the_vendor_loses_its_parse(source: Source) -> None:
    await _extracted(source, commits=2)
    await parse_source(source.workspace_id, source.id)
    sync_tests.SCRIPT.gone = {0}
    await _sync(source, full=True)

    await extract_source(source.workspace_id, source.id)  # forgets the extraction: cascade

    assert set(await _rows(source)) == {"commits-1"}


async def test_a_stored_extraction_that_no_longer_reads_is_a_failure(source: Source) -> None:
    await _extracted(source, commits=1)
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE extracted_records SET result = '{\"x\": 1}' WHERE source_id = :s"),
                {"s": source.id},
            )
            await session.commit()

    result = await parse_source(source.workspace_id, source.id)

    assert result["failed"] == 1
    row = (await _rows(source))["commits-0"]
    assert (row.status, row.failure_code, row.result) == (ParseStatus.FAILED, "malformed", None)
    assert row.message is not None and row.message.startswith("not an extracted record")
