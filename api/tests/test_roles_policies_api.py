"""Roles and policies (LEKA-403), end to end — Acme (test_knowledge_graph),
its member and admin, Globex's admin.

What these protect:
- A role of the workspace's own, created by an admin, given to a member on
  the base their seat has: the member holds what it adds — in force at their
  next request — and loses what it takes away; given on another base,
  refused (409); held, it cannot be deleted; taken back, their seat's again.
- A policy refuses what it names before anything runs — an agent of medium
  risk, refused to a member, the refusal kept with the policy that decided —
  while the exception a higher priority grants Tech Leads lets them through;
  a policy on a permission refuses the route itself.
- Enforcement follows execution: a policy created after an agent was queued
  fails its run when it comes to run.
- A decision can be asked without acting, and answers as the run would.
- Every change — a role, an assignment, a policy — is kept, before and
  after, never rewritten; a member manages none; another workspace sees none.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from leka.capabilities import sync_catalogue
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import (
    Script,
    _run,
    gemini,
    leka_gemini,  # noqa: F401 — a fixture
    queued,  # noqa: F401 — a fixture
)
from tests.test_capabilities_api import _connect
from tests.test_context_engine import model
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/governance"
ARCHITECT = "application-architecture"  # an agent of medium risk
LEAD = {
    "name": "Tech Lead",
    "base": "member",
    "added": ["intention:approve", "job:read"],
    "removed": ["source:read"],
}
NO_RISKY_AGENTS = {
    "name": "Pas d'agent risqué",
    "effect": "deny",
    "actions": ["agent:run"],
    "resource_types": ["capability"],
    "risk_at_least": "medium",
    "priority": 50,
}
LEADS_MAY = {
    "name": "Les Tech Leads peuvent",
    "effect": "allow",
    "actions": ["agent:run"],
    "roles": ["tech-lead"],
    "priority": 60,
}


async def _ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json() if response.content else None


async def _mine(client: AsyncClient) -> dict[str, Any]:
    found: dict[str, Any] = await _ok(await client.get(f"{API}/access"))
    return found


async def _sql(workspace: uuid.UUID, statement: str, **params: Any) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(text(statement), params)
            await session.commit()


async def test_a_role_of_its_own_given_held_and_taken_back(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    member = acme["member"]
    # A member manages no role.
    assert (await client.put(f"{API}/roles/tech-lead", json=LEAD)).status_code == 403

    _as(identity, acme, "admin")
    made = await _ok(await client.put(f"{API}/roles/tech-lead", json=LEAD))
    assert "intention:approve" in made["permissions"] and "source:read" not in made["permissions"]
    refused = await client.put(
        f"{API}/roles/owner-ish", json={**LEAD, "added": ["workspace:delete"]}
    )
    assert refused.status_code == 422 and "only an owner" in refused.text
    await _ok(await client.put(f"{API}/assignments/{member}", json={"role": "tech-lead"}))

    _as(identity, acme, "member")
    mine = await _mine(client)
    assert mine["custom_role"] == "tech-lead"
    assert "intention:approve" in mine["mine"] and "source:read" not in mine["mine"]
    # Taken away: the route refuses.
    assert (await client.get("/api/v1/sources")).status_code == 403

    _as(identity, acme, "admin")
    # Held: not deleted. On another base: not given.
    assert (await client.delete(f"{API}/roles/tech-lead")).status_code == 409
    await _ok(
        await client.put(
            f"{API}/roles/ops",
            json={**LEAD, "name": "Ops", "base": "admin", "added": [], "removed": ["job:read"]},
        )
    )
    wrong = await client.put(f"{API}/assignments/{member}", json={"role": "ops"})
    assert wrong.status_code == 409 and "their seat is member" in wrong.text
    # Taken back: their seat's again.
    await _ok(await client.put(f"{API}/assignments/{member}", json={"role": None}))
    _as(identity, acme, "member")
    assert (await _mine(client))["custom_role"] is None
    assert (await client.get("/api/v1/sources")).status_code == 200

    _as(identity, acme, "admin")
    kinds = [(e["subject_type"], e["kind"]) for e in await _ok(await client.get(f"{API}/history"))]
    assert ("role", "created") in kinds
    assert ("assignment", "assigned") in kinds and ("assignment", "unassigned") in kinds


async def test_a_policy_refuses_before_anything_runs_an_exception_lets_leads_through(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    leka_gemini()
    await sync_catalogue()
    await _connect(acme, "confluence")
    _as(identity, acme, "admin")
    await _ok(await client.put(f"{API}/roles/tech-lead", json=LEAD))
    denying = await _ok(await client.post(f"{API}/policies", json=NO_RISKY_AGENTS), 201)
    await _ok(await client.post(f"{API}/policies", json=LEADS_MAY), 201)

    body = {"key": ARCHITECT, "inputs": {"parcours": "Paiement CB", "perimetre": "Digital"}}
    _as(identity, acme, "member")
    refused = await client.post("/api/v1/agent-runs", json=body)
    assert refused.status_code == 403
    assert "Pas d'agent risqué" in refused.text
    # Asked without acting: the same answer.
    _as(identity, acme, "admin")
    asked = await _ok(
        await client.post(
            f"{API}/evaluate",
            json={
                "role": "member",
                "permission": "intention:create",
                "action": "agent:run",
                "resource_type": "capability",
                "risk": "medium",
            },
        )
    )
    assert (asked["allowed"], asked["reason"], asked["policy"]) == (
        False,
        "policy_denied",
        denying["id"],
    )
    as_lead = await _ok(
        await client.post(
            f"{API}/evaluate",
            json={
                "custom_role": "tech-lead",
                "permission": "intention:create",
                "action": "agent:run",
                "resource_type": "capability",
                "risk": "medium",
            },
        )
    )
    assert (as_lead["allowed"], as_lead["reason"]) == (True, "policy_allows")

    await _ok(await client.put(f"{API}/assignments/{acme['member']}", json={"role": "tech-lead"}))
    _as(identity, acme, "member")
    assert (await client.post("/api/v1/agent-runs", json=body)).status_code == 202

    _as(identity, acme, "admin")
    kept = await _ok(await client.get(f"{API}/decisions", params={"action": "agent:run"}))
    assert [(d["decision"], d["reason"]) for d in kept] == [
        ("allow", "policy_allows"),
        ("deny", "policy_denied"),
    ]

    # A policy on a permission refuses the route itself.
    await _ok(
        await client.post(
            f"{API}/policies",
            json={
                "name": "Pas d'intention",
                "effect": "deny",
                "actions": ["intention:create"],
                "roles": ["member"],
            },
        ),
        201,
    )
    _as(identity, acme, "member")
    blocked = await client.post(
        "/api/v1/intentions", json={"text": "Qui est responsable de Billing API ?"}
    )
    assert blocked.status_code == 403 and "Pas d'intention" in blocked.text


async def test_a_policy_made_after_a_run_was_queued_fails_it_when_it_runs(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    leka_gemini(gemini("# Jamais écrit."))
    await sync_catalogue()
    await _connect(acme, "confluence")
    started = await _ok(
        await client.post(
            "/api/v1/agent-runs",
            json={"key": ARCHITECT, "inputs": {"parcours": "Paiement CB", "perimetre": "Digital"}},
        ),
        202,
    )
    _as(identity, acme, "admin")
    await _ok(await client.post(f"{API}/policies", json=NO_RISKY_AGENTS), 201)
    assert await _run(acme, started["id"]) == {"status": "failed", "error": "not_permitted"}
    run = await _ok(await client.get(f"/api/v1/agent-runs/{started['id']}"))
    assert run["events"][-1]["detail"]["refused"] == "policy_denied"


async def test_every_change_kept_never_rewritten_and_the_workspace_s_own(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    made = await _ok(await client.post(f"{API}/policies", json=NO_RISKY_AGENTS), 201)
    await _ok(
        await client.put(f"{API}/policies/{made['id']}", json={**NO_RISKY_AGENTS, "priority": 70})
    )
    assert (await client.delete(f"{API}/policies/{made['id']}")).status_code == 204
    changes = await _ok(await client.get(f"{API}/history", params={"subject_type": "policy"}))
    assert [c["kind"] for c in changes] == ["deleted", "updated", "created"]
    updated = changes[1]
    assert (updated["before"]["priority"], updated["after"]["priority"]) == (50, 70)
    with pytest.raises(DBAPIError, match="append-only"):
        await _sql(acme["acme"], "UPDATE governance_events SET kind = 'created'")
    bad = await client.post(f"{API}/policies", json={**NO_RISKY_AGENTS, "actions": ["fly"]})
    assert bad.status_code == 422

    _as(identity, acme, "other_admin")
    assert await _ok(await client.get(f"{API}/history")) == []
    assert await _ok(await client.get(f"{API}/policies")) == []
