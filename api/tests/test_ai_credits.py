"""AI credits (LEKA-430), against the database.

What these protect: a workspace never put on a plan is on Free, its credits
the plan's; a plan set by LEKA — its credits overridden for a contract — and
a pack added to this month count, a pack of last month does not, and each is
kept in the audit trail; what is used is what its work cost LEKA on LEKA's
models, a workspace's own model and a failed call not counted; Facturation
reads its plan and its credits, its own and no other workspace's; each share
of the month's credits passed is told to its owners and admins once, however
often the watch runs; the server command refuses what cannot be.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.capabilities import ModelCall
from leka.db import session_factory, workspace_scope
from leka.governance import AuditEvent, PlanError, add_pack, allowance, set_plan
from leka.identity import User
from leka.metering import CreditWarning, credits_now, watch_credits
from leka.metering import credits as credit_watch
from leka.metering.cli import main
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

API = "/api/v1/billing/credits"


def _spend(workspace_id: uuid.UUID, cost_usd: float | None, **fields: Any) -> ModelCall:
    base: dict[str, Any] = {
        "workspace_id": workspace_id,
        "id": uuid.uuid4(),
        "purpose": "intention.understanding",
        "tier": "fast",
        "provider": "google",
        "model": "gemini-3.8-flash",
        "route": "default",
        "attempt": 1,
        "owner": "leka",
        "status": "ok",
        "usage_reported": True,
        "cost_usd": cost_usd,
        "at": datetime.now(UTC),
    }
    return ModelCall(**{**base, **fields})


async def _keep(workspace_id: uuid.UUID, *rows: Any) -> None:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            session.add_all(rows)
            await session.commit()


async def test_a_workspace_is_on_free_until_leka_puts_it_on_a_plan(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    now = datetime.now(UTC)
    with workspace_scope(workspace):
        async with session_factory() as session:
            free = await allowance(session, workspace, now)
            assert (free.plan.name, free.credits, free.plan.since) == ("free", 200, None)

            await set_plan(session, workspace, "growth", by="bilal", reason="pilot")
            assert (await allowance(session, workspace, now)).credits == 10_000

            await set_plan(
                session,
                workspace,
                "enterprise",
                by="bilal",
                reason="contract",
                monthly_credits=50_000,
            )
            await add_pack(session, workspace, 1_000, by="bilal", reason="asked by mail")
            await add_pack(
                session,
                workspace,
                5_000,
                by="bilal",
                reason="last month's",
                at=now.replace(day=1) - timedelta(days=2),
            )
            given = await allowance(session, workspace, now)
            assert (given.plan.name, given.plan.monthly_credits, given.packs) == (
                "enterprise",
                50_000,
                1_000,
            )
            assert given.credits == 51_000

            with pytest.raises(PlanError):
                await set_plan(session, workspace, "platinum", by="bilal", reason="no")
            with pytest.raises(PlanError):
                await add_pack(session, workspace, 0, by="bilal", reason="nothing")
            await session.commit()

            actions = (
                await session.scalars(
                    select(AuditEvent.action).where(AuditEvent.workspace_id == workspace)
                )
            ).all()
    assert sorted(actions).count("workspace.plan_changed") == 2
    assert sorted(actions).count("workspace.credits_added") == 2


async def test_used_is_what_leka_s_models_cost_its_own_model_and_failures_aside(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    await _keep(
        workspace,
        _spend(workspace, 0.90),
        _spend(workspace, 0.30, status="invalid"),
        _spend(workspace, 5.00, owner="workspace"),
        _spend(workspace, None, status="failed"),
        _spend(workspace, 7.00, at=datetime.now(UTC).replace(day=1) - timedelta(days=1)),
    )
    with workspace_scope(workspace):
        async with session_factory() as session:
            read = await credits_now(session, workspace, now=datetime.now(UTC))

    assert (read.plan, read.allowance, read.used, read.remaining) == ("free", 200, 120.0, 80.0)
    assert (read.percent, read.state, read.enforced) == (60.0, "ok", True)
    assert read.period_end - read.period_start >= timedelta(days=28)


async def test_facturation_reads_the_workspace_s_credits_and_no_other_s(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    await _keep(acme["acme"], _spend(acme["acme"], 1.70))
    _as(identity, acme, "member")
    mine = (await client.get(API)).json()
    assert (mine["plan"], mine["allowance"], mine["used"], mine["state"]) == (
        "free",
        200,
        170.0,
        "warning",
    )
    assert mine["warn_at"] == [80, 100]

    _as(identity, acme, "other_admin")
    theirs = (await client.get(API)).json()
    assert (theirs["used"], theirs["state"]) == (0.0, "ok")


async def test_each_share_passed_is_told_to_owners_and_admins_once(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Any] = []

    class Capture:
        async def send(self, message: Any) -> None:
            sent.append(message)

    monkeypatch.setattr(credit_watch, "build_email_sender", lambda: Capture())
    workspace = acme["acme"]
    await _keep(workspace, _spend(workspace, 1.65))

    with workspace_scope(workspace):
        async with session_factory() as session:
            admin = await session.scalar(select(User.email).where(User.id == acme["admin"]))

    def mine() -> list[Any]:
        return [m for m in sent if m.to == admin]

    told = await watch_credits()
    assert told[str(workspace)] == [80]
    [message] = mine()
    assert "80 %" in message.subject and "Aucun" not in message.body
    assert "aucun dépassement n'est facturé" in message.body

    # Past it all, the same day: told once more — spent — and only that.
    await _keep(workspace, _spend(workspace, 0.50))
    await watch_credits()
    await watch_credits()
    assert len(mine()) == 2
    assert "épuisés" in mine()[1].subject
    with workspace_scope(workspace):
        async with session_factory() as session:
            kept = (
                await session.scalars(
                    select(CreditWarning.threshold).where(CreditWarning.workspace_id == workspace)
                )
            ).all()
    assert sorted(kept) == [80, 100]


def test_the_command_refuses_an_unknown_plan(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["plan", str(uuid.uuid4()), "platinum", "--by", "bilal", "--reason", "no such plan"]
    )
    assert code == 1
    assert "unknown plan" in capsys.readouterr().err
