"""The normalisation job (LEKA-356): after the parsing, what it says needs it.

The fake source of test_sync.py through the whole chain — a pass, the
extraction, the parsing, then this job — against the test database.

The fake connector is no vendor the rules know: left alone, its records are
`unsupported`, and one test keeps them so. The others give the job a rule
of their own (`rules`), which makes a candidate of each commit — and an
`invalid` one of commit 2 — so what is tested is the job: what it reads,
saves, forgets and reads again. The rules themselves are
tests/test_normalisation.py's.
"""

# ruff: noqa: F811 — the fixtures of test_sync and test_parsing_job are imported by name.
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from leka.background import Event
from leka.connectors import Capability, Mapping, Source, SourceService, SourceSettings
from leka.db import session_factory, workspace_scope
from leka.ingestion import (
    ExtractedRecordRow,
    NormalisationStatus,
    NormalisedEntity,
    NormalisedRecordRow,
    NormalisedRelationship,
    ParsedRecordRow,
)
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion.extraction import ExtractedRecord
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.normalisation import (
    NORMALISER_VERSION,
    NormalisationFailure,
    NormalisationFailureCode,
    Normalised,
    NormalisedRecord,
)
from leka.ingestion.normalisation import engine as normalisation_engine
from leka.ingestion.normalisation.job import NORMALISE_JOB, normalise_source
from leka.ingestion.parsing import ParsedRecord
from leka.ingestion.parsing import engine as parsing_engine
from leka.ingestion.parsing.job import PARSE_JOB, parse_source
from tests import test_sync as sync_tests
from tests.test_parsing_job import pipeline, queued  # noqa: F401 — fixture
from tests.test_sync import _index, _sync, fake, source  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration


def _rule(extracted: object, parsed: object, mapping: object = None) -> Normalised:
    """A candidate per fake commit — `invalid` for commit 2."""
    record = ExtractedRecord.model_validate(extracted)
    parse = ParsedRecord.model_validate(parsed)
    provenance = record.provenance
    if provenance.external_id == "commits-2":
        return NormalisationFailure(
            provenance=provenance,
            normaliser_version=NORMALISER_VERSION,
            code=NormalisationFailureCode.INVALID,
            message="no sha: the extraction has no metadata.sha",
        )
    key = f"fake/{provenance.external_id}"
    return NormalisedRecord(
        provenance=provenance,
        extractor_version=record.extractor_version,
        parser_version=parse.parser_version,
        normaliser_version=NORMALISER_VERSION,
        entity=NormalisedEntity(
            type="commit",
            key=key,
            external_id=provenance.external_id,
            source_id=provenance.source_id,
            name=str(record.title),
            observed_at=provenance.fetched_at,
        ),
        relationships=[
            NormalisedRelationship(
                type="resolves", from_key=key, to_key="ticket:PAY-1", source_id=provenance.source_id
            )
        ],
        diagnostics=["unknown state: kept as the vendor wrote it"]
        if provenance.external_id == "commits-1"
        else [],
    )


@pytest.fixture
def rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(normalisation_engine, "normalise_stored", _rule)


async def _parsed(source: Source, commits: int) -> None:
    sync_tests.SCRIPT.records = {Capability.COMMITS: commits}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)
    await parse_source(source.workspace_id, source.id)


async def _rows(source: Source) -> dict[str, NormalisedRecordRow]:
    """The normalisation rows, by the external id of their record."""
    ids = {row.id: external_id for external_id, row in (await _index(source)).items()}
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(NormalisedRecordRow, ExtractedRecordRow.source_record_id)
                .join(ParsedRecordRow, ParsedRecordRow.id == NormalisedRecordRow.parsed_record_id)
                .join(
                    ExtractedRecordRow, ExtractedRecordRow.id == ParsedRecordRow.extracted_record_id
                )
                .where(NormalisedRecordRow.source_id == source.id)
            )
            return {ids[record_id]: row for row, record_id in rows.all()}


async def test_the_parsing_queues_the_normalisation(source: Source) -> None:
    await _parsed(source, 1)

    assert NORMALISE_JOB in queued()


async def test_a_vendor_no_rule_knows_is_unsupported_record_by_record(source: Source) -> None:
    await _parsed(source, 2)

    result = await normalise_source(source.workspace_id, source.id)

    assert (result["normalised"], result["failed"]) == (0, 2)
    row = (await _rows(source))["commits-0"]
    assert (row.status, row.failure_code, row.entity_key) == (
        NormalisationStatus.FAILED,
        "unsupported",
        None,
    )


@pytest.mark.usefixtures("rules")
async def test_every_parse_gets_its_candidates_or_the_reason_it_has_none(source: Source) -> None:
    await _parsed(source, 3)

    result = await normalise_source(source.workspace_id, source.id)

    assert (result["normalised"], result["failed"]) == (2, 1)
    rows = await _rows(source)
    ok = rows["commits-0"]
    assert (ok.status, ok.entity_type, ok.entity_key) == (
        NormalisationStatus.NORMALISED,
        "commit",
        "fake/commits-0",
    )
    assert ok.result is not None
    provenance = ok.result["provenance"]
    assert isinstance(provenance, dict) and provenance["external_id"] == "commits-0"
    assert (ok.normaliser_version, ok.parser_version) == (
        NORMALISER_VERSION,
        parsing_engine.PARSER_VERSION,
    )
    bad = rows["commits-2"]
    assert (bad.failure_code, bad.message) == (
        "invalid",
        "no sha: the extraction has no metadata.sha",
    )


