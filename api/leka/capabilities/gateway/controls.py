"""The workspace's AI controls where a model is called (LEKA-406): before,
which of the models routing chose this work may use, and whether a usage
limit is reached; after, what the answer may not carry. Each control that
acted is kept (ai_control_events) with the call it acted on.

    before()   the routes this work may take — ControlRefusedError when none, or
               a limit is reached
    after()    the answer, redacted where a control says so — ControlRefusedError
               when one blocks it; a flag keeps it as it is, said

The controls are read once per gateway, on its first call. What the work is
for and for whom: the request's purpose, the person it is done for
(governance.current_actor).

The workspace's AI credits (LEKA-430) are a limit of the same kind: spent
for the month — its plan's and its packs' — LEKA's models are refused it
until the month ends, a pack is added or its plan changes; never billed
past it. Its own model, its own account, still answers.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, time

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities.gateway.contract import Completion, Request
from leka.capabilities.gateway.routing import Route, Routing
from leka.capabilities.gateway.usage import leka_cost
from leka.capabilities.models import ModelCall
from leka.core.config import settings
from leka.governance import (
    PERIODS,
    Actor,
    AIControlService,
    Control,
    Used,
    ai_event,
    allowance,
    check_output,
    credits_of,
    current_actor,
    limits,
    refusing,
    spent,
)

logger = structlog.get_logger(__name__)


class ControlRefusedError(Exception):
    """A control that refused the work: `reason` refused (no model allowed),
    limited (a usage limit reached), blocked (what the answer carried)."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class Guard:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._controls: tuple[Control, ...] | None = None

    async def controls(self) -> tuple[Control, ...]:
        if self._controls is None:
            self._controls = await AIControlService(self._session, self._workspace_id).active()
        return self._controls

    def _kept(
        self,
        control: Control,
        outcome: str,
        request: Request,
        actor: Actor | None,
        *,
        provider: str | None = None,
        model: str | None = None,
        **detail: object,
    ) -> None:
        ai_event(
            self._session,
            self._workspace_id,
            control,
            outcome,
            actor=actor,
            purpose=request.purpose,
            ref=request.ref,
            run_id=request.run_id,
            provider=provider,
            model=model,
            detail=detail,
        )

    async def before(self, request: Request, routing: Routing) -> Routing:
        if not routing.routes:
            return routing
        allowed = await self._controlled(request, routing)
        allowed = await self._credited(allowed)
        if len(allowed) == len(routing.routes):
            return routing
        return replace(routing, routes=tuple(allowed))

    async def _controlled(self, request: Request, routing: Routing) -> list[Route]:
        """The routes the workspace's AI controls leave this work — none:
        refused; a usage limit reached: limited."""
        controls = await self.controls()
        if not controls:
            return list(routing.routes)
        actor = current_actor()
        allowed: list[Route] = []
        refused: list[tuple[Control, str, str]] = []
        for route in routing.routes:
            by = refusing(
                controls,
                request.purpose,
                actor,
                provider=route.endpoint.provider,
                owner=route.endpoint.owner,
            )
            if by is None:
                allowed.append(route)
            else:
                refused.append((by, route.endpoint.provider, route.profile.model))
        if not allowed:
            control, provider, model = refused[0]
            self._kept(control, "refused", request, actor, provider=provider, model=model)
            await self._session.flush()
            raise ControlRefusedError(
                f"No model this work may use here: refused by « {control.name} ».", "refused"
            )
        for control in limits(controls, request.purpose, actor):
            used = await self._used(control, request.purpose, actor)
            reached = spent(control, used)
            if reached is not None:
                self._kept(
                    control,
                    "limited",
                    request,
                    actor,
                    reached=reached,
                    calls=used.calls,
                    tokens=used.tokens,
                    cost_usd=round(used.cost_usd, 6),
                )
                await self._session.flush()
                raise ControlRefusedError(
                    f"The usage limit « {control.name} » is reached ({reached}).", "limited"
                )
        return allowed

    async def _credited(self, routes: list[Route]) -> list[Route]:
        """The routes the workspace's credits leave it: all, while some are
        left; its own model's alone once they are spent — none of those,
        refused, `limited`."""
        if not settings.credits_enforced or all(r.endpoint.owner != "leka" for r in routes):
            return routes
        now = datetime.now(UTC)
        given = await allowance(self._session, self._workspace_id, now)
        start = datetime.combine(given.period, time.min, tzinfo=UTC)
        used = credits_of(await leka_cost(self._session, self._workspace_id, since=start))
        if used < given.credits:
            return routes
        own = [r for r in routes if r.endpoint.owner != "leka"]
        if own:
            return own
        logger.info(
            "ai_credits_spent",
            workspace=str(self._workspace_id),
            plan=given.plan.name,
            credits=given.credits,
            used=round(used, 2),
        )
        raise ControlRefusedError(
            f"The AI credits of this month are spent ({given.credits} on the"
            f" {given.plan.name} plan): add a pack or change the plan.",
            "limited",
        )

    async def _used(self, control: Control, purpose: str, actor: Actor | None) -> Used:
        """What the work this limit covers took in its period: the calls
        that answered or were billed, of the purposes it names — for the
        person, when it counts per person."""
        since = datetime.now(UTC) - PERIODS[control.period]
        query = select(
            func.count(ModelCall.id),
            func.coalesce(func.sum(ModelCall.tokens_in + ModelCall.tokens_out), 0),
            func.coalesce(func.sum(ModelCall.cost_usd), 0.0),
        ).where(
            ModelCall.workspace_id == self._workspace_id,
            ModelCall.at >= since,
            ModelCall.status != "failed",
        )
        if control.purposes:
            query = query.where(or_(*(ModelCall.purpose.like(_like(p)) for p in control.purposes)))
        if control.per == "person":
            if actor is None:
                return Used()
            query = query.where(ModelCall.user_id == actor.user_id)
        calls, tokens, cost = (await self._session.execute(query)).one()
        return Used(int(calls), int(tokens), float(cost))

    async def after(self, request: Request, done: Completion) -> Completion:
        controls = await self.controls()
        if not controls or not done.text:
            return done
        actor = current_actor()
        checked = check_output(controls, request.purpose, actor, done.text)
        for control, outcome, found in checked.outcomes:
            self._kept(
                control,
                outcome,
                request,
                actor,
                provider=done.provider,
                model=done.model,
                found=list(found),
            )
        if checked.outcomes:
            await self._session.flush()
        blocked = checked.blocked_by
        if blocked is not None:
            raise ControlRefusedError(
                f"The answer was withheld by « {blocked.name} »: it carried what it may not.",
                "blocked",
            )
        return done if checked.text == done.text else replace(done, text=checked.text)


def _like(pattern: str) -> str:
    """A purpose pattern (fnmatch: * and ?) as SQL LIKE."""
    escaped = pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped.replace("*", "%").replace("?", "_")
