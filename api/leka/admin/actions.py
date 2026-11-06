"""What LEKA's team may change in an organisation (LEKA-544, LEKA-549).

Five operations, each a rule of the module that owns it where there is one
— LEKA ADMIN calls it, it does not rewrite it:

  suspend      platform's WorkspaceService.suspend: writes refused, reads and
               the bill kept
  reactivate   platform's WorkspaceService.reactivate
  add credits  governance's add_pack: credits added to this month, said by
               whom and why
  update       platform's WorkspaceService.configure (LEKA-549): its name,
               country and size, what changed said as before and after
  add a note   an internal note (LEKA-549), LEKA's team's alone: kept in
               admin_notes, never in the organisation's trail

Each is kept twice: in the organisation's own audit trail (what its
administrators see: « LEKA suspended the workspace », never the internal
reason), and in the admin trail (who at LEKA, why, from where). Each runs
under an Idempotency-Key (leka/admin/service.py `once`).

An organisation whose customer asked to delete it is left alone: reactivating
it would cancel their request, and suspending it means nothing.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin import audit
from leka.admin.models import AdminNote
from leka.admin.reads import credits_of, note_rows
from leka.admin.schemas import (
    AdminPrincipal,
    CreditAdjustment,
    NoteCreate,
    NoteRow,
    OrganisationAction,
    OrganisationUpdate,
)
from leka.db import workspace_scope
from leka.governance import CreditTransaction, PlanError, Target, add_pack, adjust
from leka.governance import audit as workspace_audit
from leka.identity import User
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


async def adjust_credits(
    session: AsyncSession,
    principal: AdminPrincipal,
    workspace_id: uuid.UUID,
    change: CreditAdjustment,
    *,
    key: str,
    route: str,
) -> OrganisationAction:
    """Credits given back or adjusted by LEKA's team (LEKA-553): a line of the
    organisation's ledger, written once for this Idempotency-Key, counted in
    this month's allowance at once; kept in its trail and in the admin trail,
    with the reason. A refund names the consumption it gives back, of this
    ledger, and never more than it took."""
    workspace = await _workspace(session, workspace_id)
    detail: dict[str, object] = {}
    if change.refund_of is not None:
        consumed = await session.get(CreditTransaction, change.refund_of)
        if (
            consumed is None
            or consumed.workspace_id != workspace_id
            or consumed.kind != "consumption"
        ):
            raise ActionError(404, "No consumption with this id in this organisation's ledger.")
        if change.credits > math.ceil(-float(consumed.credits)):
            raise ActionError(422, "A refund gives back at most what was consumed.")
        detail = {"refund_of": str(consumed.id), "reference": consumed.reference}
    with workspace_scope(workspace_id):
        try:
            line, written = await adjust(
                session,
                workspace_id,
                change.kind,
                change.credits,
                by=f"LEKA ADMIN {principal.email}",
                reason=change.reason,
                reference=f"admin:{key}",
                detail=detail,
            )
        except PlanError as error:
            raise ActionError(422, str(error)) from error
    if written:
        audit.record(
            session,
            "admin.credits_adjusted",
            admin_id=principal.admin_id,
            target_type="organisation",
            target_id=workspace_id,
            workspace_id=workspace_id,
            route=route,
            ip_prefix=principal.ip_prefix,
            detail={
                "kind": change.kind,
                "credits": change.credits,
                "reason": change.reason,
                "movement": str(line.id),
                **detail,
            },
        )
    await session.flush()
    return OrganisationAction(
        organisation_id=workspace_id,
        action="credits_adjusted",
        status=str(workspace.status),
        done_at=datetime.now(UTC),
        replayed=not written,
        credits=await credits_of(session, workspace_id),
    )


async def update_organisation(
    session: AsyncSession,
    principal: AdminPrincipal,
    workspace_id: uuid.UUID,
    change: OrganisationUpdate,
    *,
    route: str,
) -> OrganisationAction:
    """Its name, country or size; what is left out stays as it is."""
    workspace = await _workspace(session, workspace_id)
    wanted = change.model_dump(include={"name", "country", "size"}, exclude_none=True)
    changed: dict[str, list[object]] = {
        key: [getattr(workspace, key), value]
        for key, value in wanted.items()
        if getattr(workspace, key) != value
    }
    if changed:
        service = WorkspaceService(WorkspaceRepository(session), session)
        with workspace_scope(workspace_id):
            await service.configure(
                workspace,
                name=change.name if "name" in changed else None,
                country=change.country if "country" in changed else None,
                size=change.size if "size" in changed else None,
            )
            # What its administrators see: the fields LEKA changed, never
            # the internal reason.
            workspace_audit(
                session,
                workspace_id,
                "workspace",
                "workspace.updated",
                target=Target("workspace", workspace_id),
                detail={"by": "LEKA", "fields": sorted(changed)},
            )
        audit.record(
            session,
            "admin.organisation_updated",
            admin_id=principal.admin_id,
            target_type="organisation",
            target_id=workspace_id,
            workspace_id=workspace_id,
            route=route,
            ip_prefix=principal.ip_prefix,
            detail={"reason": change.reason, "changed": changed},
        )
        await session.flush()
    return OrganisationAction(
        organisation_id=workspace_id,
        action="updated",
        status=str(workspace.status),
        done_at=datetime.now(UTC),
        replayed=False,
        changed=changed,
    )


async def add_note(
    session: AsyncSession,
    principal: AdminPrincipal,
    note: NoteCreate,
    *,
    organisation_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    route: str,
) -> NoteRow:
    """An internal note about an organisation, or a person (LEKA-550):
    written down for LEKA's team, never for the customer. Allowed on an
    organisation pending deletion too: it may say why."""
    if organisation_id is not None:
        if await session.get(Workspace, organisation_id) is None:
            raise ActionError(404, "No organisation with this id.")
    elif user_id is None or await session.get(User, user_id) is None:
        raise ActionError(404, "No person with this id.")
    row = AdminNote(
        for_workspace_id=organisation_id,
        for_user_id=user_id if organisation_id is None else None,
        admin_id=principal.admin_id,
        admin_email=principal.email,
        body=note.body,
    )
    session.add(row)
    # The trail says a note was written, and how long: never what it says.
    audit.record(
        session,
        "admin.note_added",
        admin_id=principal.admin_id,
        target_type="organisation" if organisation_id is not None else "user",
        target_id=organisation_id or user_id,
        workspace_id=organisation_id,
        route=route,
        ip_prefix=principal.ip_prefix,
        detail={"characters": len(note.body)},
    )
    await session.flush()
    await session.refresh(row)
    (said,) = await note_rows(session, [row])
    return said
