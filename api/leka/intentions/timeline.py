"""An intention's whole story, in one timeline (LEKA-392): what happened to
it (LEKA-384), its analyses (388), its decision and every vote (390), its
plan and every step (391), its outcome (392) — each said by who, when, and
what — filtered by kind of thing, by who, by when; for one intention, or
the workspace's.

Read from where each is kept — every one of those records append-only or
written once — so the timeline is an audit, not a copy: nothing here can
say what the records do not.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from leka.identity import User
from leka.intentions.models import (
    Intention,
    IntentionAnalysis,
    IntentionDecision,
    IntentionDecisionVote,
    IntentionEvent,
    IntentionPlan,
    IntentionPlanEvent,
)
from leka.intentions.schemas import TimelineItem

CATEGORIES = ("intention", "analysis", "decision", "action", "outcome")
# A plan's events that are its outcome's, not its run's.
OUTCOME_KINDS = ("expectations_set", "expectation_reported")
MAX = 500
# At the same instant, the cause before what it moved: an analysis, a vote,
# a plan's step, an outcome — then the intention's own events.
RANKS = {"analysis": 0, "decision": 1, "action": 2, "outcome": 3, "intention": 4}
# And a plan's events in the order its run has them.
PLAN_ORDER = {
    kind: n
    for n, kind in enumerate(
        (
            "planned",
            "expectations_set",
            "checks_failed",
            "scheduled",
            "started",
            "awaiting_person",
            "step_started",
            "awaiting_confirmation",
            "step_succeeded",
            "step_failed",
            "cancel_requested",
            "succeeded",
            "failed",
            "cancelled",
            "verification_started",
            "expectation_reported",
            "verification_succeeded",
            "verification_partial",
            "verification_failed",
        )
    )
}


def category_of_plan_event(kind: str) -> str:
    return "outcome" if kind in OUTCOME_KINDS or kind.startswith("verification_") else "action"


@dataclass(frozen=True)
class Filters:
    intention_id: uuid.UUID | None = None
    categories: frozenset[str] = frozenset(CATEGORIES)
    actor: str | None = None  # person | system
    by: uuid.UUID | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 200


def _window[T: tuple[object, ...]](
    query: Select[T],
    at: InstrumentedAttribute[datetime],
    key: InstrumentedAttribute[uuid.UUID],
    filters: Filters,
    *,
    ends: InstrumentedAttribute[datetime | None] | None = None,
) -> Select[T]:
    """The latest `limit`, in the window — ties in a stable order; what
    `ends` later counts from then."""
    if filters.since is not None:
        start = at if ends is None else func.coalesce(ends, at)
        query = query.where(start >= filters.since)
    if filters.until is not None:
        query = query.where(at < filters.until)
    return query.order_by(at.desc(), key.desc()).limit(filters.limit)


async def timeline(
    session: AsyncSession, workspace_id: uuid.UUID, filters: Filters
) -> list[TimelineItem]:
    """The latest first, at most `limit` of them."""
    f = filters
    items: list[TimelineItem] = []
    # Within its kind, at the same instant: an intention's events by their
    # sequence, an analysis' start before its end, a plan's as its run goes.
    within: dict[str, int] = {}
    # The version each analysis read (LEKA-443).
    analysed: dict[uuid.UUID, int] = {}

    if "intention" in f.categories:
        events = select(IntentionEvent).where(IntentionEvent.workspace_id == workspace_id)
        if f.intention_id:
            events = events.where(IntentionEvent.intention_id == f.intention_id)
        if f.actor:
            events = events.where(IntentionEvent.actor == f.actor)
        if f.by:
            events = events.where(IntentionEvent.by == f.by)
        for e in (
            await session.scalars(_window(events, IntentionEvent.at, IntentionEvent.id, f))
        ).all():
            within[f"event:{e.id}"] = e.sequence
            items.append(
                TimelineItem(
                    id=f"event:{e.id}",
                    intention_id=e.intention_id,
                    category="intention",
                    kind=e.name or e.kind,
                    at=e.at,
                    actor=e.actor,
                    by=e.by,
                    reason=e.reason,
                    detail={
                        **dict(e.detail),
                        "from_status": e.from_status,
                        "to_status": e.to_status,
                        "event": e.kind,
                    },
                )
            )

    # An analysis is started by a person or the system, finished by the system.
    if "analysis" in f.categories and not (f.by and f.actor == "system"):
        analyses = select(IntentionAnalysis).where(IntentionAnalysis.workspace_id == workspace_id)
        if f.intention_id:
            analyses = analyses.where(IntentionAnalysis.intention_id == f.intention_id)
        if f.by:
            analyses = analyses.where(IntentionAnalysis.requested_by == f.by)
        elif f.actor == "person":
            analyses = analyses.where(IntentionAnalysis.requested_by.is_not(None))
        for a in (
            await session.scalars(
                _window(
                    analyses,
                    IntentionAnalysis.started_at,
                    IntentionAnalysis.id,
                    f,
                    ends=IntentionAnalysis.finished_at,
                )
            )
        ).all():
            if a.intention_version is not None:
                analysed[a.id] = a.intention_version
            detail = {"number": a.number, "trigger": a.trigger, "analysis_id": str(a.id)}
            items.append(
                TimelineItem(
                    id=f"analysis:{a.id}:started",
                    intention_id=a.intention_id,
                    category="analysis",
                    kind="analysis_started",
                    at=a.started_at,
                    actor="person" if a.requested_by else "system",
                    by=a.requested_by,
                    detail=detail,
                )
            )
            if a.finished_at is not None:
                within[f"analysis:{a.id}:finished"] = 1
                items.append(
                    TimelineItem(
                        id=f"analysis:{a.id}:finished",
                        intention_id=a.intention_id,
                        category="analysis",
                        kind=f"analysis_{a.status}",
                        at=a.finished_at,
                        actor="system",
                        detail={**detail, "status": a.status},
                    )
                )

    # A decision is opened by the system; voted by people.
    if "decision" in f.categories and f.actor != "person" and not f.by:
        opened = select(IntentionDecision).where(IntentionDecision.workspace_id == workspace_id)
        if f.intention_id:
            opened = opened.where(IntentionDecision.intention_id == f.intention_id)
        decisions = (
            await session.scalars(
                _window(opened, IntentionDecision.created_at, IntentionDecision.id, f)
            )
        ).all()
        for d in decisions:
            items.append(
                TimelineItem(
                    id=f"decision:{d.id}",
                    intention_id=d.intention_id,
                    category="decision",
                    kind="decision_opened",
                    at=d.created_at,
                    actor="system",
                    detail={
                        "number": d.number,
                        "risk": d.risk,
                        "required_approvals": d.required_approvals,
                        "actions": [p.get("action") for p in d.proposals],
                    },
                )
            )
    if "decision" in f.categories and f.actor != "system":
        votes = select(IntentionDecisionVote, IntentionDecision.intention_id).join(
            IntentionDecision, IntentionDecision.id == IntentionDecisionVote.decision_id
        )
        votes = votes.where(IntentionDecisionVote.workspace_id == workspace_id)
        if f.intention_id:
            votes = votes.where(IntentionDecision.intention_id == f.intention_id)
        if f.by:
            votes = votes.where(IntentionDecisionVote.by == f.by)
        for v, intention_id in (
            await session.execute(
                _window(votes, IntentionDecisionVote.at, IntentionDecisionVote.id, f)
            )
        ).tuples():
            items.append(
                TimelineItem(
                    id=f"vote:{v.id}",
                    intention_id=intention_id,
                    category="decision",
                    kind=f"vote_{v.verdict}",
                    at=v.at,
                    actor="person",
                    by=v.by,
                    reason=v.reason,
                    detail={"revision": v.revision, "risk": v.context.get("risk")},
                )
            )

    if {"action", "outcome"} & f.categories:
        plans = select(IntentionPlanEvent, IntentionPlan.intention_id).join(
            IntentionPlan, IntentionPlan.id == IntentionPlanEvent.plan_id
        )
        plans = plans.where(IntentionPlanEvent.workspace_id == workspace_id)
        if f.intention_id:
            plans = plans.where(IntentionPlan.intention_id == f.intention_id)
        if f.actor:
            plans = plans.where(IntentionPlanEvent.actor == f.actor)
        if f.by:
            plans = plans.where(IntentionPlanEvent.by == f.by)
        if "action" not in f.categories:
            plans = plans.where(
                IntentionPlanEvent.kind.in_(OUTCOME_KINDS)
                | IntentionPlanEvent.kind.startswith("verification_")
            )
        elif "outcome" not in f.categories:
            plans = plans.where(
                IntentionPlanEvent.kind.not_in(OUTCOME_KINDS)
                & ~IntentionPlanEvent.kind.startswith("verification_")
            )
        for p, intention_id in (
            await session.execute(_window(plans, IntentionPlanEvent.at, IntentionPlanEvent.id, f))
        ).tuples():
            category = category_of_plan_event(p.kind)
            within[f"plan-event:{p.id}"] = PLAN_ORDER.get(p.kind, len(PLAN_ORDER))
            items.append(
                TimelineItem(
                    id=f"plan-event:{p.id}",
                    intention_id=intention_id,
                    category=category,
                    kind=p.kind,
                    at=p.at,
                    actor=p.actor,
                    by=p.by,
                    detail={**dict(p.detail), "plan_id": str(p.plan_id)},
                )
            )

    # Narrowed by the queries already — but an analysis a person started is
    # finished by the system: only what each did is kept.
    if f.actor:
        items = [i for i in items if i.actor == f.actor]
    if f.by:
        items = [i for i in items if i.by == f.by]
    # An analysis' end, in the window though it started before.
    items = [
        i
        for i in items
        if (f.since is None or i.at >= f.since) and (f.until is None or i.at < f.until)
    ]
    items.sort(key=lambda i: (i.at, RANKS[i.category], within.get(i.id, 0), i.id), reverse=True)
    items = items[: f.limit]
    items = await _versioned(session, items, analysed)
    names = await _names(session, {i.by for i in items if i.by is not None})
    if names:
        items = [i.model_copy(update={"by_name": names.get(i.by)}) if i.by else i for i in items]
    if f.intention_id is None and items:
        titles = dict(
            (
                await session.execute(
                    select(Intention.id, Intention.title).where(
                        Intention.id.in_({i.intention_id for i in items})
                    )
                )
            )
            .tuples()
            .all()
        )
        items = [i.model_copy(update={"title": titles.get(i.intention_id)}) for i in items]
    return items


# The moves by which a person asked it again, before versions were kept.
ASKED = ("asked_again", "clarified")


async def _versioned(
    session: AsyncSession, items: list[TimelineItem], analysed: dict[uuid.UUID, int]
) -> list[TimelineItem]:
    """Each moment with the version of the intention it belongs to
    (LEKA-443): an analysis, the one it read; anything else, the version
    asked when it happened — each time it was asked again, one more."""
    if not items:
        return items
    asked = (
        await session.execute(
            select(IntentionEvent.intention_id, IntentionEvent.at, IntentionEvent.detail)
            .where(
                IntentionEvent.intention_id.in_({i.intention_id for i in items}),
                IntentionEvent.kind == "moved",
                IntentionEvent.detail.has_key("intention_version") | IntentionEvent.name.in_(ASKED),
            )
            .order_by(IntentionEvent.intention_id, IntentionEvent.sequence)
        )
    ).tuples()
    changes: dict[uuid.UUID, list[tuple[datetime, int]]] = {}
    for intention_id, at, detail in asked:
        seen = changes.setdefault(intention_id, [])
        version = detail.get("intention_version") if isinstance(detail, dict) else None
        before = seen[-1][1] if seen else 1
        seen.append((at, version if isinstance(version, int) else before + 1))

    def version_of(item: TimelineItem) -> int:
        if item.category == "analysis":
            found = item.detail.get("analysis_id")
            if isinstance(found, str) and uuid.UUID(found) in analysed:
                return analysed[uuid.UUID(found)]
        version = 1
        for at, then in changes.get(item.intention_id, []):
            if at <= item.at:
                version = then
        return version

    return [i.model_copy(update={"version": version_of(i)}) for i in items]


async def _names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Who did it, by name — their address when they gave none."""
    if not ids:
        return {}
    rows = await session.execute(
        select(User.id, User.first_name, User.last_name, User.email).where(User.id.in_(ids))
    )
    return {
        user: " ".join(part for part in (first, last) if part) or email
        for user, first, last, email in rows.tuples().all()
    }


def categories_of(said: Sequence[str] | None) -> frozenset[str]:
    """The kinds asked for — every one when none is."""
    wanted = frozenset(said or CATEGORIES) & frozenset(CATEGORIES)
    return wanted or frozenset(CATEGORIES)
