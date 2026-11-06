"""An intention, step by step, for LEKA's team (LEKA-551): what was asked,
how LEKA understood it and which agents it chose, each execution and its
steps, the results and the actions proposed, the errors met, what its work
used — and its whole story, oldest first.

Read where each is kept, never copied, inside `system_scope()` like every
admin read (leka/admin/reads.py). Two levels, by the role's permissions
(docs/admin/api.md § 3):

- what LEKA did and when (statuses, dates, agents, steps, codes, figures):
  `intentions:read`;
- what the customer wrote, and what LEKA read or produced from it (the
  request, the understanding, the results, the targets of an action, a
  deliverable, a reason a person may have typed): `intentions:content`
  only, and the route keeps each reading of it in the admin trail.

Nothing here acts: LEKA ADMIN never starts, stops, approves or retries
anything in a customer's environment.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from leka.admin.reads import _credits, _ms, _name, _person, intention_rows
from leka.admin.schemas import (
    AdminAnalysisResult,
    AdminAnalysisRow,
    AdminAnalysisStep,
    AdminCapabilityChoice,
    AdminConsumption,
    AdminDecisionRow,
    AdminIntentionContent,
    AdminIntentionDetail,
    AdminIntentionError,
    AdminPlanRow,
    AdminPlanStepRow,
    AdminProposalContent,
    AdminProposalRow,
    AdminRouting,
    AdminRoutingCandidate,
    AdminRunRow,
    AdminRunStep,
    AdminTimelineEntry,
    AdminVerificationRow,
    AdminVote,
    AdminWorkUsage,
    TimelineCategory,
)
from leka.capabilities import AgentRun, AgentRunEvent, CapabilityRouting, ModelCall
from leka.db import workspace_scope
from leka.identity import User
from leka.intentions import (
    Filters,
    Intention,
    IntentionAnalysis,
    IntentionAttachment,
    IntentionDecision,
    IntentionDecisionVote,
    IntentionPlan,
    IntentionPlanStep,
    IntentionVerification,
    TimelineItem,
    timeline,
)
from leka.metering import UsageRecord

DELIVERABLE_CHARACTERS = 4000
ERROR_CHARACTERS = 200
STEPS_PER_RUN = 200
TIMELINE_MAX = 1000
MODEL_ERRORS = 50
CANDIDATES = 30
# A run's own moves, in the intention's timeline; its other steps are in
# the run's steps.
RUN_MOVES = (
    "queued",
    "held",
    "approved",
    "rejected",
    "started",
    "resumed",
    "succeeded",
    "failed",
    "cancelled",
)


def _str(value: object, characters: int = 60) -> str | None:
    return value[:characters] if isinstance(value, str) and value else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _said(value: object) -> str | None:
    """A technical error as kept, on one line, cut."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:ERROR_CHARACTERS] or None


def _texts(items: object, key: str = "text") -> list[str]:
    return [str(item[key]) for item in _list(items) if isinstance(item, dict) and item.get(key)]


def _trouble(kind: str) -> bool:
    return kind.endswith(("_failed", "_retried"))


def _deliverable(output: object) -> str | None:
    if output is None:
        return None
    text = output if isinstance(output, str) else str(output)
    return text[:DELIVERABLE_CHARACTERS]


# ── Each part ────────────────────────────────────────────────────────────────


def _step(event: AgentRunEvent) -> AdminRunStep:
    """What a step did — its tool, how it went, how long, the model and the
    tokens — never its arguments, what it read or what it said."""
    detail = event.detail if isinstance(event.detail, dict) else {}
    return AdminRunStep(
        seq=event.seq,
        kind=event.kind,
        at=event.at,
        tool=_str(detail.get("name")) if event.kind == "tool" else None,
        outcome=_str(detail.get("outcome")),
        ms=_int(detail.get("ms")),
        code=_str(detail.get("code")),
        model=_str(detail.get("model"), 120),
        tokens_in=_int(detail.get("tokens_in")),
        tokens_out=_int(detail.get("tokens_out")),
    )


