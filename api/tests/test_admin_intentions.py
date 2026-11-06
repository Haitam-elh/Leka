"""The intentions module of LEKA ADMIN (LEKA-551): every customer's
intentions, found by their words, organisation, person, agent, kind and
status; each one step by step — how LEKA understood it, the agents it chose,
each run and its steps, the actions proposed, the errors met, what its work
used — and its whole story, oldest first. What the customer wrote and what
LEKA read or produced from it only for a role allowed to read it, each
reading kept; nothing here acts on a customer's environment.
"""

# ruff: noqa: F811 — the admin world's fixtures are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from leka.admin import AdminAccount, AdminAuditEvent, AdminRole
from leka.capabilities import AgentRun, AgentRunEvent, CapabilityRouting, ModelCall
from leka.core.config import settings
from leka.db import session_factory, system_scope
from leka.intentions import (
    Intention,
    IntentionAnalysis,
    IntentionAttachment,
    IntentionDecision,
    IntentionDecisionVote,
    IntentionPlan,
    IntentionPlanStep,
    IntentionVerification,
)
from leka.main import app
from leka.metering import UsageRecord
from tests.test_admin_api import API, SUPER, World, as_, world  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


def _ago(minutes: int) -> datetime:
    return NOW - timedelta(minutes=minutes)


def _usage(world: World, execution: str, kind: str, subject: str, **said: object) -> UsageRecord:
    record: dict[str, object] = {
        "calls": 0,
        "failed_calls": 0,
        "invalid_calls": 0,
        "retries": 0,
        "fallbacks": 0,
        "tool_calls": 0,
        "unreported_calls": 0,
        "latency_ms": 0,
        "tokens_status": "measured",
        "cost_status": "estimated",
        "embedding_cost": "not_applicable",
        "tool_cost": "not_applicable",
        "infra_cost": "not_applicable",
    }
    return UsageRecord(
        workspace_id=world.alpha,
        execution=execution,
        kind=kind,
        intention_id=world.intention,
        subject=subject,
        outcome="succeeded",
        started_at=_ago(20),
        metered_at=_ago(5),
        **(record | said),
    )


