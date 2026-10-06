"""A context keeping up with the company (LEKA-374), against the database.

Acme's company model, as tests/test_context_engine.py builds it: a member
asks for the context of Billing API — and the company moves on. Checkout
is retired; a Ledger service appears; the model is built again, and the
build says so.

What these protect: a context in use follows what the model changed of
what it holds — made again on its own, `changed`, the changes that made it
said, how it differs from the version before, the check kept — and each
build is followed once; a context nobody used for a while, or that
follows nothing, is only marked: behind since when, on what, found by the
`stale` filter — and made again when asked, after those changes; a new
thing its words name is news to a context made from words, and nothing is
news to a context that holds none of it; when a build changes too much to
say, every context is told the model changed; a context widened or
narrowed is made again, a version that says what of its request changed,
never narrower when widened, never with a root that is not the
workspace's, never when archived; an intention asked again makes the same
context again and says what LEKA reads differently; every recalculation
is a check, the latest first; the build's event is routed to a pass, the
sweep queues a pass for each workspace that follows and forgets old
checks.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.background import Event
from leka.background.routes import ROUTES
from leka.context import job as context_job
from leka.context import service as context_service
from leka.context.job import FOLLOW_JOB, follow_workspace, sweep_contexts
from leka.db import session_factory, workspace_scope
from leka.knowledge.job import MODEL_BUILT
from tests.test_application_landscape import _store
from tests.test_context_engine import API, _create, _get, _labels, _refresh, _sql, model
from tests.test_knowledge_graph import CHECKOUT
from tests.test_relationships_engine import _build, _declared
from tests.test_resolution_job import _source
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name


async def _retire_checkout(workspace: uuid.UUID) -> None:
    """Checkout's record goes, and the model is built again without it."""
    await _sql(workspace, "DELETE FROM normalised_records WHERE entity_key = :k", k=CHECKOUT)
    await _build(workspace)


async def _post(client: AsyncClient, path: str, body: Any = None, status: int = 200) -> Any:
    response = await client.post(f"{API}{path}", json=body)
    assert response.status_code == status, response.text
    return response.json()


