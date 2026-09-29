"""Webhook deliveries, from the door to extraction (LEKA-350).

A webhook source is configured as any source — through the API, tested,
activated — and then its system sends: POST /api/v1/webhooks/sources/{id},
signed with the secret. The door verifies and keeps the delivery; a pass
stores what it holds, as it stores what it reads; extraction follows.

What these protect: nothing unsigned is written — not a row; a delivery
the definition cannot read is refused while its sender listens, and logged
for the admin; what is kept is stored in the order it came, deletions
included, and never swept; the inbox is bounded and says so; the log is
read by the source's members only, never with a body, and kept 30 days.

The queue is not here (test_background_e2e.py is): what would have been
enqueued is captured where `enqueue_job` is called.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, text

from leka.core import ratelimit
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import (
    DeliveryStatus,
    SourceRecord,
    SyncRun,
    SyncTrigger,
    WebhookDelivery,
)
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion import sync as sync_module
from leka.ingestion import webhooks as webhooks_module
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.lifecycle import sweep_processing
from leka.ingestion.purge import PURGE_JOB
from leka.ingestion.sync import sync_source
from leka.platform import LocalObjectStore
from tests.conftest import FakeIdentity, error_code
from tests.test_custom_webhook_connector import DEFINITION, SECRET, ticket
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1"


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[list[dict[str, Any]]]:
    """What would have been queued — passes, stages, purges — and a store of
    the test's own for what the passes write."""
    from leka.platform import storage

    calls: list[dict[str, Any]] = []

    async def capture(job: str, *args: object, **kwargs: Any) -> object:
        calls.append({"job": job, "args": args, **kwargs})
        return object()

    monkeypatch.setattr(storage, "_store", LocalObjectStore(tmp_path))
    monkeypatch.setattr(sync_module, "enqueue_job", capture)
    monkeypatch.setattr(pipeline_module, "enqueue_job", capture)
    yield calls


async def _source(client: AsyncClient, *, activate: bool = True, **config: Any) -> dict[str, Any]:
    body = {
        "type": "custom_webhook",
        "display_name": "Helpdesk hooks",
        "config": {"definition": json.dumps(DEFINITION), **config},
        "credentials": {"secret": SECRET},
    }
    created = await client.post(f"{API}/sources", json=body)
    assert created.status_code == 201, created.text
    source: dict[str, Any] = created.json()
    tested = (await client.post(f"{API}/sources/{source['id']}/test")).json()
    assert tested["ok"], tested
    if activate:
        activated = await client.post(f"{API}/sources/{source['id']}/activate")
        assert activated.status_code == 200, activated.text
        source = activated.json()
    # Not in what the API returns — the session says it — but what a pass needs.
    with system_scope():
        async with session_factory() as session:
            workspace_id = await session.scalar(
                text("SELECT workspace_id FROM sources WHERE id = :s"), {"s": source["id"]}
            )
    return {**source, "workspace_id": str(workspace_id)}


def _signed(document: object, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(document).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Leka-Signature": f"sha256={signature}",
        "X-GitHub-Delivery": f"d-{uuid.uuid4().hex[:8]}",
    }


async def _send(client: AsyncClient, source: dict[str, Any], document: object) -> Response:
    body, headers = _signed(document)
    return await client.post(
        f"{API}/webhooks/sources/{source['id']}", content=body, headers=headers
    )


async def _deliveries(source: dict[str, Any]) -> list[WebhookDelivery]:
    with workspace_scope(uuid.UUID(source["workspace_id"])):
        async with session_factory() as session:
            rows = await session.execute(
                select(WebhookDelivery)
                .where(WebhookDelivery.source_id == uuid.UUID(source["id"]))
                .order_by(WebhookDelivery.received_at)
            )
            return list(rows.scalars())


async def _index(source: dict[str, Any]) -> dict[str, SourceRecord]:
    with workspace_scope(uuid.UUID(source["workspace_id"])):
        async with session_factory() as session:
            rows = await session.execute(
                select(SourceRecord).where(SourceRecord.source_id == uuid.UUID(source["id"]))
            )
            return {row.external_id: row for row in rows.scalars()}


