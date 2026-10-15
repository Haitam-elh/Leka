"""The agents a workspace may run (2026-10-14, the product call: « un compte
Free a utilisé l'agent Architecte applicatif gratuitement »).

    owned()    its plan, and what it runs: the agents its plan includes, an
               option bought alone, a bundle's agents, or every one LEKA
               granted it (its team's, for tests)
    Owned.why  why it may not run an agent — `not_for_sale` for one the
               catalogue does not sell (LEKA-454: never shown available),
               `plan_required` on a plan below the catalogue's least (Free),
               `not_owned` when its option is not bought — or None
    grant()    an agent, a bundle, or every one, from now on: bought (its
               Stripe subscription) or granted by LEKA — kept, said why
    end()      no longer: a subscription cancelled, a grant taken back —
               ended, never deleted

Read where an agent is offered or started (capabilities' catalogue): a
refusal is the server's, never only a screen's.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing.catalogue import catalogue
from leka.billing.models import AgentEntitlement
from leka.governance import plan_of

PLANS = ("free", "starter", "growth", "business", "enterprise")
EVERY = "*"


def plan_runs_agents(plan: str) -> bool:
    """Whether a plan runs agents at all: the catalogue's least, or above."""
    least = catalogue().add_ons.minimum_plan
    return plan in PLANS and PLANS.index(plan) >= PLANS.index(least)


@dataclass(frozen=True)
class Owned:
    plan: str
    every: bool
    agents: frozenset[str]
    bundles: frozenset[str]
    # Its plan's own agents (LEKA-454), and every agent on sale.
    included: frozenset[str] = frozenset()
    on_sale: frozenset[str] = frozenset()

    def why(self, key: str) -> str | None:
        """Why this agent may not run here — None when it may."""
        if self.every or key in self.included:
            return None
        if key not in self.on_sale:
            return "not_for_sale"
        if not plan_runs_agents(self.plan):
            return "plan_required"
        if key in self.agents:
            return None
        return "not_owned"


async def _active(session: AsyncSession, workspace_id: uuid.UUID) -> list[AgentEntitlement]:
    return list(
        (
            await session.scalars(
                select(AgentEntitlement).where(
                    AgentEntitlement.workspace_id == workspace_id,
                    AgentEntitlement.status == "active",
                )
            )
        ).all()
    )


async def owned(session: AsyncSession, workspace_id: uuid.UUID) -> Owned:
    sold = catalogue().add_ons
    rows = await _active(session, workspace_id)
    bundles = frozenset(r.key for r in rows if r.kind == "bundle")
    agents = {r.key for r in rows if r.kind == "agent"}
    for key in bundles:
        bundle = sold.bundle(key)
        if bundle is not None:
            agents |= set(bundle.agents)
    plan = (await plan_of(session, workspace_id)).name
    return Owned(
        plan=plan,
        every=any(r.kind == "all" for r in rows),
        agents=frozenset(agents),
        bundles=bundles,
        included=sold.included_in(plan),
        on_sale=frozenset(sold.agents) if sold.available else frozenset(),
    )


async def entitlements(session: AsyncSession, workspace_id: uuid.UUID) -> list[AgentEntitlement]:
    """What it owns, as it was granted — the latest first."""
    rows = await _active(session, workspace_id)
    return sorted(rows, key=lambda r: r.started_at, reverse=True)


async def grant(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    key: str = EVERY,
    kind: str = "all",
    origin: str = "grant",
    by: str,
    reason: str | None = None,
    subscription: str | None = None,
    now: datetime | None = None,
) -> AgentEntitlement:
    """From now on; the same, active, is kept as it is."""
    for row in await _active(session, workspace_id):
        if (row.kind, row.key) == (kind, key):
            return row
    row = AgentEntitlement(
        workspace_id=workspace_id,
        key=key,
        kind=kind,
        origin=origin,
        status="active",
        stripe_subscription_id=subscription,
        by_whom=by[:120],
        reason=(reason or None) and reason[:300],
        started_at=now or datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


async def end(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    key: str | None = None,
    subscription: str | None = None,
    now: datetime | None = None,
) -> int:
    """No longer: those of a subscription, or of a key. How many ended."""
    ended = 0
    for row in await _active(session, workspace_id):
        if (subscription and row.stripe_subscription_id == subscription) or (
            key and row.key == key
        ):
            row.status = "ended"
            row.ended_at = now or datetime.now(UTC)
            ended += 1
    await session.flush()
    return ended
