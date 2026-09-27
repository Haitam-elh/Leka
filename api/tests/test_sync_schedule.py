"""Starting a sync: the schedule, the activation, the "sync now" (LEKA-352).

What these protect: a switched-on source is read without anyone asking — at
once when it is activated, then when it has not been tried for an hour —
never twice at a time, never while switched off; and the API lets an admin
ask for a pass and anyone read how far each source has been read.

The queue itself is not here (test_background_e2e.py is): what is asserted
is what would have been enqueued, captured where `enqueue_job` is called.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.background import Event, JobQueue, JobRunRepository
from leka.connectors import Source, SourceStatus
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import SourceSync
from leka.ingestion import sync as sync_module
from tests.conftest import FakeIdentity, error_code
from tests.test_sources_api import _as, _create, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1"


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every pass that would have been put on the queue, instead of the queue."""
    calls: list[dict[str, Any]] = []
    active: set[str] = set()

    async def fake_enqueue_job(job: str, *args: object, **kwargs: Any) -> object | None:
        key = kwargs["concurrency_key"]
        if key in active:
            return None
        active.add(key)
        calls.append({"job": job, "args": args, **kwargs})
        return object()

    monkeypatch.setattr(sync_module, "enqueue_job", fake_enqueue_job)
    return calls


async def _activated(client: AsyncClient) -> dict[str, Any]:
    source = await _create(client, display_name=f"Fake {uuid.uuid4().hex[:6]}")
    url = f"{API}/sources/{source['id']}"
    await client.post(f"{url}/test")
    activated: dict[str, Any] = (await client.post(f"{url}/activate")).json()
    assert activated["status"] == "active"
    return activated


async def _set(source_id: str, workspace_id: uuid.UUID, sql: str, **values: object) -> None:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            await session.execute(text(sql), {"s": uuid.UUID(source_id), **values})
            await session.commit()


# ── the activation ───────────────────────────────────────────────────────────


async def test_activating_a_source_publishes_its_first_sync_with_the_change(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)

    with system_scope():
        async with session_factory() as session:
            events = (
                (
                    await session.execute(
                        select(Event).where(
                            Event.workspace_id == acme["acme"], Event.type == "source.activated"
                        )
                    )
                )
                .scalars()
                .all()
            )
    assert [event.payload for event in events] == [{"source_id": source["id"]}]


async def test_the_activation_event_queues_a_pass_under_the_source_key(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)
    with system_scope():
        async with session_factory() as session:
            event = (
                (await session.execute(select(Event).where(Event.type == "source.activated")))
                .scalars()
                .first()
            )
    assert event is not None

    assert await sync_module._on_activated(event.id) == "queued"
    # Twice (dispatch is at-least-once): one pass, not two.
    assert await sync_module._on_activated(event.id) == "already_active"

    (call,) = enqueued
    assert call["job"] == "leka.ingestion.sync.run_sync"
    assert call["args"] == (str(acme["acme"]), source["id"])
    assert call["concurrency_key"] == f"sync:{source['id']}"
    # Full: a re-activation follows a change of scope or credentials.
    assert call["job_kwargs"] == {"full": True, "trigger": "activation"}


# ── the schedule ─────────────────────────────────────────────────────────────