def _said(changes: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
    return {(c["kind"], c["change"], c["name"]) for c in changes}


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    queued: list[dict[str, Any]] = []

    async def capture(job: str, *args: object, **kwargs: Any) -> object:
        queued.append({"job": job, "args": args, **kwargs})
        return object()

    monkeypatch.setattr(context_job, "enqueue_job", capture)
    return queued


async def test_a_context_in_use_follows_what_the_model_changed_of_what_it_holds(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model)
    context_id = made["context_id"]
    up = (await _get(client, f"/{context_id}"))["freshness"]
    assert (up["state"], up["following"], up["changes"]) == ("fresh", "active", 0)

    await _retire_checkout(acme["acme"])

    # The build says what it did.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            told = (await session.execute(select(Event).where(Event.type == MODEL_BUILT))).scalars()
            assert all("run_id" in event.payload for event in told)

    counts = await follow_workspace(acme["acme"])
    assert counts["builds"] >= 1
    assert (counts["version"], counts["errors"]) == (1, 0)

    latest = await _get(client, f"/{context_id}/assembled")
    assert (latest["version"], latest["trigger"]) == (2, "changed")
    said = _said(latest["changes"])
    assert ("entity", "removed", "Checkout") in said
    assert ("relationship", "removed", "Checkout → Billing API") in said
    assert all(c["touches"] == "held" for c in latest["changes"])
    assert latest["change_count"] >= 2
    assert latest["delta"]["removed"] >= 2
    assert "Checkout" not in _labels(latest)
    assert (await _get(client, f"/{context_id}"))["freshness"]["state"] == "fresh"

    [check] = (await _get(client, f"/{context_id}/checks"))["data"]
    assert (check["trigger"], check["outcome"], check["version"], check["checked_by"]) == (
        "changed",
        "version",
        2,
        None,
    )
    assert ("entity", "removed", "Checkout") in _said(check["changes"])

    # Followed again: each build once, nothing made twice.
    again = await follow_workspace(acme["acme"])
    assert (again["builds"], again["version"], again["touched"]) == (0, 0, 0)
    versions = await _get(client, f"/{context_id}/versions")
    assert [v["trigger"] for v in versions["data"]] == ["changed", "created"]


async def test_a_context_nobody_uses_or_that_follows_nothing_is_only_marked(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    dormant = (await _create(client, model))["context_id"]
    off = (await _create(client, model, purpose="Who runs Billing API?"))["context_id"]
    await _sql(
        acme["acme"],
        "UPDATE contexts SET used_at = now() - interval '30 days',"
        " created_at = now() - interval '30 days' WHERE id = :id",
        id=dormant,
    )
    response = await client.patch(f"{API}/{off}", json={"follow": False})
    assert response.status_code == 200, response.text
    assert (response.json()["follow"], response.json()["freshness"]["following"]) == (False, "off")

    await _retire_checkout(acme["acme"])
    counts = await follow_workspace(acme["acme"])
    assert (counts["touched"], counts["version"]) == (2, 0)

    # Listed, not read: reading would say it is in use.
    behind = {c["id"]: c for c in (await _get(client, "", stale="true"))["data"]}
    assert set(behind) == {dormant, off}
    assert not {dormant, off} & {c["id"] for c in (await _get(client, "", stale="false"))["data"]}
    sleeping = behind[dormant]["freshness"]
    assert (sleeping["state"], sleeping["reasons"], sleeping["following"]) == (
        "stale",
        ["changes"],
        "dormant",
    )
    assert sleeping["since"] is not None
    assert sleeping["changes"] >= 2
    assert ("entity", "removed", "Checkout") in _said(sleeping["pending"])
    assert behind[off]["freshness"]["following"] == "off"
    assert [v["version"] for v in (await _get(client, f"/{dormant}/versions"))["data"]] == [1]

    # Someone asks: made again, after what it was behind on.
    moved = await _refresh(client, dormant)
    assert (moved["changed"], moved["version"]["version"], moved["version"]["trigger"]) == (
        True,
        2,
        "refreshed",
    )
    assert ("entity", "removed", "Checkout") in _said(moved["version"]["changes"])
    assert moved["check"]["change_count"] >= 2
    now = (await _get(client, f"/{dormant}"))["freshness"]
    assert (now["state"], now["following"], now["pending"]) == ("fresh", "active", [])


async def test_a_new_thing_its_words_name_is_news_and_nothing_else(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    billing = (await _create(client, model))["context_id"]
    ledger = await _post(
        client,
        "",
        {"title": "Ledger", "purpose": "Why is the ledger slow?", "subject": {"type": "request"}},
        status=201,
    )
    assert "Ledger" not in _labels(ledger)

    finance = await _source(acme["acme"], "Finance")
    for record_id, name in (("s-9", "Ledger"), ("s-10", "Payroll")):
        await _store(acme["acme"], finance, _declared("service", record_id, name, {}))
    await _build(acme["acme"])
    await follow_workspace(acme["acme"])

    latest = await _get(client, f"/{ledger['context_id']}/assembled")
    assert (latest["version"], latest["trigger"]) == (2, "changed")
    assert [(c["change"], c["name"], c["touches"]) for c in latest["changes"]] == [
        ("added", "Ledger", "words")
    ]
    assert "Ledger" in _labels(latest)
    untouched = await _get(client, f"/{billing}")
    assert (untouched["current_version"], untouched["freshness"]["state"]) == (1, "fresh")


async def test_a_build_that_changes_too_much_to_say_tells_every_context(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context_id = (await _create(client, model))["context_id"]
    await _sql(acme["acme"], "UPDATE contexts SET follow = false WHERE id = :id", id=context_id)
    monkeypatch.setattr(context_service, "MAX_CHANGES", 1)

    await _retire_checkout(acme["acme"])
    counts = await follow_workspace(acme["acme"])

    assert counts["touched"] == 1
    [listed] = (await _get(client, "", stale="true"))["data"]
    assert [(c["kind"], c["change"]) for c in listed["freshness"]["pending"]] == [
        ("model", "changed")
    ]


async def test_widened_and_narrowed_a_context_is_made_again_saying_what_changed(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    context_id = (await _create(client, model))["context_id"]

    wider = await _post(client, f"/{context_id}/expand")
    assert (wider["changed"], wider["version"]["version"], wider["version"]["trigger"]) == (
        True,
        2,
        "expanded",
    )
    assert [(c["field"], c["before"], c["after"]) for c in wider["version"]["changes"]] == [
        ("depth", 1, 2),
        ("limit", 100, 200),
        ("window_days", 14, 28),
    ]
    request = (await _get(client, f"/{context_id}"))["request"]
    assert (request["depth"], request["limit"], request["window_days"]) == (2, 200, 28)

    narrower = await _post(
        client, f"/{context_id}/compress", {"limit": 3, "reason": "A short summary"}
    )
    version = narrower["version"]
    assert (version["version"], version["trigger"], version["reason"]) == (
        3,
        "compressed",
        "A short summary",
    )
    assert version["element_count"] <= 3
    assert version["delta"]["removed"] > 0
    held = await _get(client, f"/{context_id}/assembled")
    assert held["elements"][0]["label"] == "Billing API"

    # Never narrower when widened, never past what it is.
    refused = await client.post(f"{API}/{context_id}/expand", json={"limit": 2})
    assert refused.status_code == 422
    assert "only widens" in refused.text
    assert (
        await client.post(f"{API}/{context_id}/compress", json={"limit": 50})
    ).status_code == 422
    unknown = await client.post(f"{API}/{context_id}/expand", json={"roots": [str(uuid.uuid4())]})
    assert unknown.status_code == 404

    checks = (await _get(client, f"/{context_id}/checks"))["data"]
    assert [(c["trigger"], c["outcome"], c["version"]) for c in checks] == [
        ("compressed", "version", 3),
        ("expanded", "version", 2),
    ]

    await _post(client, f"/{context_id}/archive")
    assert (await client.post(f"{API}/{context_id}/expand")).status_code == 409
    assert (await client.post(f"{API}/{context_id}/compress")).status_code == 409


async def test_an_intention_asked_again_makes_the_same_context_again(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    asked = await _post(client, "/intents", {"text": "Pourquoi Billing API est lent ?"}, 201)
    context_id = asked["context_id"]

    again = await _post(
        client, f"/{context_id}/intent", {"text": "Qui est responsable de Checkout ?"}
    )
    assert (again["context_id"], again["version"], again["trigger"]) == (context_id, 2, "reasked")
    assert again["intent"]["kind"] == "ownership"
    said = {
        c["field"]: (c["before"], c["after"]) for c in again["changes"] if c["kind"] == "intent"
    }
    assert said["kind"] == ("diagnose", "ownership")
    assert said["text"] == ("Pourquoi Billing API est lent ?", "Qui est responsable de Checkout ?")
    assert "Checkout" in said["subjects"][1]
    assert again["delta"] is not None
    detail = await _get(client, f"/{context_id}")
    assert detail["purpose"] == "Qui est responsable de Checkout ?"
    assert [v["trigger"] for v in (await _get(client, f"/{context_id}/versions"))["data"]] == [
        "reasked",
        "created",
    ]

    assert (
        await client.post(f"{API}/{context_id}/intent", json={"text": "Pourquoi ?"})
    ).status_code == 422
    asked_for_billing = (await _create(client, model))["context_id"]
    assert (
        await client.post(
            f"{API}/{asked_for_billing}/intent", json={"text": "Qui est responsable de Checkout ?"}
        )
    ).status_code == 409


async def test_a_refresh_that_finds_nothing_new_is_a_check_too(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    context_id = (await _create(client, model))["context_id"]
    same = await _refresh(client, context_id)
    assert (same["changed"], same["check"]["outcome"], same["check"]["version"]) == (
        False,
        "unchanged",
        1,
    )
    [check] = (await _get(client, f"/{context_id}/checks"))["data"]
    assert (check["trigger"], check["outcome"], check["checked_by"] is not None) == (
        "refreshed",
        "unchanged",
        True,
    )


async def test_the_build_s_event_queues_a_pass_and_the_sweep_queues_each_that_follows(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = acme["acme"]
    context_id = (await _create(client, model))["context_id"]
    await _refresh(client, context_id)
    await _retire_checkout(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            event = (
                (await session.execute(select(Event).where(Event.type == MODEL_BUILT)))
                .scalars()
                .first()
            )
    assert event is not None
    # The contexts follow the build — beside the analyses (LEKA-377).
    assert "leka.context.job.run_follow_for_event" in [route.job for route in ROUTES[MODEL_BUILT]]
    queued = _capture(monkeypatch)

    assert await context_job._queue_for_event(event.id) == "queued"
    [call] = queued
    assert (call["job"], call["args"], call["concurrency_key"]) == (
        FOLLOW_JOB,
        (str(workspace),),
        f"context:{workspace}",
    )

    queued.clear()
    result = await sweep_contexts()
    assert [c["args"] for c in queued if c["for_workspace_id"] == workspace] == [(str(workspace),)]
    assert result["pruned"] == 0

    later = await sweep_contexts(now=datetime.now(UTC) + timedelta(days=91))
    assert later["pruned"] >= 1
    assert (await _get(client, f"/{context_id}/checks"))["data"] == []