async def _tell(world: World) -> tuple[uuid.UUID, uuid.UUID]:
    """The world's intention, all the way: understood, routed, two runs (one
    that delivered, one that failed), a model refusing twice, an action
    decided and run — and failed —, its check, a file it was asked with.
    What the customer wrote or LEKA read carries the marker: none of it may
    reach a role without intentions:content."""
    m = world.marker
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                update(Intention).where(Intention.id == world.intention).values(kind="diagnose")
            )
            done, broken = (
                await session.scalars(
                    select(AgentRun)
                    .where(AgentRun.intention_id == world.intention)
                    .order_by(AgentRun.queued_at)
                )
            ).all()
            decision = IntentionDecision(
                workspace_id=world.alpha,
                id=uuid.uuid4(),
                intention_id=world.intention,
                number=1,
                status="approved",
                risk="medium",
                required_approvals=1,
                proposals=[
                    {
                        "id": "p1",
                        "action": "rollback",
                        "targets": [
                            {"id": str(uuid.uuid4()), "name": f"payment-api-{m}", "type": "service"}
                        ],
                        "environment": "production",
                        "constraints": [],
                        "reversible": True,
                    }
                ],
                decided_at=_ago(15),
            )
            plan = IntentionPlan(
                workspace_id=world.alpha,
                id=uuid.uuid4(),
                intention_id=world.intention,
                decision_id=decision.id,
                number=1,
                revision=1,
                status="failed",
                started_at=_ago(14),
                finished_at=_ago(13),
                error="webhook_refused",
            )
            session.add(decision)
            await session.flush()
            session.add(plan)
            await session.flush()

            def event(run: AgentRun, seq: int, kind: str, at: datetime, **detail: object) -> None:
                session.add(
                    AgentRunEvent(
                        workspace_id=world.alpha,
                        run_id=run.id,
                        seq=seq,
                        kind=kind,
                        at=at,
                        detail=detail,
                    )
                )

            event(done, 1, "queued", _ago(20), by=str(world.owner))
            event(done, 2, "started", _ago(20))
            event(
                done,
                3,
                "tool",
                _ago(19),
                name="read_file",
                arguments={"path": f"secret-{m}.py"},
                outcome="ok",
                ms=40,
                why=f"to read {m}",
            )
            event(
                done,
                4,
                "answered",
                _ago(19),
                provider="gemini",
                model="gemini-2.5-pro",
                tokens_in=1000,
                tokens_out=200,
            )
            event(done, 5, "succeeded", _ago(18), chars=120)
            event(broken, 1, "queued", _ago(10), by=str(world.owner))
            event(broken, 2, "started", _ago(10))
            event(broken, 3, "render_failed", _ago(8), code="render_timeout", said=f"said {m}")
            event(broken, 4, "failed", _ago(6), code="timeout", seconds=240)
            session.add_all(
                [
                    IntentionAnalysis(
                        workspace_id=world.alpha,
                        intention_id=world.intention,
                        number=1,
                        trigger="created",
                        status="partial",
                        readiness="limited",
                        requested_by=world.owner,
                        started_at=_ago(29),
                        finished_at=_ago(28),
                        selection=[
                            {
                                "name": "standing",
                                "version": 1,
                                "method": "rules",
                                "chosen": True,
                                "reason": "always",
                            },
                            {
                                "name": "changes",
                                "version": 1,
                                "method": "rules",
                                "chosen": False,
                                "reason": "no_model",
                            },
                        ],
                        steps=[
                            {"name": "standing", "status": "succeeded", "duration_ms": 1200},
                            {
                                "name": "ownership",
                                "status": "failed",
                                "duration_ms": 300,
                                "error": "TimeoutError",
                            },
                        ],
                        result={
                            "status": "partial",
                            "risk": "medium",
                            "confidence": 0.6,
                            "summary": [{"code": "s", "text": f"Summary {m}"}],
                            "findings": [{"id": "f1", "code": "f", "text": f"Finding {m}"}],
                            "causes": [{"id": "c1", "label": f"Cause {m}"}],
                            "recommendations": [{"id": "r1", "text": f"Roll back {m}"}],
                            "uncertainties": [],
                            "missing": [{"code": "x", "text": f"Missing {m}"}],
                            "answer": {"text": f"Answer {m}"},
                        },
                    ),
                    CapabilityRouting(
                        workspace_id=world.alpha,
                        subject_type="intention",
                        subject_id=world.intention,
                        version=1,
                        outcome="routed",
                        selected=["code-review"],
                        query={"text": f"Why slow {m}"},
                        decision={
                            "candidates": [
                                {
                                    "key": "code-review",
                                    "score": 0.9,
                                    "eligible": True,
                                    "selected": True,
                                },
                                {
                                    "key": "security-review",
                                    "score": 0.2,
                                    "eligible": True,
                                    "selected": False,
                                },
                            ],
                            "excluded": [{"key": "design-review"}],
                            "why": None,
                        },
                        at=_ago(25),
                    ),
                    *(
                        ModelCall(
                            workspace_id=world.alpha,
                            purpose="agent:code-review",
                            ref=f"agent_run:{broken.id}",
                            run_id=broken.id,
                            tier="deep",
                            provider="gemini",
                            model="gemini-2.5-pro",
                            route="primary",
                            owner="leka",
                            status="failed",
                            error="429: spend cap reached",
                            at=at,
                        )
                        for at in (_ago(7), _ago(6))
                    ),
                    _usage(
                        world,
                        f"agent_run:{done.id}",
                        "agent_run",
                        "code-review",
                        calls=3,
                        tokens_in=1000,
                        tokens_out=200,
                        leka_cost_usd=0.05,
                        models=["gemini/gemini-2.5-pro"],
                    ),
                    _usage(
                        world,
                        f"llm_run:{uuid.uuid4()}",
                        "llm_run",
                        "intention.understanding",
                        calls=1,
                        failed_calls=1,
                        tokens_in=300,
                        tokens_out=50,
                        leka_cost_usd=0.01,
                        models=["mistral/mistral-small"],
                    ),
                    IntentionDecisionVote(
                        workspace_id=world.alpha,
                        decision_id=decision.id,
                        revision=1,
                        verdict="approve",
                        by=world.owner,
                        at=_ago(15),
                        reason=f"Go {m}",
                    ),
                    IntentionPlanStep(
                        workspace_id=world.alpha,
                        plan_id=plan.id,
                        position=1,
                        proposal_id="p1",
                        action="rollback",
                        executor="webhook",
                        status="failed",
                        started_at=_ago(14),
                        finished_at=_ago(13),
                        error="502 from the endpoint",
                    ),
                    IntentionVerification(
                        workspace_id=world.alpha,
                        intention_id=world.intention,
                        plan_id=plan.id,
                        status="failed",
                        observe_after=_ago(12),
                        deadline=NOW + timedelta(hours=1),
                        expectations=[{"kind": "healthy"}],
                    ),
                    IntentionAttachment(
                        workspace_id=world.alpha,
                        intention_id=world.intention,
                        uploaded_by=world.owner,
                        name=f"trace-{m}.log",
                        content_type="text/plain",
                        size_bytes=10,
                        checksum_sha256="0" * 64,
                        storage_key=f"attachments/{m}",
                    ),
                ]
            )
            await session.commit()
            return done.id, broken.id


