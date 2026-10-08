"""A workspace's language model, over HTTP (LEKA-394).

What these protect:
- Anyone in the workspace reads what answers here: Gemini 3.8 Flash by
  default, its list price and the one to come; the providers one may bring
  and what each takes; who would answer, in order — nobody when LEKA holds
  no key.
- An admin brings the company's own model — an Azure OpenAI here: what it
  lacks is refused, field by field; an address that is not public https is
  refused; once saved, it answers first. Its key is never sent back — its
  last four characters are; a later change keeps it, a new provider asks
  for a new one. A member changes nothing.
- Tested: it answered, said, and marked so; removed: LEKA's answers again.
- What was asked of models: counted, priced, LEKA's and the workspace's
  own apart, by day, by model, by purpose — this workspace's only.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from leka.capabilities import ModelCall, sync_catalogue
from leka.capabilities.gateway import service, workspace
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

API = "/api/v1/models"
AZURE = {
    "provider": "azure_openai",
    "model": "gpt-prod",
    "base_url": "https://acme-ai.openai.azure.com",
    "api_version": "2024-10-21",
    "api_key": "azure-secret-key-9876",
}


@pytest.fixture
def leka_holds_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = settings.model_copy(
        update={
            "google_api_key": SecretStr("g-key"),
            "mistral_api_key": None,
            "anthropic_api_key": None,
            "llm_fallbacks": "",
        }
    )
    monkeypatch.setattr(service, "settings", configured)
    monkeypatch.setattr(workspace, "settings", configured)


async def test_anyone_reads_what_answers_here(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nothing = settings.model_copy(
        update={"google_api_key": None, "mistral_api_key": None, "anthropic_api_key": None}
    )
    monkeypatch.setattr(service, "settings", nothing)
    monkeypatch.setattr(workspace, "settings", nothing)
    _as(identity, acme, "member")
    response = await client.get(API)
    assert response.status_code == 200, response.text
    seen = response.json()
    assert (seen["default"]["provider"], seen["default"]["model"]) == ("google", "gemini-3.8-flash")
    assert seen["default"]["title"] == "Gemini 3.8 Flash"
    assert seen["default"]["price"]["per_million_in"] == 0.75
    assert seen["default"]["next_price"] == {
        "since": "2027-01-01",
        "per_million_in": 1.5,
        "per_million_out": 7.5,
    }
    providers = {p["name"]: p for p in seen["providers"]}
    assert set(providers) == {"google", "mistral", "openai", "azure_openai", "anthropic"}
    assert providers["azure_openai"]["needs"] == ["key", "model", "url"]
    # No key held: nothing answers, and it is said.
    assert (seen["ready"], seen["default_ready"], seen["answering"]) == (False, False, [])
    assert seen["own"] is None


async def test_an_admin_brings_the_company_model_and_its_key_never_comes_back(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka_holds_gemini: None,
) -> None:
    _as(identity, acme, "admin")
    without_key = {k: v for k, v in AZURE.items() if k != "api_key"}
    refused = await client.put(f"{API}/settings", json=without_key)
    assert refused.status_code == 422
    assert refused.json()["error"]["details"][0]["field"] == "api_key"
    refused = await client.put(f"{API}/settings", json={**AZURE, "base_url": None})
    assert refused.json()["error"]["details"][0]["field"] == "base_url"
    refused = await client.put(f"{API}/settings", json={**AZURE, "base_url": "http://10.0.0.4"})
    assert refused.status_code == 422

    saved = await client.put(f"{API}/settings", json=AZURE)
    assert saved.status_code == 200, saved.text
    assert "azure-secret-key-9876" not in saved.text
    own = saved.json()["own"]
    assert (own["provider"], own["model"], own["key_hint"], own["status"]) == (
        "azure_openai",
        "gpt-prod",
        "9876",
        "untested",
    )
    assert [(a["provider"], a["why"]) for a in saved.json()["answering"]] == [
        ("azure_openai", "own"),
        ("google", "default"),
    ]

    # A later change keeps the key; "ours only" leaves LEKA's out.
    kept = await client.put(
        f"{API}/settings", json={**without_key, "model": "gpt-prod-2", "exclusive": True}
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["own"]["key_hint"] == "9876"
    assert [a["why"] for a in kept.json()["answering"]] == ["own"]
    # Another provider: a key is one vendor's.
    other = await client.put(f"{API}/settings", json={"provider": "mistral"})
    assert other.json()["error"]["details"][0]["field"] == "api_key"

    _as(identity, acme, "member")
    forbidden = await client.put(f"{API}/settings", json=AZURE)
    assert forbidden.status_code == 403
    assert (await client.delete(f"{API}/settings")).status_code == 403


async def test_tested_then_removed(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka_holds_gemini: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[httpx.Request] = []

    def azure(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(
            200,
            json={
                "model": "gpt-4.1-2025-04-14",
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 1},
            },
        )

    # The customer's address goes through the public-only transport: here,
    # the scripted one in its place.
    monkeypatch.setattr(service, "PublicTransport", lambda: httpx.MockTransport(azure))
    _as(identity, acme, "admin")
    assert (await client.put(f"{API}/settings", json=AZURE)).status_code == 200
    tested = await client.post(f"{API}/settings/test")
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is True
    assert tested.json()["version"] == "gpt-4.1-2025-04-14"
    assert asked[0].headers["api-key"] == "azure-secret-key-9876"
    assert (await client.get(API)).json()["own"]["status"] == "ok"

    assert (await client.delete(f"{API}/settings")).status_code == 204
    assert (await client.delete(f"{API}/settings")).status_code == 404
    seen = (await client.get(API)).json()
    assert seen["own"] is None
    assert [a["why"] for a in seen["answering"]] == ["default"]


def _call(workspace_id: uuid.UUID, **fields: Any) -> ModelCall:
    base: dict[str, Any] = {
        "workspace_id": workspace_id,
        "id": uuid.uuid4(),
        "purpose": "intention.understanding",
        "tier": "fast",
        "provider": "google",
        "model": "gemini-3.8-flash",
        "version": "gemini-3.8-flash-001",
        "route": "default",
        "attempt": 1,
        "owner": "leka",
        "status": "ok",
        "tokens_in": 1000,
        "tokens_out": 200,
        "tokens_thinking": 0,
        "tool_calls": 0,
        "cost_usd": 0.0015,
        "latency_ms": 800,
        "at": datetime.now(UTC) - timedelta(hours=1),
    }
    return ModelCall(**{**base, **fields})


async def test_what_was_asked_of_models_is_counted_and_priced(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            session.add_all(
                [
                    _call(acme["acme"]),
                    _call(acme["acme"], purpose="capability.synthesis", latency_ms=1200),
                    _call(acme["acme"], status="failed", tokens_in=0, tokens_out=0, cost_usd=None),
                    _call(
                        acme["acme"],
                        provider="azure_openai",
                        model="gpt-prod",
                        owner="workspace",
                        route="own",
                        cost_usd=None,
                    ),
                ]
            )
            await session.commit()
    with workspace_scope(acme["globex"]):
        async with session_factory() as session:
            session.add(_call(acme["globex"]))
            await session.commit()

    _as(identity, acme, "member")
    response = await client.get(f"{API}/usage", params={"days": 7})
    assert response.status_code == 200, response.text
    usage = response.json()
    total = usage["total"]
    assert (total["calls"], total["failed"], total["tokens_in"]) == (4, 1, 3000)
    assert total["cost_usd"] == pytest.approx(0.003)
    # The workspace's own model: no list price, said rather than guessed.
    assert (usage["own"]["calls"], usage["own"]["unpriced"]) == (1, 1)
    assert usage["leka"]["calls"] == 3
    assert len(usage["by_day"]) == 7
    assert sum(d["calls"] for d in usage["by_day"]) == 4
    models = {(m["provider"], m["model"]): m for m in usage["by_model"]}
    assert models[("google", "gemini-3.8-flash")]["title"] == "Gemini 3.8 Flash"
    assert models[("google", "gemini-3.8-flash")]["tally"]["calls"] == 3
    purposes = [p["purpose"] for p in usage["by_purpose"]]
    assert purposes[0] == "intention.understanding"
    assert usage["latest"][0]["provider"] in {"google", "azure_openai"}


async def test_the_catalogue_says_which_model_runs_what_by_what_it_needs(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka_holds_gemini: None,
) -> None:
    """A capability's needs choose its model (LEKA-394): the synthesis needs
    a structured answer — Gemini can, so it is available and says so; an
    agent waits for its runtime still (LEKA-395)."""
    await sync_catalogue()
    _as(identity, acme, "member")
    response = await client.get("/api/v1/capabilities", params={"lifecycle": "active"})
    assert response.status_code == 200, response.text
    found = {c["key"]: c for c in response.json()}
    synthesis = found["synthesis"]
    assert (synthesis["kind"], synthesis["available"]) == ("model", True)
    assert synthesis["model_needs"] == {
        "structured": True,
        "tools": False,
        "context": 0,
        "quality": 2,
    }
    assert synthesis["answering"] == {
        "provider": "google",
        "model": "gemini-3.8-flash",
        "title": "Gemini 3.8 Flash",
        "owner": "leka",
    }
    architect = found["application-architecture"]
    assert "no_model" not in [r["code"] for r in architect["reasons"]]
    # And agents run (LEKA-395).
    assert "no_runtime" not in [r["code"] for r in architect["reasons"]]
    # LEKA's own rules need no model.
    assert (found["ownership"]["answering"], found["ownership"]["model_needs"]) == (None, None)
