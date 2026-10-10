"""The governance of consequential actions, end to end (LEKA-404).

Acme's company model (test_knowledge_graph). Its people ask LEKA to act on
Billing API; the workspace's governance says who must approve, and when
nothing may.

What these protect:
- The policy: configured by an admin — roles, how long an approval holds,
  when one waiting is escalated, the rules that raise a risk — refused when
  it cannot be, every change kept in the trail with before and after; what
  it says of an action, evaluated without anything kept.
- The risk: something critical in production makes a restart high; a
  migration in production is critical — two approvals, never the asker,
  and an owner among them.
- Delegation: an approver lends their authority to a member, up to a risk,
  for a time; the member's vote counts as theirs and keeps both names;
  beyond the risk, without one, once revoked — refused.
- A freeze: what it covers cannot be approved, and an approved one does
  not run while it holds. A waiver: what it covers is approved in advance
  in its grantor's name, runs, and no longer runs once the waiver is
  revoked.
- Before an action runs: an approval expired, or a policy tightened since,
  stops it.
- A decision waiting too long is escalated once, its asker and owners told.
- The trail is append-only; a person deleted is forgotten from it, nothing
  else.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from leka.db import session_factory, system_scope, workspace_scope
from leka.identity import EmailMessage
from leka.intentions import oversight as oversight_module
from leka.intentions.oversight import OversightService
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intention_actions_api import _plan, _start, jobs  # noqa: F401 — fixtures
from tests.test_intention_decisions_api import (  # noqa: F401 — fixtures
    _asked,
    _decisions,
    _refusal,
    _status,
    _vote,
    queued,
    second,
)
from tests.test_sources_api import _as, _user, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1"
RESTART = "Redémarre Billing API en production"
MIGRATE = "Migre Billing API vers PostgreSQL en production"


@pytest.fixture
async def owner(acme: dict[str, uuid.UUID]) -> AsyncIterator[uuid.UUID]:
    """Acme's owner: a critical action needs one among its approvers."""
    user = await _user("owner")
    await _sql(
        "INSERT INTO memberships (workspace_id, user_id, role) VALUES (:w, :u, 'owner')",
        w=acme["acme"],
        u=user,
    )
    acme["owner"] = user
    yield user
    await _sql("DELETE FROM users WHERE id = :u", u=user)


async def _sql(statement: str, **params: Any) -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(text(statement), params)
            await session.commit()


async def _billing(acme: dict[str, uuid.UUID]) -> uuid.UUID:
    with system_scope():
        async with session_factory() as session:
            found: uuid.UUID = (
                await session.execute(
                    text(
                        "SELECT id FROM entities WHERE workspace_id = :w AND name = 'Billing API'"
                    ),
                    {"w": acme["acme"]},
                )
            ).scalar_one()
            return found


