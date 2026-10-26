"""Dedicated agents (2026-10-25): an agent made for one organisation — the
application architect, on its documentation — assigned by LEKA from the
server (leka.ops.enterprise), never sold.

Acme has the architect assigned (tests/test_sources_api.py); Globex does not.

What these protect:
- Not assigned: never seen — not in the catalogue, its sheet a 404, not in
  what is sold —, never run (refused by the server), never named as a
  workflow's step; a run of that workflow skips it from the start.
- Assigned: seen, said dedicated, said its own in what is sold, run
  whatever the plan — Free included, LEKA's grant taken back.
- Never sold: in no plan, no bundle, no add-on.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import json
import uuid
from collections.abc import Callable

from httpx import AsyncClient
from sqlalchemy import select

from leka.billing import catalogue as offer
from leka.billing import end
from leka.billing.entitlements import EVERY
from leka.capabilities import WorkflowRunStep, execute_workflow, sync_catalogue
from leka.capabilities.registry import catalogue as registered
from leka.db import session_factory, workspace_scope
from leka.governance import set_plan
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401
from tests.test_workflow_runs_api import (
    Script,
    _detail,
    _intention,
    _start,
    _steps,
    scripted,
    workflows_queued,
)

_ = (model, scripted, workflows_queued)  # fixtures, requested by name
API = "/api/v1"
ARCHITECT = "application-architecture"
DOSSIER = "architecture-dossier"
PAID = {"plan_required", "not_owned", "not_for_sale"}


async def _why(client: AsyncClient, key: str) -> set[str]:
    found = (await client.get(f"{API}/capabilities/{key}")).json()
    return {r["code"] for r in found["reasons"]} & PAID


async def test_an_agent_dedicated_to_others_is_never_seen_nor_run(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await sync_catalogue()
    _as(identity, acme, "other_admin")
    listed = (await client.get(f"{API}/capabilities")).json()
    assert ARCHITECT not in {c["key"] for c in listed}
    assert all(c["dedicated"] is False for c in listed)
    assert (await client.get(f"{API}/capabilities/{ARCHITECT}")).status_code == 404
    # Refused by the server, not only a screen: as if it did not exist.
    started = await client.post(
        f"{API}/agent-runs",
        json={"key": ARCHITECT, "inputs": {"parcours": "Paiement CB", "perimetre": "Digital"}},
    )
    assert (started.status_code, started.json()["error"]["code"]) == (404, "not_found")
    sold = (await client.get(f"{API}/billing/add-ons")).json()
    assert ARCHITECT not in {a["key"] for a in sold["agents"]}
    assert sold["dedicated"] == []
    assert all(ARCHITECT not in b["agents"] for b in sold["bundles"])
    # The dossier can do without its deck: here, its step is never named.
    flow = (await client.get(f"{API}/workflows/{DOSSIER}")).json()
    assert [s["id"] for s in flow["steps"]] == ["standing", "dependencies", "documentation"]
    assert ARCHITECT not in json.dumps(flow["steps"])
    every = (await client.get(f"{API}/workflows")).json()
    assert ARCHITECT not in json.dumps([w["steps"] for w in every])


async def test_a_run_of_its_workflow_skips_it_from_the_start(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    scripted: Callable[[Script], list[str]],
) -> None:
    await sync_catalogue()
    _as(identity, acme, "other_admin")
    intention = await _intention(client)
    called = scripted({})
    run = await _start(
        client,
        DOSSIER,
        intention_id=intention,
        inputs={"parcours": "Paiement CB", "perimetre": "Digital", "deck": True},
    )
    done = await execute_workflow(acme["globex"], uuid.UUID(run["id"]))
    assert done == {"status": "succeeded"}
    assert called == ["standing", "dependencies", "documentation"]
    detail = await _detail(client, run["id"])
    assert _steps(detail) == {
        "standing": "succeeded",
        "dependencies": "succeeded",
        "documentation": "succeeded",
    }
    assert ARCHITECT not in json.dumps(detail)
    # Kept as skipped — never run, never pending.
    with workspace_scope(acme["globex"]):
        async with session_factory() as session:
            deck = await session.scalar(
                select(WorkflowRunStep).where(
                    WorkflowRunStep.run_id == uuid.UUID(run["id"]), WorkflowRunStep.step == "deck"
                )
            )
    assert deck is not None
    assert (deck.status, deck.reason, deck.attempts) == ("skipped", "not_here", 0)


async def test_a_dedicated_agent_is_its_organisations_whatever_its_plan(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await sync_catalogue()
    _as(identity, acme, "admin")
    # On Free, LEKA's grant taken back: no agent on sale runs.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            await set_plan(session, acme["acme"], "free", by="tests", reason="a customer on it")
            await end(session, acme["acme"], key=EVERY)
            await session.commit()
    assert await _why(client, "incident-investigation") == {"plan_required"}
    # Its own: nothing to pay for it.
    found = (await client.get(f"{API}/capabilities/{ARCHITECT}")).json()
    assert found["dedicated"] is True
    assert await _why(client, ARCHITECT) == set()
    listed = (await client.get(f"{API}/capabilities")).json()
    assert [c["key"] for c in listed if c["dedicated"]] == [ARCHITECT]
    sold = (await client.get(f"{API}/billing/add-ons")).json()
    assert sold["dedicated"] == [ARCHITECT]
    assert ARCHITECT not in {a["key"] for a in sold["agents"]}
    # Its workflow's step said, here.
    flow = (await client.get(f"{API}/workflows/{DOSSIER}")).json()
    assert "deck" in [s["id"] for s in flow["steps"]]


def test_a_dedicated_agent_is_never_sold() -> None:
    dedicated = {d.key for d in registered() if d.dedicated}
    assert dedicated == {ARCHITECT}
    sold = offer().add_ons
    for key in dedicated:
        assert key not in sold.agents
        assert all(key not in bundle.agents for bundle in sold.bundles)
        assert all(key not in sold.included_in(plan.key) for plan in offer().plans)