# What the customer wrote, or what LEKA read or produced from it.
def _secrets(m: str) -> tuple[str, ...]:
    return (
        f"slow? {m}",
        f"secret-{m}",
        f"to read {m}",
        f"said {m}",
        f"Summary {m}",
        f"Finding {m}",
        f"Answer {m}",
        f"Go {m}",
        f"payment-api-{m}",
        f"trace-{m}",
        f"Why slow {m}",
        f"The deliverable {m}",
    )


async def _read(role: AdminRole, world: World) -> list[AdminAuditEvent]:
    """What the role's admin was kept reading of the module."""
    with system_scope():
        async with session_factory() as session:
            return list(
                (
                    await session.scalars(
                        select(AdminAuditEvent)
                        .join(AdminAccount, AdminAccount.id == AdminAuditEvent.admin_id)
                        .where(
                            AdminAccount.email == f"{role.value}-{world.marker}@leka.test",
                            AdminAuditEvent.action == "admin.viewed_content",
                        )
                        .order_by(AdminAuditEvent.at)
                    )
                ).all()
            )


async def test_intentions_are_found_by_words_organisation_person_and_kind(
    client: AsyncClient, world: World
) -> None:
    await _tell(world)
    m = world.marker

    async def found(**params: str) -> list[str]:
        response = await client.get(
            f"{API}/intentions", params=params, headers=as_(world, AdminRole.OPERATIONS)
        )
        assert response.status_code == 200, response.text
        return [row["id"] for row in response.json()["data"]]

    mine = [str(world.intention)]
    alpha = str(world.alpha)
    assert await found(q="payment-api slow", organisation_id=alpha) == mine
    assert await found(q="nothing like it", organisation_id=alpha) == []
    assert await found(q=str(world.intention)) == mine
    assert await found(organisation=f"alpha {m}") == mine
    assert await found(organisation=f"demo-{m}") == []
    assert await found(user=f"owner-{m}") == mine
    assert await found(user="Nora", organisation_id=alpha) == mine
    assert await found(user=f"member-{m}") == []
    assert await found(organisation_id=alpha, kind="diagnose", status="completed") == mine
    assert await found(organisation_id=alpha, kind="change") == []
    assert await found(organisation_id=alpha, agent="security-review") == []


async def test_a_short_description_is_content_and_each_page_of_it_is_kept(
    client: AsyncClient, world: World
) -> None:
    params = {"organisation_id": str(world.alpha)}
    operations = await client.get(
        f"{API}/intentions", params=params, headers=as_(world, AdminRole.OPERATIONS)
    )
    [row] = operations.json()["data"]
    assert row["description"] is None
    assert row["title"] == "Why is payment-api slow?"
    assert await _read(AdminRole.OPERATIONS, world) == []

    support = await client.get(
        f"{API}/intentions", params=params, headers=as_(world, AdminRole.SUPPORT)
    )
    [row] = support.json()["data"]
    assert row["description"] == f"Why is payment-api slow? {world.marker}"
    [kept] = await _read(AdminRole.SUPPORT, world)
    assert (kept.target_type, kept.target_id) == ("intention", None)
    assert kept.detail == {"read": "descriptions", "intentions": [str(world.intention)]}