def _analysis(row: IntentionAnalysis, people: dict[uuid.UUID, User]) -> AdminAnalysisRow:
    result = row.result if isinstance(row.result, dict) else None
    return AdminAnalysisRow(
        id=row.id,
        number=row.number,
        trigger=row.trigger,
        status=row.status,
        readiness=row.readiness,
        requested_by=_person(people.get(row.requested_by)) if row.requested_by else None,
        started_at=row.started_at,
        finished_at=row.finished_at,
        duration_ms=_ms(row.started_at, row.finished_at),
        error=_said(row.error),
        risk=_str(result.get("risk")) if result else None,
        confidence=_float(result.get("confidence")) if result else None,
        findings=len(_list(result.get("findings"))) if result else 0,
        recommendations=len(_list(result.get("recommendations"))) if result else 0,
        selection=[
            AdminCapabilityChoice(
                name=str(c.get("name", "")),
                chosen=bool(c.get("chosen")),
                reason=str(c.get("reason", "")),
            )
            for c in row.selection
            if isinstance(c, dict)
        ],
        steps=[
            AdminAnalysisStep(
                name=str(s.get("name", "")),
                status=str(s.get("status", "")),
                duration_ms=_int(s.get("duration_ms")),
                error=_said(s.get("error")),
                reason=_str(s.get("reason")),
            )
            for s in row.steps
            if isinstance(s, dict)
        ],
    )


def _result(row: IntentionAnalysis) -> AdminAnalysisResult | None:
    result = row.result if isinstance(row.result, dict) else None
    if result is None:
        return None
    answer = result.get("answer")
    return AdminAnalysisResult(
        number=row.number,
        answer=str(answer["text"]) if isinstance(answer, dict) and answer.get("text") else None,
        summary=_texts(result.get("summary")),
        findings=_texts(result.get("findings")),
        causes=_texts(result.get("causes"), "label"),
        recommendations=_texts(result.get("recommendations")),
        uncertainties=_texts(result.get("uncertainties")),
        missing=_texts(result.get("missing")),
    )


def _routing(row: CapabilityRouting) -> AdminRouting:
    decision = row.decision if isinstance(row.decision, dict) else {}
    return AdminRouting(
        id=row.id,
        at=row.at,
        version=row.version,
        outcome=row.outcome,
        selected=[str(key) for key in row.selected],
        why=_str(decision.get("why")),
        candidates=[
            AdminRoutingCandidate(
                key=str(c.get("key", "")),
                score=_float(c.get("score")),
                eligible=bool(c.get("eligible")),
                selected=bool(c.get("selected")),
            )
            for c in _list(decision.get("candidates"))[:CANDIDATES]
            if isinstance(c, dict)
        ],
        excluded=[
            str(c["key"])
            for c in _list(decision.get("excluded"))[:CANDIDATES]
            if isinstance(c, dict) and c.get("key")
        ],
    )


def _decision(
    row: IntentionDecision, votes: Sequence[IntentionDecisionVote], people: dict[uuid.UUID, User]
) -> AdminDecisionRow:
    return AdminDecisionRow(
        id=row.id,
        number=row.number,
        status=row.status,
        risk=row.risk,
        required_approvals=row.required_approvals,
        created_at=row.created_at,
        decided_at=row.decided_at,
        proposals=[
            AdminProposalRow(
                id=str(p.get("id", "")),
                action=str(p.get("action", "")),
                reversible=p["reversible"] if isinstance(p.get("reversible"), bool) else None,
                targets=len(_list(p.get("targets"))),
            )
            for p in row.proposals
            if isinstance(p, dict)
        ],
        votes=[
            AdminVote(
                verdict=v.verdict,
                at=v.at,
                by=_person(people.get(v.by)) if v.by else None,
            )
            for v in votes
        ],
    )


