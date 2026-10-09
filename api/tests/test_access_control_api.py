"""The authorisation model (LEKA-402), end to end — Acme's company model
(test_knowledge_graph), its member, its admin, and Globex's admin.

What these protect:
- An entity restricted by an admin, saying why, is gone for a member —
  asked directly (404, as another workspace's would be), searched, as the
  other end of a relationship, in the dependencies walked — while the admin
  still sees it; lifted, everyone does again. A member may not restrict.
- Work done for the member sees what they may: an agent's search leaves the
  restricted entity out.
- A capability's own permission is decided before anything runs: an agent
  only who may approve may use, refused to a member (403), allowed to an
  admin.
- Every refusal and every write allowed is kept — who, as which role, what,
  on what, by which rule and why — and read back by an admin only; the
  trail is never changed.
- A suspended workspace refuses a write before the role is looked at, and
  says so.
- Another workspace restricts nothing here, reads nothing of here.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import importlib
import json
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from leka.capabilities import find, sync_catalogue
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import (
    Script,
    _run,
    gemini,
    leka_gemini,  # noqa: F401 — a fixture
    queued,  # noqa: F401 — a fixture
)
from tests.test_context_engine import model
from tests.test_knowledge_graph import BILLING, CHECKOUT
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1"
catalogue_module = importlib.import_module("leka.capabilities.catalogue")


async def _restrict(client: AsyncClient, entity: uuid.UUID, code: int = 200) -> Any:
    response = await client.put(
        f"{API}/governance/restrictions/{entity}", json={"reason": "Données de paiement"}
    )
    assert response.status_code == code, response.text
    return response.json() if response.content else None


async def _decisions(client: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get(f"{API}/governance/decisions", params=params)
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()
    return found


async def _sql(workspace: uuid.UUID, statement: str, **params: Any) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(text(statement), params)
            await session.commit()


def _names(found: dict[str, Any]) -> set[str]:
    return {hit["entity"]["name"] for hit in found["entities"]}


async def test_a_restricted_entity_is_gone_for_a_member_everywhere(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    billing, checkout = model[BILLING], model[CHECKOUT]
    # A member may not restrict — refused, and the refusal kept.
    await _restrict(client, billing, 403)

    _as(identity, acme, "admin")
    restricted = await _restrict(client, billing)
    assert (restricted["name"], restricted["reason"]) == ("Billing API", "Données de paiement")
    assert (await client.get(f"{API}/knowledge/entities/{billing}")).status_code == 200
    assert [
        r["entity_id"] for r in (await client.get(f"{API}/governance/restrictions")).json()
    ] == [str(billing)]

    _as(identity, acme, "member")
    # Asked directly: not found — as another workspace's would be.
    assert (await client.get(f"{API}/knowledge/entities/{billing}")).status_code == 404
    searched = (await client.get(f"{API}/knowledge/search", params={"q": "billing"})).json()
    assert "Billing API" not in _names(searched)
    # Nor as the other end of Checkout's relationships.
    seen = (await client.get(f"{API}/knowledge/entities/{checkout}")).json()
    assert str(billing) not in [link["other"]["id"] for link in seen["relationships"]]
    # Nor walked through.
    walked = await client.get(
        f"{API}/knowledge/entities/{billing}/dependencies", params={"direction": "upstream"}
    )
    assert walked.status_code == 404
    # The member may not read the trail, nor the restrictions.
    assert (await client.get(f"{API}/governance/decisions")).status_code == 403
    assert (await client.get(f"{API}/governance/restrictions")).status_code == 403

    _as(identity, acme, "admin")
    refused = await _decisions(client, decision="deny")
    said = {(d["permission"], d["rule"], d["reason"], d["role"]) for d in refused}
    assert ("entity:restrict", "role", "role_lacks_permission", "member") in said
    assert ("workspace:read", "restriction", "restricted", "member") in said
    restricting = [
        d for d in await _decisions(client, decision="allow") if d["action"] == "entity:restrict"
    ]
    assert restricting and restricting[0]["role"] == "admin"
    assert restricting[0]["route"].startswith("PUT /api/v1/governance/restrictions/")

    # Lifted: everyone sees it again.
    assert (await client.delete(f"{API}/governance/restrictions/{billing}")).status_code == 204
    _as(identity, acme, "member")
    assert (await client.get(f"{API}/knowledge/entities/{billing}")).status_code == 200


async def test_work_done_for_a_member_sees_what_they_may(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    await sync_catalogue()
    _as(identity, acme, "admin")
    await _restrict(client, model[BILLING])
    _as(identity, acme, "member")
    script = leka_gemini(
        gemini(call={"name": "search_entities", "args": {"query": "billing"}}),
        gemini("# Rien de restreint."),
    )
    started = await client.post(
        f"{API}/agent-runs", json={"key": "architecture-analysis", "inputs": {"sujet": "Checkout"}}
    )
    assert started.status_code == 202, started.text
    assert await _run(acme, started.json()["id"]) == {"status": "succeeded"}
    part = script.asked[1]["contents"][-1]["parts"][0]["functionResponse"]
    found = json.loads(part["response"]["result"])["found"]
    assert "Billing API" not in [f["name"] for f in found]
    # Nor in the context it was given.
    given = json.loads(script.asked[0]["contents"][0]["parts"][0]["text"])
    assert str(model[BILLING]) not in [e["id"] for e in given["context"]]


async def test_a_capability_s_permission_is_decided_before_it_runs(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leka_gemini()
    await sync_catalogue()
    agent = find("architecture-analysis")
    assert agent is not None
    guarded = replace(agent, key="analysis-for-approvers", permission="intention:approve")
    every = catalogue_module.catalogue()
    monkeypatch.setattr(catalogue_module, "catalogue", lambda: (*every, guarded))
    monkeypatch.setattr(
        importlib.import_module("leka.api.agent_runs"),
        "find",
        lambda key: guarded if key == guarded.key else find(key),
    )

    body = {"key": "analysis-for-approvers", "inputs": {}}
    refused = await client.post(f"{API}/agent-runs", json=body)
    assert refused.status_code == 403
    assert (await client.get(f"{API}/agent-runs")).json() == []

    _as(identity, acme, "admin")
    assert (await client.post(f"{API}/agent-runs", json=body)).status_code == 202
    runs = await _decisions(client, action="agent:run")
    assert [(d["decision"], d["role"], d["resource_id"]) for d in runs] == [
        ("allow", "admin", "analysis-for-approvers"),
        ("deny", "member", "analysis-for-approvers"),
    ]


async def test_the_trail_is_never_changed_and_suspended_refuses_writes(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    await _restrict(client, model[BILLING])
    with pytest.raises(DBAPIError, match="append-only"):
        await _sql(acme["acme"], "UPDATE access_decisions SET decision = 'deny'")

    await _sql(
        acme["acme"], "UPDATE workspaces SET status = 'suspended' WHERE id = :w", w=acme["acme"]
    )
    try:
        refused = await client.delete(f"{API}/governance/restrictions/{model[BILLING]}")
        assert refused.status_code == 403
        assert "suspended" in refused.text
        # Reading stays allowed.
        assert (await client.get(f"{API}/governance/restrictions")).status_code == 200
        said = await _decisions(client, decision="deny")
        assert said[0]["reason"] == "workspace_suspended" and said[0]["rule"] == "workspace"
    finally:
        await _sql(
            acme["acme"], "UPDATE workspaces SET status = 'active' WHERE id = :w", w=acme["acme"]
        )


async def test_another_workspace_restricts_nothing_and_reads_nothing_here(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    await _restrict(client, model[BILLING])

    _as(identity, acme, "other_admin")
    # Acme's entity is not Globex's: not found, not "forbidden".
    await _restrict(client, model[CHECKOUT], 404)
    assert (await client.get(f"{API}/knowledge/entities/{model[CHECKOUT]}")).status_code == 404
    assert (await client.get(f"{API}/governance/restrictions")).json() == []
    assert all(d["role"] == "admin" for d in await _decisions(client))
    assert not [d for d in await _decisions(client) if d["resource_id"] == str(model[BILLING])]
