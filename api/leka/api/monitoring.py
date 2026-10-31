"""The watch (LEKA-442).

    GET /monitoring    what the plan includes, the alerts open, those ended
                       in the last 7 days
    POST /monitoring/alerts/{id}/acknowledge
                       taken in hand (LEKA-463): by whom, when — the first
                       only; it stays open until the trouble ends
    GET    /monitoring/rules            the alert rules people set (LEKA-477),
                                        what may be watched, the channels and
                                        where each stands, the plan's limit
    POST   /monitoring/rules            one more — checked here: its subject
                                        watched, its conditions seen there,
                                        its channels integrated and in the
                                        plan, its recipients members, the
                                        plan's limit (403 plan_limit)
    PATCH  /monitoring/rules/{id}       changed, turned off or on
    DELETE /monitoring/rules/{id}       removed
    POST   /monitoring/rules/{id}/test  each of its channels tried now, each
                                        telling kept — a failure said
    PUT    /monitoring/channels/{key}   Slack, Teams or Discord connected by
                                        its webhook (LEKA-496): checked, kept
                                        encrypted, shown by its hint only
    GET    /monitoring/night-review     what LEKA went through overnight
                                        and the points it found (null: none
                                        yet)
    POST   /monitoring/night-review     gone through again now
    GET    /monitoring/now              what LEKA is working on, now: each
                                        piece of work, its step, where to
                                        follow it
    DELETE /monitoring/channels/{key}   disconnected
    POST   /monitoring/channels/{key}/test  a message sent now: where it
                                        stands said

Read by every member (`source:read`), as the environment is; acknowledged,
and its rules set, by who manages the sources (`source:manage`). A Free
workspace reads what its plan includes and no alert — never one simulated.
A route validates, calls one service, and returns (architecture rule 6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.billing.limits import PlanLimitError, room_for_alert_rule
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission
from leka.monitoring import (
    AlertDeliveryRead,
    AlertRead,
    AlertRepository,
    AlertRule,
    AlertRuleChange,
    AlertRuleRead,
    AlertRulesRead,
    AlertRuleWrite,
    ChannelRead,
    MonitoringEntitlementRead,
    MonitoringRead,
    NightReviewRead,
    WatchableRead,
    WebhookConnect,
    WorkingRead,
    entitled,
    latest_night_review,
    night_review,
    night_standing,
    webhooks,
    working_now,
)
from leka.monitoring import rules as alert_rules

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

Reader = Annotated[Principal, Depends(require_permission(Permission.SOURCE_READ))]
Manager = Annotated[Principal, Depends(require_permission(Permission.SOURCE_MANAGE))]
ENDED = timedelta(days=7)


@router.get("", response_model=MonitoringRead)
async def monitoring(session: SessionDep, principal: Reader) -> MonitoringRead:
    found = await entitled(session, principal.workspace_id)
    rows = await AlertRepository(session, principal.workspace_id).lately(datetime.now(UTC) - ENDED)
    alerts = [AlertRead.model_validate(row, from_attributes=True) for row in rows]
    return MonitoringRead(
        entitlement=MonitoringEntitlementRead(
            plan=found.plan,
            proactive=found.monitoring.proactive,
            alerts=list(found.monitoring.alerts),
            contractual=found.monitoring.contractual,
            provisional=found.monitoring.provisional,
            alerts_from=found.alerts_from,
            email_from=found.email_from,
        ),
        open=[a for a in alerts if a.status == "open"],
        ended=[a for a in alerts if a.status != "open"],
    )


@router.get("/night-review", response_model=NightReviewRead | None)
async def night(session: SessionDep, principal: Reader) -> NightReviewRead | None:
    """The last night review: what LEKA went through, what it found to look
    at (2026-10-29). None before the first."""
    found = await latest_night_review(session)
    if found is None:
        return None
    # As it stands now: what was settled since is gone (2026-10-31).
    points, settled = await night_standing(session, found)
    return NightReviewRead(
        id=found.id,
        at=found.at,
        trigger=found.trigger,
        checked=found.checked,
        points=points,
        settled=settled,
    )


@router.post("/night-review", response_model=NightReviewRead)
async def night_again(session: SessionDep, principal: Reader) -> NightReviewRead:
    """Gone through again now, for whoever reads the environment."""
    row = await night_review(session, principal.workspace_id, trigger="asked", by=principal.user_id)
    return NightReviewRead.model_validate(row)


@router.get("/now", response_model=list[WorkingRead])
async def now(session: SessionDep, principal: Reader) -> list[WorkingRead]:
    """What LEKA is working on, now (2026-10-29): intentions analysed,
    agents at work, sources read, pull requests repaired."""
    return [WorkingRead.model_validate(item) for item in await working_now(session)]


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertRead)
async def acknowledge(alert_id: uuid.UUID, session: SessionDep, principal: Manager) -> AlertRead:
    row = await AlertRepository(session, principal.workspace_id).acknowledge(
        alert_id, by=principal.user_id, at=datetime.now(UTC)
    )
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such alert.")
    await session.commit()
    return AlertRead.model_validate(row, from_attributes=True)


# ── the rules a person sets (LEKA-477) ──────────────────────────────────────


def _rule_refused(error: alert_rules.RuleRefusedError) -> ApiError:
    if error.code == "not_found":
        return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, str(error))
    return ApiError(
        422,
        ErrorCode.VALIDATION_FAILED,
        str(error),
        details=[FieldError(field="rule", message=error.code)],
    )


def _limited(error: PlanLimitError) -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.PLAN_LIMIT, str(error))


async def _rule_read(
    session: SessionDep, principal: Principal, rows: list[AlertRule]
) -> list[AlertRuleRead]:
    told = await alert_rules.deliveries(session, principal.workspace_id, [r.id for r in rows])
    return [
        AlertRuleRead.model_validate(row, from_attributes=True).model_copy(
            update={
                "deliveries": [
                    AlertDeliveryRead.model_validate(d, from_attributes=True) for d in told[row.id]
                ]
            }
        )
        for row in rows
    ]


@router.get("/rules", response_model=AlertRulesRead)
async def read_rules(session: SessionDep, principal: Reader) -> AlertRulesRead:
    now = datetime.now(UTC)
    workspace = principal.workspace_id
    rows = list(
        (
            await session.scalars(
                select(AlertRule)
                .where(AlertRule.workspace_id == workspace)
                .order_by(AlertRule.created_at)
            )
        ).all()
    )
    limit, used = await alert_rules.quota(session, workspace)
    upgrade = None
    if limit is not None and used >= limit:
        try:
            await room_for_alert_rule(session, workspace, used)
        except PlanLimitError as error:
            upgrade = error.upgrade
    return AlertRulesRead(
        limit=limit,
        used=used,
        upgrade=upgrade,
        channels=[
            ChannelRead(key=c.key, status=c.status, hint=c.hint, error=c.error)
            for c in await alert_rules.channels(session, workspace)
        ],
        watchable=[
            WatchableRead(
                subject_type=w.subject_type,
                subject_id=w.subject_id,
                name=w.name,
                kind=w.kind,
                conditions=list(w.conditions),
                state=w.state,
                fresh=w.fresh,
                observed_at=w.observed_at,
            )
            for w in await alert_rules.watchable(session, workspace, now)
        ],
        rules=await _rule_read(session, principal, rows),
    )


@router.post("/rules", response_model=AlertRuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: AlertRuleWrite, session: SessionDep, principal: Manager
) -> AlertRuleRead:
    spec = alert_rules.RuleSpec(
        name=body.name.strip(),
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        conditions=tuple(body.conditions),
        severity=body.severity,
        confirm_minutes=body.confirm_minutes,
        repeat_hours=body.repeat_hours,
        channels=tuple(body.channels),
        recipients=tuple(body.recipients),
        enabled=body.enabled,
    )
    try:
        row = await alert_rules.create(
            session, principal.workspace_id, spec, by=principal.user_id, now=datetime.now(UTC)
        )
    except alert_rules.RuleRefusedError as error:
        raise _rule_refused(error) from None
    except PlanLimitError as error:
        raise _limited(error) from None
    return (await _rule_read(session, principal, [row]))[0]


@router.patch("/rules/{rule_id}", response_model=AlertRuleRead)
async def change_rule(
    rule_id: uuid.UUID, body: AlertRuleChange, session: SessionDep, principal: Manager
) -> AlertRuleRead:
    asked = body.model_dump(exclude_unset=True)
    # Only « tell again » may be emptied: none, once per episode.
    changes: dict[str, object] = {
        key: value for key, value in asked.items() if value is not None or key == "repeat_hours"
    }
    for key in ("conditions", "channels", "recipients"):
        if key in changes:
            changes[key] = tuple(changes[key])  # type: ignore[arg-type]
    if "name" in changes:
        changes["name"] = str(changes["name"]).strip()
    try:
        row = await alert_rules.change(
            session, principal.workspace_id, rule_id, changes, now=datetime.now(UTC)
        )
    except alert_rules.RuleRefusedError as error:
        raise _rule_refused(error) from None
    except PlanLimitError as error:
        raise _limited(error) from None
    return (await _rule_read(session, principal, [row]))[0]


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_rule(rule_id: uuid.UUID, session: SessionDep, principal: Manager) -> None:
    try:
        await alert_rules.remove(session, principal.workspace_id, rule_id)
    except alert_rules.RuleRefusedError as error:
        raise _rule_refused(error) from None


@router.post("/rules/{rule_id}/test", response_model=AlertRuleRead)
async def test_rule(rule_id: uuid.UUID, session: SessionDep, principal: Manager) -> AlertRuleRead:
    try:
        await alert_rules.test(session, principal.workspace_id, rule_id, now=datetime.now(UTC))
        row = await alert_rules.one(session, principal.workspace_id, rule_id)
    except alert_rules.RuleRefusedError as error:
        raise _rule_refused(error) from None
    return (await _rule_read(session, principal, [row]))[0]


# ── the channels connected by a webhook (LEKA-496) ──────────────────────────


async def _channel_read(session: SessionDep, principal: Principal, key: str) -> ChannelRead:
    found = next(
        c for c in await alert_rules.channels(session, principal.workspace_id) if c.key == key
    )
    return ChannelRead(key=found.key, status=found.status, hint=found.hint, error=found.error)


def _webhook_refused(error: webhooks.WebhookRefusedError) -> ApiError:
    return ApiError(
        422,
        ErrorCode.VALIDATION_FAILED,
        str(error),
        details=[FieldError(field="url", message=error.code)],
    )


@router.put("/channels/{key}", response_model=ChannelRead)
async def connect_channel(
    key: str, body: WebhookConnect, session: SessionDep, principal: Manager
) -> ChannelRead:
    try:
        await webhooks.connect(session, principal.workspace_id, key, body.url, by=principal.user_id)
    except webhooks.WebhookRefusedError as error:
        raise _webhook_refused(error) from None
    await session.commit()
    return await _channel_read(session, principal, key)


@router.delete("/channels/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_channel(key: str, session: SessionDep, principal: Manager) -> None:
    if not await webhooks.disconnect(session, principal.workspace_id, key):
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "Not connected.")
    await session.commit()


@router.post("/channels/{key}/test", response_model=ChannelRead)
async def test_channel(key: str, session: SessionDep, principal: Manager) -> ChannelRead:
    endpoint = (await webhooks.endpoints(session, principal.workspace_id)).get(key)
    if endpoint is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "Not connected.")
    await webhooks.post(endpoint, "LEKA : test d'envoi / delivery test ✓", now=datetime.now(UTC))
    await session.commit()
    return await _channel_read(session, principal, key)