def _later(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


async def _post(client: AsyncClient, path: str, code: int, **body: Any) -> Any:
    response = await client.post(f"{API}{path}", json=body)
    assert response.status_code == code, response.text
    return response.json()


async def _trail(client: AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(f"{API}/decisions/governance-history")
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()
    return found


def _failed(said: dict[str, Any]) -> set[str]:
    return {d["field"] for d in said["error"].get("details") or []}


# ── the policy ───────────────────────────────────────────────────────────────


async def test_the_policy_is_configured_evaluated_and_every_change_kept(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    billing = await _billing(acme)
    # What it would say, as a member may ask: nothing is kept.
    said = await _post(
        client,
        "/decisions/policy/evaluate",
        200,
        action="migrate",
        environment="production",
        targets=[str(billing)],
    )
    assert (said["risk"], said["approvals"], said["separate"], said["role"]) == (
        "critical",
        2,
        True,
        "owner",
    )
    assert (said["valid_hours"], said["escalate_hours"]) == (24, 4)
    assert [r["params"].get("rule") for r in said["reasons"] if r["code"] == "rule"] == [
        "irreversible",
        "irreversible_in_production",
    ]
    staging = await _post(
        client,
        "/decisions/policy/evaluate",
        200,
        action="restart",
        environment="staging",
        risk="low",
    )
    assert (staging["risk"], staging["approvals"], staging["role"]) == ("low", 1, None)

    # Billing API is critical: restarting it in production is high.
    await _sql(
        'UPDATE entities SET attributes = attributes || \'{"criticality": "critical"}\''
        " WHERE id = :e",
        e=billing,
    )
    intention = await _asked(client, acme, RESTART)
    [decision] = await _decisions(client, intention)
    assert (decision["risk"], decision["required_approvals"], decision["separate_asker"]) == (
        "high",
        2,
        True,
    )
    reasons = decision["governance"]["reasons"]
    assert reasons[-1]["params"]["rule"] == "critical_target_in_production"
    assert decision["governance"]["valid_hours"] == 72
    assert decision["governance"]["escalate_at"] is not None

    # An admin's to change; a member's to read.
    refused = await client.put(f"{API}/decisions/policy", json={"roles": {"high": "admin"}})
    assert refused.status_code == 403
    _as(identity, acme, "admin")
    for wrong in (
        {"roles": {"critical": "member"}},
        {"valid_hours": {"high": 0}},
        {"rules": [{"name": "x", "at_least": "urgent"}]},
    ):
        response = await client.put(f"{API}/decisions/policy", json=wrong)
        assert response.status_code == 422, wrong
    changed = await client.put(
        f"{API}/decisions/policy",
        json={
            "roles": {"high": "admin"},
            "valid_hours": {"medium": 12},
            "escalate_hours": {"medium": None},
            "rules": [{"name": "databases", "at_least": "high", "target_types": ["database"]}],
        },
    )
    assert changed.status_code == 200, changed.text
    policy = changed.json()
    assert (policy["roles"]["high"], policy["roles"]["critical"]) == ("admin", "owner")
    assert (policy["valid_hours"]["medium"], policy["escalate_hours"]["medium"]) == (12, None)
    assert policy["rules"] == [
        {
            "name": "databases",
            "at_least": "high",
            "actions": [],
            "environments": [],
            "target_types": ["database"],
            "target_criticality": [],
            "reversible": None,
        }
    ]
    # Its own rules replace LEKA's: a migration is no longer raised by them.
    now = await _post(
        client,
        "/decisions/policy/evaluate",
        200,
        action="migrate",
        environment="staging",
        risk="low",
    )
    assert now["risk"] == "low"
    # Open already: it keeps what it was opened with.
    [still] = await _decisions(client, intention)
    assert still["risk"] == "high"

    [event] = await _trail(client)
    assert (event["kind"], event["by"]) == ("policy_changed", str(acme["admin"]))
    assert set(event["detail"]["changed"]) == {"roles", "valid_hours", "escalate_hours", "rules"}
    assert event["detail"]["before"]["roles"]["high"] is None
    assert event["detail"]["after"]["roles"]["high"] == "admin"
    # Said again, nothing changes: nothing kept.
    await client.put(f"{API}/decisions/policy", json={"roles": {"high": "admin"}})
    assert len(await _trail(client)) == 1


async def test_a_critical_action_needs_two_approvals_and_an_owner(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    second: uuid.UUID,
    owner: uuid.UUID,
) -> None:
    intention = await _asked(client, acme, MIGRATE)
    [decision] = await _decisions(client, intention)
    assert (decision["risk"], decision["required_approvals"], decision["separate_asker"]) == (
        "critical",
        2,
        True,
    )
    assert decision["governance"]["required_role"] == "owner"

    _as(identity, acme, "admin")
    await _vote(client, intention, "approve")
    _as(identity, acme, "second")
    two = await _vote(client, intention, "approve")
    # Two approvals, no owner among them: it waits.
    assert (two["status"], two["approvers"]) == (
        "proposed",
        [str(acme["admin"]), str(second)],
    )
    _as(identity, acme, "owner")
    approved = await _vote(client, intention, "approve")
    assert approved["status"] == "approved"
    assert [v["role"] for v in approved["votes"]] == ["admin", "admin", "owner"]
    assert approved["votes"][2]["context"]["required_role"] == "owner"
    held = datetime.fromisoformat(approved["governance"]["valid_until"])
    decided = datetime.fromisoformat(approved["decided_at"])
    assert held - decided == timedelta(hours=24)
    assert await _status(client, intention) == "approved"


# ── delegation ───────────────────────────────────────────────────────────────


async def test_a_member_votes_with_an_authority_lent_and_kept_as_both(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    second: uuid.UUID,
) -> None:
    member = str(acme["member"])
    # Only who may approve lends it.
    await _post(
        client,
        "/decisions/delegations",
        403,
        to=str(second),
        max_risk="low",
        reason="Congés",
        ends_at=_later(days=1),
    )
    _as(identity, acme, "admin")
    for wrong in (
        {"to": str(acme["admin"])},  # to oneself
        {"to": str(acme["other_admin"])},  # not a member here
        {"ends_at": _later(days=91)},
    ):
        body = {"to": member, "max_risk": "low", "reason": "Congés", "ends_at": _later(days=7)}
        await _post(client, "/decisions/delegations", 422, **(body | wrong))
    low = await _post(
        client,
        "/decisions/delegations",
        201,
        to=member,
        max_risk="low",
        reason="Congés",
        ends_at=_later(days=7),
    )
    assert (low["delegated_by"], low["delegated_to"], low["active"]) == (
        str(acme["admin"]),
        member,
        True,
    )

    _as(identity, acme, "second")
    intention = await _asked(client, acme, RESTART)
    _as(identity, acme, "member")
    # A member votes only for someone, and only as lent.
    await _vote(client, intention, "approve", code=403)
    beyond = await _vote(client, intention, "approve", code=403, on_behalf_of=str(acme["admin"]))
    assert _refusal(beyond) == "no_delegation"
    none = await _vote(client, intention, "approve", code=403, on_behalf_of=str(second))
    assert _refusal(none) == "no_delegation"
    mine = await _vote(client, intention, "approve", code=403, on_behalf_of=member)
    assert _refusal(mine) == "no_delegation"

    _as(identity, acme, "admin")
    medium = await _post(
        client,
        "/decisions/delegations",
        201,
        to=member,
        max_risk="medium",
        reason="Astreinte",
        ends_at=_later(days=2),
    )
    _as(identity, acme, "member")
    # Who lent it, or an admin, revokes it.
    refused = await _post(client, f"/decisions/delegations/{low['id']}/revoke", 403)
    assert _refusal(refused) == "not_yours"
    approved = await _vote(client, intention, "approve", on_behalf_of=str(acme["admin"]))
    assert (approved["status"], approved["approvers"]) == ("approved", [str(acme["admin"])])
    [vote] = approved["votes"]
    assert (vote["by"], vote["on_behalf_of"], vote["role"]) == (member, str(acme["admin"]), "admin")
    assert vote["context"]["delegation_id"] == medium["id"]

    _as(identity, acme, "admin")
    revoked = await _post(client, f"/decisions/delegations/{medium['id']}/revoke", 200)
    assert (revoked["revoked_by"], revoked["active"]) == (str(acme["admin"]), False)
    again = await _post(client, f"/decisions/delegations/{medium['id']}/revoke", 409)
    assert _refusal(again) == "already_revoked"
    listed = (await client.get(f"{API}/decisions/delegations")).json()
    assert {(d["id"], d["active"]) for d in listed} == {(low["id"], True), (medium["id"], False)}
    assert [e["kind"] for e in await _trail(client)] == [
        "delegation_revoked",
        "delegation_granted",
        "delegation_granted",
    ]

    # Revoked: no longer.
    _as(identity, acme, "second")
    later = await _asked(client, acme, RESTART)
    _as(identity, acme, "member")
    gone = await _vote(client, later, "approve", code=403, on_behalf_of=str(acme["admin"]))
    assert _refusal(gone) == "no_delegation"


# ── exceptions ───────────────────────────────────────────────────────────────


async def test_a_freeze_stops_approval_and_execution(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    freeze = {
        "kind": "freeze",
        "reason": "Clôture comptable",
        "environments": ["production"],
        "ends_at": _later(days=1),
    }
    await _post(client, "/decisions/exceptions", 403, **freeze)
    _as(identity, acme, "admin")
    held = await _post(client, "/decisions/exceptions", 201, **freeze)
    assert (held["kind"], held["active"], held["granted_by"]) == (
        "freeze",
        True,
        str(acme["admin"]),
    )

    _as(identity, acme, "member")
    intention = await _asked(client, acme, RESTART)
    [decision] = await _decisions(client, intention)
    assert decision["governance"]["frozen"] is True
    assert decision["governance"]["exceptions"][0]["reason"] == "Clôture comptable"

    _as(identity, acme, "admin")
    refused = await _vote(client, intention, "approve", code=409)
    assert _refusal(refused) == "frozen"
    assert "Clôture comptable" in refused["error"]["message"]
    await _post(client, f"/decisions/exceptions/{held['id']}/revoke", 200)
    approved = await _vote(client, intention, "approve")
    assert approved["status"] == "approved"

    # Frozen again once approved: it does not run.
    again = await _post(client, "/decisions/exceptions", 201, **freeze)
    await _plan(client, intention)
    stopped = await _start(client, intention, code=409)
    assert "check.not_frozen" in _failed(stopped)
    assert await _status(client, intention) == "approved"
    await _post(client, f"/decisions/exceptions/{again['id']}/revoke", 200)
    started = await _start(client, intention)
    assert started["status"] == "running"

    kinds = [e["kind"] for e in await _trail(client)]
    assert kinds == [
        "exception_revoked",
        "exception_granted",
        "exception_revoked",
        "decision_frozen",
        "exception_granted",
    ]


async def test_a_waiver_approves_a_standard_change_in_advance(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    waiver = {
        "kind": "waiver",
        "reason": "Redémarrages de routine",
        "actions": ["restart"],
        "environments": ["production"],
        "max_risk": "medium",
        "ends_at": _later(days=7),
    }
    _as(identity, acme, "admin")
    # A waiver names its actions and environments, never above medium.
    unnamed = await _post(client, "/decisions/exceptions", 422, **(waiver | {"environments": []}))
    assert _refusal(unnamed) == "invalid_exception"
    await _post(client, "/decisions/exceptions", 422, **(waiver | {"max_risk": "high"}))
    granted = await _post(client, "/decisions/exceptions", 201, **waiver)

    _as(identity, acme, "member")
    intention = await _asked(client, acme, RESTART)
    [decision] = await _decisions(client, intention)
    assert (decision["status"], decision["approvers"], decision["votes"]) == (
        "approved",
        [str(acme["admin"])],
        [],
    )
    assert decision["governance"]["waived"] is True
    assert await _status(client, intention) == "approved"
    # In its grantor's name, the waiver said.
    history = (await client.get(f"{API}/intentions/{intention['id']}/history")).json()
    approved = next(e for e in history if e["to_status"] == "approved")
    assert (approved["actor"], approved["by"], approved["reason"]) == (
        "person",
        str(acme["admin"]),
        "Redémarrages de routine",
    )
    assert approved["detail"]["waived_by"] == granted["id"]

    # It runs.
    _as(identity, acme, "admin")
    await _plan(client, intention)
    assert (await _start(client, intention))["status"] == "running"

    # Not what it does not cover: a migration waits for people.
    _as(identity, acme, "member")
    migrate = await _asked(client, acme, MIGRATE)
    [waiting] = await _decisions(client, migrate)
    assert (waiting["status"], waiting["governance"]["waived"]) == ("proposed", False)

    # Revoked: what it approved and has not run no longer runs.
    another = await _asked(client, acme, RESTART)
    _as(identity, acme, "admin")
    await _post(client, f"/decisions/exceptions/{granted['id']}/revoke", 200)
    await _plan(client, another)
    stopped = await _start(client, another, code=409)
    assert "check.waiver_holds" in _failed(stopped)

    trail = await _trail(client)
    waived = [e for e in trail if e["kind"] == "decision_waived"]
    assert len(waived) == 2
    assert waived[0]["by"] == str(acme["admin"])
    assert waived[0]["detail"]["exception"] == granted["id"]


# ── before it runs ───────────────────────────────────────────────────────────


async def test_an_approval_expired_or_a_policy_tightened_stops_it(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    await client.put(f"{API}/decisions/policy", json={"valid_hours": {"medium": 1}})
    _as(identity, acme, "member")
    intention = await _asked(client, acme, RESTART)
    _as(identity, acme, "admin")
    approved = await _vote(client, intention, "approve")
    held = datetime.fromisoformat(approved["governance"]["valid_until"])
    assert held - datetime.fromisoformat(approved["decided_at"]) == timedelta(hours=1)
    await _plan(client, intention)

    # Tightened since: one approval is no longer enough.
    await client.put(f"{API}/decisions/policy", json={"approvals": {"medium": 2}})
    tightened = await _start(client, intention, code=409)
    assert "check.policy_met" in _failed(tightened)
    await client.put(f"{API}/decisions/policy", json={"approvals": {"medium": 1}})

    # Approved too long ago.
    await _sql(
        "UPDATE intention_decisions SET valid_until = now() - interval '1 minute' WHERE id = :d",
        d=approved["id"],
    )
    expired = await _start(client, intention, code=409)
    assert _failed(expired) >= {"check.approval_valid"}
    assert "check.policy_met" not in _failed(expired)


# ── escalation ───────────────────────────────────────────────────────────────


async def test_a_decision_waiting_too_long_is_escalated_once(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    owner: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[EmailMessage] = []

    class Capture:
        async def send(self, message: EmailMessage) -> None:
            sent.append(message)

    monkeypatch.setattr(oversight_module, "build_email_sender", lambda: Capture())
    intention = await _asked(client, acme, RESTART)
    [decision] = await _decisions(client, intention)
    created = datetime.fromisoformat(decision["created_at"])

    async def escalate(after: timedelta) -> list[uuid.UUID]:
        with workspace_scope(acme["acme"]):
            async with session_factory() as session:
                done = await OversightService(session, acme["acme"]).escalate(now=created + after)
                await session.commit()
                return [d.id for d in done]

    # Medium: escalated after 48 hours, once.
    assert await escalate(timedelta(hours=47)) == []
    assert await escalate(timedelta(hours=49)) == [uuid.UUID(decision["id"])]
    assert await escalate(timedelta(hours=50)) == []
    told = sorted(m.to.split("-")[0] for m in sent)
    assert told == ["member", "owner"]
    assert "Billing API" in sent[0].subject

    [escalated] = await _decisions(client, intention)
    assert escalated["governance"]["escalated_at"] is not None
    _as(identity, acme, "admin")
    [event] = await _trail(client)
    assert (event["kind"], event["by"], event["subject_id"]) == (
        "decision_escalated",
        None,
        decision["id"],
    )


# ── the trail ────────────────────────────────────────────────────────────────


async def test_the_trail_is_append_only_and_forgets_only_who(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    second: uuid.UUID,
) -> None:
    _as(identity, acme, "second")
    await _post(
        client,
        "/decisions/exceptions",
        201,
        kind="freeze",
        reason="Migration du datacenter",
        ends_at=_later(hours=4),
    )
    [event] = await _trail(client)
    with system_scope():
        async with session_factory() as session:
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    text("UPDATE governance_events SET kind = 'policy_changed' WHERE id = :e"),
                    {"e": event["id"]},
                )
    # Their account deleted: who it was is forgotten, nothing else.
    await _sql("DELETE FROM users WHERE id = :u", u=second)
    _as(identity, acme, "admin")
    [kept] = await _trail(client)
    assert (kept["kind"], kept["by"], kept["detail"]["reason"]) == (
        "exception_granted",
        None,
        "Migration du datacenter",
    )