def _plan(row: IntentionPlan, steps: Sequence[IntentionPlanStep]) -> AdminPlanRow:
    return AdminPlanRow(
        id=row.id,
        number=row.number,
        status=row.status,
        scheduled_for=row.scheduled_for,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error=_said(row.error),
        steps=[
            AdminPlanStepRow(
                position=s.position,
                action=s.action,
                executor=s.executor,
                status=s.status,
                started_at=s.started_at,
                finished_at=s.finished_at,
                duration_ms=_ms(s.started_at, s.finished_at),
                error=_said(s.error),
            )
            for s in steps
        ],
    )


def _consumption(usage: Sequence[UsageRecord], duration_ms: int | None) -> AdminConsumption:
    """Its work's use, from the metering ledger: a figure no record measured
    is null, never 0."""

    def total(values: list[int | float | None]) -> Any:
        said = [v for v in values if v is not None]
        return sum(said) if said else None

    by_work: dict[tuple[str, str], list[UsageRecord]] = defaultdict(list)
    for record in usage:
        by_work[(record.kind, record.subject)].append(record)
    cost = total([r.leka_cost_usd for r in usage])
    return AdminConsumption(
        duration_ms=duration_ms,
        calls=sum(r.calls for r in usage),
        failed_calls=sum(r.failed_calls for r in usage),
        retries=sum(r.retries for r in usage),
        tokens_in=total([r.tokens_in for r in usage]),
        tokens_out=total([r.tokens_out for r in usage]),
        cost_usd=round(cost, 4) if cost is not None else None,
        credits=_credits(cost),
        models=sorted({str(m) for r in usage for m in r.models}),
        by_work=[
            AdminWorkUsage(
                kind=kind,
                subject=subject,
                executions=len(records),
                calls=sum(r.calls for r in records),
                tokens_in=total([r.tokens_in for r in records]),
                tokens_out=total([r.tokens_out for r in records]),
                credits=_credits(total([r.leka_cost_usd for r in records])),
            )
            for (kind, subject), records in sorted(
                by_work.items(), key=lambda item: -sum(r.calls for r in item[1])
            )
        ],
    )


# ── The story ────────────────────────────────────────────────────────────────


def _item_ref(item: TimelineItem) -> str | None:
    detail = item.detail
    if item.category == "analysis" and isinstance(detail.get("analysis_id"), str):
        return f"analysis:{detail['analysis_id']}"
    if item.id.startswith("decision:"):
        return item.id
    if isinstance(detail.get("plan_id"), str):
        return f"plan:{detail['plan_id']}"
    return None


def _from_item(
    item: TimelineItem, errors: dict[str, str | None], *, with_content: bool
) -> AdminTimelineEntry:
    """A moment of the customer's own timeline (leka/intentions/timeline.py)."""
    detail = item.detail
    ref = _item_ref(item)
    category: TimelineCategory = item.category
    return AdminTimelineEntry(
        at=item.at,
        category=category,
        kind=item.kind,
        subject=None,
        ref=ref,
        from_status=_str(detail.get("from_status")),
        to_status=_str(detail.get("to_status")),
        actor=item.actor,
        by=item.by_name,
        error=_said(detail.get("error")) or (errors.get(ref) if ref else None),
        reason=item.reason if with_content else None,
    )


def _from_run(
    run: AgentRun, event: AgentRunEvent, people: dict[uuid.UUID, User]
) -> AdminTimelineEntry:
    detail = event.detail if isinstance(event.detail, dict) else {}
    queued_by = run.requested_by if event.kind == "queued" else None
    person = people.get(queued_by) if queued_by else None
    return AdminTimelineEntry(
        at=event.at,
        category="run",
        kind=event.kind,
        subject=run.key,
        ref=f"run:{run.id}",
        from_status=None,
        to_status=None,
        actor="person" if person else "system",
        by=(_name(person) or person.email) if person else None,
        error=_said(detail.get("code")) or (_said(run.error) if event.kind == "failed" else None),
        reason=None,
    )


def _from_routing(row: CapabilityRouting) -> AdminTimelineEntry:
    return AdminTimelineEntry(
        at=row.at,
        category="routing",
        kind=row.outcome,
        subject=", ".join(str(key) for key in row.selected) or None,
        ref=f"routing:{row.id}",
        from_status=None,
        to_status=None,
        actor="system",
        by=None,
        error=None,
        reason=None,
    )


