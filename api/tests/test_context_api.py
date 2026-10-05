"""The context API, as LEKA's services and screens use it (LEKA-376).

Acme's company model, as tests/test_context_engine.py builds it: Billing
API, from PagerDuty and the catalogue; Checkout, which the catalogue says
depends on it; Nora Diallo, of Payments.

What these protect: the contract is published — its version, the header
it is said in, what each part is judged by, its JSON schema, what each
ticket added — every response says it, and a client asking for another is
refused before anything is read; contexts are queried by what they hold,
their words — taken literally — their quality, who made them; an element
is inspected — what quality says of it, its history across versions, what
people said — and not found when the version does not hold it; its
evidence is the records it was read from, an entity's every record its key
resolved from, a relationship's the record that stated it, a record gone
from its source said and listed last; what happens to a context is
streamed — up to date or not at once, each time it is made again, resumed
after the last event told, as it happens, and the end when archived.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from leka.context import stream
from tests.conftest import FakeIdentity
from tests.test_context_engine import API, _create, _get, _refresh, _sql, model
from tests.test_knowledge_graph import BILLING, CHECKOUT, NORA
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name


def _events(body: str) -> list[tuple[str | None, str, dict[str, Any]]]:
    """A stream's events: (id, event, data)."""
    told: list[tuple[str | None, str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line and line[0] != ":"
        )
        if "event" in fields:
            told.append((fields.get("id"), fields["event"], json.loads(fields.get("data", "{}"))))
    return told


async def test_the_contract_is_published_said_on_every_response_and_held_to(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    response = await client.get(f"{API}/contract")
    assert response.status_code == 200, response.text
    assert response.headers["Leka-Context-Contract"] == "1"
    contract = response.json()
    assert (contract["version"], contract["supported"], contract["header"]) == (
        1,
        [1],
        "Leka-Context-Contract",
    )
    assert contract["versions"] == {
        "ranking": 1,
        "quality": 1,
        "intent": 1,
        "strategy.hybrid": 1,
        "strategy.neighbourhood": 1,
    }
    assert {"elements", "quality", "intent", "trigger"} <= set(
        contract["json_schema"]["properties"]
    )
    assert [c["ticket"] for c in contract["changes"]] == [
        "LEKA-371",
        "LEKA-372",
        "LEKA-373",
        "LEKA-374",
        "LEKA-375",
    ]

    made = await _create(client, model)
    asked = await client.get(
        f"{API}/{made['context_id']}/assembled", headers={"Leka-Context-Contract": "1"}
    )
    assert (asked.status_code, asked.headers["Leka-Context-Contract"]) == (200, "1")
    refused = await client.post(
        f"{API}/{made['context_id']}/refresh", headers={"Leka-Context-Contract": "2"}
    )
    assert refused.status_code == 406
    assert refused.json()["error"]["code"] == "contract_unsupported"
    # Refused before anything was made.
    assert [
        v["version"] for v in (await _get(client, f"/{made['context_id']}/versions"))["data"]
    ] == [1]


async def test_contexts_are_queried_by_what_they_hold_their_words_quality_and_maker(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    billing = (await _create(client, model))["context_id"]
    _as(identity, acme, "admin")
    nora = (
        await client.post(
            API,
            json={
                "title": "Nora",
                "purpose": "Who is Nora Diallo?",
                "subject": {"type": "request"},
                "roots": [str(model[NORA])],
            },
        )
    ).json()["context_id"]

    def ids(page: dict[str, Any]) -> set[str]:
        return {c["id"] for c in page["data"]}

    held = ids(await _get(client, "", holds=str(model[NORA])))
    assert nora in held and billing not in held
    assert billing in ids(await _get(client, "", holds=str(model[BILLING])))
    assert ids(await _get(client, "", q="nora")) == {nora}
    assert ids(await _get(client, "", q="BILLING api")) == {billing}
    # The words are taken as written: a wildcard is a character.
    assert ids(await _get(client, "", q="%_")) == set()
    assert ids(await _get(client, "", mine="true")) == {nora}
    _as(identity, acme, "member")
    assert ids(await _get(client, "", mine="true")) == {billing}
    assert billing in ids(await _get(client, "", level="high"))
    assert billing not in ids(await _get(client, "", level="low"))
    assert (await client.get(API, params={"level": "great"})).status_code == 422


async def test_an_element_is_inspected_its_quality_its_history_what_people_said(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model)
    context_id = made["context_id"]
    root = str(model[BILLING])
    await client.post(f"{API}/{context_id}/feedback", json={"ref_id": root, "verdict": "useful"})
    widened = await client.post(f"{API}/{context_id}/expand")
    assert widened.status_code == 200, widened.text

    inspected = await _get(client, f"/{context_id}/elements/{root}")
    assert (inspected["version"], inspected["element"]["label"]) == (2, "Billing API")
    assert [g["kind"] for g in inspected["quality"]["gaps"]] == ["undocumented"]
    assert ("completeness", "start") in {
        (f["measure"], f["name"]) for f in inspected["quality"]["factors"]
    }
    assert [(s["version"], s["trigger"], s["held"], s["rank"]) for s in inspected["history"]] == [
        (2, "expanded", True, 1),
        (1, "created", True, 1),
    ]
    assert inspected["feedback"]["useful"] == 1

    # As version 1 held it.
    first = await _get(client, f"/{context_id}/elements/{root}", version=1)
    assert first["version"] == 1
    for path, params in (
        (f"/{context_id}/elements/{uuid.uuid4()}", {}),
        (f"/{context_id}/elements/{root}", {"version": 9}),
    ):
        response = await client.get(f"{API}{path}", params=params)
        assert response.status_code == 404, path


async def test_the_evidence_of_an_element_is_the_records_it_was_read_from(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model)
    context_id = made["context_id"]

    entity = await _get(client, f"/{context_id}/elements/{model[BILLING]}/evidence")
    assert (entity["kind"], entity["label"], entity["truncated"]) == (
        "entity",
        "Billing API",
        False,
    )
    # Every record its key resolved from, from each source that says it.
    assert sorted((r["source_name"], r["external_id"], r["gone"]) for r in entity["records"]) == [
        ("Catalogue", BILLING, False),
        ("PagerDuty", BILLING, False),
    ]

    [tie] = [
        e
        for e in made["elements"]
        if e["kind"] == "relationship" and e["label"] == "Checkout → Billing API"
    ]
    stated = await _get(client, f"/{context_id}/elements/{tie['ref_id']}/evidence")
    assert stated["kind"] == "relationship"
    # The record that stated it: Checkout's, in the catalogue.
    assert [(r["source_name"], r["external_id"]) for r in stated["records"]] == [
        ("Catalogue", CHECKOUT)
    ]

    # A record the source no longer shows: said, and listed last.
    [pagerduty] = [r["source_id"] for r in entity["records"] if r["source_name"] == "PagerDuty"]
    await _sql(
        acme["acme"],
        "UPDATE source_records SET deleted_at = now() WHERE source_id = :s",
        s=uuid.UUID(pagerduty),
    )
    again = await _get(client, f"/{context_id}/elements/{model[BILLING]}/evidence")
    assert [(r["source_name"], r["gone"]) for r in again["records"]] == [
        ("Catalogue", False),
        ("PagerDuty", True),
    ]
    missing = await client.get(
        f"{API}/{context_id}/elements/{model[CHECKOUT]}/evidence", params={"version": 9}
    )
    assert missing.status_code == 404


async def test_what_happens_to_a_context_is_streamed_resumed_and_told_live(
    client: AsyncClient, model: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stream, "POLL", 0.05)
    made = await _create(client, model)
    context_id = made["context_id"]
    first = await _refresh(client, context_id, reason="One")
    await _refresh(client, context_id, reason="Two")

    response = await client.get(
        f"{API}/{context_id}/events",
        params={"timeout": 1, "after": made["assembled_at"]},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.startswith("retry: 3000")
    told = _events(response.text)
    assert [event for _, event, _ in told] == ["check", "check", "freshness", "bye"]
    one, two = told[0], told[1]
    assert (one[2]["trigger"], one[2]["outcome"], one[0]) == (
        "refreshed",
        "unchanged",
        first["check"]["checked_at"].replace("Z", "+00:00"),
    )
    assert told[2][2]["state"] == "fresh"

    # Resumed after the last event told: only what came after.
    resumed = _events(
        (
            await client.get(
                f"{API}/{context_id}/events",
                params={"timeout": 1},
                headers={"Last-Event-ID": one[0] or ""},
            )
        ).text
    )
    assert [(i, e) for i, e, _ in resumed if e == "check"] == [(two[0], "check")]

    # As it happens.
    async def later() -> None:
        await asyncio.sleep(0.3)
        await client.post(f"{API}/{context_id}/expand")

    live, _ = await asyncio.gather(
        client.get(f"{API}/{context_id}/events", params={"timeout": 2}), later()
    )
    events = _events(live.text)
    checks = [data for _, event, data in events if event == "check"]
    assert [(c["trigger"], c["outcome"], c["version"]) for c in checks] == [
        ("expanded", "version", 2)
    ]

    # Archived: said, and the end.
    await client.post(f"{API}/{context_id}/archive")
    ended = _events((await client.get(f"{API}/{context_id}/events", params={"timeout": 5})).text)
    assert [event for _, event, _ in ended][-1] == "archived"
    assert (await client.get(f"{API}/{uuid.uuid4()}/events")).status_code == 404