async def test_the_schedule_offers_what_was_not_tried_for_an_hour(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    never = await _activated(client)
    recent = await _activated(client)
    stale = await _activated(client)
    off = await _activated(client)
    await client.post(f"{API}/sources/{off['id']}/disable")
    draft = await _create(client, display_name="Draft")

    now = datetime.now(UTC)
    for source, tried in ((recent, now - timedelta(minutes=10)), (stale, now - timedelta(hours=3))):
        await _set(
            source["id"],
            acme["acme"],
            "INSERT INTO source_syncs (workspace_id, source_id, capability, last_started_at) "
            "SELECT workspace_id, id, 'issues', :at FROM sources WHERE id = :s",
            at=tried,
        )

    result = await sync_module.enqueue_due_syncs(now=now)

    offered = {call["args"][1] for call in enqueued}
    assert {never["id"], stale["id"]} <= offered
    assert not {recent["id"], off["id"], draft["id"]} & offered
    assert result["queued"] >= 2


# ── the API ──────────────────────────────────────────────────────────────────


async def test_an_admin_asks_for_a_pass_and_a_second_click_is_not_an_error(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)
    url = f"{API}/ingestion/sources/{source['id']}/sync"

    first = await client.post(url, params={"full": "true"})
    second = await client.post(url)

    assert (first.status_code, first.json()) == (202, {"queued": True})
    assert (second.status_code, second.json()) == (202, {"queued": False})
    assert enqueued[0]["job_kwargs"] == {"full": True, "trigger": "manual"}
    assert enqueued[0]["queue"].value == "leka:high"


async def test_only_an_activated_source_can_be_synchronised(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    draft = await _create(client)

    refused = await client.post(f"{API}/ingestion/sources/{draft['id']}/sync")

    assert refused.status_code == 409
    assert error_code(refused) == "conflict"


async def test_a_member_reads_how_far_sources_were_read_but_cannot_start_a_pass(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)
    at = datetime.now(UTC)
    await _set(
        source["id"],
        acme["acme"],
        "INSERT INTO source_syncs (workspace_id, source_id, capability, records_total, "
        "last_succeeded_at, status) SELECT workspace_id, id, c, n, :at, 'idle' FROM sources, "
        "(VALUES ('commits', 40), ('issues', 2)) AS v(c, n) WHERE id = :s",
        at=at,
    )

    _as(identity, acme, "member")
    syncs = (await client.get(f"{API}/ingestion/sources/{source['id']}/syncs")).json()
    summary = (await client.get(f"{API}/ingestion/syncs")).json()
    refused = await client.post(f"{API}/ingestion/sources/{source['id']}/sync")

    assert syncs["pass_state"] is None
    assert [(row["capability"], row["records_total"]) for row in syncs["capabilities"]] == [
        ("commits", 40),
        ("issues", 2),
    ]
    assert [(row["source_id"], row["records_total"]) for row in summary] == [(source["id"], 42)]
    assert refused.status_code == 403


async def test_another_workspace_cannot_read_or_start_a_sync(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)

    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/ingestion/sources/{source['id']}/syncs")).status_code == 404
    assert (await client.post(f"{API}/ingestion/sources/{source['id']}/sync")).status_code == 404
    assert (await client.get(f"{API}/ingestion/syncs")).json() == []


def test_the_sync_does_not_read_a_source_waiting_for_a_person() -> None:
    assert SourceStatus.ERROR not in sync_module.SYNCABLE
    assert SourceStatus.DISABLED not in sync_module.SYNCABLE
    assert Source is not None and SourceSync is not None


async def _run(workspace_id: uuid.UUID, source_id: str, status: str) -> None:
    """A job run of the sync for this source, in this status."""
    with system_scope():
        async with session_factory() as session:
            run = await JobRunRepository(session).create(
                job="leka.ingestion.sync.run_sync",
                args=[str(workspace_id), source_id],
                kwargs={"full": False},
                for_workspace_id=workspace_id,
                request_id=None,
                queue=JobQueue.DEFAULT,
                concurrency_key=f"sync:{source_id}",
            )
            assert run is not None
            await session.flush()
            await session.execute(
                text("UPDATE job_runs SET status = :st WHERE id = :id"),
                {"st": status, "id": run.id},
            )
            await session.commit()


async def test_under_way_means_a_worker_holds_it_not_that_a_row_says_so(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    left = await _activated(client)  # a row says running, no job: a worker died
    waiting = await _activated(client)  # a pass queued, nothing read yet
    await _set(
        left["id"],
        acme["acme"],
        "INSERT INTO source_syncs (workspace_id, source_id, capability, status) "
        "SELECT workspace_id, id, 'commits', 'running' FROM sources WHERE id = :s",
    )
    await _run(acme["acme"], waiting["id"], "queued")

    abandoned = (await client.get(f"{API}/ingestion/sources/{left['id']}/syncs")).json()
    summary = {row["source_id"]: row for row in (await client.get(f"{API}/ingestion/syncs")).json()}

    assert abandoned["pass_state"] is None
    (commits,) = abandoned["capabilities"]
    assert commits["status"] == "failed"
    assert "interrompue" in commits["last_error"]["message"]
    assert summary[waiting["id"]]["pass_state"] == "queued"
    assert summary[waiting["id"]]["records_total"] == 0

    await _run(acme["acme"], left["id"], "running")
    running = (await client.get(f"{API}/ingestion/sources/{left['id']}/syncs")).json()
    assert running["pass_state"] == "running"
    assert running["capabilities"][0]["status"] == "running"


async def test_the_passes_of_a_source_are_read_newest_first_by_its_members(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)
    now = datetime.now(UTC)
    await _set(
        source["id"],
        acme["acme"],
        "INSERT INTO sync_runs (workspace_id, source_id, trigger, full_read, status, started_at, "
        "finished_at, records, payloads, bytes) SELECT workspace_id, id, t, f, st, "
        "CAST(:now AS timestamptz) - a, "
        "CASE WHEN st = 'running' THEN NULL "
        "ELSE CAST(:now AS timestamptz) - a + interval '1 minute' END, r, 1, 100 "
        "FROM sources, (VALUES ('activation', true, 'succeeded', interval '2 hours', 40), "
        "('schedule', false, 'running', interval '1 minute', 3)) AS v(t, f, st, a, r) "
        "WHERE id = :s",
        now=now,
    )

    _as(identity, acme, "member")
    runs = (await client.get(f"{API}/ingestion/sources/{source['id']}/runs")).json()["data"]

    assert [(run["trigger"], run["status"], run["records"]) for run in runs] == [
        ("schedule", "running", 3),
        ("activation", "succeeded", 40),
    ]
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/ingestion/sources/{source['id']}/runs")).status_code == 404


# ── backpressure (LEKA-353) ──────────────────────────────────────────────────


async def test_the_schedule_leaves_room_per_workspace_and_in_total(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as(identity, acme, "admin")
    sources = [await _activated(client) for _ in range(4)]
    # One pass of this workspace is already under way.
    await _run(acme["acme"], sources[0]["id"], "running")
    monkeypatch.setattr(sync_module, "MAX_ACTIVE_PASSES_PER_WORKSPACE", 2)

    result = await sync_module.enqueue_due_syncs()

    mine = [call for call in enqueued if call["args"][0] == str(acme["acme"])]
    assert len(mine) == 1  # 2 allowed, 1 already running
    assert result["deferred"] >= 2

    enqueued.clear()
    monkeypatch.setattr(sync_module, "MAX_ACTIVE_PASSES_PER_WORKSPACE", 10)
    monkeypatch.setattr(sync_module, "MAX_ACTIVE_PASSES", 0)
    result = await sync_module.enqueue_due_syncs()
    assert enqueued == [] and result["queued"] == 0


async def test_a_person_waiting_is_not_held_back_by_the_schedule_s_limits(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)
    monkeypatch.setattr(sync_module, "MAX_ACTIVE_PASSES", 0)

    response = await client.post(f"{API}/ingestion/sources/{source['id']}/sync")

    assert response.json() == {"queued": True}


async def test_what_a_source_holds_is_counted_from_the_index(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    """Live records, not everything ever written: a list re-read every hour
    (repositories, branches) must not grow the count (LEKA-353)."""
    _as(identity, acme, "admin")
    source = await _activated(client)
    await _set(
        source["id"],
        acme["acme"],
        "INSERT INTO source_syncs (workspace_id, source_id, capability, records_total, status) "
        "SELECT workspace_id, id, 'commits', 900, 'idle' FROM sources WHERE id = :s",
    )
    await _set(
        source["id"],
        acme["acme"],
        "INSERT INTO source_records (workspace_id, source_id, kind, external_id, checksum, "
        "first_seen_at, last_seen_at, deleted_at) SELECT workspace_id, id, 'commits', e, "
        "repeat('a', 64), now(), now(), d FROM sources, (VALUES ('c1', NULL::timestamptz), "
        "('c2', NULL), ('c3', now())) AS v(e, d) WHERE id = :s",
    )

    summary = (await client.get(f"{API}/ingestion/syncs")).json()
    syncs = (await client.get(f"{API}/ingestion/sources/{source['id']}/syncs")).json()

    assert [row["records_total"] for row in summary if row["source_id"] == source["id"]] == [2]
    assert [row["records_total"] for row in syncs["capabilities"]] == [2]


# ── the extraction, over the API (LEKA-354) ──────────────────────────────────


async def test_a_member_reads_what_extraction_made_of_a_source(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)
    at = datetime.now(UTC)
    checksum = "0" * 64
    await _set(
        source["id"],
        acme["acme"],
        "INSERT INTO source_records (workspace_id, source_id, kind, external_id, checksum, "
        "first_seen_at, last_seen_at, payload_key) SELECT workspace_id, id, 'commits', e, :c, "
        ":at, :at, 'k' FROM sources, (VALUES ('c-1'), ('c-2'), ('c-3')) AS v(e) WHERE id = :s",
        c=checksum,
        at=at,
    )
    await _set(
        source["id"],
        acme["acme"],
        "INSERT INTO extracted_records (workspace_id, source_id, source_record_id, kind, "
        "status, extractor, extractor_version, checksum, result, failure_code, message, "
        "extracted_at) SELECT r.workspace_id, r.source_id, r.id, r.kind, "
        "CASE WHEN r.external_id = 'c-3' THEN 'failed' ELSE 'extracted' END, 'fake.commits', 1, "
        ":c, CASE WHEN r.external_id = 'c-3' THEN NULL ELSE '{}'::jsonb END, "
        "CASE WHEN r.external_id = 'c-3' THEN 'malformed' END, "
        "CASE WHEN r.external_id = 'c-3' THEN 'missing field ''title''' END, :at "
        "FROM source_records r WHERE r.source_id = :s",
        c=checksum,
        at=at,
    )

    _as(identity, acme, "member")
    read = (await client.get(f"{API}/ingestion/sources/{source['id']}/extraction")).json()

    assert (read["extracted"], read["failed"], read["malformed"], read["unsupported"]) == (
        2,
        1,
        1,
        0,
    )
    assert read["extractors"] == [{"extractor": "fake.commits", "extracted": 2, "failed": 1}]
    (failure,) = read["failures"]
    assert (failure["external_id"], failure["code"], failure["message"]) == (
        "c-3",
        "malformed",
        "missing field 'title'",
    )
    assert read["last_extracted_at"] is not None


async def test_another_workspace_cannot_read_a_source_s_extraction(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)

    _as(identity, acme, "other_admin")
    url = f"{API}/ingestion/sources/{source['id']}/extraction"
    assert (await client.get(url)).status_code == 404


# ── the parsing, over the API (LEKA-355) ─────────────────────────────────────


async def test_a_member_reads_what_parsing_found_in_a_source(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)
    at = datetime.now(UTC)
    checksum = "0" * 64
    await _set(
        source["id"],
        acme["acme"],
        "INSERT INTO source_records (workspace_id, source_id, kind, external_id, checksum, "
        "first_seen_at, last_seen_at, payload_key) SELECT workspace_id, id, 'commits', e, :c, "
        ":at, :at, 'k' FROM sources, (VALUES ('c-1'), ('c-2'), ('c-3')) AS v(e) WHERE id = :s",
        c=checksum,
        at=at,
    )
    await _set(
        source["id"],
        acme["acme"],
        "INSERT INTO extracted_records (workspace_id, source_id, source_record_id, kind, "
        "status, extractor, extractor_version, checksum, result, extracted_at) "
        "SELECT workspace_id, source_id, id, kind, 'extracted', 'fake.commits', 1, :c, "
        "'{}'::jsonb, :at FROM source_records WHERE source_id = :s",
        c=checksum,
        at=at,
    )
    parsed = (
        '{"facts": [{"type": "references"}, {"type": "change_type"}], "quality": {"score": %s}}'
    )
    await _set(
        source["id"],
        acme["acme"],
        "INSERT INTO parsed_records (workspace_id, source_id, extracted_record_id, kind, status, "
        "checksum, extractor_version, parser_version, result, failure_code, message, parsed_at) "
        "SELECT x.workspace_id, x.source_id, x.id, x.kind, "
        "CASE r.external_id WHEN 'c-3' THEN 'failed' ELSE 'parsed' END, :c, 1, 1, "
        "CASE r.external_id WHEN 'c-1' THEN CAST(:one AS jsonb) "
        "WHEN 'c-2' THEN CAST(:half AS jsonb) END, "
        "CASE r.external_id WHEN 'c-3' THEN 'malformed' END, "
        "CASE r.external_id WHEN 'c-3' THEN 'not an extracted record: provenance (missing)' END, "
        ":at FROM extracted_records x JOIN source_records r ON r.id = x.source_record_id "
        "WHERE x.source_id = :s",
        c=checksum,
        at=at,
        one=parsed % "1.0",
        half=parsed % "0.5",
    )

    _as(identity, acme, "member")
    read = (await client.get(f"{API}/ingestion/sources/{source['id']}/parsing")).json()

    assert (read["parsed"], read["failed"]) == (2, 1)
    assert read["facts"] == {"references": 2, "change_type": 2}
    assert read["average_quality"] == 0.75
    ((failure),) = read["failures"]
    assert (failure["external_id"], failure["code"]) == ("c-3", "malformed")


async def test_another_workspace_cannot_read_a_source_s_parsing(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)

    _as(identity, acme, "other_admin")
    url = f"{API}/ingestion/sources/{source['id']}/parsing"
    assert (await client.get(url)).status_code == 404


# ── the normalisation, over the API (LEKA-356) ───────────────────────────────


async def test_a_member_reads_the_candidates_made_of_a_source(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)
    at = datetime.now(UTC)
    checksum = "0" * 64
    steps = [
        "INSERT INTO source_records (workspace_id, source_id, kind, external_id, checksum, "
        "first_seen_at, last_seen_at, payload_key) SELECT workspace_id, id, 'commits', e, :c, "
        ":at, :at, 'k' FROM sources, (VALUES ('c-1'), ('c-2'), ('c-3')) AS v(e) WHERE id = :s",
        "INSERT INTO extracted_records (workspace_id, source_id, source_record_id, kind, "
        "status, extractor, extractor_version, checksum, result, extracted_at) "
        "SELECT workspace_id, source_id, id, kind, 'extracted', 'x', 1, :c, '{}'::jsonb, :at "
        "FROM source_records WHERE source_id = :s",
        "INSERT INTO parsed_records (workspace_id, source_id, extracted_record_id, kind, status, "
        "checksum, extractor_version, parser_version, result, parsed_at) "
        "SELECT workspace_id, source_id, id, kind, 'parsed', :c, 1, 1, '{}'::jsonb, :at "
        "FROM extracted_records WHERE source_id = :s",
        "INSERT INTO normalised_records (workspace_id, source_id, parsed_record_id, kind, status, "
        "checksum, extractor_version, parser_version, normaliser_version, entity_type, "
        "entity_key, result, failure_code, message, normalised_at) "
        "SELECT p.workspace_id, p.source_id, p.id, p.kind, "
        "CASE r.external_id WHEN 'c-3' THEN 'failed' ELSE 'normalised' END, :c, 1, 1, 1, "
        "CASE r.external_id WHEN 'c-3' THEN NULL ELSE 'commit' END, "
        "CASE r.external_id WHEN 'c-3' THEN NULL ELSE 'k/' || r.external_id END, "
        "CASE r.external_id WHEN 'c-1' THEN CAST(:one AS jsonb) "
        "WHEN 'c-2' THEN CAST(:two AS jsonb) END, "
        "CASE r.external_id WHEN 'c-3' THEN 'invalid' END, "
        "CASE r.external_id WHEN 'c-3' THEN 'no sha: the extraction has no metadata.sha' END, :at "
        "FROM parsed_records p JOIN extracted_records x ON x.id = p.extracted_record_id "
        "JOIN source_records r ON r.id = x.source_record_id WHERE p.source_id = :s",
    ]
    one = '{"relationships": [{"type": "part_of"}, {"type": "resolves"}], "diagnostics": ["d"]}'
    two = '{"relationships": [{"type": "part_of"}], "diagnostics": []}'
    for sql in steps:
        await _set(source["id"], acme["acme"], sql, c=checksum, at=at, one=one, two=two)

    _as(identity, acme, "member")
    read = (await client.get(f"{API}/ingestion/sources/{source['id']}/normalisation")).json()

    assert (read["normalised"], read["failed"], read["invalid"], read["unsupported"]) == (
        2,
        1,
        1,
        0,
    )
    assert read["entities"] == {"commit": 2}
    assert read["relationships"] == {"part_of": 2, "resolves": 1}
    assert read["with_diagnostics"] == 1
    ((failure),) = read["failures"]
    assert (failure["external_id"], failure["code"]) == ("c-3", "invalid")


async def test_another_workspace_cannot_read_a_source_s_normalisation(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    source = await _activated(client)

    _as(identity, acme, "other_admin")
    url = f"{API}/ingestion/sources/{source['id']}/normalisation"
    assert (await client.get(url)).status_code == 404
