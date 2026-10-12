"""Decisions on intentions, end to end (LEKA-390): proposed by the
analysis, voted on by people under the workspace's policy, the intention
moved once decided — every vote kept.

Acme's company model (test_knowledge_graph). Its member asks « Redémarre
Billing API en production »; its admins decide.

What these protect:
- An action asked is put to a decision once analysed: what it would do,
  on what, where, whether it can be undone, at which risk — production
  makes it at least medium — and how many must approve; linked to the
  intention. A question asks for no decision.
- Approved by who may approve: the intention approved, by that person,
  with the decision in its history; a member may not approve.
- Rejected, it says why: the intention rejected, nothing to approve after.
- Modified: a new revision — where it runs — its earlier approvals void,
  the modifier's own counting; approved twice by the same person, refused.
- The policy: two approvers wanted, two are needed; the asker may not be
  the one on a risk the policy keeps apart; changed by an admin only,
  refused when it cannot be, the decisions already open keeping theirs.
- Changes asked: it waits for its asker; asked again and analysed, a new
  decision, the earlier superseded; its intention cancelled, its decision
  is no longer waiting.
- À valider: the queue and its counts; every vote with who, when, why and
  its context, which the database refuses to change; another workspace's
  is not there.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from leka.api import intentions as intentions_api
from leka.db import session_factory, system_scope
from leka.intentions.analysis import Capability, Material, Output
from leka.intentions.capabilities import CAPABILITIES
from leka.intentions.processing import analyse_intention
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_sources_api import _as, _user, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1"
RESTART = "Redémarre Billing API en production"


@pytest.fixture(autouse=True)
def queued(monkeypatch: pytest.MonkeyPatch) -> None:
    """No worker here: the tests run the analysis themselves."""

    async def queue(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(intentions_api, "queue_analysis", queue)


@pytest.fixture
async def second(acme: dict[str, uuid.UUID]) -> AsyncIterator[uuid.UUID]:
    """A second admin in Acme: four eyes need two."""
    user = await _user("second_admin")
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO memberships (workspace_id, user_id, role) VALUES (:w, :u, 'admin')"
                ),
                {"w": acme["acme"], "u": user},
            )
            await session.commit()
    acme["second"] = user
    yield user
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user})
            await session.commit()


async def _asked(
    client: AsyncClient, acme: dict[str, uuid.UUID], words: str = RESTART
) -> dict[str, Any]:
    """Asked, and analysed as the job would: its decision opened."""
    response = await client.post(f"{API}/intentions", json={"text": words})
    assert response.status_code == 201, response.text
    intention: dict[str, Any] = response.json()["intention"]
    await analyse_intention(acme["acme"], uuid.UUID(intention["id"]), trigger="created")
    return intention


async def _decisions(client: AsyncClient, intention: dict[str, Any]) -> list[dict[str, Any]]:
    response = await client.get(f"{API}/intentions/{intention['id']}/decisions")
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()
    return found


async def _vote(
    client: AsyncClient, intention: dict[str, Any], verdict: str, code: int = 200, **body: Any
) -> dict[str, Any]:
    response = await client.post(
        f"{API}/intentions/{intention['id']}/decision/{verdict}", json=body
    )
    assert response.status_code == code, response.text
    said: dict[str, Any] = response.json()
    return said


async def _status(client: AsyncClient, intention: dict[str, Any]) -> str:
    response = await client.get(f"{API}/intentions/{intention['id']}")
    status: str = response.json()["status"]
    return status


def _refusal(said: dict[str, Any]) -> str | None:
    details = said["error"].get("details") or []
    return next((d["message"] for d in details if d["field"] == "refusal"), None)


async def _policy(client: AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.put(f"{API}/decisions/policy", json=body)
    assert response.status_code == 200, response.text
    said: dict[str, Any] = response.json()
    return said


# ── proposed, approved ───────────────────────────────────────────────────────


async def test_an_action_asked_is_put_to_a_decision_and_approved(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _asked(client, acme)
    assert await _status(client, intention) == "awaiting_decision"

    [decision] = await _decisions(client, intention)
    assert (decision["number"], decision["status"], decision["open"]) == (1, "proposed", True)
    # One thing relies on it, and it runs in production: medium — one
    # approval, which the asker may give.
    assert (decision["risk"], decision["required_approvals"]) == ("medium", 1)
    assert decision["separate_asker"] is False
    [proposal] = decision["proposals"]
    assert (proposal["action"], proposal["environment"], proposal["reversible"]) == (
        "restart",
        "production",
        True,
    )
    assert [t["name"] for t in proposal["targets"]] == ["Billing API"]
    assert decision["asked_by"] == str(acme["member"])
    assert decision["analysis_id"] is not None

    # Linked: its history says so.
    detail = (await client.get(f"{API}/intentions/{intention['id']}")).json()
    assert ("decision", decision["id"]) in {(lk["kind"], lk["ref_id"]) for lk in detail["links"]}

    # A member may not approve.
    await _vote(client, intention, "approve", code=403)

    _as(identity, acme, "admin")
    approved = await _vote(client, intention, "approve", reason="Off-peak, fine.")
    assert (approved["status"], approved["open"]) == ("approved", False)
    assert approved["approvers"] == [str(acme["admin"])]
    [vote] = approved["votes"]
    assert (vote["verdict"], vote["by"], vote["reason"]) == (
        "approve",
        str(acme["admin"]),
        "Off-peak, fine.",
    )
    # The context it was cast in.
    assert vote["context"]["risk"] == decision["risk"]
    assert vote["context"]["proposals"][0]["action"] == "restart"
    assert vote["context"]["intention_status"] == "awaiting_decision"

    assert await _status(client, intention) == "approved"
    history = (await client.get(f"{API}/intentions/{intention['id']}/history")).json()
    moved = history[-1]
    assert (moved["name"], moved["actor"], moved["by"]) == (
        "approved",
        "person",
        str(acme["admin"]),
    )
    assert moved["detail"]["decision_id"] == decision["id"]
    # Decided: nothing more to vote on.
    await _vote(client, intention, "approve", code=409)


async def test_a_question_asks_for_no_decision(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    intention = await _asked(client, acme, "Qui est responsable de Billing API ?")
    assert await _status(client, intention) == "completed"
    assert await _decisions(client, intention) == []


async def test_a_negated_action_asks_for_no_decision(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    """« Ne redémarre pas » restarts nothing (LEKA-434)."""
    intention = await _asked(client, acme, "Ne redémarre pas Billing API en production")
    assert await _status(client, intention) != "awaiting_decision"
    assert await _decisions(client, intention) == []


async def test_each_action_is_proposed_on_what_was_said_with_it(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    intention = await _asked(
        client, acme, "Redémarre Billing API et rollback Checkout en production"
    )
    [decision] = await _decisions(client, intention)
    assert {p["action"]: [t["name"] for t in p["targets"]] for p in decision["proposals"]} == {
        "restart": ["Billing API"],
        "rollback": ["Checkout"],
    }


def _failing(_: Material) -> Output:
    raise RuntimeError("the changes could not be read")


# Its changes never read: what an action in production needs, missing.
CHANGES_FAILED = [
    c if c.name != "changes" else Capability("changes", 1, ".", goals=c.goals, run=_failing)
    for c in CAPABILITIES
]


async def _asked_without_changes(
    client: AsyncClient, acme: dict[str, uuid.UUID], words: str = RESTART
) -> dict[str, Any]:
    response = await client.post(f"{API}/intentions", json={"text": words})
    assert response.status_code == 201, response.text
    intention: dict[str, Any] = response.json()["intention"]
    await analyse_intention(
        acme["acme"], uuid.UUID(intention["id"]), trigger="created", capabilities=CHANGES_FAILED
    )
    return intention


async def test_a_high_risk_action_without_its_evidence_cannot_be_approved(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    """A restart in production made high by the policy, its changes never
    read (LEKA-436): proposed, never as grounded — blocked, said why."""
    _as(identity, acme, "admin")
    await _policy(
        client,
        rules=[
            {
                "name": "Restarts in production",
                "at_least": "high",
                "actions": ["restart"],
                "environments": ["production"],
            }
        ],
    )
    _as(identity, acme, "member")
    intention = await _asked_without_changes(client, acme)
    [decision] = await _decisions(client, intention)
    assert decision["risk"] == "high"
    grounding = decision["governance"]["grounding"]
    assert grounding["gate"] == "blocked"
    assert "changes" in grounding["missing"]

    _as(identity, acme, "admin")
    refused = await client.post(f"{API}/intentions/{intention['id']}/decision/approve", json={})
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["details"] == [{"field": "refusal", "message": "ungrounded"}]
    assert await _status(client, intention) == "awaiting_decision"


async def test_a_medium_risk_action_without_its_evidence_needs_one_more_approval(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    # What it reaches never read: the « action » capability failed.
    broken = [
        c if c.name != "action" else Capability("action", 1, ".", goals=c.goals, run=_failing)
        for c in CAPABILITIES
    ]
    response = await client.post(f"{API}/intentions", json={"text": RESTART})
    intention: dict[str, Any] = response.json()["intention"]
    await analyse_intention(
        acme["acme"], uuid.UUID(intention["id"]), trigger="created", capabilities=broken
    )
    [decision] = await _decisions(client, intention)
    assert (decision["risk"], decision["required_approvals"]) == ("medium", 2)
    assert decision["governance"]["grounding"] == {
        "gate": "validation",
        "missing": ["action"],
        "stale": [],
    }


async def test_a_question_partly_answered_is_said_partial_no_decision(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    """Informational: answered with what is in the way said — never gated."""
    question = "Qu'est-ce qui a changé sur Billing API cette semaine ?"
    intention = await _asked_without_changes(client, acme, question)
    assert await _status(client, intention) == "completed"
    analysis = (await client.get(f"{API}/intentions/{intention['id']}/analysis")).json()
    assert analysis["status"] == "partial"
    assert await _decisions(client, intention) == []


# ── rejected, modified ───────────────────────────────────────────────────────


async def test_rejected_it_says_why_and_nothing_runs(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _asked(client, acme)
    _as(identity, acme, "admin")
    unsaid = await _vote(client, intention, "reject", code=422)
    assert _refusal(unsaid) == "reason_required"

    rejected = await _vote(client, intention, "reject", reason="Not during the sales.")
    assert rejected["status"] == "rejected"
    assert await _status(client, intention) == "rejected"
    history = (await client.get(f"{API}/intentions/{intention['id']}/history")).json()
    assert (history[-1]["name"], history[-1]["reason"]) == ("rejected", "Not during the sales.")
    # Rejected: never approved after.
    await _vote(client, intention, "approve", code=409)


async def test_modified_its_earlier_approvals_void(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    second: uuid.UUID,
) -> None:
    _as(identity, acme, "admin")
    await _policy(client, approvals={"medium": 2, "high": 2}, separate=[])
    _as(identity, acme, "member")
    intention = await _asked(client, acme)

    _as(identity, acme, "second")
    first = await _vote(client, intention, "approve")
    assert (first["status"], first["approvers"]) == ("proposed", [str(second)])

    _as(identity, acme, "admin")
    unsaid = await _vote(client, intention, "modify", code=422, environment="staging")
    assert _refusal(unsaid) == "reason_required"
    same = await _vote(client, intention, "modify", code=422, reason="Same.", keep=["restart"])
    assert _refusal(same) == "nothing_changed"
    staged = await _vote(
        client, intention, "modify", environment="staging", reason="Try it in staging first."
    )
    assert staged["revision"] == 2
    assert staged["proposals"][0]["environment"] == "staging"
    # What the second admin approved is no longer what is decided.
    assert (staged["status"], staged["approvers"]) == ("proposed", [str(acme["admin"])])
    modify = staged["votes"][-1]
    assert modify["changes"]["from"]["proposals"][0]["environment"] == "production"
    assert modify["changes"]["to"]["proposals"][0]["environment"] == "staging"

    twice = await _vote(client, intention, "approve", code=409)
    assert _refusal(twice) == "already_approved"
    _as(identity, acme, "second")
    approved = await _vote(client, intention, "approve")
    assert approved["status"] == "approved"
    assert approved["approvers"] == [str(acme["admin"]), str(second)]
    assert await _status(client, intention) == "approved"


# ── the policy ───────────────────────────────────────────────────────────────


async def test_the_asker_may_not_approve_alone_what_the_policy_keeps_apart(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    second: uuid.UUID,
) -> None:
    _as(identity, acme, "admin")
    await _policy(client, separate=["medium", "high"], approvals={"high": 1})
    intention = await _asked(client, acme)
    [decision] = await _decisions(client, intention)
    assert decision["separate_asker"] is True

    own = await _vote(client, intention, "approve", code=403)
    assert _refusal(own) == "asker_may_not_approve"
    _as(identity, acme, "second")
    approved = await _vote(client, intention, "approve")
    assert approved["status"] == "approved"


async def test_the_policy_is_an_admins_and_kept_as_said(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    default = (await client.get(f"{API}/decisions/policy")).json()
    assert {k: default[k] for k in ("approvals", "separate", "production_raises", "roles")} == {
        "approvals": {"low": 1, "medium": 1, "high": 2, "critical": 2},
        "separate": ["high", "critical"],
        "production_raises": True,
        "roles": {"low": None, "medium": None, "high": None, "critical": "owner"},
    }
    assert (default["valid_hours"]["critical"], default["escalate_hours"]["critical"]) == (24, 4)
    assert len(default["rules"]) == 3
    assert default["customised"] is False
    # A member reads it, may not change it.
    refused = await client.put(f"{API}/decisions/policy", json={"approvals": {"high": 3}})
    assert refused.status_code == 403
    intention = await _asked(client, acme)
    [before] = await _decisions(client, intention)

    _as(identity, acme, "admin")
    wrong = await client.put(f"{API}/decisions/policy", json={"approvals": {"medium": 3}})
    assert wrong.status_code == 422
    changed = await _policy(client, approvals={"low": 2, "medium": 3, "high": 4})
    # Critical, not said, asks at least what high does.
    assert (changed["approvals"], changed["customised"]) == (
        {"low": 2, "medium": 3, "high": 4, "critical": 4},
        True,
    )
    # Open already: it keeps the policy it was opened with.
    [after] = await _decisions(client, intention)
    assert after["required_approvals"] == before["required_approvals"]


# ── sent back, superseded ────────────────────────────────────────────────────


async def test_changes_asked_it_waits_then_a_new_decision_supersedes(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _asked(client, acme)
    _as(identity, acme, "admin")
    sent = await _vote(client, intention, "request-changes", reason="Say which window.")
    assert (sent["status"], sent["open"]) == ("changes_requested", False)
    assert await _status(client, intention) == "awaiting_decision"

    _as(identity, acme, "member")
    again = await client.post(
        f"{API}/intentions/{intention['id']}/ask",
        json={"text": "Redémarre Billing API en production cette nuit"},
    )
    assert again.status_code == 200, again.text
    await analyse_intention(acme["acme"], uuid.UUID(intention["id"]), trigger="asked_again")
    latest, earlier = await _decisions(client, intention)
    assert (latest["number"], latest["status"], latest["open"]) == (2, "proposed", True)
    assert (earlier["number"], earlier["status"]) == (1, "superseded")


async def test_an_intention_cancelled_leaves_its_decision_behind(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _asked(client, acme)
    cancelled = await client.post(
        f"{API}/intentions/{intention['id']}/cancel", json={"reason": "Fixed by itself."}
    )
    assert cancelled.status_code == 200, cancelled.text
    [decision] = await _decisions(client, intention)
    assert (decision["status"], decision["open"]) == ("superseded", False)
    waiting = (await client.get(f"{API}/decisions", params={"status": "proposed"})).json()
    assert intention["id"] not in {i["intention"]["id"] for i in waiting["data"]}
    gone = (await client.get(f"{API}/decisions", params={"status": "withdrawn"})).json()
    assert intention["id"] in {i["intention"]["id"] for i in gone["data"]}
    summary = (await client.get(f"{API}/decisions/summary")).json()
    assert (summary["proposed"], summary["superseded"]) == (0, 1)
    _as(identity, acme, "admin")
    await _vote(client, intention, "approve", code=409)


# ── À valider, audit ─────────────────────────────────────────────────────────


async def test_the_queue_its_counts_its_audit(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = await _asked(client, acme)
    queue = (await client.get(f"{API}/decisions", params={"status": "proposed"})).json()
    [item] = [i for i in queue["data"] if i["intention"]["id"] == intention["id"]]
    assert item["intention"]["title"] == RESTART
    assert item["decision"]["open"] is True
    summary = (await client.get(f"{API}/decisions/summary")).json()
    assert summary["proposed"] >= 1

    _as(identity, acme, "admin")
    rejected = await _vote(client, intention, "reject", reason="No.")
    decided = (await client.get(f"{API}/decisions", params={"status": "rejected"})).json()
    assert intention["id"] in {i["intention"]["id"] for i in decided["data"]}

    # A vote is never changed.
    vote_id = rejected["votes"][0]["id"]
    with system_scope():
        async with session_factory() as session:
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    text("UPDATE intention_decision_votes SET reason = 'Yes.' WHERE id = :v"),
                    {"v": vote_id},
                )

    _as(identity, acme, "other_admin")
    elsewhere = await client.get(f"{API}/intentions/{intention['id']}/decisions")
    assert elsewhere.status_code == 404
    theirs = (await client.get(f"{API}/decisions", params={"status": "rejected"})).json()
    assert theirs["data"] == []
    await _vote(client, intention, "approve", code=404)
