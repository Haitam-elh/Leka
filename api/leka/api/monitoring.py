"""The watch (LEKA-442).

    GET /monitoring    what the plan includes, the alerts open, those ended
                       in the last 7 days

Read by every member (`source:read`), as the environment is. A Free
workspace reads what its plan includes and no alert — never one simulated.
A route validates, calls one service, and returns (architecture rule 6).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends

from leka.api.dependencies import SessionDep
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