async def test_an_intention_step_by_step_without_what_the_customer_wrote(
    client: AsyncClient, world: World
) -> None:
    done, broken = await _tell(world)
    m = world.marker
    response = await client.get(
        f"{API}/intentions/{world.intention}", headers=as_(world, AdminRole.OPERATIONS)
    )
    assert response.status_code == 200, response.text
    for secret in _secrets(m):
        assert secret not in response.text, secret
    body = response.json()
    assert (body["content"], body["description"], body["kind"]) == (None, None, "diagnose")

    # How LEKA understood it: the capabilities it chose and why, what each did.
    [analysis] = body["analyses"]
    assert (analysis["status"], analysis["readiness"], analysis["risk"]) == (
        "partial",
        "limited",
        "medium",
    )
    assert (analysis["findings"], analysis["recommendations"], analysis["duration_ms"]) == (
        1,
        1,
        60_000,
    )
    assert analysis["requested_by"]["email"] == f"owner-{m}@acme.test"
    assert [(c["name"], c["chosen"], c["reason"]) for c in analysis["selection"]] == [
        ("standing", True, "always"),
        ("changes", False, "no_model"),
    ]
    assert [(s["name"], s["status"], s["error"]) for s in analysis["steps"]] == [
        ("standing", "succeeded", None),
        ("ownership", "failed", "TimeoutError"),
    ]
    # The agents its router chose, among which.
    [routing] = body["routings"]
    assert (routing["outcome"], routing["selected"], routing["excluded"]) == (
        "routed",
        ["code-review"],
        ["design-review"],
    )
    assert [(c["key"], c["score"], c["selected"]) for c in routing["candidates"]] == [
        ("code-review", 0.9, True),
        ("security-review", 0.2, False),
    ]

    # Each run, its steps: what it did, never what it read.
    first, second = body["runs"]
    assert (first["id"], first["status"], second["id"], second["status"]) == (
        str(done),
        "succeeded",
        str(broken),
        "failed",
    )
    assert [s["kind"] for s in first["steps"]] == [
        "queued",
        "started",
        "tool",
        "answered",
        "succeeded",
    ]
    tool, answered = first["steps"][2], first["steps"][3]
    assert (tool["tool"], tool["outcome"], tool["ms"]) == ("read_file", "ok", 40)
    assert (answered["model"], answered["tokens_in"], answered["tokens_out"]) == (
        "gemini-2.5-pro",
        1000,
        200,
    )
    assert second["steps"][2]["code"] == "render_timeout"
    spent = round(0.05 / settings.credit_usd, 2)
    assert (first["calls"], first["tokens_in"], first["credits"]) == (3, 1000, spent)
    # Its calls not measured yet: said so, never 0.
    assert (second["calls"], second["credits"]) == (None, None)
    assert first["requested_by"]["name"] == "Nora Diallo"

    # The actions proposed, decided, run and checked.
    [decision] = body["decisions"]
    assert (decision["status"], decision["risk"], decision["proposals"]) == (
        "approved",
        "medium",
        [{"id": "p1", "action": "rollback", "reversible": True, "targets": 1}],
    )
    assert [(v["verdict"], v["by"]["email"]) for v in decision["votes"]] == [
        ("approve", f"owner-{m}@acme.test")
    ]
    [plan] = body["plans"]
    assert (plan["status"], plan["error"]) == ("failed", "webhook_refused")
    assert [(s["action"], s["status"], s["error"]) for s in plan["steps"]] == [
        ("rollback", "failed", "502 from the endpoint")
    ]
    [check] = body["verifications"]
    assert (check["status"], check["expectations"], check["results"]) == ("failed", 1, 0)

    # Every error met, where; a model's same refusal once, counted.
    errors = body["errors"]
    assert [e["at"] for e in errors] == sorted((e["at"] for e in errors), reverse=True)
    assert {(e["source"], e["subject"], e["error"]) for e in errors} == {
        ("analysis_step", "ownership", "TimeoutError"),
        ("run", "code-review", "the model timed out"),
        ("run_step", "code-review", "render_failed: render_timeout"),
        ("plan", None, "webhook_refused"),
        ("plan_step", "rollback", "502 from the endpoint"),
        ("model_call", "agent:code-review · gemini-2.5-pro", "429: spend cap reached"),
    }
    assert next(e["count"] for e in errors if e["source"] == "model_call") == 2

    # What its work used, from the metering ledger.
    used = body["consumption"]
    assert (used["calls"], used["failed_calls"], used["tokens_in"], used["tokens_out"]) == (
        4,
        1,
        1300,
        250,
    )
    assert used["credits"] == round(0.06 / settings.credit_usd, 2)
    assert used["models"] == ["gemini/gemini-2.5-pro", "mistral/mistral-small"]
    assert [(w["kind"], w["subject"], w["calls"]) for w in used["by_work"]] == [
        ("agent_run", "code-review", 3),
        ("llm_run", "intention.understanding", 1),
    ]
    assert used["duration_ms"] == body["duration_ms"]

    # Its story, oldest first: no reason a person may have written.
    story = body["timeline"]
    assert [e["at"] for e in story] == sorted(e["at"] for e in story)
    assert {e["category"] for e in story} == {
        "intention",
        "analysis",
        "routing",
        "run",
        "decision",
    }
    assert all(e["reason"] is None for e in story)
    assert [(e["kind"], e["error"]) for e in story if e["ref"] == f"run:{broken}"] == [
        ("queued", None),
        ("started", None),
        ("render_failed", "render_timeout"),
        ("failed", "timeout"),
    ]
    queued = next(e for e in story if e["ref"] == f"run:{done}")
    assert (queued["subject"], queued["actor"], queued["by"]) == (
        "code-review",
        "person",
        "Nora Diallo",
    )
    assert [e["to_status"] for e in story if e["category"] == "intention"] == [None, "completed"]
    routed = next(e for e in story if e["category"] == "routing")
    assert (routed["kind"], routed["subject"]) == ("routed", "code-review")


