"""The capability router (LEKA-398), over HTTP — on Acme's company model
(test_knowledge_graph).

What these protect: an intention asked is routed when it is first read —
who owns Billing API to LEKA's ownership analysis, on its goal and kind,
its context read; the routing is kept and read back, routed again when
asked or once the intention is asked again, a new decision beside the
earlier; words routed alone the same way.
The architect, matched, is left out while it cannot run here — no source,
no model — said why, LEKA's own taking its place; once it can, it is routed
to, saying what to ask before it runs. Another workspace's intention is not
found.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select

from leka.capabilities import CapabilityRouting, sync_catalogue
from leka.capabilities.gateway import service
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity
from tests.test_capabilities_api import _connect
from tests.test_context_engine import model
from tests.test_intention_decisions_api import queued  # noqa: F401 — a fixture
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1"
ARCHITECTURE = "Construis l'architecture du parcours Paiement CB sur le périmètre Digital"


@pytest.fixture
def leka_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = settings.model_copy(
        update={
            "google_api_key": SecretStr("g-key"),
            "mistral_api_key": None,
            "anthropic_api_key": None,
            "llm_fallbacks": "",
        }
    )
    monkeypatch.setattr(service, "settings", configured)


async def _route(client: AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/capabilities/route", json=body)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


async def _kept(workspace: uuid.UUID) -> int:
    with workspace_scope(workspace):
        async with session_factory() as session:
            return int(await session.scalar(select(func.count(CapabilityRouting.id))) or 0)


async def test_an_intention_is_routed_kept_and_routed_again(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    await sync_catalogue()
    created = await client.post(
        f"{API}/intentions", json={"text": "Qui est responsable de Billing API ?"}
    )
    assert created.status_code == 201, created.text
    intention = created.json()["intention"]["id"]

    first = await client.get(f"{API}/intentions/{intention}/routing")
    assert first.status_code == 200, first.text
    routing = first.json()
    assert (routing["subject_type"], routing["subject_id"]) == ("intention", intention)
    assert routing["outcome"] == "routed"
    assert routing["selected"][0] == "ownership"
    best = routing["candidates"][0]
    assert best["key"] == "ownership" and best["selected"] is True
    assert {s["code"] for s in best["signals"]} >= {"goal", "kind"}
    assert routing["query"]["goal"] == "find_owner"
    # Its context was read.
    assert "service" in routing["query"]["context_types"]
    assert "synthesis" in routing["background"]

    # Kept: read back as decided.
    again = (await client.get(f"{API}/intentions/{intention}/routing")).json()
    assert again["id"] == routing["id"]
    assert await _kept(acme["acme"]) == 1
    # Routed again when asked: a new decision beside the earlier.
    rerouted = await client.post(f"{API}/intentions/{intention}/routing")
    assert rerouted.status_code == 200
    assert rerouted.json()["id"] != routing["id"]
    assert await _kept(acme["acme"]) == 2
    assert rerouted.json()["query"]["intention_version"] == 1

    # Asked again — answered, reworded: routed again when read, never left
    # as it was (2026-10-29).
    asked = await client.post(
        f"{API}/intentions/{intention}/ask", json={"text": "Qu'a changé sur Billing API ?"}
    )
    assert asked.status_code == 200, asked.text
    now = (await client.get(f"{API}/intentions/{intention}/routing")).json()
    assert now["id"] != rerouted.json()["id"]
    assert (now["query"]["intention_version"], now["query"]["goal"]) == (2, "find_change")
    assert (await client.get(f"{API}/intentions/{intention}/routing")).json()["id"] == now["id"]
    assert await _kept(acme["acme"]) == 3

    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/intentions/{intention}/routing")).status_code == 404
    assert (await client.get(f"{API}/intentions/{uuid.uuid4()}/routing")).status_code == 404


async def test_the_architect_is_left_out_until_it_can_run_then_routed_to(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: None,
) -> None:
    await sync_catalogue()
    asked = {"text": ARCHITECTURE, "goal": "map_dependencies", "kind": "dependency"}
    without = await _route(client, **asked)
    assert without["subject_type"] == "request"
    # LEKA's own take its place: the library's architecture analysis
    # (LEKA-400), which needs no source, among them.
    assert "architecture-analysis" in without["selected"]
    [architect] = [c for c in without["excluded"] if c["key"] == "application-architecture"]
    assert architect["eligible"] is True and architect["available"] is False
    assert [r["code"] for r in architect["reasons"]] == ["missing_source"]

    await _connect(acme, "confluence")
    routed = await _route(client, **asked)
    assert routed["outcome"] == "routed"
    assert routed["selected"][0] == "application-architecture"
    first = routed["candidates"][0]
    assert first["needs_inputs"] == ["parcours", "perimetre"]
    assert "words" in {s["code"] for s in first["signals"]}

    # Words alone, pointing nowhere: clarified, with what it could mean.
    vague = await _route(client, text="bonjour à tous")
    assert (vague["outcome"], vague["why"]) == ("clarify", "no_goal")