# ── An intention ─────────────────────────────────────────────────────────────


async def intention_detail(
    session: AsyncSession, intention_id: uuid.UUID, *, with_content: bool
) -> AdminIntentionDetail | None:
    intention = await session.get(Intention, intention_id)
    if intention is None:
        return None
    workspace_id = intention.workspace_id
    (row,) = await intention_rows(session, [intention], with_content=with_content)

    analyses = (
        await session.scalars(
            select(IntentionAnalysis)
            .where(IntentionAnalysis.intention_id == intention_id)
            .order_by(IntentionAnalysis.number)
        )
    ).all()
    routings = (
        await session.scalars(
            select(CapabilityRouting)
            .where(
                CapabilityRouting.workspace_id == workspace_id,
                CapabilityRouting.subject_type == "intention",
                CapabilityRouting.subject_id == intention_id,
            )
            .order_by(CapabilityRouting.at)
        )
    ).all()
    runs = (
        await session.scalars(
            select(AgentRun)
            .where(AgentRun.intention_id == intention_id)
            .order_by(AgentRun.queued_at)
        )
    ).all()
    run_ids = [r.id for r in runs]
    decisions = (
        await session.scalars(
            select(IntentionDecision)
            .where(IntentionDecision.intention_id == intention_id)
            .order_by(IntentionDecision.number)
        )
    ).all()
    plans = (
        await session.scalars(
            select(IntentionPlan)
            .where(IntentionPlan.intention_id == intention_id)
            .order_by(IntentionPlan.number)
        )
    ).all()
    verifications = (
        await session.scalars(
            select(IntentionVerification)
            .where(IntentionVerification.intention_id == intention_id)
            .order_by(IntentionVerification.observe_after)
        )
    ).all()
    usage = (
        await session.scalars(
            select(UsageRecord)
            .where(UsageRecord.intention_id == intention_id)
            .order_by(UsageRecord.started_at)
        )
    ).all()

    # Each run's first steps, and every move of it however late.
    steps: dict[uuid.UUID, list[AgentRunEvent]] = defaultdict(list)
    moves: list[AgentRunEvent] = []
    if run_ids:
        numbered = (
            select(
                AgentRunEvent,
                func.row_number()
                .over(partition_by=AgentRunEvent.run_id, order_by=AgentRunEvent.seq)
                .label("n"),
            )
            .where(AgentRunEvent.run_id.in_(run_ids))
            .subquery()
        )
        event = aliased(AgentRunEvent, numbered)
        for e in (
            await session.scalars(
                select(event).where(numbered.c.n <= STEPS_PER_RUN).order_by(event.run_id, event.seq)
            )
        ).all():
            steps[e.run_id].append(e)
        moves = list(
            (
                await session.scalars(
                    select(AgentRunEvent)
                    .where(
                        AgentRunEvent.run_id.in_(run_ids),
                        or_(
                            AgentRunEvent.kind.in_(RUN_MOVES),
                            AgentRunEvent.kind.endswith("_failed"),
                            AgentRunEvent.kind.endswith("_retried"),
                        ),
                    )
                    .order_by(AgentRunEvent.at, AgentRunEvent.seq)
                )
            ).all()
        )
    votes: dict[uuid.UUID, list[IntentionDecisionVote]] = defaultdict(list)
    if decisions:
        for v in (
            await session.scalars(
                select(IntentionDecisionVote)
                .where(IntentionDecisionVote.decision_id.in_([d.id for d in decisions]))
                .order_by(IntentionDecisionVote.at)
            )
        ).all():
            votes[v.decision_id].append(v)
    plan_steps: dict[uuid.UUID, list[IntentionPlanStep]] = defaultdict(list)
    if plans:
        for s in (
            await session.scalars(
                select(IntentionPlanStep)
                .where(IntentionPlanStep.plan_id.in_([p.id for p in plans]))
                .order_by(IntentionPlanStep.position)
            )
        ).all():
            plan_steps[s.plan_id].append(s)

    wanted = {
        *(a.requested_by for a in analyses),
        *(r.requested_by for r in runs),
        *(v.by for each in votes.values() for v in each),
    }
    people = {
        u.id: u
        for u in (
            await session.scalars(select(User).where(User.id.in_({p for p in wanted if p})))
        ).all()
    }

    # Per run, what its calls used: its own line of the metering ledger.
    measured = {r.execution: r for r in usage if r.kind == "agent_run"}

    def run_row(run: AgentRun) -> AdminRunRow:
        record = measured.get(f"agent_run:{run.id}")
        return AdminRunRow(
            id=run.id,
            key=run.key,
            version=run.version,
            status=run.status,
            model=run.model,
            requested_by=_person(people.get(run.requested_by)) if run.requested_by else None,
            queued_at=run.queued_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            duration_ms=_ms(run.started_at, run.finished_at),
            error=_said(run.error),
            calls=record.calls if record else None,
            failed_calls=record.failed_calls if record else None,
            tokens_in=record.tokens_in if record else None,
            tokens_out=record.tokens_out if record else None,
            credits=_credits(record.leka_cost_usd) if record else None,
            steps=[_step(e) for e in steps.get(run.id, [])],
        )

    errors = await _errors(
        session, workspace_id, intention_id, analyses, runs, moves, plans, plan_steps
    )
    story = await _story(
        session,
        intention,
        analyses,
        routings,
        runs,
        moves,
        people,
        with_content=with_content,
    )

    content = None
    if with_content:
        attachments = (
            await session.scalars(
                select(IntentionAttachment.name)
                .where(
                    IntentionAttachment.workspace_id == workspace_id,
                    IntentionAttachment.intention_id == intention_id,
                )
                .order_by(IntentionAttachment.created_at)
            )
        ).all()
        content = AdminIntentionContent(
            text=intention.text,
            summary=intention.summary,
            goal=intention.goal,
            understanding=intention.understanding
            if isinstance(intention.understanding, dict)
            else None,
            attachments=list(attachments),
            results=[r for a in analyses if (r := _result(a)) is not None],
            proposals=[
                AdminProposalContent(
                    decision=d.number,
                    id=str(p.get("id", "")),
                    action=str(p.get("action", "")),
                    environment=_str(p.get("environment"), 120),
                    targets=[
                        str(t.get("name"))
                        for t in _list(p.get("targets"))
                        if isinstance(t, dict) and t.get("name")
                    ],
                )
                for d in decisions
                for p in d.proposals
                if isinstance(p, dict)
            ],
            deliverables={
                str(r.id): text for r in runs if (text := _deliverable(r.output)) is not None
            },
        )

    return AdminIntentionDetail(
        **row.model_dump(),
        timeline=story,
        analyses=[_analysis(a, people) for a in analyses],
        routings=[_routing(r) for r in routings],
        runs=[run_row(r) for r in runs],
        decisions=[_decision(d, votes.get(d.id, []), people) for d in decisions],
        plans=[_plan(p, plan_steps.get(p.id, [])) for p in plans],
        verifications=[
            AdminVerificationRow(
                id=v.id,
                status=v.status,
                observe_after=v.observe_after,
                deadline=v.deadline,
                observed_at=v.observed_at,
                concluded_at=v.concluded_at,
                expectations=len(v.expectations),
                results=len(v.results),
            )
            for v in verifications
        ],
        errors=errors,
        consumption=_consumption(usage, row.duration_ms),
        content=content,
    )


