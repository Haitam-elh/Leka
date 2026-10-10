"""AI governance (LEKA-406), end to end — Acme (test_knowledge_graph), its
member and admin; the architect, an agent of medium risk, run on LEKA's
Gemini (scripted).

What these protect:
- Model access: a control allowing only Mistral leaves the architect no
  model — its run fails, said why (refused); a control for admins only does
  not touch a member's run.
- Usage: a limit of one call a day per person lets a member's first run
  through and refuses the next (limited); every call says whom it was for.
- Output: a secret in what the agent delivers is redacted before it is kept;
  a block fails the run instead (blocked) — the secret kept nowhere.
- Approval: an agent at or above the risk waits — nothing queued — until
  someone who may approve says so: approved, it is queued; rejected,
  cancelled. Who asked it never approves it; a member may not approve. A
  workflow does not wait: its agent step fails, said why.
- Every outcome is kept, append-only; every change to a control is in the
  governance history; a member reads the controls and changes none.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from leka.api import intentions as intentions_api
from leka.capabilities import ModelCall, execute_workflow, sync_catalogue
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity, error_fields
from tests.test_agent_runs_api import (
    Script,
    _run,
    gemini,
    leka_gemini,  # noqa: F401 — a fixture
    queued,  # noqa: F401 — a fixture
)
from tests.test_capabilities_api import _connect
from tests.test_context_engine import model
from tests.test_deliverables import deck as drawn_deck
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures
from tests.test_workflow_runs_api import (
    Script as Steps,
)
from tests.test_workflow_runs_api import (
    _intention,
    scripted,  # noqa: F401 — a fixture
    workflows_queued,  # noqa: F401 — a fixture
)

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/governance/ai"
RUNS = "/api/v1/agent-runs"
ARCHITECT = "application-architecture"  # an agent of medium risk
ASKED = {"parcours": "Paiement CB", "perimetre": "Digital"}
BODY = {"key": ARCHITECT, "inputs": ASKED}
SECRET = "AKIAIOSFODNN7EXAMPLE"


async def _ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json() if response.content else None


async def _ready(acme: dict[str, uuid.UUID]) -> None:
    await sync_catalogue()
    await _connect(acme, "confluence")


async def _control(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], **body: Any
) -> dict[str, Any]:
    """Made by the admin; the member asks again after."""
    _as(identity, acme, "admin")
    made: dict[str, Any] = await _ok(
        await client.post(f"{API}/controls", json={"name": "Un contrôle", **body}), 201
    )
    _as(identity, acme, "member")
    return made


async def _start(client: AsyncClient) -> dict[str, Any]:
    started: dict[str, Any] = await _ok(await client.post(RUNS, json=BODY), 202)
    return started


async def _events(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID], **params: Any
) -> list[dict[str, Any]]:
    _as(identity, acme, "admin")
    found: list[dict[str, Any]] = await _ok(await client.get(f"{API}/events", params=params))
    _as(identity, acme, "member")
    return found


async def test_a_model_the_workspace_does_not_allow_never_answers(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    script = leka_gemini()
    await _ready(acme)
    # For admins only: a member's run is not touched by it.
    admins = await _control(
        client, identity, acme, kind="model_access", providers=["mistral"], roles=["admin"]
    )
    script.answers.append(gemini("# Architecture — Paiement CB"))
    script.answers.append(gemini(drawn_deck(app_view=False).model_dump_json()))
    first = await _start(client)
    assert await _run(acme, first["id"]) == {"status": "succeeded"}

    _as(identity, acme, "admin")
    await _ok(
        await client.put(
            f"{API}/controls/{admins['id']}",
            json={"name": "Mistral seulement", "kind": "model_access", "providers": ["mistral"]},
        )
    )
    _as(identity, acme, "member")
    second = await _start(client)
    assert await _run(acme, second["id"]) == {"status": "failed", "error": "no_model"}
    run = await _ok(await client.get(f"{RUNS}/{second['id']}"))
    failed = run["events"][-1]["detail"]
    assert failed["reason"] == "refused" and "Mistral seulement" in failed["said"]
    # Gemini was never asked again: the first run's analysis and its deck only.
    assert len(script.asked) == 2

    (refused,) = await _events(client, identity, acme, outcome="refused")
    assert (refused["control_name"], refused["purpose"], refused["provider"]) == (
        "Mistral seulement",
        f"agent:{ARCHITECT}",
        "google",
    )
    assert refused["user_id"] == str(acme["member"])


async def test_a_usage_limit_per_person_refuses_past_it(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    # A run of the architect is two calls: its analysis, then its deck — both
    # the agent's, both counted.
    content = gemini(drawn_deck(app_view=False).model_dump_json())
    leka_gemini(gemini("# Une"), content, gemini("# Jamais"), content)
    await _ready(acme)
    await _control(
        client,
        identity,
        acme,
        kind="usage_limit",
        purposes=["agent:*"],
        per="person",
        period="day",
        max_calls=2,
    )
    first = await _start(client)
    assert await _run(acme, first["id"]) == {"status": "succeeded"}
    second = await _start(client)
    assert await _run(acme, second["id"]) == {"status": "failed", "error": "no_model"}
    run = await _ok(await client.get(f"{RUNS}/{second['id']}"))
    assert run["events"][-1]["detail"]["reason"] == "limited"

    (limited,) = await _events(client, identity, acme, outcome="limited")
    assert limited["detail"]["reached"] == "calls" and limited["detail"]["calls"] == 2

    # Another person is not counted against it: the admin's run answers.
    _as(identity, acme, "admin")
    theirs = await _start(client)
    assert await _run(acme, theirs["id"]) == {"status": "succeeded"}

    # Each call says whom it was for.
    calls = await _ok(await client.get(f"{API}/calls", params={"user_id": str(acme["member"])}))
    # Refused before it was asked: the second run made no call.
    assert [c["user_id"] for c in calls] == [str(acme["member"])] * 2


async def test_a_secret_in_an_answer_is_redacted_or_blocks_it(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    deck = f"# Architecture\n\nLa clé {SECRET} ouvre le bucket."
    # The first run: its analysis, then its deck; the second: its analysis.
    leka_gemini(gemini(deck), gemini(drawn_deck(app_view=False).model_dump_json()), gemini(deck))
    await _ready(acme)
    redact = await _control(client, identity, acme, kind="output_check", detect=["secrets"])
    started = await _start(client)
    assert await _run(acme, started["id"]) == {"status": "succeeded"}
    done = await _ok(await client.get(f"{RUNS}/{started['id']}"))
    assert SECRET not in done["output"] and "[redacted]" in done["output"]
    (redacted,) = await _events(client, identity, acme, outcome="redacted")
    assert redacted["detail"]["found"] == ["aws_key"]
    # Linked to the run it happened in.
    (of_run,) = await _events(client, identity, acme, run_id=started["id"])
    assert of_run["outcome"] == "redacted"

    _as(identity, acme, "admin")
    await _ok(
        await client.put(
            f"{API}/controls/{redact['id']}",
            json={
                "name": "Aucun secret",
                "kind": "output_check",
                "detect": ["secrets"],
                "on_finding": "block",
            },
        )
    )
    _as(identity, acme, "member")
    blocked = await _start(client)
    assert await _run(acme, blocked["id"]) == {"status": "failed", "error": "no_model"}
    run = await _ok(await client.get(f"{RUNS}/{blocked['id']}"))
    assert run["events"][-1]["detail"]["reason"] == "blocked"
    assert run["output"] is None
    # What it found is said, never the text: the secret is kept nowhere.
    events = await _events(client, identity, acme)
    assert SECRET not in str(events)


async def test_a_risky_agent_waits_for_someone_who_may_approve(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    queued: list[uuid.UUID],
) -> None:
    leka_gemini(gemini("# Approuvé"))
    await _ready(acme)
    await _control(
        client, identity, acme, name="Revue des agents", kind="approval", risk_at_least="medium"
    )
    held = await _start(client)
    assert held["status"] == "awaiting_approval"
    assert queued == []
    # The worker leaves it: not queued.
    assert await _run(acme, held["id"]) == {"status": "not_queued"}
    # A member may not approve.
    assert (await client.post(f"{RUNS}/{held['id']}/approve")).status_code == 403
    waiting = await _ok(await client.get(RUNS, params={"status": "awaiting_approval"}))
    assert [r["id"] for r in waiting] == [held["id"]]

    _as(identity, acme, "admin")
    approved = await _ok(
        await client.post(f"{RUNS}/{held['id']}/approve", json={"note": "Vu avec l'équipe"})
    )
    assert approved["status"] == "queued" and queued == [uuid.UUID(held["id"])]
    # Queued from now: the sweep does not count the wait for approval.
    assert approved["queued_at"] > held["queued_at"]
    assert (await client.post(f"{RUNS}/{held['id']}/approve")).status_code == 409
    assert await _run(acme, held["id"]) == {"status": "succeeded"}
    kinds = [e["kind"] for e in (await _ok(await client.get(f"{RUNS}/{held['id']}")))["events"]]
    assert kinds[:2] == ["held", "approved"] and kinds[-1] == "succeeded"

    # Who asked it never approves it — an admin neither.
    own = await _start(client)
    assert own["status"] == "awaiting_approval"
    refused = await client.post(f"{RUNS}/{own['id']}/approve")
    assert refused.status_code == 403 and "does not approve" in refused.text

    # Rejected: cancelled, never run.
    _as(identity, acme, "member")
    other = await _start(client)
    _as(identity, acme, "admin")
    rejected = await _ok(await client.post(f"{RUNS}/{other['id']}/reject"))
    assert rejected["status"] == "cancelled"
    assert await _run(acme, other["id"]) == {"status": "not_queued"}
    # Who asked may still cancel theirs while it waits.
    cancelled = await _ok(await client.post(f"{RUNS}/{own['id']}/cancel"))
    assert cancelled["status"] == "cancelled"

    outcomes = [e["outcome"] for e in await _ok(await client.get(f"{API}/events"))]
    assert sorted(outcomes) == ["approved", "held", "held", "held", "rejected"]
    decided = await _ok(await client.get(f"{API}/events", params={"outcome": "approved"}))
    assert decided[0]["detail"]["control"] == "Revue des agents"
    assert decided[0]["detail"]["note"] == "Vu avec l'équipe"
    assert decided[0]["user_id"] == str(acme["admin"])


async def test_a_workflow_does_not_wait_its_held_agent_step_fails(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    scripted: Callable[[Steps], list[str]],
    workflows_queued: list[uuid.UUID],
    leka_gemini: Callable[..., Script],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def queue(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(intentions_api, "queue_analysis", queue)
    script = leka_gemini()
    scripted({})
    await _ready(acme)
    await _control(client, identity, acme, name="Revue", kind="approval", risk_at_least="medium")
    intention = await _intention(client, "Monte le dossier de Paiement CB")
    started = await _ok(
        await client.post(
            "/api/v1/workflow-runs",
            json={
                "key": "architecture-dossier",
                "inputs": {**ASKED, "deck": True},
                "intention_id": intention,
            },
        ),
        202,
    )
    await execute_workflow(acme["acme"], uuid.UUID(started["id"]))
    done = await _ok(await client.get(f"/api/v1/workflow-runs/{started['id']}"))
    deck = next(s for s in done["steps"] if s["step"] == "deck")
    assert (deck["status"], deck["reason"]) == ("failed", "approval_required")
    assert deck["output"]["control"] == "Revue"
    # The agent's model was never asked: only the intention was read.
    assert not any("PRINCIPE ABSOLU" in str(asked) for asked in script.asked)
    (held,) = await _events(client, identity, acme, outcome="held")
    assert held["detail"]["step"] == "deck" and held["user_id"] == str(acme["member"])


async def test_controls_changed_by_whom_may_kept_and_never_rewritten(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    # A member reads them, changes none, reads no audit.
    assert (await _ok(await client.get(f"{API}/controls"))) == []
    denied = await client.post(f"{API}/controls", json={"name": "x", "kind": "approval"})
    assert denied.status_code == 403
    assert (await client.get(f"{API}/events")).status_code == 403
    assert (await client.get(f"{API}/calls")).status_code == 403

    _as(identity, acme, "admin")
    # What cannot be kept says which field.
    invalid = await client.post(
        f"{API}/controls", json={"name": "Sans limite", "kind": "usage_limit"}
    )
    assert invalid.status_code == 422 and "max_calls" in error_fields(invalid)
    unknown = await client.post(
        f"{API}/controls", json={"name": "Rôle", "kind": "approval", "roles": ["nobody"]}
    )
    assert unknown.status_code == 422 and "nobody" in unknown.text

    made = await _ok(
        await client.post(
            f"{API}/controls",
            json={"name": "Limite", "kind": "usage_limit", "max_tokens": 100_000, "detect": []},
        ),
        201,
    )
    assert (made["max_tokens"], made["period"], made["per"]) == (100_000, "day", "workspace")
    # A role it names, since deleted, does not stop it being turned off.
    await _ok(
        await client.put(
            "/api/v1/governance/roles/contractor",
            json={"name": "Prestataire", "base": "member", "added": [], "removed": ["source:read"]},
        )
    )
    theirs = await _ok(
        await client.post(
            f"{API}/controls",
            json={"name": "Prestataires", "kind": "approval", "roles": ["contractor"]},
        ),
        201,
    )
    assert (await client.delete("/api/v1/governance/roles/contractor")).status_code == 204
    off = await _ok(
        await client.put(
            f"{API}/controls/{theirs['id']}",
            json={
                "name": "Prestataires",
                "kind": "approval",
                "roles": ["contractor"],
                "enabled": False,
            },
        )
    )
    assert off["enabled"] is False
    assert (await client.delete(f"{API}/controls/{theirs['id']}")).status_code == 204

    kind_changed = await client.put(
        f"{API}/controls/{made['id']}", json={"name": "Limite", "kind": "approval"}
    )
    assert kind_changed.status_code == 422
    await _ok(
        await client.put(
            f"{API}/controls/{made['id']}",
            json={"name": "Limite", "kind": "usage_limit", "max_tokens": 50_000},
        )
    )
    assert (await client.delete(f"{API}/controls/{made['id']}")).status_code == 204
    assert (await client.delete(f"{API}/controls/{made['id']}")).status_code == 404

    history = await _ok(
        await client.get("/api/v1/governance/history", params={"subject_type": "ai_control"})
    )
    mine = [h for h in history if h["subject_id"] == made["id"]]
    assert [h["kind"] for h in mine] == ["deleted", "updated", "created"]
    assert mine[1]["before"]["config"]["max_tokens"] == 100_000

    # What a control did is never rewritten.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO ai_control_events (workspace_id, kind, outcome, at)"
                    " VALUES (:w, 'approval', 'held', now())"
                ),
                {"w": acme["acme"]},
            )
            await session.commit()
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(text("UPDATE ai_control_events SET outcome = 'approved'"))
            await session.rollback()
            # The calls carry whom they were for: the column is there.
            assert (await session.scalars(select(ModelCall.user_id).limit(1))).all() == []
