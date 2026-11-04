"""A workspace's own language model, over HTTP (LEKA-394, LEKA-530).

What these protect:
- Anyone in the workspace reads whether its contract brings a model of its
  own, and the providers it may bring — never LEKA's models, their prices,
  an order of answer, the tokens or the cost of what was asked: the LEKA
  team assigns a model to each agent (agents/models.yaml) and reads what it
  used internally.
- No customer chooses or switches LEKA's model: the routes that did are
  gone, and what was asked of models is not served to customers.
- A plan without its own model (every public plan) cannot bring one; under
  an Enterprise contract an admin brings the company's — an Azure OpenAI
  here: what it lacks is refused, field by field; an address that is not
  public https is refused; its key is never sent back, its last four
  characters are; a later change keeps it, a new provider asks for a new
  one. A member changes nothing.
- Tested: it answered, said, and marked so; removed: LEKA's answers again —
  on any plan, so a model brought before stays the workspace's to remove.
- A capability says whose model would run it, never which.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from leka.capabilities import WorkspaceModel, sync_catalogue
from leka.capabilities.gateway import service
from leka.core.config import settings
from leka.db import session_factory, workspace_scope
from leka.governance import set_plan
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
# What a customer must never read of LEKA's models.
LEKA_S = ("price", "per_million", "default", "answering", "choosable", "fallbacks", "tokens")


@pytest.fixture
def leka_holds_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = settings.model_copy(
        update={"google_api_key": SecretStr("g-key"), "mistral_api_key": None}
    )
    monkeypatch.setattr(service, "settings", configured)


async def _enterprise(workspace: uuid.UUID) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await set_plan(session, workspace, "enterprise", by="test", reason="LEKA-530")
            await session.commit()


async def test_anyone_reads_whether_its_contract_brings_its_own_model_never_leka_s(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "member")
    response = await client.get(API)
    assert response.status_code == 200, response.text
    seen = response.json()
    assert (seen["offered"], seen["own"]) == (False, None)
    providers = {p["name"]: p for p in seen["providers"]}
    assert set(providers) == {"google", "mistral", "openai", "azure_openai", "anthropic"}
    assert providers["azure_openai"]["needs"] == ["key", "model", "url"]
    assert set(providers["google"]) == {"name", "title", "needs", "default_model"}
    for word in LEKA_S:
        assert word not in response.text.replace("default_model", ""), word

    # Choosing LEKA's model, reading what was asked of models: gone.
    _as(identity, acme, "admin")
    mistral = {"provider": "mistral", "model": "mistral-large-latest"}
    assert (await client.put(f"{API}/default", json=mistral)).status_code in (404, 405)
    assert (await client.delete(f"{API}/default")).status_code in (404, 405)
    assert (await client.get(f"{API}/usage")).status_code in (404, 405)

    await _enterprise(acme["acme"])
    assert (await client.get(API)).json()["offered"] is True


async def test_a_public_plan_cannot_bring_its_own_model_an_enterprise_contract_can(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka_holds_gemini: None,
) -> None:
    _as(identity, acme, "admin")
    refused = await client.put(f"{API}/settings", json=AZURE)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "plan_required"

    await _enterprise(acme["acme"])
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
    # A later change keeps the key.
    kept = await client.put(
        f"{API}/settings", json={**without_key, "model": "gpt-prod-2", "exclusive": True}
    )
    assert kept.status_code == 200, kept.text
    assert (kept.json()["own"]["key_hint"], kept.json()["own"]["exclusive"]) == ("9876", True)
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
    await _enterprise(acme["acme"])
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
    assert (await client.get(API)).json()["own"] is None


async def test_a_model_brought_before_stays_the_workspace_s_to_see_and_remove(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    """Brought on a public plan before LEKA-530: kept, said, removable — and
    never changed again there."""
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            session.add(
                WorkspaceModel(
                    workspace_id=acme["acme"],
                    id=uuid.uuid4(),
                    provider="mistral",
                    model="mistral-medium-latest",
                    key_hint="4321",
                    enabled=True,
                    changed_at=datetime.now(UTC),
                )
            )
            await session.commit()
    _as(identity, acme, "admin")
    seen = (await client.get(API)).json()
    assert (seen["offered"], seen["own"]["model"]) == (False, "mistral-medium-latest")
    assert (await client.put(f"{API}/settings", json=AZURE)).status_code == 403
    assert (await client.delete(f"{API}/settings")).status_code == 204


async def test_a_capability_says_whose_model_would_run_it_never_which(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka_holds_gemini: None,
) -> None:
    await sync_catalogue()
    _as(identity, acme, "member")
    response = await client.get("/api/v1/capabilities", params={"lifecycle": "active"})
    assert response.status_code == 200, response.text
    found = {c["key"]: c for c in response.json()}
    synthesis = found["synthesis"]
    assert (synthesis["kind"], synthesis["available"]) == ("model", True)
    assert synthesis["answering"] == {"owner": "leka"}
    architect = found["application-architecture"]
    assert architect["answering"] == {"owner": "leka"}
    assert "no_model" not in [r["code"] for r in architect["reasons"]]
    assert "gemini" not in response.text.lower()
    # LEKA's own rules need no model.
    assert (found["ownership"]["answering"], found["ownership"]["model_needs"]) == (None, None)
