"""LEKA's capabilities, over HTTP (LEKA-393).

Acme's company model (test_knowledge_graph), its sources (PagerDuty and the
declared ones), its member and admins.

What these protect:
- The catalogue, for a workspace and a person: LEKA's own analyses,
  available; the application architect registered — what it takes, what it
  delivers — and every reason it cannot run here yet: no source to read,
  no model (LEKA-394); a source connected, one reason less; its
  instructions never sent. What does not run is shown only when asked.
- Filtered by category, kind, words, availability; most used first.
- What ran: an intention analysed is counted — this week, by category, the
  most used; each capability with its history.
- Turned off by an admin, saying why — its analyses no longer run it, said
  so — and on again; a member may not; another workspace is untouched.
- Kept at hand: « Mes capacités ».
- Discovered for a router: ranked, each with why.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.capabilities import sync_catalogue
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intention_decisions_api import _asked, queued  # noqa: F401 — a fixture
from tests.test_resolution_job import _source
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/capabilities"
ARCHITECT = "application-architecture"


async def _list(client: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get(API, params=params)
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()
    return found


def _by_key(found: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {c["key"]: c for c in found}


async def _connect(acme: dict[str, uuid.UUID], kind: str) -> None:
    """A source of this kind, connected and read from."""
    source = await _source(acme["acme"], f"{kind} {uuid.uuid4().hex[:6]}")
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE sources SET kind = :k, status = 'active' WHERE id = :s"),
                {"k": kind, "s": source},
            )
            await session.commit()


async def test_the_catalogue_for_a_workspace_and_a_person(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    await sync_catalogue()
    response = await client.get(API)
    assert response.status_code == 200
    # An agent's instructions never leave the server.
    assert "PRINCIPE ABSOLU" not in response.text and "ENGIE" not in response.text
    found = _by_key(response.json())
    assert {"standing", "ownership", "dependencies", ARCHITECT} <= set(found)
    assert found["ownership"]["available"] is True
    assert (found["ownership"]["kind"], found["ownership"]["category"]) == ("rules", "knowledge")
    assert found["ownership"]["registered_at"] is not None

    architect = found[ARCHITECT]
    assert (architect["kind"], architect["lifecycle"], architect["version"]) == (
        "agent",
        "active",
        "18.0.0",
    )
    assert [i["name"] for i in architect["inputs"]] == ["parcours", "perimetre", "vue_applicative"]
    assert (architect["output"], architect["formats"]) == ("document", ["pptx", "pdf"])
    assert architect["available"] is False
    # Agents run (LEKA-395): what is in its way is what it needs.
    assert [r["code"] for r in architect["reasons"]] == ["missing_source", "no_model"]
    assert architect["sources"] == [{"any_of": ["confluence", "microsoft_365"], "connected": False}]
    # What does not run, only when asked.
    assert "correlate-deploy-with-latency" not in found
    drafts = await _list(client, lifecycle="draft")
    assert {c["key"] for c in drafts} >= {"correlate-deploy-with-latency"}
    assert all(c["lifecycle"] == "draft" for c in drafts)

    # A source to read from, connected: one reason less.
    await _connect(acme, "confluence")
    architect = _by_key(await _list(client))[ARCHITECT]
    assert [r["code"] for r in architect["reasons"]] == ["no_model"]
    assert architect["sources"][0]["connected"] is True

    # Filtered.
    assert {c["key"] for c in await _list(client, category="architecture")} >= {
        ARCHITECT,
        "dependencies",
    }
    assert [c["key"] for c in await _list(client, kind="agent")] == [ARCHITECT]
    assert [c["key"] for c in await _list(client, q="architecte")] == [ARCHITECT]
    assert ARCHITECT not in {c["key"] for c in await _list(client, available="true")}
    names = [c["title"] for c in await _list(client, sort="name")]
    assert names == sorted(names, key=str.lower)

    detail = (await client.get(f"{API}/{ARCHITECT}")).json()
    assert detail["history"][0]["version"] == "18.0.0"
    assert detail["events"][0]["kind"] == "registered"
    assert "instructions" not in detail
    assert (await client.get(f"{API}/nothing-like-this")).status_code == 404


async def test_what_ran_is_counted(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    await sync_catalogue()
    before = (await client.get(f"{API}/summary")).json()
    assert before["runs"] == 0 and before["top"] == []
    assert before["available"] < before["total"]  # the architect waits for a model
    assert {c["category"] for c in before["categories"]} >= {"architecture", "knowledge"}
    assert len(before["days"]) == 7

    await _asked(client, acme)  # analysed as the job would
    after = (await client.get(f"{API}/summary")).json()
    assert after["runs"] > 0
    assert after["analysis_ms"] is not None
    assert "standing" in {t["key"] for t in after["top"]}
    assert sum(sum(d["runs"].values()) for d in after["days"]) == after["runs"]

    standing = (await client.get(f"{API}/standing")).json()
    assert standing["usage"]["runs"] == 1
    assert sum(d["runs"].get("knowledge", 0) for d in standing["days"]) == 1
    # The most used first.
    assert (await _list(client))[0]["key"] in {t["key"] for t in after["top"]}


async def test_turned_off_for_the_workspace_saying_why(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    url = f"{API}/ownership/settings"
    _as(identity, acme, "member")
    assert (await client.put(url, json={"enabled": False, "reason": "x"})).status_code == 403
    _as(identity, acme, "admin")
    said = await client.put(url, json={"enabled": False})
    assert said.status_code == 422
    assert said.json()["error"]["details"][0]["field"] == "reason"

    off = (await client.put(url, json={"enabled": False, "reason": "Pas encore."})).json()
    assert (off["enabled"], off["enabled_reason"], off["available"]) == (
        False,
        "Pas encore.",
        False,
    )
    assert [r["code"] for r in off["reasons"]] == ["disabled"]
    # Its analyses no longer run it, and say so.
    _as(identity, acme, "member")
    asked = await _asked(client, acme, "Qui est responsable de Billing API ?")
    analysis = (await client.get(f"/api/v1/intentions/{asked['id']}/analysis")).json()
    choice = next(c for c in analysis["selection"] if c["name"] == "ownership")
    assert (choice["chosen"], choice["reason"]) == (False, "disabled")
    assert "ownership" not in {s["name"] for s in analysis["steps"]}

    # Another workspace is untouched.
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/ownership")).json()["enabled"] is True

    _as(identity, acme, "admin")
    on = (await client.put(url, json={"enabled": True})).json()
    assert (on["enabled"], on["available"]) == (True, True)
    assert (await client.put(f"{API}/nothing/settings", json={"enabled": True})).status_code == 404


async def test_kept_at_hand(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    assert await _list(client, view="mine") == []
    assert (await client.put(f"{API}/dependencies/favourite")).status_code == 204
    assert (await client.put(f"{API}/dependencies/favourite")).status_code == 204
    mine = await _list(client, view="mine")
    assert [(c["key"], c["favourite"]) for c in mine] == [("dependencies", True)]
    # Someone else's are their own.
    _as(identity, acme, "admin")
    assert await _list(client, view="mine") == []
    _as(identity, acme, "member")
    assert (await client.delete(f"{API}/dependencies/favourite")).status_code == 204
    assert await _list(client, view="mine") == []
    assert (await client.put(f"{API}/nothing/favourite")).status_code == 404


async def test_discovered_for_a_router(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    owner = await client.post(
        f"{API}/discover",
        json={"goal": "find_owner", "kind": "ownership", "text": "Qui est responsable ?"},
    )
    assert owner.status_code == 200
    first = owner.json()[0]
    assert first["capability"]["key"] == "ownership"
    assert first["reasons"][:2] == ["goal", "kind"]

    deck = (
        await client.post(
            f"{API}/discover",
            json={
                "goal": "map_dependencies",
                "entity_types": ["application"],
                "text": "Construis l'architecture du parcours Paiement CB",
            },
        )
    ).json()
    assert deck[0]["capability"]["key"] == ARCHITECT
    assert deck[0]["capability"]["available"] is False
    only = (
        await client.post(
            f"{API}/discover",
            json={"goal": "map_dependencies", "available_only": True},
        )
    ).json()
    assert ARCHITECT not in {m["capability"]["key"] for m in only}
