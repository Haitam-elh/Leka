"""The watch (LEKA-442).

    GET /monitoring    what the plan includes, the alerts open, those ended
                       in the last 7 days
    POST /monitoring/alerts/{id}/acknowledge
                       taken in hand (LEKA-463): by whom, when — the first
                       only; it stays open until the trouble ends

Read by every member (`source:read`), as the environment is; acknowledged
by who manages the sources (`source:manage`). A Free
workspace reads what its plan includes and no alert — never one simulated.
A route validates, calls one service, and returns (architecture rule 6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.core.errors import ErrorCode
from leka.governance import Permission, Principal, require_permission
from leka.monitoring import (
    AlertRead,
    AlertRepository,
    MonitoringEntitlementRead,
    MonitoringRead,
    entitled,
)

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


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertRead)
async def acknowledge(alert_id: uuid.UUID, session: SessionDep, principal: Manager) -> AlertRead:
    row = await AlertRepository(session, principal.workspace_id).acknowledge(
        alert_id, by=principal.user_id, at=datetime.now(UTC)
    )
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such alert.")
    await session.commit()
    return AlertRead.model_validate(row, from_attributes=True)