@pytest.mark.usefixtures("rules")
async def test_a_second_run_finds_nothing_to_do(source: Source) -> None:
    await _parsed(source, 2)
    await normalise_source(source.workspace_id, source.id)

    assert await normalise_source(source.workspace_id, source.id) == {
        "normalised": 0,
        "failed": 0,
        "forgotten": 0,
    }


@pytest.mark.usefixtures("rules")
async def test_a_record_parsed_again_is_normalised_again(source: Source) -> None:
    await _parsed(source, 2)
    await normalise_source(source.workspace_id, source.id)
    sync_tests.SCRIPT.edited = {0}
    await _sync(source)
    await extract_source(source.workspace_id, source.id)
    await parse_source(source.workspace_id, source.id)

    assert (await normalise_source(source.workspace_id, source.id))["normalised"] == 1


@pytest.mark.usefixtures("rules")
async def test_new_rules_normalise_everything_again(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _parsed(source, 2)
    await normalise_source(source.workspace_id, source.id)
    monkeypatch.setattr(normalisation_engine, "NORMALISER_VERSION", NORMALISER_VERSION + 1)

    assert (await normalise_source(source.workspace_id, source.id))["normalised"] == 2
    assert {row.normaliser_version for row in (await _rows(source)).values()} == {
        NORMALISER_VERSION + 1
    }


@pytest.mark.usefixtures("rules")
async def test_only_normalisation_to_do_is_queued_by_the_pass(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _parsed(source, 1)
    await normalise_source(source.workspace_id, source.id)
    sync_tests.queued_purges.clear()
    monkeypatch.setattr(normalisation_engine, "NORMALISER_VERSION", NORMALISER_VERSION + 1)

    await _sync(source)

    jobs = [job for job, _ in sync_tests.queued_purges]
    assert NORMALISE_JOB in jobs
    assert PARSE_JOB not in jobs


@pytest.mark.usefixtures("rules")
async def test_a_parse_that_now_fails_loses_its_candidates(
    source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _parsed(source, 2)
    await normalise_source(source.workspace_id, source.id)
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE extracted_records SET result = '{\"x\": 1}' "
                    "WHERE source_id = :s AND kind = 'commits'"
                    " AND source_record_id IN (SELECT id FROM source_records"
                    " WHERE external_id = 'commits-0')"
                ),
                {"s": source.id},
            )
            await session.commit()
    monkeypatch.setattr(parsing_engine, "PARSER_VERSION", parsing_engine.PARSER_VERSION + 1)
    await parse_source(source.workspace_id, source.id)  # commits-0 now fails to parse

    result = await normalise_source(source.workspace_id, source.id)

    assert result["forgotten"] == 1
    assert set(await _rows(source)) == {"commits-1"}


@pytest.mark.usefixtures("rules")
async def test_a_record_deleted_at_the_vendor_loses_its_candidates(source: Source) -> None:
    await _parsed(source, 2)
    await normalise_source(source.workspace_id, source.id)
    sync_tests.SCRIPT.gone = {0}
    await _sync(source, full=True)

    await extract_source(source.workspace_id, source.id)  # cascade: parse, candidates

    assert set(await _rows(source)) == {"commits-1"}


# ── a new mapping (LEKA-351) ─────────────────────────────────────────────────


async def _save_mapping(source: Source, mapping: Mapping) -> None:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            service = SourceService(session, source.workspace_id, actor_user_id=None)
            await service.save_settings(
                await service.get(source.id), SourceSettings(mapping=mapping)
            )
            await session.commit()


@pytest.mark.usefixtures("rules")
async def test_a_new_mapping_normalises_the_source_again(source: Source) -> None:
    await _parsed(source, 2)
    await normalise_source(source.workspace_id, source.id)
    assert {row.settings_version for row in (await _rows(source)).values()} == {0}

    await _save_mapping(source, Mapping(states={"frozen": "closed"}))
    result = await normalise_source(source.workspace_id, source.id)

    assert result["normalised"] == 2
    assert {row.settings_version for row in (await _rows(source)).values()} == {1}


async def test_a_mapping_change_queues_the_normalisation_once_committed(source: Source) -> None:
    await _parsed(source, 1)
    await normalise_source(source.workspace_id, source.id)
    sync_tests.queued_purges.clear()

    await _save_mapping(source, Mapping(states={"frozen": "closed"}))
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(Event).where(Event.type == "source.mapping_changed")
            )
            (event,) = [e for e in rows.scalars() if e.payload["source_id"] == str(source.id)]

    assert await pipeline_module._advance_for_event(event.id) == "normalisation"
    assert NORMALISE_JOB in queued()