async def _errors(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    intention_id: uuid.UUID,
    analyses: Sequence[IntentionAnalysis],
    runs: Sequence[AgentRun],
    moves: Sequence[AgentRunEvent],
    plans: Sequence[IntentionPlan],
    plan_steps: dict[uuid.UUID, list[IntentionPlanStep]],
) -> list[AdminIntentionError]:
    """Every technical error met on its way, where: an analysis and its
    capabilities, a run and its steps, a plan and its actions, a model's
    refusals — the latest first."""
    found: list[AdminIntentionError] = []

    def met(at: Any, source: Any, subject: str | None, ref: str | None, error: object) -> None:
        said = _said(error)
        if at is not None and said:
            found.append(
                AdminIntentionError(
                    at=at, source=source, subject=subject, ref=ref, error=said, count=1
                )
            )

    for a in analyses:
        ref = f"analysis:{a.id}"
        met(a.finished_at or a.started_at, "analysis", None, ref, a.error)
        for s in a.steps:
            if isinstance(s, dict) and s.get("error"):
                met(
                    a.finished_at or a.started_at,
                    "analysis_step",
                    _str(s.get("name")),
                    ref,
                    s.get("error"),
                )
    keys = {r.id: r.key for r in runs}
    for r in runs:
        met(r.finished_at or r.started_at or r.queued_at, "run", r.key, f"run:{r.id}", r.error)
    for e in moves:
        if _trouble(e.kind):
            detail = e.detail if isinstance(e.detail, dict) else {}
            met(
                e.at,
                "run_step",
                keys.get(e.run_id),
                f"run:{e.run_id}",
                f"{e.kind}: {detail['code']}" if detail.get("code") else e.kind,
            )
    for p in plans:
        met(p.finished_at or p.started_at, "plan", None, f"plan:{p.id}", p.error)
        for step in plan_steps.get(p.id, []):
            met(
                step.finished_at or step.started_at or p.finished_at,
                "plan_step",
                step.action,
                f"plan:{p.id}",
                step.error,
            )

    # A model's refusals, grouped: the same refusal a hundred times is one line.
    refs = [f"intention:{intention_id}", *(f"agent_run:{r.id}" for r in runs)]
    calls = (
        select(
            ModelCall.status,
            ModelCall.purpose,
            ModelCall.model,
            func.substr(ModelCall.error, 1, ERROR_CHARACTERS).label("said"),
            ModelCall.at,
        )
        .where(
            ModelCall.workspace_id == workspace_id,
            ModelCall.status != "ok",
            or_(ModelCall.ref.in_(refs), ModelCall.run_id.in_(list(keys))),
        )
        .subquery()
    )
    latest = func.max(calls.c.at)
    for status, purpose, model, said, count, at in (
        await session.execute(
            select(
                calls.c.status,
                calls.c.purpose,
                calls.c.model,
                calls.c.said,
                func.count(),
                latest,
            )
            .group_by(calls.c.status, calls.c.purpose, calls.c.model, calls.c.said)
            .order_by(latest.desc())
            .limit(MODEL_ERRORS)
        )
    ).all():
        found.append(
            AdminIntentionError(
                at=at,
                source="model_call",
                subject=f"{purpose} · {model}",
                ref=None,
                error=_said(said) or str(status),
                count=int(count),
            )
        )
    found.sort(key=lambda e: e.at, reverse=True)
    return found


