"""The extraction job (LEKA-354): after a pass, what the index says needs it.

The fake source of test_sync.py, a pass of it, then the job — against the
test database and a local object store. The fake connector's records get a
strategy of their own here (commits); its issues have none, and stay
`unsupported`.
"""

# ruff: noqa: F811 — the fixtures of test_sync are imported to be requested by name.
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from leka.connectors import Capability, Source, SourceKind
from leka.db import session_factory, workspace_scope
from leka.ingestion import ExtractedRecordRow, ExtractionStatus
from leka.ingestion.extraction import Extracted, MalformedPayloadError
from leka.ingestion.extraction import engine as engine_module
from leka.ingestion.extraction.contract import FailureCode
from leka.ingestion.extraction.job import EXTRACT_JOB, extract_source
from leka.ingestion.models import EXTRACTION_FAILURES
from leka.platform import LocalObjectStore, from_bytes
from tests import test_sync as sync_tests
from tests.test_sync import _index, _live_payloads, _sync, fake, source  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

FAKE = SourceKind.SLACK


def _commit(payload: dict[str, Any]) -> Extracted:
    if payload["n"] == 2:
        raise MalformedPayloadError("missing field 'title'")
    edited = " (edited)" if payload["edited"] else ""
    return Extracted(title=f"commit {payload['n']}{edited}")


@pytest.fixture(autouse=True)
def commits_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A strategy for the fake connector's commits, version 1."""
    _version(monkeypatch, 1)


def _version(monkeypatch: pytest.MonkeyPatch, version: int) -> None:
    monkeypatch.setitem(
        engine_module._STRATEGIES,
        (FAKE, Capability.COMMITS),
        engine_module.Strategy("fake.commits", version, lambda r: _commit(r.payload)),
    )


async def _rows(source: Source) -> dict[str, ExtractedRecordRow]:
    """The extraction rows, by the external id of their record."""
    commits = await _index(source, "commits")
    issues = await _index(source, "issues")
    by_id = {row.id: external_id for external_id, row in {**commits, **issues}.items()}
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(ExtractedRecordRow).where(ExtractedRecordRow.source_id == source.id)
            )
            return {by_id[row.source_record_id]: row for row in rows.scalars()}


async def test_a_pass_queues_the_extraction_of_what_it_stored(source: Source) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 2}

    await _sync(source)

    assert (EXTRACT_JOB, (str(source.workspace_id), str(source.id))) in sync_tests.queued_purges


async def test_every_record_gets_a_result_or_the_reason_it_has_none(source: Source) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 3, Capability.ISSUES: 1}
    await _sync(source)

    result = await extract_source(source.workspace_id, source.id)

    assert (result["extracted"], result["failed"]) == (2, 2)
    rows = await _rows(source)
    ok = rows["commits-0"]
    assert (ok.status, ok.extractor, ok.extractor_version) == (
        ExtractionStatus.EXTRACTED,
        "fake.commits",
        1,
    )
    assert ok.result is not None
    assert ok.result["title"] == "commit 0"
    provenance = ok.result["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["external_id"] == "commits-0"
    assert provenance["checksum"] == ok.checksum
    malformed = rows["commits-2"]
    assert (malformed.status, malformed.failure_code, malformed.result) == (
        ExtractionStatus.FAILED,
        "malformed",
        None,
    )
    assert malformed.message == "missing field 'title'"
    unsupported = rows["issues-0"]
    assert (unsupported.failure_code, unsupported.extractor) == ("unsupported", None)


async def test_a_second_run_finds_nothing_to_do(source: Source) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 2, Capability.ISSUES: 1}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)
    before = {k: v.updated_at for k, v in (await _rows(source)).items()}

    result = await extract_source(source.workspace_id, source.id)

    assert result == {
        "extracted": 0,
        "failed": 0,
        "passed_over": 0,
        "forgotten": 0,
        "secrets_taken_out": 0,
    }
    assert {k: v.updated_at for k, v in (await _rows(source)).items()} == before


async def test_a_record_changed_at_the_vendor_is_extracted_again(source: Source) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 2}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)
    sync_tests.SCRIPT.edited = {1}
    await _sync(source)

    result = await extract_source(source.workspace_id, source.id)

    assert result["extracted"] == 1
    row = (await _rows(source))["commits-1"]
    assert row.result is not None and row.result["title"] == "commit 1 (edited)"
    assert row.checksum == (await _index(source))["commits-1"].checksum


async def test_a_new_version_of_a_strategy_extracts_its_records_again(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 2, Capability.ISSUES: 1}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)
    _version(monkeypatch, 2)

    result = await extract_source(source.workspace_id, source.id)

    assert result["extracted"] == 2  # the commits; the issue has no strategy still
    assert (await _rows(source))["commits-0"].extractor_version == 2


async def test_a_record_deleted_at_the_vendor_loses_what_was_extracted(source: Source) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 2}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)
    sync_tests.SCRIPT.gone = {0}
    await _sync(source, full=True)

    result = await extract_source(source.workspace_id, source.id)

    assert result["forgotten"] == 1
    assert set(await _rows(source)) == {"commits-1"}


async def test_a_batch_gone_since_is_passed_over_and_read_next_time(
    source: Source, fake: LocalObjectStore
) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: 2}  # one batch of two
    await _sync(source)
    (batch,) = await _live_payloads(source)
    held = b"".join([chunk async for chunk in fake.get(batch.object_key)])
    await fake.delete(batch.object_key)  # a purge rewrote it, say

    result = await extract_source(source.workspace_id, source.id)

    assert (result["extracted"], result["passed_over"]) == (0, 2)
    await fake.put(batch.object_key, from_bytes(held), content_type="application/x-ndjson")
    assert (await extract_source(source.workspace_id, source.id))["extracted"] == 2


def test_the_table_knows_every_failure_code_the_contract_has() -> None:
    assert set(EXTRACTION_FAILURES) == {code.value for code in FailureCode}