async def test_what_the_customer_wrote_and_leka_produced_is_for_support(
    client: AsyncClient, world: World
) -> None:
    await _tell(world)
    m = world.marker
    response = await client.get(
        f"{API}/intentions/{world.intention}", headers=as_(world, AdminRole.SUPPORT)
    )
    body = response.json()
    content = body["content"]
    assert content["text"] == f"Why is payment-api slow? {m}"
    assert content["attachments"] == [f"trace-{m}.log"]
    [result] = content["results"]
    assert result == {
        "number": 1,
        "answer": f"Answer {m}",
        "summary": [f"Summary {m}"],
        "findings": [f"Finding {m}"],
        "causes": [f"Cause {m}"],
        "recommendations": [f"Roll back {m}"],
        "uncertainties": [],
        "missing": [f"Missing {m}"],
    }
    assert content["proposals"] == [
        {
            "decision": 1,
            "id": "p1",
            "action": "rollback",
            "environment": "production",
            "targets": [f"payment-api-{m}"],
        }
    ]
    assert list(content["deliverables"].values()) == [f"The deliverable {m}"]
    assert [e["reason"] for e in body["timeline"] if e["reason"]] == [f"Go {m}"]
    [kept] = await _read(AdminRole.SUPPORT, world)
    assert (kept.target_type, kept.target_id) == ("intention", str(world.intention))


def test_nothing_in_the_intentions_module_acts() -> None:
    """Read only: no route of the module starts, stops, approves or retries
    anything in a customer's environment."""
    paths = {
        path: set(operations)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(f"{API}/intentions")
    }
    assert paths == {f"{API}/intentions": {"get"}, f"{API}/intentions/{{intention_id}}": {"get"}}