async def _story(
    session: AsyncSession,
    intention: Intention,
    analyses: Sequence[IntentionAnalysis],
    routings: Sequence[CapabilityRouting],
    runs: Sequence[AgentRun],
    moves: Sequence[AgentRunEvent],
    people: dict[uuid.UUID, User],
    *,
    with_content: bool,
) -> list[AdminTimelineEntry]:
    """Its whole story, oldest first: the customer's own timeline (its
    moves, analyses, decisions and votes, plans and outcomes), with which
    agents were chosen and every move of their runs."""
    with workspace_scope(intention.workspace_id):
        items = await timeline(
            session,
            intention.workspace_id,
            Filters(intention_id=intention.id, limit=TIMELINE_MAX),
        )
    failed = {f"analysis:{a.id}": _said(a.error) for a in analyses}
    by_id = {r.id: r for r in runs}
    entries = [_from_item(i, failed, with_content=with_content) for i in reversed(items)]
    entries += [_from_routing(r) for r in routings]
    entries += [_from_run(by_id[e.run_id], e, people) for e in moves if e.run_id in by_id]
    # Stable: at the same instant, the customer timeline's own order kept.
    entries.sort(key=lambda e: e.at)
    return entries[-TIMELINE_MAX:]


__all__ = ["intention_detail"]