async def _pass(source: dict[str, Any], **kwargs: Any) -> sync_module.SyncReport:
    return await sync_source(
        uuid.UUID(source["workspace_id"]),
        uuid.UUID(source["id"]),
        trigger=kwargs.pop("trigger", SyncTrigger.WEBHOOK),
        **kwargs,
    )


def _passes(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in calls if c["job"] == sync_module.SYNC_JOB]


# ── the whole way: configured, sent, stored, extracted ───────────────────────


async def test_a_signed_delivery_is_kept_then_stored_by_a_pass_then_extracted(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    assert source["capabilities"] == ["records"]
    identity.sign_in(uuid.uuid4(), None)  # the system that sends has no session

    answer = await _send(client, source, ticket())

    assert answer.status_code == 202, answer.text
    accepted = answer.json()
    assert {k: accepted[k] for k in ("status", "resource", "records", "gone")} == {
        "status": "pending",
        "resource": "tickets",
        "records": 1,
        "gone": 0,
    }
    [delivery] = await _deliveries(source)
    assert (delivery.status, delivery.body is not None) == (DeliveryStatus.PENDING, True)
    assert delivery.delivery_id is not None and delivery.delivery_id.startswith("d-")
    [queued] = _passes(enqueued)
    assert queued["job_kwargs"] == {"full": False, "trigger": "webhook"}
    assert queued["concurrency_key"] == f"sync:{source['id']}"  # one pass at a time

    report = await _pass(source)

    assert (report.status, report.records) == ("succeeded", {"records": 1})
    index = await _index(source)
    assert set(index) == {"tickets:101"}
    assert index["tickets:101"].deleted_at is None
    [delivery] = await _deliveries(source)
    assert delivery.status is DeliveryStatus.STORED
    assert delivery.body is None  # let go once stored: the payload holds it now
    assert delivery.run_id is not None and delivery.processed_at is not None
    with workspace_scope(uuid.UUID(source["workspace_id"])):
        async with session_factory() as session:
            run = await session.get(SyncRun, delivery.run_id)
            assert run is not None
            assert (run.trigger, run.full_read, run.records) == (SyncTrigger.WEBHOOK, False, 1)
    extracted = await extract_source(uuid.UUID(source["workspace_id"]), uuid.UUID(source["id"]))
    assert (extracted["extracted"], extracted["failed"]) == (1, 0)


async def test_a_delivery_sent_again_is_not_written_again(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    await _send(client, source, ticket())
    await _pass(source)
    first = (await _index(source))["tickets:101"].payload_key

    # Senders retry: the same change, again.
    await _send(client, source, ticket())
    report = await _pass(source)

    assert report.records == {"records": 1}  # seen
    assert (await _index(source))["tickets:101"].payload_key == first  # not written


async def test_what_came_is_stored_in_the_order_it_came_deletions_included(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    deleted = {"event": "ticket.deleted", "ticket": {"id": 101}}

    # Updated, then deleted, before any pass: gone.
    await _send(client, source, ticket(subject="VPN drops"))
    assert (await _send(client, source, deleted)).json()["gone"] == 1
    report = await _pass(source)
    assert report.deleted == {"records": 1}
    assert (await _index(source))["tickets:101"].deleted_at is not None
    # What was deleted leaves the store too: the purge is asked for.
    assert any(c["job"] == PURGE_JOB for c in enqueued)

    # Deleted, then created again: back.
    await _send(client, source, deleted)
    await _send(client, source, ticket(event="ticket.created"))
    await _pass(source)
    assert (await _index(source))["tickets:101"].deleted_at is None


async def test_a_full_pass_never_sweeps_what_was_received(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    await _send(client, source, ticket())
    await _pass(source)

    # The weekly full pass, an activation's, a person's: nothing was listed,
    # so nothing unlisted is gone.
    report = await _pass(source, full=True, trigger=SyncTrigger.SCHEDULE)

    assert (report.status, report.deleted) == ("succeeded", {})
    assert (await _index(source))["tickets:101"].deleted_at is None


async def test_a_pass_takes_what_another_left_and_refuses_what_the_definition_no_longer_reads(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    await _send(client, source, ticket())
    # The definition changed between the door and the pass: the title is read
    # elsewhere now, and this delivery has nothing there.
    changed = json.loads(json.dumps(DEFINITION))
    changed["resources"][0]["mapping"]["title"] = "headline"
    with workspace_scope(uuid.UUID(source["workspace_id"])):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE sources SET config = CAST(:c AS jsonb) WHERE id = :s"),
                {"c": json.dumps({"definition": json.dumps(changed)}), "s": source["id"]},
            )
            await session.commit()

    report = await _pass(source, trigger=SyncTrigger.SCHEDULE)

    assert (report.status, report.records) == ("succeeded", {"records": 0})
    [delivery] = await _deliveries(source)
    assert delivery.status is DeliveryStatus.REJECTED
    assert delivery.error is not None and delivery.error["reason"] == "unmapped"
    assert delivery.body is None


# ── the door ─────────────────────────────────────────────────────────────────


async def test_nothing_unsigned_is_written_not_even_a_row(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    url = f"{API}/webhooks/sources/{source['id']}"
    body, headers = _signed(ticket())

    unsigned = await client.post(url, content=body)
    other_secret = await client.post(
        url, content=body, headers=_signed(ticket(), "another-secret-entirely")[1]
    )
    altered = await client.post(url, content=body.replace(b"101", b"666"), headers=headers)

    for answer in (unsigned, other_secret, altered):
        assert answer.status_code == 401
        assert error_code(answer) == "not_authenticated"
        assert SECRET not in answer.text
    assert await _deliveries(source) == []
    assert _passes(enqueued) == []


async def test_an_address_that_is_not_a_webhook_source_s_is_not_found(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    rest = await client.post(
        f"{API}/sources",
        json={
            "type": "custom_rest",
            "display_name": "Helpdesk API",
            "config": {
                "base_url": "https://helpdesk.acme.example/api",
                "definition": json.dumps(
                    {
                        "resources": [
                            {"name": "t", "path": "/t", "mapping": {"id": "id", "title": "t"}}
                        ]
                    }
                ),
            },
            "credentials": {"secret": SECRET},
        },
    )
    body, headers = _signed(ticket())

    for source_id in (str(uuid.uuid4()), rest.json()["id"]):
        answer = await client.post(
            f"{API}/webhooks/sources/{source_id}", content=body, headers=headers
        )
        assert (answer.status_code, error_code(answer)) == (404, "not_found")


async def test_a_source_not_switched_on_takes_nothing(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client, activate=False)

    answer = await _send(client, source, ticket())

    assert (answer.status_code, error_code(answer)) == (409, "conflict")
    assert await _deliveries(source) == []


@pytest.mark.parametrize(
    ("document", "status", "reason"),
    [
        ("<ticket id=101/>", 400, "malformed"),
        (ticket(id=None), 422, "unmapped"),
    ],
)
async def test_a_signed_delivery_the_definition_cannot_read_is_refused_and_logged(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
    document: object,
    status: int,
    reason: str,
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    if isinstance(document, str):
        body = document.encode()
        signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        answer = await client.post(
            f"{API}/webhooks/sources/{source['id']}",
            content=body,
            headers={"X-Leka-Signature": signature},
        )
    else:
        answer = await _send(client, source, document)

    assert (answer.status_code, error_code(answer)) == (status, "validation_failed")
    [delivery] = await _deliveries(source)
    assert delivery.status is DeliveryStatus.REJECTED
    assert delivery.error is not None and delivery.error["reason"] == reason
    assert delivery.body is None  # what could not be read is not kept
    assert _passes(enqueued) == []


async def test_an_event_nobody_asked_for_is_acknowledged_and_ignored(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)

    answer = await _send(client, source, {"event": "agent.logged_in", "agent": 7})

    # Acknowledged: a sender refused would retry, for nothing.
    assert (answer.status_code, answer.json()["status"]) == (202, "ignored")
    [delivery] = await _deliveries(source)
    assert (delivery.status, delivery.body) == (DeliveryStatus.IGNORED, None)
    assert _passes(enqueued) == []


async def test_a_delivery_too_large_is_refused_before_it_is_read(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    body = b"[" + b" " * webhooks_module.MAX_BODY_BYTES + b"]"

    answer = await client.post(
        f"{API}/webhooks/sources/{source['id']}", content=body, headers=_signed(ticket())[1]
    )

    assert (answer.status_code, error_code(answer)) == (413, "validation_failed")
    assert await _deliveries(source) == []


async def test_a_full_inbox_asks_the_sender_to_come_back(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    monkeypatch.setattr(webhooks_module, "MAX_BACKLOG", 1)

    assert (await _send(client, source, ticket())).status_code == 202
    waiting = await _send(client, source, ticket(id=102))
    assert (waiting.status_code, error_code(waiting)) == (429, "rate_limited")
    assert waiting.headers["Retry-After"] == str(webhooks_module.BACKLOG_RETRY_SECONDS)

    await _pass(source)  # the inbox empties
    assert (await _send(client, source, ticket(id=102))).status_code == 202


async def test_a_source_takes_so_many_deliveries_a_minute(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    monkeypatch.setattr(webhooks_module, "SOURCE_LIMIT", ratelimit.Limit(1, 60))

    assert (await _send(client, source, ticket())).status_code == 202
    second = await _send(client, source, ticket(id=102))

    assert (second.status_code, error_code(second)) == (429, "rate_limited")
    assert int(second.headers["Retry-After"]) > 0


# ── the log ──────────────────────────────────────────────────────────────────


async def test_members_read_the_log_newest_first_never_a_body(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    await _send(client, source, ticket())
    await _send(client, source, ticket(id=None))
    await _send(client, source, {"event": "agent.logged_in"})

    _as(identity, acme, "member")
    log = (await client.get(f"{API}/ingestion/sources/{source['id']}/deliveries")).json()["data"]

    assert [(d["status"], d["resource"], d["records"]) for d in log] == [
        ("ignored", None, 0),
        ("rejected", None, 0),
        ("pending", "tickets", 1),
    ]
    assert log[1]["error"]["reason"] == "unmapped"
    assert all("body" not in d for d in log)
    assert all(d["delivery_id"].startswith("d-") for d in log)
    _as(identity, acme, "other_admin")
    other = await client.get(f"{API}/ingestion/sources/{source['id']}/deliveries")
    assert other.status_code == 404


async def test_the_catalogue_says_which_kind_is_sent_to(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "member")

    catalogue = (await client.get(f"{API}/connectors/catalog")).json()

    assert [entry["key"] for entry in catalogue if entry["receives"]] == ["custom_webhook"]


async def test_the_log_is_kept_thirty_days_and_a_pending_delivery_until_stored(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    enqueued: list[dict[str, Any]],
) -> None:
    _as(identity, acme, "admin")
    source = await _source(client)
    await _send(client, source, ticket())
    await _pass(source)
    await _send(client, source, ticket(id=102))  # pending
    now = datetime.now(UTC) + timedelta(days=31)

    result = await sweep_processing(now=now)

    assert (result["deliveries"], result["webhook_passes"]) == (1, 1)
    [left] = await _deliveries(source)
    assert left.status is DeliveryStatus.PENDING
    with workspace_scope(uuid.UUID(source["workspace_id"])):
        async with session_factory() as session:
            triggers = (
                await session.execute(
                    select(SyncRun.trigger).where(SyncRun.source_id == uuid.UUID(source["id"]))
                )
            ).scalars()
            assert SyncTrigger.WEBHOOK not in list(triggers)
