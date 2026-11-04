"""The AI capacity's prompts (LEKA-527): at 90 % and 100 % of a month's AI
credits, the next plan offered in a banner.

What these protect: nothing under 90 %; at 90 %, the usage and the next plan
— its credits and its price as the catalogue and checkout have them, on the
subscription's own cadence; at 100 %, said spent and what that does; each
threshold kept once a month, whoever reads it and however many at once; a
person's 90 % put aside, the 100 % still comes; a new month starts over; an
upgrade hides what no longer applies; no plan to buy above, or a contract:
when the credits come back and whom to ask; one who may not pay asks the
admins — once; nothing claims more credits before the plan is applied.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from leka.billing import BillingAccount, catalogue, quote
from leka.db import session_factory, workspace_scope
from leka.governance import set_plan
from leka.metering import CreditWarning, credit_prompt, dismiss_credit_prompt
from leka.notifications import Notification
from tests.conftest import FakeIdentity
from tests.test_ai_credits import _keep, _spend
from tests.test_sources_api import _as, acme  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

PROMPT = "/api/v1/billing/credits/prompt"


async def _on(workspace: uuid.UUID, plan: str, **more: Any) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await set_plan(session, workspace, plan, by="test", reason="LEKA-527", **more)
            await session.commit()


async def _kept(workspace: uuid.UUID, threshold: int) -> int:
    with workspace_scope(workspace):
        async with session_factory() as session:
            return int(
                await session.scalar(
                    select(func.count()).where(
                        CreditWarning.workspace_id == workspace,
                        CreditWarning.threshold == threshold,
                    )
                )
                or 0
            )


async def test_nothing_under_90_then_the_next_plan_with_its_credits_and_price(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    _as(identity, acme, "admin")
    # Free: 200 credits a month; 1 credit = 0.01 $ of LEKA's model cost.
    await _keep(workspace, _spend(workspace, 1.70))
    assert (await client.get(PROMPT)).json() is None

    await _keep(workspace, _spend(workspace, 0.12))
    said: dict[str, Any] = (await client.get(PROMPT)).json()
    assert (said["threshold"], said["allowance"], said["percent"]) == (90, 200, 91.0)
    assert said["used"] == pytest.approx(182) and said["remaining"] == pytest.approx(18)
    assert (said["path"], said["can_pay"], said["asked"]) == ("upgrade", True, False)
    current, recommended = said["current"], said["recommended"]
    assert (current["key"], current["credits"], current["monthly"]) == ("free", 200, 0)
    # The next plan, as the catalogue and checkout price it — never the page's.
    offer = catalogue()
    expected = quote(
        offer.plan("starter"), "month", offer, today=datetime.now(UTC).date(), trial=False
    )
    assert (recommended["key"], recommended["credits"]) == ("starter", 2000)
    assert (recommended["interval"], recommended["monthly"], recommended["charged"]) == (
        "month",
        expected.monthly,
        expected.charged,
    )
    assert recommended["discount"] == expected.discount
    assert (said["more_credits"], said["more_monthly"]) == (1800, expected.list_monthly)
    assert said["currency"] == offer.currency
    # Read again, twice: the 90 % kept once.
    await client.get(PROMPT)
    assert await _kept(workspace, 90) == 1


async def test_spent_said_with_what_it_does_and_the_90_put_aside_never_hides_the_100(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _keep(workspace, _spend(workspace, 1.85))
    _as(identity, acme, "member")
    assert (await client.get(PROMPT)).json()["threshold"] == 90
    put = await client.post(f"{PROMPT}/dismiss", json={"threshold": 90})
    assert put.status_code == 204
    assert (await client.get(PROMPT)).json() is None
    # Put aside by the member: the admin still sees it.
    _as(identity, acme, "admin")
    assert (await client.get(PROMPT)).json()["threshold"] == 90

    await _keep(workspace, _spend(workspace, 0.20))
    _as(identity, acme, "member")
    spent: dict[str, Any] = (await client.get(PROMPT)).json()
    assert (spent["threshold"], spent["enforced"], spent["remaining"]) == (100, True, 0)
    assert spent["period_end"] > spent["period_start"]
    assert (await client.post(f"{PROMPT}/dismiss", json={"threshold": 100})).status_code == 204
    assert (await client.get(PROMPT)).json() is None
    # A threshold no prompt has: refused.
    assert (await client.post(f"{PROMPT}/dismiss", json={"threshold": 50})).status_code == 422


async def test_a_new_month_starts_over_and_an_upgrade_hides_what_no_longer_applies(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace, member = acme["acme"], acme["member"]
    now = datetime.now(UTC)
    await _keep(workspace, _spend(workspace, 1.90, at=now))
    with workspace_scope(workspace):
        async with session_factory() as session:
            found = await credit_prompt(session, workspace, member, can_pay=False, now=now)
            assert found is not None and found.threshold == 90
            await dismiss_credit_prompt(session, workspace, member, 90, now=now)
            await session.commit()
            assert await credit_prompt(session, workspace, member, can_pay=False, now=now) is None
    # The next month: nothing used, nothing to say; used again, said again.
    later = (now.replace(day=1) + timedelta(days=32)).replace(day=2)
    with workspace_scope(workspace):
        async with session_factory() as session:
            assert await credit_prompt(session, workspace, member, can_pay=False, now=later) is None
    await _keep(workspace, _spend(workspace, 1.95, at=later))
    with workspace_scope(workspace):
        async with session_factory() as session:
            again = await credit_prompt(session, workspace, member, can_pay=False, now=later)
            assert again is not None and again.threshold == 90

    # This month, on Starter: 190 of 2,000 — what no longer applies is gone.
    await _on(workspace, "starter")
    with workspace_scope(workspace):
        async with session_factory() as session:
            assert await credit_prompt(session, workspace, member, can_pay=False, now=now) is None


async def test_the_subscription_s_cadence_kept_and_no_plan_above_or_a_contract(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    _as(identity, acme, "admin")
    # Growth, billed yearly: Business offered yearly too — never another cadence.
    await _on(workspace, "growth")
    with workspace_scope(workspace):
        async with session_factory() as session:
            session.add(
                BillingAccount(
                    workspace_id=workspace,
                    id=uuid.uuid4(),
                    plan="growth",
                    interval="year",
                    launch_offer_used=True,
                )
            )
            await session.commit()
    await _keep(workspace, _spend(workspace, 92.0))
    said: dict[str, Any] = (await client.get(PROMPT)).json()
    offer = catalogue()
    today = datetime.now(UTC).date()
    business = quote(offer.plan("business"), "year", offer, today=today, launch=False, trial=False)
    growth = quote(offer.plan("growth"), "year", offer, today=today, launch=False, trial=False)
    assert (said["recommended"]["key"], said["recommended"]["interval"]) == ("business", "year")
    assert (said["recommended"]["charged"], said["recommended"]["discount"]) == (
        business.charged,
        "annual",
    )
    # What it adds, as a yearly subscription pays it: both with their discount.
    assert said["more_monthly"] == business.monthly - growth.monthly
    assert said["more_credits"] == 40_000 - 10_000

    # Business: above it, Enterprise — through LEKA's sales, no price.
    await _on(workspace, "business")
    await _keep(workspace, _spend(workspace, 300.0))
    sales: dict[str, Any] = (await client.get(PROMPT)).json()
    assert (sales["path"], sales["recommended"]["key"]) == ("sales", "enterprise")
    assert (sales["recommended"]["credits"], sales["recommended"]["monthly"]) == (None, None)
    assert sales["contact_url"].startswith("https://")

    # A contract — Enterprise, or credits other than a plan's: no plan to buy;
    # when the credits come back, and whom to ask.
    await _on(workspace, "growth", monthly_credits=4_000)
    contract: dict[str, Any] = (await client.get(PROMPT)).json()
    assert (contract["path"], contract["recommended"]) == ("contract", None)
    assert contract["more_credits"] is None and contract["period_end"]


async def test_one_who_may_not_pay_asks_the_admins_once(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _keep(workspace, _spend(workspace, 1.95))
    _as(identity, acme, "member")
    said: dict[str, Any] = (await client.get(PROMPT)).json()
    assert (said["can_pay"], said["asked"]) == (False, False)
    asked = await client.post(f"{PROMPT}/ask", json={"threshold": 90})
    assert asked.status_code == 200 and asked.json()["asked"] is True
    await client.post(f"{PROMPT}/ask", json={"threshold": 90})
    assert (await client.get(PROMPT)).json()["asked"] is True
    with workspace_scope(workspace):
        async with session_factory() as session:
            told = (
                await session.scalars(
                    select(Notification).where(Notification.kind == "billing.upgrade_asked")
                )
            ).all()
    [one] = told
    assert (one.audience_permission, one.params["plan"], one.link) == (
        "workspace:update",
        "Starter",
        "/billing/plans?plan=starter",
    )
    # Who may pay changes the plan: nothing to ask.
    _as(identity, acme, "admin")
    assert (await client.post(f"{PROMPT}/ask", json={"threshold": 90})).status_code == 409
    # A threshold not shown now: nothing to ask either.
    _as(identity, acme, "member")
    assert (await client.post(f"{PROMPT}/ask", json={"threshold": 100})).status_code == 409


async def test_read_by_many_at_once_each_threshold_is_kept_once(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    await _keep(workspace, _spend(workspace, 2.10))

    async def read(user: uuid.UUID) -> Any:
        with workspace_scope(workspace):
            async with session_factory() as session:
                found = await credit_prompt(session, workspace, user, can_pay=False)
                await session.commit()
                return found

    found = await asyncio.gather(*(read(acme[who]) for who in ("admin", "member") * 4))
    assert {f.threshold for f in found} == {100}
    assert (await _kept(workspace, 90), await _kept(workspace, 100)) == (1, 1)
