"""The Admin API over real rows (LEKA-544): every module's reads, the
activity journal, the dashboard's figures, and the sensitive operations.

One small world: an organisation on Growth with two people, an intention
asked and completed, two runs of an agent, a source in error, a failed
payment, a signed-in session — and a demonstration organisation every
figure must leave out. Four admins, one per role.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import redis.asyncio as redis
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from leka.admin import (
    ActivityEvent,
    ActivityWatermark,
    AdminAccount,
    AdminAuditEvent,
    AdminRole,
    create_account,
    sweep_activity,
)
from leka.admin.models import AdminDailyFigure
from leka.admin.overview import record_day, revenue
from leka.billing import AgentEntitlement, BillingAccount, StripeEvent
from leka.capabilities import AgentRun
from leka.connectors import HealthStatus, Source, SourceKind
from leka.core.config import settings
from leka.core.security import hash_token
from leka.db import session_factory, system_scope
from leka.governance import AuditEvent, WorkspacePlan
from leka.identity import Session, User
from leka.intentions import Intention, IntentionAnalysis, IntentionEvent
from leka.platform import Membership, Role, Workspace, WorkspaceStatus
from tests.conftest import error_code

pytestmark = pytest.mark.integration

API = "/api/v1/admin"
PASSWORD = "a long admin passphrase"
NOW = datetime.now(UTC)


@dataclass
class World:
    alpha: uuid.UUID
    demo: uuid.UUID
    owner: uuid.UUID
    member: uuid.UUID
    unverified: uuid.UUID
    intention: uuid.UUID
    marker: str
    tokens: dict[AdminRole, str]
    admins: list[str]


async def _build(marker: str) -> tuple[uuid.UUID, ...]:
    with system_scope():
        async with session_factory() as session:
            alpha = Workspace(id=uuid.uuid4(), name=f"Alpha {marker}", slug=f"alpha-{marker}")
            demo = Workspace(
                id=uuid.uuid4(), name=f"Demo {marker}", slug=f"demo-{marker}", demo=True
            )
            owner = User(
                id=uuid.uuid4(),
                email=f"owner-{marker}@acme.test",
                first_name="Nora",
                last_name="Diallo",
                email_verified_at=NOW - timedelta(days=40),
            )
            member = User(
                id=uuid.uuid4(), email=f"member-{marker}@acme.test", email_verified_at=NOW
            )
            unverified = User(id=uuid.uuid4(), email=f"new-{marker}@acme.test")
            session.add_all([alpha, demo, owner, member, unverified])
            await session.flush()
            await session.execute(
                text("UPDATE users SET created_at = :at WHERE id = :id"),
                {"at": NOW - timedelta(days=40), "id": owner.id},
            )
            intention = Intention(
                id=uuid.uuid4(),
                workspace_id=alpha.id,
                text=f"Why is payment-api slow? {marker}",
                title="Why is payment-api slow?",
                status="completed",
                status_changed_at=NOW,
                created_by=owner.id,
            )
            session.add_all(
                [
                    Membership(workspace_id=alpha.id, user_id=owner.id, role=Role.OWNER),
                    Membership(workspace_id=alpha.id, user_id=member.id, role=Role.MEMBER),
                    Membership(workspace_id=demo.id, user_id=member.id, role=Role.OWNER),
                    WorkspacePlan(
                        workspace_id=alpha.id,
                        id=uuid.uuid4(),
                        plan="growth",
                        reason="test",
                        set_by="test",
                        at=NOW - timedelta(days=5),
                    ),
                    BillingAccount(
                        workspace_id=alpha.id,
                        plan="growth",
                        interval="month",
                        status="active",
                        current_period_end=NOW + timedelta(days=20),
                    ),
                    intention,
                ]
            )
            await session.flush()
            session.add_all(
                [
                    IntentionEvent(
                        workspace_id=alpha.id,
                        intention_id=intention.id,
                        sequence=1,
                        kind="created",
                        actor="person",
                        by=owner.id,
                        at=NOW - timedelta(minutes=30),
                    ),
                    IntentionEvent(
                        workspace_id=alpha.id,
                        intention_id=intention.id,
                        sequence=2,
                        kind="moved",
                        from_status="analysing",
                        to_status="completed",
                        actor="system",
                        at=NOW - timedelta(minutes=1),
                    ),
                    AgentRun(
                        workspace_id=alpha.id,
                        key="code-review",
                        version="1.0.0",
                        status="succeeded",
                        inputs={},
                        requested_by=owner.id,
                        intention_id=intention.id,
                        format="markdown",
                        output=f"The deliverable {marker}",
                        detail={},
                        queued_at=NOW - timedelta(minutes=20),
                        started_at=NOW - timedelta(minutes=20),
                        finished_at=NOW - timedelta(minutes=18),
                    ),
                    AgentRun(
                        workspace_id=alpha.id,
                        key="code-review",
                        version="1.0.0",
                        status="failed",
                        inputs={},
                        requested_by=owner.id,
                        intention_id=intention.id,
                        format="markdown",
                        error="the model timed out",
                        detail={},
                        queued_at=NOW - timedelta(minutes=10),
                        started_at=NOW - timedelta(minutes=10),
                        finished_at=NOW - timedelta(minutes=6),
                    ),
                    Source(
                        workspace_id=alpha.id,
                        kind=SourceKind.GITHUB,
                        name=f"github-{marker}",
                        health_status=HealthStatus.UNHEALTHY,
                        last_error="401 from GitHub",
                    ),
                    StripeEvent(
                        event_id=f"evt_{marker}",
                        type="invoice.payment_failed",
                        for_workspace_id=alpha.id,
                        outcome="applied",
                        detail={},
                        received_at=NOW - timedelta(hours=1),
                    ),
                    Session(
                        user_id=owner.id,
                        token_hash=hash_token(f"session-{marker}"),
                        active_workspace_id=alpha.id,
                        last_seen_at=NOW,
                        expires_at=NOW + timedelta(days=7),
                    ),
                ]
            )
            await session.commit()
    return alpha.id, demo.id, owner.id, member.id, unverified.id, intention.id


@pytest.fixture
async def world(client: AsyncClient) -> AsyncIterator[World]:
    marker = uuid.uuid4().hex[:8]
    alpha, demo, owner, member, unverified, intention = await _build(marker)
    # Read the whole history again: what earlier tests wrote, and this world.
    async with session_factory() as session:
        await session.execute(delete(ActivityWatermark))
        await session.commit()
    await sweep_activity()

    tokens: dict[AdminRole, str] = {}
    admins: list[str] = []
    for role in AdminRole:
        email = f"{role.value}-{marker}@leka.test"
        async with session_factory() as session:
            await create_account(
                session, email=email, name=role.value, role=role.value, password=PASSWORD, by="test"
            )
            await session.commit()
        signed = await client.post(
            f"{API}/auth/sign-in", json={"email": email, "password": PASSWORD}
        )
        tokens[role] = signed.json()["token"]
        admins.append(email)

    yield World(alpha, demo, owner, member, unverified, intention, marker, tokens, admins)

    with system_scope():
        async with session_factory() as session:
            await session.execute(delete(Workspace).where(Workspace.id.in_([alpha, demo])))
            await session.execute(delete(User).where(User.id.in_([owner, member, unverified])))
            await session.execute(delete(AdminAccount).where(AdminAccount.email.in_(admins)))
            await session.execute(
                delete(StripeEvent).where(StripeEvent.event_id == f"evt_{marker}")
            )
            await session.commit()


def as_(world: World, role: AdminRole) -> dict[str, str]:
    return {"Authorization": f"Bearer {world.tokens[role]}"}


async def _trail(action: str, target: uuid.UUID) -> list[AdminAuditEvent]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(AdminAuditEvent).where(
                        AdminAuditEvent.action == action, AdminAuditEvent.target_id == str(target)
                    )
                )
            ).all()
        )


SUPER = AdminRole.SUPER_ADMIN

# ── Organisations ────────────────────────────────────────────────────────────


async def test_organisations_list_real_customers_with_their_figures(
    client: AsyncClient, world: World
) -> None:
    response = await client.get(
        f"{API}/organisations", params={"q": world.marker}, headers=as_(world, SUPER)
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert [r["id"] for r in rows] == [str(world.alpha)]
    alpha = rows[0]
    assert alpha["plan"] == "growth"
    assert alpha["owner"]["email"] == f"owner-{world.marker}@acme.test"
    assert alpha["owner"]["name"] == "Nora Diallo"
    assert (alpha["members"], alpha["intentions"]) == (2, 1)
    assert alpha["last_activity_at"] is not None

    with_demo = await client.get(
        f"{API}/organisations",
        params={"q": world.marker, "include_demo": "true"},
        headers=as_(world, SUPER),
    )
    assert {r["id"] for r in with_demo.json()["data"]} == {str(world.alpha), str(world.demo)}


async def test_organisations_are_found_by_owner_email_and_plan_and_paged(
    client: AsyncClient, world: World
) -> None:
    by_email = await client.get(
        f"{API}/organisations", params={"q": f"owner-{world.marker}@"}, headers=as_(world, SUPER)
    )
    assert [r["id"] for r in by_email.json()["data"]] == [str(world.alpha)]
    by_plan = await client.get(
        f"{API}/organisations", params={"plan": "growth", "limit": 200}, headers=as_(world, SUPER)
    )
    assert str(world.alpha) in {r["id"] for r in by_plan.json()["data"]}
    assert all(r["plan"] == "growth" for r in by_plan.json()["data"])

    paged: dict[str, str | int] = {"q": world.marker, "include_demo": "true", "limit": 1}
    first = await client.get(f"{API}/organisations", params=paged, headers=as_(world, SUPER))
    assert len(first.json()["data"]) == 1
    cursor = first.json()["next_cursor"]
    assert cursor
    second = await client.get(
        f"{API}/organisations", params={**paged, "cursor": cursor}, headers=as_(world, SUPER)
    )
    assert second.json()["data"][0]["id"] != first.json()["data"][0]["id"]

    refused = await client.get(
        f"{API}/organisations", params={"sort": "password_hash"}, headers=as_(world, SUPER)
    )
    assert refused.status_code == 400
    assert error_code(refused) == "invalid_sort"


async def test_an_organisation_whole_and_its_reading_kept(
    client: AsyncClient, world: World
) -> None:
    response = await client.get(
        f"{API}/organisations/{world.alpha}", headers=as_(world, AdminRole.SUPPORT)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["billing"]["status"] == "active"
    assert body["credits"]["plan"] == "growth"
    assert body["counts"]["agent_runs"] == 2
    assert body["counts"]["agent_runs_failed"] == 1
    assert body["counts"]["intentions_completed"] == 1
    assert body["counts"]["sources_in_error"] == 1
    assert body["counts"]["active_users_30d"] == 1
    assert body["agents_used"] == ["code-review"]
    assert len(await _trail("admin.viewed", world.alpha)) == 1

    members = await client.get(
        f"{API}/organisations/{world.alpha}/members", headers=as_(world, SUPER)
    )
    assert {m["role"] for m in members.json()["members"]} == {"owner", "member"}

    missing = await client.get(f"{API}/organisations/{uuid.uuid4()}", headers=as_(world, SUPER))
    assert missing.status_code == 404


# ── People ───────────────────────────────────────────────────────────────────


async def test_people_are_classified_by_what_they_did(client: AsyncClient, world: World) -> None:
    response = await client.get(
        f"{API}/users", params={"q": world.marker, "limit": 50}, headers=as_(world, SUPER)
    )
    statuses = {r["email"].split("-")[0]: r["status"] for r in response.json()["data"]}
    # The owner asked an intention this month; the member just signed up;
    # the third never confirmed their address.
    assert statuses == {"owner": "active", "member": "new", "new": "unverified"}

    owner = await client.get(f"{API}/users/{world.owner}", headers=as_(world, SUPER))
    assert owner.status_code == 200
    body = owner.json()
    assert [o["organisation"]["id"] for o in body["organisations"]] == [str(world.alpha)]
    assert body["agent_runs"] == 2
    assert len(body["sign_ins"]) >= 1


# ── Intentions ───────────────────────────────────────────────────────────────


async def test_intentions_across_customers_with_their_five_statuses(
    client: AsyncClient, world: World
) -> None:
    response = await client.get(
        f"{API}/intentions",
        params={"organisation_id": str(world.alpha), "status": "completed", "agent": "code-review"},
        headers=as_(world, AdminRole.OPERATIONS),
    )
    rows = response.json()["data"]
    assert [r["id"] for r in rows] == [str(world.intention)]
    assert rows[0]["admin_status"] == "completed"
    assert rows[0]["agents"] == ["code-review"]


async def test_what_a_customer_wrote_is_for_support_and_each_reading_is_kept(
    client: AsyncClient, world: World
) -> None:
    support = await client.get(
        f"{API}/intentions/{world.intention}", headers=as_(world, AdminRole.SUPPORT)
    )
    body = support.json()
    assert body["content"]["text"].endswith(world.marker)
    assert list(body["content"]["deliverables"].values()) == [f"The deliverable {world.marker}"]
    assert [e["to_status"] for e in body["timeline"]] == [None, "completed"]
    assert [r["status"] for r in body["runs"]] == ["succeeded", "failed"]
    assert body["runs"][1]["error"] == "the model timed out"

    operations = await client.get(
        f"{API}/intentions/{world.intention}", headers=as_(world, AdminRole.OPERATIONS)
    )
    assert operations.json()["content"] is None
    assert f"slow? {world.marker}" not in operations.text
    assert "The deliverable" not in operations.text

    assert len(await _trail("admin.viewed_content", world.intention)) == 1
    assert len(await _trail("admin.viewed", world.intention)) == 1


# ── Agents, credits, money, environments ─────────────────────────────────────


async def test_agents_are_measured_from_their_runs(client: AsyncClient, world: World) -> None:
    response = await client.get(
        f"{API}/agents",
        params={"organisation_id": str(world.alpha)},
        headers=as_(world, AdminRole.FINANCE),
    )
    (stat,) = response.json()["data"]
    assert (stat["key"], stat["runs"], stat["succeeded"], stat["failed"]) == (
        "code-review",
        2,
        1,
        1,
    )
    assert stat["success_rate"] == 0.5
    assert stat["average_duration_ms"] == 180000
    # No usage metered for these runs: unavailable, never 0.
    assert stat["cost_usd"] is None


async def test_money_is_finance_s_and_a_refusal_is_kept(client: AsyncClient, world: World) -> None:
    subscriptions = await client.get(
        f"{API}/subscriptions",
        params={"plan": "growth", "limit": 200},
        headers=as_(world, AdminRole.FINANCE),
    )
    assert str(world.alpha) in {r["organisation"]["id"] for r in subscriptions.json()["data"]}
    events = await client.get(
        f"{API}/billing/events",
        params={"organisation_id": str(world.alpha), "type": "invoice.*"},
        headers=as_(world, AdminRole.FINANCE),
    )
    assert [e["type"] for e in events.json()["data"]] == ["invoice.payment_failed"]

    refused = await client.get(f"{API}/subscriptions", headers=as_(world, AdminRole.SUPPORT))
    assert refused.status_code == 403
    assert error_code(refused) == "permission_denied"
    async with session_factory() as session:
        kept = await session.scalar(
            select(func.count()).where(
                AdminAuditEvent.action == "admin.refused",
                AdminAuditEvent.admin_email == f"support-{world.marker}@leka.test",
            )
        )
    assert kept == 1


async def test_credits_and_sources_in_error(client: AsyncClient, world: World) -> None:
    month = await client.get(
        f"{API}/organisations/{world.alpha}/credits", headers=as_(world, AdminRole.FINANCE)
    )
    assert month.json()["credits"]["plan"] == "growth"
    listed = await client.get(
        f"{API}/credits", params={"q": world.marker}, headers=as_(world, AdminRole.FINANCE)
    )
    assert [r["organisation"]["id"] for r in listed.json()["data"]] == [str(world.alpha)]

    sources = await client.get(
        f"{API}/sources",
        params={"organisation_id": str(world.alpha), "in_error": "true"},
        headers=as_(world, AdminRole.OPERATIONS),
    )
    (row,) = sources.json()["data"]
    assert (row["kind"], row["health"], row["last_error"]) == (
        "github",
        "unhealthy",
        "401 from GitHub",
    )
    assert "credential" not in sources.text


# ── The activity journal ─────────────────────────────────────────────────────


async def test_the_journal_says_what_happened_once(client: AsyncClient, world: World) -> None:
    response = await client.get(
        f"{API}/organisations/{world.alpha}/activity",
        params={"limit": 200},
        headers=as_(world, SUPER),
    )
    kinds = sorted(e["kind"] for e in response.json()["data"])
    assert kinds == sorted(
        [
            "workspace.created",
            "member.joined",
            "member.joined",
            "intention.created",
            "intention.completed",
            "agent_run.succeeded",
            "agent_run.failed",
            "source.connected",
            "payment.failed",
            "user.signed_in",
            "user.active",
        ]
    )
    assert all(world.marker not in str(e["properties"]) for e in response.json()["data"])

    async def count() -> int:
        async with session_factory() as session:
            return int(
                await session.scalar(
                    select(func.count()).where(ActivityEvent.for_workspace_id == world.alpha)
                )
                or 0
            )

    before = await count()
    async with session_factory() as session:
        await session.execute(delete(ActivityWatermark))
        await session.commit()
    await sweep_activity()
    await sweep_activity()
    assert await count() == before

    signed_up = await client.get(
        f"{API}/activity",
        params={"kind": "user.signed_up", "user_id": str(world.member)},
        headers=as_(world, SUPER),
    )
    assert len(signed_up.json()["data"]) == 1


async def test_the_dashboard_counts_real_customers_only(client: AsyncClient, world: World) -> None:
    response = await client.get(
        f"{API}/overview", params={"period": "7d"}, headers=as_(world, AdminRole.FINANCE)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["window"]["bucket"] == "day"
    assert body["activity"]["dau"] >= 1
    assert body["product"]["agent_runs"] >= 2
    assert body["business"]["payments_failed"] >= 1
    # Finance reads billing: the amounts are its to read.
    assert body["business"]["amounts_granted"] is True
    assert body["acquisition"]["by_plan"].get("growth", 0) >= 1
    assert body["acquisition"]["organisations_paid"] >= 1
    assert set(body["series"]) == {
        "organisations",
        "users",
        "users_new",
        "users_active",
        "intentions_created",
        "credits_consumed",
        "mrr",
    }
    # Every day of the period, a point: none missing where nothing happened.
    assert len(body["series"]["intentions_created"]) == 8

    bad = await client.get(
        f"{API}/overview",
        params={
            "period": "custom",
            "from": NOW.isoformat(),
            "to": (NOW - timedelta(days=1)).isoformat(),
        },
        headers=as_(world, SUPER),
    )
    assert bad.status_code == 400


async def test_amounts_are_only_for_who_reads_billing(client: AsyncClient, world: World) -> None:
    support = (await client.get(f"{API}/overview", headers=as_(world, AdminRole.SUPPORT))).json()
    business = support["business"]
    assert business["amounts_granted"] is False
    assert [business[k] for k in ("mrr", "arr", "collected", "collected_tax", "refunded")] == [
        None
    ] * 5
    assert (support["costs"]["amounts_granted"], support["costs"]["ai_usd"]) == (False, None)
    assert "mrr" not in support["series"]
    # What is counted, not an amount, stays: the subscriptions, the payments failed.
    assert business["payments_failed"] >= 1

    finance = (await client.get(f"{API}/overview", headers=as_(world, AdminRole.FINANCE))).json()
    assert finance["business"]["amounts_granted"] is True
    assert finance["costs"]["amounts_granted"] is True


async def test_the_mrr_is_each_paying_subscription_once_coupon_off_trials_apart(
    world: World,
) -> None:
    def monthly(amount: int, percent_off: float | None = None) -> dict[str, object]:
        ends = (NOW + timedelta(days=200)).isoformat()
        return {
            "amount": amount,
            "currency": "eur",
            "interval": "month",
            "interval_count": 1,
            "discount": {"percent_off": percent_off, "amount_off": None, "ends": ends}
            if percent_off
            else None,
        }

    m = world.marker
    paying, trial, unknown, demo = (
        Workspace(id=uuid.uuid4(), name=f"{name} {m}", slug=f"mrr-{name}-{m}", demo=name == "demo")
        for name in ("paying", "trial", "unknown", "demo")
    )
    with system_scope():
        async with session_factory() as session:
            before = await revenue(session, NOW)
            session.add_all([paying, trial, unknown, demo])
            await session.flush()

            def account(ws: Workspace, status: str, recurring: object) -> BillingAccount:
                return BillingAccount(
                    workspace_id=ws.id,
                    plan="growth",
                    status=status,
                    interval="month",
                    stripe_subscription_id=f"sub_{ws.slug}",
                    recurring=recurring,
                )

            def add_on(key: str) -> AgentEntitlement:
                # Two agents bought together: one subscription, counted once.
                return AgentEntitlement(
                    workspace_id=paying.id,
                    key=key,
                    kind="agent",
                    origin="purchase",
                    stripe_subscription_id=f"sub_addons_{m}",
                    by_whom="stripe",
                    started_at=NOW,
                    recurring=monthly(1500),
                )

            session.add_all(
                [
                    account(paying, "active", monthly(17900, percent_off=20)),
                    account(trial, "trialing", monthly(17900)),
                    account(unknown, "active", None),
                    account(demo, "active", monthly(59900)),
                    add_on("code-review"),
                    add_on("architecture-analysis"),
                ]
            )
            await session.flush()
            after = await revenue(session, NOW)
            assert round(after.cents - before.cents) == 14320 + 1500
            assert (
                after.counted - before.counted,
                after.unknown - before.unknown,
                after.trialing - before.trialing,
            ) == (2, 1, 1)

            # Kept once a day, the last sweep of the day saying it.
            day = datetime(2031, 1, 2, 9, tzinfo=UTC)
            await record_day(session, day)
            await record_day(session, day + timedelta(hours=3))
            kept = (
                await session.scalars(
                    select(AdminDailyFigure).where(AdminDailyFigure.day == day.date())
                )
            ).all()
            assert len(kept) == 1
            # In 2031 the coupon has ended: the whole price, as that day says it.
            then = await revenue(session, day + timedelta(hours=3))
            assert round(then.cents - before.cents) == 17900 + 1500
            assert kept[0].mrr is not None and float(kept[0].mrr) == then.mrr
            assert kept[0].at == day + timedelta(hours=3)
            await session.rollback()


async def test_a_period_of_its_own_says_each_figure_exactly(
    client: AsyncClient, world: World
) -> None:
    """March 2031: only what this test made happened then."""
    m = world.marker
    start = datetime(2031, 3, 1, tzinfo=UTC)
    born = start + timedelta(days=1, hours=10)
    beta = Workspace(id=uuid.uuid4(), name=f"Beta {m}", slug=f"beta-{m}")
    shown = Workspace(id=uuid.uuid4(), name=f"Shown {m}", slug=f"shown-{m}", demo=True)
    person = User(id=uuid.uuid4(), email=f"beta-{m}@acme.test")
    asked = Intention(
        id=uuid.uuid4(),
        workspace_id=beta.id,
        text=f"Map our services {m}",
        title="Map our services",
        status="completed",
        status_changed_at=born + timedelta(hours=6),
    )
    facts = [
        ("workspace.created", born, beta.id, None, {}),
        ("user.active", born, beta.id, person.id, {}),
        ("intention.created", born, beta.id, person.id, {}),
        ("intention.completed", born + timedelta(hours=6), beta.id, None, {}),
        ("intention.failed", born + timedelta(hours=7), beta.id, None, {}),
        ("subscription.started", born + timedelta(days=3), beta.id, None, {"outcome": "applied"}),
        ("payment.failed", born + timedelta(days=4), beta.id, None, {"outcome": "applied"}),
        # No organisation of LEKA's answers for it: never counted.
        ("payment.failed", born + timedelta(days=4), None, None, {"outcome": "ignored"}),
        ("intention.created", born, shown.id, None, {}),
    ]
    with system_scope():
        async with session_factory() as session:
            session.add_all([beta, shown, person])
            await session.flush()
            await session.execute(
                text("UPDATE workspaces SET created_at = :at WHERE id IN (:beta, :shown)"),
                {"at": born, "beta": beta.id, "shown": shown.id},
            )
            session.add(asked)
            await session.flush()
            session.add_all(
                [
                    IntentionEvent(
                        workspace_id=beta.id,
                        intention_id=asked.id,
                        sequence=1,
                        kind="moved",
                        from_status="analysing",
                        to_status="completed",
                        actor="system",
                        at=born + timedelta(hours=6),
                    ),
                    *(
                        IntentionAnalysis(
                            workspace_id=beta.id,
                            intention_id=asked.id,
                            number=number,
                            trigger="created",
                            status=status,
                            started_at=born,
                            finished_at=born + timedelta(hours=1),
                        )
                        for number, status in ((1, "failed"), (2, "complete"), (3, "blocked"))
                    ),
                    *(
                        AgentRun(
                            workspace_id=beta.id,
                            key="architecture-analysis",
                            version="1.0.0",
                            status=status,
                            inputs={},
                            format="markdown",
                            detail={},
                            queued_at=born + timedelta(hours=2),
                            started_at=born + timedelta(hours=2),
                            finished_at=born + timedelta(hours=3),
                        )
                        for status in ("succeeded", "failed")
                    ),
                ]
            )
            await session.execute(
                insert(ActivityEvent).values(
                    [
                        {
                            "id": uuid.uuid4(),
                            "kind": kind,
                            "at": at,
                            "for_workspace_id": workspace,
                            "user_id": user,
                            "properties": properties,
                            "dedupe_key": f"test-548:{m}:{n}",
                        }
                        for n, (kind, at, workspace, user, properties) in enumerate(facts)
                    ]
                )
            )
            await session.commit()
    try:
        response = await client.get(
            f"{API}/overview",
            params={
                "period": "custom",
                "from": start.isoformat(),
                "to": (start + timedelta(days=30)).isoformat(),
            },
            headers=as_(world, SUPER),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["acquisition"]["organisations_new"] == 1
        activity = body["activity"]
        assert activity["organisations_active"] == 1
        assert (activity["intentions_completed"], activity["intentions_failed"]) == (1, 1)
        assert activity["intention_success_rate"] == 0.5
        # The blocked one asked a question: neither ended nor failed.
        assert (activity["analyses_completed"], activity["analyses_failed"]) == (1, 1)
        product = body["product"]
        assert (product["agent_runs"], product["agent_success_rate"]) == (2, 0.5)
        assert product["agent_adoption_rate"] == 1.0
        assert product["top_agents"] == [
            {"key": "architecture-analysis", "runs": 2, "succeeded": 1, "failed": 1}
        ]
        business = body["business"]
        assert (business["subscriptions_started"], business["payments_failed"]) == (1, 1)
        intelligence = body["intelligence"]
        assert (intelligence["organisations_created"], intelligence["activated"]) == (1, 1)
        assert intelligence["activation_rate"] == 1.0
        assert intelligence["time_to_first_value_hours"] == 6.0
        assert (intelligence["converted"], intelligence["conversion_rate"]) == (1, 1.0)
        # A point a day; the organisations in all, Beta among them from its day.
        organisations = body["series"]["organisations"]
        assert len(organisations) == 30
        assert organisations[-1]["value"] - organisations[0]["value"] == 1
        assert organisations[1]["value"] - organisations[0]["value"] == 1
        # The latest activity, whatever the period: Beta's, the latest of all.
        named = {(r["kind"], (r["organisation"] or {}).get("name")) for r in body["recent"]}
        assert ("subscription.started", beta.name) in named
        assert all(
            r["organisation"] is None or r["organisation"]["id"] != str(shown.id)
            for r in body["recent"]
        )
    finally:
        with system_scope():
            async with session_factory() as session:
                await session.execute(
                    delete(ActivityEvent).where(ActivityEvent.dedupe_key.like(f"test-548:{m}:%"))
                )
                await session.execute(
                    delete(Workspace).where(Workspace.id.in_([beta.id, shown.id]))
                )
                await session.execute(delete(User).where(User.id == person.id))
                await session.commit()


async def test_the_incidents_firing_now_are_the_ops_watch_s(
    client: AsyncClient, world: World
) -> None:
    store = redis.from_url(str(settings.redis_url))
    key = "leka:ops:alert:backup_stale"
    since = NOW - timedelta(hours=2)
    await store.set(
        key,
        json.dumps({"since": since.isoformat(), "told": since.isoformat(), "why": "none in 30 h"}),
    )
    try:
        body = (await client.get(f"{API}/overview", headers=as_(world, SUPER))).json()
        [incident] = [i for i in body["technical"]["incidents"] if i["rule"] == "backup_stale"]
        assert (incident["severity"], incident["title"], incident["why"]) == (
            "critical",
            "Backups are not being taken",
            "none in 30 h",
        )
        assert datetime.fromisoformat(incident["since"]) == since
    finally:
        await store.delete(key)
        await store.aclose()


# ── Sensitive operations ─────────────────────────────────────────────────────


async def test_suspending_is_done_once_said_twice_and_kept(
    client: AsyncClient, world: World
) -> None:
    path = f"{API}/organisations/{world.alpha}/suspend"
    key = {"Idempotency-Key": f"suspend-{world.marker}"}
    headers = {**as_(world, AdminRole.OPERATIONS), **key}

    first = await client.post(path, json={"reason": "unpaid since October"}, headers=headers)
    assert first.status_code == 200
    assert (first.json()["status"], first.json()["replayed"]) == ("suspended", False)
    again = await client.post(path, json={"reason": "unpaid since October"}, headers=headers)
    assert (again.json()["status"], again.json()["replayed"]) == ("suspended", True)
    assert len(await _trail("admin.organisation_suspended", world.alpha)) == 1

    other = await client.post(path, json={"reason": "another reason"}, headers=headers)
    assert other.status_code == 409
    no_key = await client.post(
        path, json={"reason": "no key"}, headers=as_(world, AdminRole.OPERATIONS)
    )
    assert no_key.status_code == 422

    with system_scope():
        async with session_factory() as session:
            told = (
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.workspace_id == world.alpha,
                        AuditEvent.action == "workspace.suspended",
                    )
                )
            ).all()
            workspace = await session.get(Workspace, world.alpha)
    assert len(told) == 1
    assert "unpaid" not in str(told[0].detail)
    assert workspace is not None and workspace.status == WorkspaceStatus.SUSPENDED

    back = await client.post(
        f"{API}/organisations/{world.alpha}/reactivate",
        json={"reason": "paid"},
        headers={**as_(world, AdminRole.OPERATIONS), "Idempotency-Key": f"back-{world.marker}"},
    )
    assert back.json()["status"] == "active"


async def test_who_may_change_an_organisation(client: AsyncClient, world: World) -> None:
    path = f"{API}/organisations/{world.alpha}/suspend"
    for role in (AdminRole.FINANCE, AdminRole.SUPPORT):
        refused = await client.post(
            path,
            json={"reason": "not mine"},
            headers={**as_(world, role), "Idempotency-Key": f"k-{role.value}-1"},
        )
        assert refused.status_code == 403, role


async def test_credits_are_added_by_finance_with_a_reason(
    client: AsyncClient, world: World
) -> None:
    path = f"{API}/organisations/{world.alpha}/credits"
    added = await client.post(
        path,
        json={"credits": 500, "reason": "a gesture after the outage"},
        headers={**as_(world, AdminRole.FINANCE), "Idempotency-Key": f"credits-{world.marker}"},
    )
    assert added.status_code == 200
    assert added.json()["credits"]["packs"] == 500

    for body in ({"credits": 0, "reason": "zero"}, {"credits": 10, "reason": ""}):
        invalid = await client.post(
            path,
            json=body,
            headers={**as_(world, AdminRole.FINANCE), "Idempotency-Key": f"bad-{uuid.uuid4()}"},
        )
        assert invalid.status_code == 422
    refused = await client.post(
        path,
        json={"credits": 10, "reason": "not mine"},
        headers={**as_(world, AdminRole.SUPPORT), "Idempotency-Key": f"support-{world.marker}"},
    )
    assert refused.status_code == 403


async def test_an_organisation_its_customer_asked_to_delete_is_left_alone(
    client: AsyncClient, world: World
) -> None:
    with system_scope():
        async with session_factory() as session:
            workspace = await session.get(Workspace, world.alpha)
            assert workspace is not None
            workspace.status = WorkspaceStatus.PENDING_DELETION
            workspace.deletion_requested_at = NOW
            await session.commit()
    response = await client.post(
        f"{API}/organisations/{world.alpha}/reactivate",
        json={"reason": "by mistake"},
        headers={**as_(world, SUPER), "Idempotency-Key": f"del-{world.marker}"},
    )
    assert response.status_code == 409
    with system_scope():
        async with session_factory() as session:
            still = await session.get(Workspace, world.alpha)
    assert still is not None and still.deletion_requested_at is not None


async def test_the_admin_trail_is_super_admin_s(client: AsyncClient, world: World) -> None:
    await client.get(f"{API}/organisations/{world.alpha}", headers=as_(world, SUPER))
    trail = await client.get(
        f"{API}/audit", params={"organisation_id": str(world.alpha)}, headers=as_(world, SUPER)
    )
    assert "admin.viewed" in {e["action"] for e in trail.json()["data"]}
    assert (
        await client.get(f"{API}/audit", headers=as_(world, AdminRole.OPERATIONS))
    ).status_code == 403
