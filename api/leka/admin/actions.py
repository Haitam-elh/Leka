"""What LEKA's team may change in an organisation (LEKA-544, LEKA-549).

Three operations, each already a rule of the module that owns it — LEKA
ADMIN calls it, it does not rewrite it:

  suspend      platform's WorkspaceService.suspend: writes refused, reads and
               the bill kept
  reactivate   platform's WorkspaceService.reactivate
  add credits  governance's add_pack: credits added to this month, said by
               whom and why

Each is kept twice: in the organisation's own audit trail (what its
administrators see: « LEKA suspended the workspace », never the internal
reason), and in the admin trail (who at LEKA, why, from where). Each runs
under an Idempotency-Key (leka/admin/service.py `once`).

An organisation whose customer asked to delete it is left alone: reactivating
it would cancel their request, and suspending it means nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin import audit
from leka.admin.reads import credits_of
from leka.admin.schemas import AdminPrincipal, OrganisationAction
from leka.db import workspace_scope
from leka.governance import Target, add_pack
from leka.governance import audit as workspace_audit
from leka.platform import Workspace, WorkspaceRepository, WorkspaceService, WorkspaceStatus


class ActionError(Exception):
    """Refused, with the HTTP status that says why."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def _workspace(session: AsyncSession, workspace_id: uuid.UUID) -> Workspace:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise ActionError(404, "No organisation with this id.")
    if workspace.status == WorkspaceStatus.PENDING_DELETION:
        raise ActionError(
            409, "Its customer asked to delete this organisation: it is left as it is."
        )
    return workspace


async def set_suspended(
    session: AsyncSession,
    principal: AdminPrincipal,
    workspace_id: uuid.UUID,
    *,
    suspended: bool,
    reason: str,
    route: str,
) -> OrganisationAction:
    workspace = await _workspace(session, workspace_id)
    service = WorkspaceService(WorkspaceRepository(session), session)
    action = "suspended" if suspended else "reactivated"
    with workspace_scope(workspace_id):
        if suspended:
            await service.suspend(workspace)
        else:
            await service.reactivate(workspace)
        workspace_audit(
            session,
            workspace_id,
            "workspace",
            f"workspace.{action}",
            target=Target("workspace", workspace_id),
            detail={"by": "LEKA"},
        )
    audit.record(
        session,
        f"admin.organisation_{action}",
        admin_id=principal.admin_id,
        target_type="organisation",
        target_id=workspace_id,
        workspace_id=workspace_id,
        route=route,
        ip_prefix=principal.ip_prefix,
        detail={"reason": reason},
    )
    await session.flush()
    return OrganisationAction(
        organisation_id=workspace_id,
        action=action,
        status=str(workspace.status),
        done_at=datetime.now(UTC),
        replayed=False,
    )


async def add_credits(
    session: AsyncSession,
    principal: AdminPrincipal,
    workspace_id: uuid.UUID,
    *,
    amount: int,
    reason: str,
    route: str,
) -> OrganisationAction:
    workspace = await _workspace(session, workspace_id)
    with workspace_scope(workspace_id):
        await add_pack(
            session, workspace_id, amount, by=f"LEKA ADMIN {principal.email}", reason=reason
        )
    audit.record(
        session,
        "admin.credits_added",
        admin_id=principal.admin_id,
        target_type="organisation",
        target_id=workspace_id,
        workspace_id=workspace_id,
        route=route,
        ip_prefix=principal.ip_prefix,
        detail={"credits": amount, "reason": reason},
    )
    return OrganisationAction(
        organisation_id=workspace_id,
        action="credits_added",
        status=str(workspace.status),
        done_at=datetime.now(UTC),
        replayed=False,
        credits=await credits_of(session, workspace_id),
    )
