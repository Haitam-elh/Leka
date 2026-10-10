"""The audit trail, over HTTP (LEKA-407): searched, read, exported; how long
it is kept.

    GET  /governance/audit                 the events, the latest first, a page
                                           at a time — filtered by category,
                                           action, outcome, person, target,
                                           period, request, words
    GET  /governance/audit/export          the same, as CSV (at most 10 000) —
                                           the export itself in the trail
    GET  /governance/audit/settings        how long it is kept, the oldest kept
    PUT  /governance/audit/settings        kept so long — the owner's alone
    GET  /governance/audit/{id}            one event, and what else its request did

Reading takes `audit:read` (admins, the owner, a role of the workspace's own
granting it); the retention, `audit:manage` — the owner's only: shortening
it erases evidence. Nothing here changes or deletes an event: no route
does. The workspace is the session's (rule 3).
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.core.errors import ErrorCode
from leka.governance import (
    RETENTION_DEFAULT,
    RETENTION_MAX,
    RETENTION_MIN,
    AuditCategoryWord,
    AuditEventDetail,
    AuditEventRead,
    AuditPageRead,
    AuditQuery,
    AuditSettingsRead,
    AuditSettingsUpdate,
    AuditTrail,
    CursorError,
    Permission,
    Principal,
    Target,
    audit,
    require_permission,
)

router = APIRouter(prefix="/governance/audit", tags=["governance"])

Reader = Annotated[Principal, Depends(require_permission(Permission.AUDIT_READ))]
Keeper = Annotated[Principal, Depends(require_permission(Permission.AUDIT_MANAGE))]
OutcomeWord = Literal["success", "failure", "denied"]

EXPORTED = (
    "at",
    "category",
    "action",
    "outcome",
    "actor_type",
    "actor_id",
    "actor_role",
    "target_type",
    "target_id",
    "target_label",
    "request_id",
    "ip",
    "detail",
)


# What a spreadsheet would take for a formula, said first in a cell.
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    """A value as a cell — never read as a formula when the file is opened:
    a name someone chose (a source, an entity) could otherwise run in the
    reader's spreadsheet."""
    said = "" if value is None else str(value)
    return f"'{said}" if said.startswith(_FORMULA) else said


def _query(
    category: Annotated[list[AuditCategoryWord] | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    outcome: Annotated[OutcomeWord | None, Query()] = None,
    actor: Annotated[uuid.UUID | None, Query()] = None,
    target_type: Annotated[str | None, Query(max_length=40)] = None,
    target_id: Annotated[str | None, Query(max_length=100)] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    request_id: Annotated[str | None, Query(max_length=128)] = None,
) -> AuditQuery:
    return AuditQuery(
        categories=tuple(category or ()),
        action=action or None,
        outcome=outcome,
        actor_id=actor,
        target_type=target_type or None,
        target_id=target_id or None,
        since=since,
        until=until,
        text=(q or "").strip() or None,
        request_id=request_id or None,
    )


Searched = Annotated[AuditQuery, Depends(_query)]


@router.get("", response_model=AuditPageRead, summary="Search the audit trail")
async def search(
    session: SessionDep,
    principal: Reader,
    query: Searched,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPageRead:
    try:
        page = await AuditTrail(session, principal.workspace_id).search(
            query, cursor=cursor, limit=limit
        )
    except CursorError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, str(error)
        ) from error
    return AuditPageRead(
        events=[AuditEventRead.model_validate(e) for e in page.events], next=page.next
    )


@router.get(
    "/export",
    response_class=Response,
    summary="The audit trail, as CSV",
    responses={200: {"content": {"text/csv": {}}}},
)
async def export(session: SessionDep, principal: Reader, query: Searched) -> Response:
    """What the search finds, at most 10 000 events, the latest first. The
    export is itself kept in the trail, with what it asked."""
    rows = await AuditTrail(session, principal.workspace_id).export(query)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(EXPORTED)
    for row in rows:
        writer.writerow(
            _cell(value)
            for value in [
                row.at.isoformat(),
                row.category,
                row.action,
                row.outcome,
                row.actor_type,
                row.actor_id or "",
                row.actor_role or "",
                row.target_type or "",
                row.target_id or "",
                row.target_label or "",
                row.request_id or "",
                row.ip or "",
                json.dumps(row.detail, ensure_ascii=False, default=str),
            ]
        )
    audit(
        session,
        principal.workspace_id,
        "audit",
        "audit.exported",
        actor_id=principal.user_id,
        actor_role=principal.custom_role or principal.role.value,
        target=Target("audit_events"),
        detail={
            "count": len(rows),
            "filters": {
                k: v
                for k, v in {
                    "category": list(query.categories),
                    "action": query.action,
                    "outcome": query.outcome,
                    "actor": str(query.actor_id) if query.actor_id else None,
                    "target_type": query.target_type,
                    "target_id": query.target_id,
                    "since": query.since.isoformat() if query.since else None,
                    "until": query.until.isoformat() if query.until else None,
                    "q": query.text,
                }.items()
                if v
            },
        },
    )
    await session.commit()
    return Response(
        content=out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="leka-audit.csv"'},
    )


async def _settings(trail: AuditTrail) -> AuditSettingsRead:
    days, row = await trail.retention()
    return AuditSettingsRead(
        retention_days=days,
        default_days=RETENTION_DEFAULT,
        min_days=RETENTION_MIN,
        max_days=RETENTION_MAX,
        oldest=await trail.oldest(),
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
    )


@router.get("/settings", response_model=AuditSettingsRead, summary="How long the trail is kept")
async def settings(session: SessionDep, principal: Reader) -> AuditSettingsRead:
    return await _settings(AuditTrail(session, principal.workspace_id))


@router.put("/settings", response_model=AuditSettingsRead, summary="Keep the trail so long")
async def keep(
    body: AuditSettingsUpdate, session: SessionDep, principal: Keeper
) -> AuditSettingsRead:
    """From 90 days to seven years. Shortened, what is older goes at the next
    sweep, daily. The change is in the trail."""
    trail = AuditTrail(session, principal.workspace_id)
    try:
        await trail.set_retention(
            body.retention_days,
            by=principal.user_id,
            role=principal.custom_role or principal.role.value,
        )
    except ValueError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, str(error)
        ) from error
    await session.commit()
    return await _settings(trail)


@router.get("/{event_id}", response_model=AuditEventDetail, summary="One audit event")
async def event(event_id: uuid.UUID, session: SessionDep, principal: Reader) -> AuditEventDetail:
    trail = AuditTrail(session, principal.workspace_id)
    row = await trail.event(event_id)
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such event.")
    return AuditEventDetail(
        **AuditEventRead.model_validate(row).model_dump(),
        related=[AuditEventRead.model_validate(r) for r in await trail.related(row)],
    )
