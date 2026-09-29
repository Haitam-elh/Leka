"""Validation, the job, the quarantine and the API (LEKA-358), against the database.

A source's normalised records as normalisation leaves them — a good pull
request, a doubtful one, a broken one — validated by the stage. What these
protect: every record gets its verdict, traced to its source and to the run
that made it; a broken record is quarantined and LEFT OUT of entity
resolution while the others go on; corrected, it comes back; the stage runs
when there is something to validate and not otherwise; normalisation hands
over to it, and it to resolution; members read a source's quality, never
another workspace's.

The rules themselves are tests/test_validation.py's.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.db import session_factory, workspace_scope
from leka.ingestion import (
    ProcessingRun,
    ProcessingStage,
    ResolvedEntity,
    ValidatedRecordRow,
)
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion.repository import ProcessingRunRepository
from leka.ingestion.resolution.job import RESOLVE_JOB, resolve_workspace
from leka.ingestion.validation import rules
from leka.ingestion.validation.job import VALIDATE_JOB, validate_source
from tests.conftest import FakeIdentity
from tests.test_resolution_job import _source
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures
from tests.test_validation import PR, SARA, person, pull_request, record

pytestmark = pytest.mark.integration

API = "/api/v1/ingestion"
NOW = datetime.now(UTC)


async def _stored(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    result: dict[str, Any],
    *,
    seen: datetime = NOW,
    status: str = "normalised",
) -> uuid.UUID:
    """A normalised record as normalisation leaves it, and the rows it came
    from — its source record last seen at `seen`."""
    key = result["entity"]["key"] if isinstance(result.get("entity"), dict) else str(uuid.uuid4())
    checksum = hashlib.sha256(key.encode() + source_id.bytes + uuid.uuid4().bytes).hexdigest()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            values = {"w": workspace_id, "s": source_id, "c": checksum, "at": seen}
            found = await session.scalar(
                text(
                    "INSERT INTO source_records (workspace_id, source_id, kind, external_id, "
                    "checksum, first_seen_at, last_seen_at) VALUES (:w, :s, 'issues', :e, :c, "
                    ":at, :at) RETURNING id"
                ),
                {**values, "e": f"{key}-{checksum[:6]}"},
            )
            extracted = await session.scalar(
                text(
                    "INSERT INTO extracted_records (workspace_id, source_id, source_record_id, "
                    "kind, status, checksum, result, extracted_at) VALUES (:w, :s, :r, 'issues', "
                    "'extracted', :c, '{}', :at) RETURNING id"
                ),
                {**values, "r": found},
            )
            parsed = await session.scalar(
                text(
                    "INSERT INTO parsed_records (workspace_id, source_id, extracted_record_id, "
                    "kind, status, checksum, parser_version, result, parsed_at) VALUES (:w, :s, "
                    ":x, 'issues', 'parsed', :c, 1, '{}', :at) RETURNING id"
                ),
                {**values, "x": extracted},
            )
            normalised = await session.scalar(
                text(
                    "INSERT INTO normalised_records (workspace_id, source_id, parsed_record_id, "
                    "kind, status, checksum, parser_version, normaliser_version, entity_type, "
                    "entity_key, result, failure_code, normalised_at) VALUES (:w, :s, :p, "
                    "'issues', :st, :c, 1, 1, :t, :k, CAST(:j AS jsonb), :f, now()) RETURNING id"
                ),
                {
                    **values,
                    "p": parsed,
                    "st": status,
                    "t": result.get("entity", {}).get("type") if status == "normalised" else None,
                    "k": key if status == "normalised" else None,
                    "j": json.dumps(result) if status == "normalised" else None,
                    "f": None if status == "normalised" else "invalid",
                },
            )
            await session.commit()
            return normalised  # type: ignore[no-any-return]


async def _validated(workspace_id: uuid.UUID) -> dict[str | None, ValidatedRecordRow]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(ValidatedRecordRow))
            return {row.entity_key: row for row in rows.scalars()}


async def _helpdesk(workspace_id: uuid.UUID) -> uuid.UUID:
    """A source whose records are one good, one doubtful, one broken."""
    source = await _source(workspace_id, "GitHub")
    await _stored(workspace_id, source, pull_request())
    await _stored(
        workspace_id,
        source,
        record(
            "issue",
            "github.com/acme/api#7",
            related=[person(SARA)],
            relationships=[("authored_by", "github.com/acme/api#7", SARA)],
            url="https://github.com/acme/api/issues/7",
            state="open",
            priority="p0",
            created_at="2026-09-20T08:00:00Z",
            updated_at="2026-09-21T08:00:00Z",
        ),
    )
    await _stored(
        workspace_id,
        source,
        record("issue", "github.com/acme/api#8", updated_at="yesterday", state="open"),
    )
    return source


# ── the job ──────────────────────────────────────────────────────────────────


async def test_every_record_gets_its_verdict_traced_to_its_source_and_run(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    source = await _helpdesk(workspace)

    counts = await validate_source(workspace, source)

    assert (counts["valid"], counts["warning"], counts["quarantined"]) == (1, 1, 1)
    rows = await _validated(workspace)
    good, doubtful, broken = rows[PR], rows["github.com/acme/api#7"], rows["github.com/acme/api#8"]
    assert (good.status, good.quality, good.issues) == ("valid", 1.0, [])
    assert doubtful.status == "warning"
    assert [i["code"] for i in doubtful.issues] == ["unknown_priority"]
    assert broken.status == "quarantined"
    assert broken.quality == 0.0
    [issue] = [i for i in broken.issues if i["severity"] == "error"]
    assert (issue["code"], issue["field"]) == ("bad_date", "entity.attributes.updated_at")
    assert "yesterday" not in json.dumps(broken.issues)
    with workspace_scope(workspace):
        async with session_factory() as session:
            [run] = (
                await session.execute(
                    select(ProcessingRun).where(ProcessingRun.stage == ProcessingStage.VALIDATION)
                )
            ).scalars()
    assert {row.run_id for row in rows.values()} == {run.id}
    assert {row.source_id for row in rows.values()} == {source}
    assert (run.counts["quarantined"], run.versions) == (1, {"validator": rules.VALIDATOR_VERSION})


async def test_a_quarantined_record_is_left_out_of_resolution_the_others_go_on(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    source = await _helpdesk(workspace)
    await validate_source(workspace, source)

    await resolve_workspace(workspace)

    with workspace_scope(workspace):
        async with session_factory() as session:
            entities = {e.key: e for e in (await session.execute(select(ResolvedEntity))).scalars()}
    assert "github.com/acme/api#8" not in entities
    assert entities[PR].quality == 1.0
    assert entities["github.com/acme/api#7"].quality is not None
    assert entities["github.com/acme/api#7"].quality < 1.0
    assert entities[SARA].quality is None  # only named by others: no record of its own


async def test_a_corrected_record_comes_out_of_quarantine(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    source = await _helpdesk(workspace)
    await validate_source(workspace, source)
    rows = await _validated(workspace)
    fixed = record(
        "issue",
        "github.com/acme/api#8",
        updated_at="2026-09-29T08:00:00Z",
        state="open",
    )
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE normalised_records SET result = CAST(:j AS jsonb), "
                    "normalised_at = now() WHERE id = :id"
                ),
                {"j": json.dumps(fixed), "id": rows["github.com/acme/api#8"].normalised_record_id},
            )
            await session.commit()

    counts = await validate_source(workspace, source)

    assert (counts["valid"] + counts["warning"], counts["quarantined"]) == (1, 0)
    assert (await _validated(workspace))["github.com/acme/api#8"].status == "valid"


async def test_nothing_new_is_nothing_to_validate_new_rules_are(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    source = await _helpdesk(workspace)
    await validate_source(workspace, source)

    again = await validate_source(workspace, source)
    from leka.ingestion.validation import job

    monkeypatch.setattr(job, "VALIDATOR_VERSION", rules.VALIDATOR_VERSION + 1)
    renewed = await validate_source(workspace, source)

    assert sum(again[k] for k in ("valid", "warning", "quarantined")) == 0
    assert sum(renewed[k] for k in ("valid", "warning", "quarantined")) == 3


async def test_a_record_that_fails_normalisation_since_loses_its_verdict(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    source = await _helpdesk(workspace)
    await validate_source(workspace, source)
    rows = await _validated(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE normalised_records SET status = 'failed', result = NULL, "
                    "entity_key = NULL, failure_code = 'invalid' WHERE id = :id"
                ),
                {"id": rows[PR].normalised_record_id},
            )
            await session.commit()

    counts = await validate_source(workspace, source)

    assert counts["forgotten"] == 1
    assert PR not in await _validated(workspace)


async def test_two_records_one_source_makes_one_are_flagged(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    source = await _source(workspace, "GitHub")
    await _stored(workspace, source, pull_request())
    await _stored(workspace, source, pull_request())

    await validate_source(workspace, source)

    with workspace_scope(workspace):
        async with session_factory() as session:
            rows = (await session.execute(select(ValidatedRecordRow))).scalars().all()
    assert len(rows) == 2
    assert all(any(i["code"] == "duplicate_in_source" for i in r.issues) for r in rows)


async def test_a_record_not_seen_for_weeks_is_stale(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    source = await _source(workspace, "GitHub")
    await _stored(workspace, source, pull_request(), seen=NOW - timedelta(days=19))

    await validate_source(workspace, source)

    row = (await _validated(workspace))[PR]
    assert (row.status, [i["code"] for i in row.issues]) == ("warning", ["stale"])
    assert 0.4 < row.freshness < 0.6


async def test_normalisation_hands_over_to_validation_and_validation_to_resolution(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    source = await _helpdesk(workspace)
    queued: list[str] = []

    async def capture(job: str, *args: object, **kwargs: Any) -> object:
        queued.append(job)
        return object()

    monkeypatch.setattr(pipeline_module, "enqueue_job", capture)
    with workspace_scope(workspace):
        async with session_factory() as session:
            from leka.connectors import Source

            found = await session.get(Source, source)
            assert found is not None
            after = await pipeline_module.advance(
                session, workspace, found, after=ProcessingStage.NORMALISATION
            )
    assert (after, queued) == (ProcessingStage.VALIDATION, [VALIDATE_JOB])

    await validate_source(workspace, source)  # its own advance, at its end

    assert queued == [VALIDATE_JOB, RESOLVE_JOB]


async def test_a_reprocess_of_validation_drops_its_verdicts(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    source = await _helpdesk(workspace)
    await validate_source(workspace, source)

    with workspace_scope(workspace):
        async with session_factory() as session:
            removed = await ProcessingRunRepository(session, workspace).delete_rows(
                source, ProcessingStage.VALIDATION
            )
            await session.commit()

    assert removed == 3
    assert await _validated(workspace) == {}


# ── the API ──────────────────────────────────────────────────────────────────


async def test_members_read_what_a_source_s_records_are_worth(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    source = await _helpdesk(workspace)
    await validate_source(workspace, source)
    _as(identity, acme, "member")

    read = (await client.get(f"{API}/sources/{source}/validation")).json()
    overview = (await client.get(f"{API}/quality")).json()

    assert (read["valid"], read["warning"], read["quarantined"]) == (1, 1, 1)
    assert read["scores"]["quality"] is not None
    assert 0 < read["scores"]["quality"] < 1
    codes = {i["code"]: i for i in read["issues"]}
    assert codes["bad_date"]["severity"] == "error"
    assert codes["bad_date"]["records"] == 1
    assert codes["unknown_priority"]["remediation"].startswith("Donnez à cette priorité")
    [quarantined] = read["quarantined_records"]
    assert quarantined["entity_key"] == "github.com/acme/api#8"
    assert [(line["source_id"], line["quarantined"]) for line in overview] == [(str(source), 1)]


async def test_another_workspace_s_quality_is_not_read(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    source = await _helpdesk(acme["acme"])
    await validate_source(acme["acme"], source)
    _as(identity, acme, "other_admin")

    assert (await client.get(f"{API}/sources/{source}/validation")).status_code == 404
    assert (await client.get(f"{API}/quality")).json() == []
