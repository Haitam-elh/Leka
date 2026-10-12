"""Intentions, end to end (LEKA-384): asked, kept, moved, linked, audited.

Acme's company model (test_knowledge_graph): Billing API, of Billing
platform, owned by Payments. Nora's member asks « Pourquoi Billing API est
lente depuis hier ? »; the admin may approve.

What these protect: an intention is created with what it was asked —
words, scope, who — and its context assembled for it, linked, in one
transaction: nothing to start from keeps nothing; its status is kept and
queried, by phase, status, asker, words, what it is linked to, and
counted; the lifecycle's moves, by the actor each allows, each an event of
its history — numbered, who, when, from where to where, why — that the
database refuses to change; asking again makes its context's next version;
cancelling, archiving, restoring, by its asker or an approver only;
contexts, findings, entities linked and checked, decisions, actions and
outcomes linked by what makes them; another workspace's is 404.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from leka.db import session_factory, system_scope, workspace_scope
from leka.intelligence import Finding
from leka.intentions import (
    Actor,
    IllegalTransitionError,
    IntentionRepository,
    IntentionService,
    IntentionStatus,
)
from tests.conftest import FakeIdentity, error_code
from tests.test_context_engine import model
from tests.test_knowledge_graph import BILLING
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/intentions"
ASKED = "Pourquoi Billing API est lente depuis hier ?"
S = IntentionStatus


async def _ask(client: AsyncClient, words: str = ASKED, **scope: Any) -> dict[str, Any]:
    response = await client.post(API, json={"text": words, **scope})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def _get(client: AsyncClient, path: str = "", **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _history(client: AsyncClient, intention_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = await _get(client, f"/{intention_id}/history")
    return found


def _service(session: Any, workspace: uuid.UUID) -> IntentionService:
    return IntentionService(IntentionRepository(session, workspace))


# ── asking ─────────────────────────────────────────────────────────────────


async def test_an_intention_is_kept_with_what_was_asked_and_its_context(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    created = await _ask(client, environment="production")
    intention, context = created["intention"], created["context"]

    assert intention["title"] == ASKED
    assert intention["text"] == ASKED
    assert intention["scope"] == {"environment": "production"}
    assert intention["created_by"] == str(acme["member"])
    assert intention["kind"] == "diagnose"
    # Asked, its context assembled: LEKA analyses it.
    assert (intention["status"], intention["phase"]) == ("analysing", "active")
    assert intention["context_id"] == context["context_id"]
    assert "cancelled" in intention["moves"]
    assert context["subject"] == {"type": "intention", "id": intention["id"]}
    # About Billing API, named by its words.
    assert str(model[BILLING]) in context["request"]["roots"]
    [link] = intention["links"]
    assert (link["kind"], link["ref_id"]) == ("context", context["context_id"])
    assert link["detail"]["version"] == context["version"]

    history = await _history(client, intention["id"])
    assert [(e["sequence"], e["kind"], e["actor"]) for e in history] == [
        (1, "created", "person"),
        (2, "linked", "system"),
        (3, "moved", "system"),
    ]
    assert history[0]["by"] == str(acme["member"])
    assert history[0]["detail"]["scope"] == {"environment": "production"}
    moved = history[2]
    assert (moved["from_status"], moved["to_status"], moved["name"]) == (
        "submitted",
        "analysing",
        "analysis_started",
    )
    assert moved["by"] is None


async def test_nothing_to_start_from_keeps_nothing(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    response = await client.post(API, json={"text": "?? !! ??"})
    assert response.status_code == 422, response.text
    assert error_code(response) == "validation_failed"
    assert (await _get(client))["data"] == []
    assert (await _get(client, "/counts"))["all"] == 0


async def test_its_status_is_kept_and_queried(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    first = (await _ask(client))["intention"]
    second = (await _ask(client, "Qui est responsable de Billing API ?"))["intention"]
    _as(identity, acme, "admin")
    theirs = (await _ask(client, "Qu'est-ce qui a changé sur Billing API ?"))["intention"]
    _as(identity, acme, "member")
    await client.post(f"{API}/{second['id']}/cancel", json={"reason": "asked twice"})

    assert {i["id"] for i in (await _get(client))["data"]} == {
        first["id"],
        second["id"],
        theirs["id"],
    }
    active = await _get(client, phase="active")
    assert {i["id"] for i in active["data"]} == {first["id"], theirs["id"]}
    finished = await _get(client, phase="finished")
    assert [i["status"] for i in finished["data"]] == ["cancelled"]
    assert [i["id"] for i in (await _get(client, status="cancelled"))["data"]] == [second["id"]]
    mine = await _get(client, mine="true")
    assert {i["id"] for i in mine["data"]} == {first["id"], second["id"]}
    assert [i["id"] for i in (await _get(client, q="responsable"))["data"]] == [second["id"]]
    linked = await _get(client, linked=first["context_id"])
    assert [i["id"] for i in linked["data"]] == [first["id"]]
    assert await _get(client, "/counts") == {
        "all": 3,
        "active": 2,
        "scheduled": 0,
        "finished": 1,
        "archived": 0,
    }
    assert (await _get(client, "/counts", mine="true"))["all"] == 2


# ── the lifecycle, as LEKA and people move it ──────────────────────────────


async def test_the_lifecycle_from_analysis_to_verified_each_move_in_its_history(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    intention = (await _ask(client))["intention"]
    workspace, member = acme["acme"], acme["member"]
    ident = uuid.UUID(intention["id"])

    with workspace_scope(workspace):
        async with session_factory() as session:
            service = _service(session, workspace)
            await service.move(
                ident,
                S.AWAITING_DECISION,
                actor=Actor.SYSTEM,
                summary="A deployment yesterday slowed Billing API.",
            )
            # A decision is a person's: LEKA itself may not approve.
            with pytest.raises(IllegalTransitionError):
                await service.move(ident, S.APPROVED, actor=Actor.SYSTEM)
            # And a person's move names the person.
            with pytest.raises(IllegalTransitionError):
                await service.move(ident, S.APPROVED, actor=Actor.PERSON)
            await service.move(
                ident, S.APPROVED, actor=Actor.PERSON, by=acme["admin"], reason="roll it back"
            )
            for to in (S.EXECUTING, S.VERIFYING, S.COMPLETED):
                await service.move(ident, to, actor=Actor.SYSTEM)
            await session.commit()

    done = await _get(client, f"/{intention['id']}")
    assert (done["status"], done["phase"]) == ("completed", "finished")
    assert done["summary"] == "A deployment yesterday slowed Billing API."
    assert done["moves"] == ["analysing"]
    moves = [e for e in await _history(client, intention["id"]) if e["kind"] == "moved"]
    assert [(e["from_status"], e["to_status"], e["actor"], e["name"]) for e in moves] == [
        ("submitted", "analysing", "system", "analysis_started"),
        ("analysing", "awaiting_decision", "system", "proposed"),
        ("awaiting_decision", "approved", "person", "approved"),
        ("approved", "executing", "system", "execution_started"),
        ("executing", "verifying", "system", "executed"),
        ("verifying", "completed", "system", "verified"),
    ]
    approved = moves[2]
    assert (approved["by"], approved["reason"]) == (str(acme["admin"]), "roll it back")
    assert [e["sequence"] for e in await _history(client, intention["id"])] == list(
        range(1, len(await _history(client, intention["id"])) + 1)
    )
    _ = member


async def test_asked_again_its_context_is_made_again(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    created = await _ask(client)
    intention = created["intention"]

    response = await client.post(
        f"{API}/{intention['id']}/ask",
        json={"text": "Pourquoi Billing API est lente cette semaine ?", "environment": "staging"},
    )
    assert response.status_code == 200, response.text
    asked = response.json()
    assert asked["context"]["context_id"] == created["context"]["context_id"]
    assert asked["context"]["version"] == created["context"]["version"] + 1
    assert asked["intention"]["text"] == "Pourquoi Billing API est lente cette semaine ?"
    assert asked["intention"]["scope"] == {"environment": "staging"}
    assert asked["intention"]["status"] == "analysing"
    assert asked["intention"]["links"][0]["detail"]["version"] == asked["context"]["version"]
    last = (await _history(client, intention["id"]))[-1]
    assert (last["name"], last["from_status"], last["to_status"], last["actor"]) == (
        "asked_again",
        "analysing",
        "analysing",
        "person",
    )
    assert last["detail"]["before"]["text"] == ASKED
    assert last["detail"]["version"] == asked["context"]["version"]


async def test_cancelled_archived_restored_by_its_asker_or_an_approver(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "admin")
    theirs = (await _ask(client))["intention"]
    _as(identity, acme, "member")
    mine = (await _ask(client, "Qui est responsable de Billing API ?"))["intention"]

    # Not the member's, and a member may not approve.
    refused = await client.post(f"{API}/{theirs['id']}/cancel", json={})
    assert refused.status_code == 403
    assert error_code(refused) == "permission_denied"

    # Archived only once done with.
    early = await client.post(f"{API}/{mine['id']}/archive")
    assert early.status_code == 409
    cancelled = await client.post(f"{API}/{mine['id']}/cancel", json={"reason": "duplicate"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["moves"] == []
    again = await client.post(f"{API}/{mine['id']}/cancel", json={})
    assert again.status_code == 409
    # Cancelled is final: not asked again.
    reask = await client.post(f"{API}/{mine['id']}/ask", json={"text": ASKED})
    assert reask.status_code == 409

    archived = await client.post(f"{API}/{mine['id']}/archive")
    assert archived.json()["archived_at"] is not None
    assert [i["id"] for i in (await _get(client, phase="archived"))["data"]] == [mine["id"]]
    assert mine["id"] not in {i["id"] for i in (await _get(client))["data"]}
    assert (await _get(client, "/counts"))["archived"] == 1
    restored = await client.post(f"{API}/{mine['id']}/restore")
    assert restored.json()["archived_at"] is None
    kinds = [e["kind"] for e in await _history(client, mine["id"])]
    assert kinds[-3:] == ["moved", "archived", "restored"]
    cancel = next(e for e in await _history(client, mine["id"]) if e["name"] == "cancelled")
    assert (cancel["reason"], cancel["by"]) == ("duplicate", str(acme["member"]))

    # The admin may approve: they may handle the member's.
    _as(identity, acme, "admin")
    other = (await _ask(client, "Qu'est-ce qui a changé sur Billing API ?"))["intention"]
    _as(identity, acme, "member")
    mine2 = (await _ask(client))["intention"]
    _as(identity, acme, "admin")
    assert (await client.post(f"{API}/{mine2['id']}/cancel", json={})).status_code == 200
    _ = other


# ── links ──────────────────────────────────────────────────────────────────


async def _finding(workspace: uuid.UUID, entity: uuid.UUID) -> uuid.UUID:
    now = datetime.now(UTC)
    with workspace_scope(workspace):
        async with session_factory() as session:
            finding = Finding(
                workspace_id=workspace,
                analyzer="ownership",
                analyzer_version=1,
                key=f"entity:{entity}",
                category="organisation",
                code="ownership.no_owner",
                params={},
                statement="No team or person is named as owner of Billing API.",
                severity="medium",
                rank=200,
                confidence=0.9,
                subject_type="entity",
                subject_id=entity,
                subject_name="Billing API",
                status="open",
                first_seen_at=now,
                last_seen_at=now,
                first_run_id=uuid.uuid4(),
                last_run_id=uuid.uuid4(),
                occurrences=1,
                reopened=0,
            )
            session.add(finding)
            await session.commit()
            return finding.id


async def test_context_findings_entities_linked_and_checked(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = (await _ask(client))["intention"]
    path = f"{API}/{intention['id']}/links"
    billing = model[BILLING]
    finding = await _finding(acme["acme"], billing)

    entity = await client.post(path, json={"kind": "entity", "ref_id": str(billing)})
    assert entity.status_code == 201, entity.text
    assert (entity.json()["label"], entity.json()["detail"]) == ("Billing API", {"type": "service"})
    found = await client.post(path, json={"kind": "finding", "ref_id": str(finding)})
    assert found.json()["label"] == "No team or person is named as owner of Billing API."
    assert found.json()["detail"]["code"] == "ownership.no_owner"
    # Its values too: the interface words it as Insights does — its
    # statement is English, in a French history.
    assert "params" in found.json()["detail"]
    [linked] = [
        e for e in await _history(client, intention["id"]) if e["detail"].get("kind") == "finding"
    ]
    assert linked["detail"]["code"] == "ownership.no_owner"
    assert "params" in linked["detail"]
    # Linked twice: the same link.
    twice = await client.post(path, json={"kind": "entity", "ref_id": str(billing)})
    assert twice.json()["id"] == entity.json()["id"]
    # Nothing of that kind, or another kind's id.
    for kind, ref in (("entity", uuid.uuid4()), ("finding", billing), ("context", finding)):
        refused = await client.post(path, json={"kind": kind, "ref_id": str(ref)})
        assert refused.status_code == 422, (kind, refused.text)
    # Decisions are linked by what makes them (LEKA-390), not by a person.
    decision = await client.post(path, json={"kind": "decision", "ref_id": str(uuid.uuid4())})
    assert decision.status_code == 422

    detail = await _get(client, f"/{intention['id']}")
    assert [link["kind"] for link in detail["links"]] == ["context", "entity", "finding"]
    by_entity = await _get(client, linked=str(billing))
    assert [i["id"] for i in by_entity["data"]] == [intention["id"]]

    gone = await client.delete(f"{path}/{entity.json()['id']}")
    assert gone.status_code == 204
    context_link = detail["links"][0]["id"]
    kept = await client.delete(f"{path}/{context_link}")
    assert kept.status_code == 422
    assert [e["kind"] for e in await _history(client, intention["id"])][-1] == "unlinked"
    _ = identity


async def test_decisions_actions_outcomes_are_linked_by_what_makes_them(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    intention = (await _ask(client))["intention"]
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            service = _service(session, acme["acme"])
            decision = uuid.uuid4()
            for kind in ("decision", "action", "outcome"):
                link = await service.link(
                    uuid.UUID(intention["id"]),
                    kind,
                    decision if kind == "decision" else uuid.uuid4(),
                    actor=Actor.SYSTEM,
                    label=f"the {kind}",
                    detail={"made_by": "LEKA-390"},
                )
                assert link is not None
            await session.commit()
    kinds = [link["kind"] for link in (await _get(client, f"/{intention['id']}"))["links"]]
    assert kinds == ["context", "decision", "action", "outcome"]
    linked = [e for e in await _history(client, intention["id"]) if e["kind"] == "linked"]
    assert [e["detail"]["kind"] for e in linked] == ["context", "decision", "action", "outcome"]
    assert {e["actor"] for e in linked} == {"system"}


# ── audit ──────────────────────────────────────────────────────────────────


async def test_its_history_cannot_be_rewritten(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    intention = (await _ask(client))["intention"]
    with system_scope():
        async with session_factory() as session:
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    text("UPDATE intention_events SET reason = 'edited' WHERE intention_id = :i"),
                    {"i": intention["id"]},
                )
            await session.rollback()
            # The one change allowed: who did it forgotten, with the user.
            await session.execute(
                text("UPDATE intention_events SET by = NULL WHERE intention_id = :i"),
                {"i": intention["id"]},
            )
            await session.commit()
    assert {e["by"] for e in await _history(client, intention["id"])} == {None}


async def test_another_workspace_s_intention_is_not_there(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = (await _ask(client))["intention"]
    _as(identity, acme, "other_admin")
    for method, path in (
        ("GET", f"/{intention['id']}"),
        ("GET", f"/{intention['id']}/history"),
        ("POST", f"/{intention['id']}/cancel"),
        ("POST", f"/{intention['id']}/archive"),
    ):
        response = await client.request(
            method, f"{API}{path}", json={} if method == "POST" else None
        )
        assert response.status_code == 404, (method, path, response.text)
    assert (await _get(client))["data"] == []


# ── understood (LEKA-385) ──────────────────────────────────────────────────


async def test_an_intention_is_understood_and_kept_with_its_words(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    intention = (await _ask(client))["intention"]
    understood = intention["understanding"]
    assert understood["text"] == ASKED
    assert (understood["mode"], understood["goal"]["code"]) == ("question", "explain_cause")
    assert "pourquoi" in understood["goal"]["said"]
    assert [e["entity_id"] for e in understood["entities"]] == [str(model[BILLING])]
    assert understood["clear"] is True
    assert intention["goal"] == "explain_cause"
    assert intention["status"] == "analysing"
    listed = (await _get(client))["data"]
    assert [i["goal"] for i in listed] == ["explain_cause"]


async def test_not_understood_enough_it_is_asked_then_clarified(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    created = await _ask(client, "Redémarre le service")
    intention = created["intention"]
    assert intention["status"] == "needs_clarification"
    assert intention["goal"] == "act"
    understood = intention["understanding"]
    assert understood["clear"] is False
    assert understood["actions"] == [
        {
            "code": "restart",
            "said": "redemarre",
            "changes_systems": True,
            "polarity": "affirmed",
            "targets": [],
        }
    ]
    blocking = {a["kind"] for a in understood["ambiguities"] if a["blocking"]}
    assert "action_without_target" in blocking
    assert intention["moves"] == ["analysing", "cancelled"]
    moved = (await _history(client, intention["id"]))[-1]
    assert (moved["from_status"], moved["to_status"], moved["name"], moved["actor"]) == (
        "submitted",
        "needs_clarification",
        "clarification_asked",
        "system",
    )
    assert "action_without_target" in moved["detail"]["ambiguities"]

    # Clarified: asked again, naming what to restart.
    response = await client.post(
        f"{API}/{intention['id']}/ask", json={"text": "Redémarre Billing API"}
    )
    assert response.status_code == 200, response.text
    clarified = response.json()["intention"]
    assert clarified["status"] == "analysing"
    assert clarified["understanding"]["clear"] is True
    assert clarified["understanding"]["entities"][0]["name"] == "Billing API"
    last = (await _history(client, intention["id"]))[-1]
    assert (last["name"], last["actor"]) == ("clarified", "person")


async def test_asked_again_and_still_unclear_it_is_asked_again(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    intention = (await _ask(client, "Redémarre le service"))["intention"]
    response = await client.post(f"{API}/{intention['id']}/ask", json={"text": "Redémarre le truc"})
    assert response.status_code == 200, response.text
    assert response.json()["intention"]["status"] == "needs_clarification"
    names = [e["name"] for e in await _history(client, intention["id"]) if e["kind"] == "moved"]
    assert names == ["clarification_asked", "clarified", "clarification_asked"]


async def test_what_leka_would_understand_is_said_and_nothing_kept(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    response = await client.post(
        f"{API}/understand", json={"text": "Peux-tu faire un rollback de Billing API ?"}
    )
    assert response.status_code == 200, response.text
    understood = response.json()
    assert (understood["mode"], understood["goal"]["code"]) == ("request", "act")
    assert [a["code"] for a in understood["actions"]] == ["rollback"]
    assert understood["clear"] is True
    assert (await _get(client, "/counts"))["all"] == 0


# ── scoped (LEKA-386) ──────────────────────────────────────────────────────


async def test_its_scope_is_kept_resolved_against_the_model(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    created = await _ask(
        client,
        "Pourquoi Billing API est lente depuis hier ? Sans rien modifier, c'est urgent",
    )
    scope = created["intention"]["understanding"]["scope"]
    assert [(e["name"], e["lifecycle"]) for e in scope["entities"]] == [("Billing API", "active")]
    assert scope["period"]["explicit"] is True
    assert scope["period"]["said"]
    kinds = {c["kind"]: c for c in scope["constraints"]}
    assert kinds["read_only"]["said"] == "sans rien modifier"
    assert kinds["urgency"]["hard"] is False
    assert scope["missing"] == []

    # The model says it has gone dormant: said, not blocking.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE entities SET lifecycle = 'dormant' WHERE id = :i"),
                {"i": model[BILLING]},
            )
            await session.commit()
    dormant = (await _ask(client))["intention"]
    understood = dormant["understanding"]
    assert understood["scope"]["entities"][0]["lifecycle"] == "dormant"
    assert {a["kind"] for a in understood["ambiguities"]} >= {"subject_dormant"}
    assert dormant["status"] == "analysing"


# ── its context (LEKA-387) ─────────────────────────────────────────────────


async def test_its_context_is_assembled_from_its_scope_what_it_excludes_never_held(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    from tests.test_knowledge_graph import CHECKOUT

    plain = (await _ask(client, "Qu'est-ce qui dépend de Billing API ?"))["intention"]
    held = await _get(client, f"/{plain['id']}/context")
    assert str(model[CHECKOUT]) in {e["ref_id"] for e in held["context"]["elements"]}

    excluding = (await _ask(client, "Qu'est-ce qui dépend de Billing API, sauf Checkout ?"))[
        "intention"
    ]
    scope = excluding["understanding"]["scope"]
    assert [e["name"] for e in scope["excluded"]] == ["Checkout"]
    found = await _get(client, f"/{excluding['id']}/context")
    context = found["context"]
    assert str(model[CHECKOUT]) not in {e["ref_id"] for e in context["elements"]}
    assert str(model[CHECKOUT]) not in context["request"]["roots"]
    assert context["request"]["exclude"] == [str(model[CHECKOUT])]
    assert context["subject"] == {"type": "intention", "id": excluding["id"]}


async def test_its_context_says_whether_it_can_ground_an_analysis(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    intention = (await _ask(client, "Qui est responsable de Billing API ?"))["intention"]
    ready = intention["readiness"]
    assert ready["status"] in ("ready", "limited")
    assert ready["context_id"] == intention["context_id"]
    assert ready["elements"] > 0
    assert ready["facets"]["technical"] >= 1
    assert ready["sources"] >= 1
    assert ready["critical"] == []
    moved = (await _history(client, intention["id"]))[-1]
    assert moved["detail"]["readiness"] == ready["status"]

    found = await _get(client, f"/{intention['id']}/context")
    assert found["readiness"]["status"] == ready["status"]
    # Every element says where it came from; the quality says how sure.
    assert all(
        e["provenance"]["sources"] for e in found["context"]["elements"] if e["kind"] == "entity"
    )
    assert found["context"]["quality"]["level"] in ("high", "medium", "low")
    first = await _get(client, f"/{intention['id']}/context", version=1)
    assert first["context"]["version"] == 1


async def test_a_diagnosis_no_source_can_ground_is_limited_said_why(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    """Acme's sources read no incident, deployment or metric: why Billing API
    is slow cannot be grounded — said before any analysis, and analysed
    anyway: LEKA's analyst says what it could not see."""
    intention = (await _ask(client))["intention"]
    ready = intention["readiness"]
    assert ready["status"] == "limited"
    assert [issue["kind"] for issue in ready["critical"]] == ["no_source_for"]
    # Understood — the question is clear — only not well groundable.
    assert intention["status"] == "analysing"


async def test_a_critical_gap_is_surfaced_before_any_analysis(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    """A question about everything — what is slow — names nothing: said,
    and looked into; never stopped for a question."""
    intention = (await _ask(client, "Pourquoi tout est si lent depuis hier ?"))["intention"]
    ready = intention["readiness"]
    assert ready["status"] == "limited"
    assert "no_subject" in {issue["kind"] for issue in ready["critical"]}
    assert intention["status"] == "analysing"
    moved = (await _history(client, intention["id"]))[-1]
    assert moved["detail"]["readiness"] == "limited"
    assert "no_subject" in moved["detail"]["critical"]


async def test_an_action_naming_nothing_is_asked_what_it_acts_on(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    intention = (await _ask(client, "Redémarre tout en production"))["intention"]
    assert intention["status"] == "needs_clarification"


async def test_another_workspace_s_context_is_not_there(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    intention = (await _ask(client))["intention"]
    _as(identity, acme, "other_admin")
    response = await client.get(f"{API}/{intention['id']}/context")
    assert response.status_code == 404
