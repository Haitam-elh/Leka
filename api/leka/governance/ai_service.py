"""A workspace's AI controls (LEKA-406), kept and changed — every change in
the governance history — and what each did, kept apart for audit.

    controls()    every one, on or off
    active()      those in force, as the gateway and the runs read them
    save()        created or changed — ControlError when it cannot be
    delete()      removed; what it did stays
    events()      what the controls did, the latest first
    ai_event()    one outcome, added to the session it happened in
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from leka.governance.ai import Actor, Control, ControlError, checked_control, control_of
from leka.governance.audit import ai_audited, governance_audited
from leka.governance.models import AIControl, AIControlEvent, GovernanceEvent
from leka.governance.repository import AIControlRepository, PolicyRepository
from leka.platform import Role


def control_of_row(row: AIControl) -> Control:
    return control_of(
        row.name,
        row.kind,
        row.config or {},
        purposes=row.purposes,
        roles=row.roles,
        control_id=row.id,
    )


def _said(row: AIControl) -> dict[str, object]:
    return {
        "name": row.name,
        "description": row.description,
        "kind": row.kind,
        "purposes": list(row.purposes),
        "roles": list(row.roles),
        "config": dict(row.config or {}),
        "enabled": row.enabled,
    }


@dataclass(frozen=True)
class ControlInput:
    name: str
    kind: str
    config: Mapping[str, object]
    purposes: Sequence[str] = ()
    roles: Sequence[str] = ()
    enabled: bool = True
    description: str | None = None


def ai_event(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    control: Control | None,
    outcome: str,
    *,
    kind: str | None = None,
    actor: Actor | None = None,
    user_id: uuid.UUID | None = None,
    purpose: str | None = None,
    ref: str | None = None,
    run_id: uuid.UUID | None = None,
    provider: str | None = None,
    model: str | None = None,
    detail: Mapping[str, object] | None = None,
) -> None:
    """What a control did, kept with what happened — in the same session,
    committed with it."""
    row = AIControlEvent(
        workspace_id=workspace_id,
        id=uuid.uuid4(),
        control_id=control.id if control is not None else None,
        control_name=control.name[:120] if control is not None else None,
        kind=kind or (control.kind if control is not None else "approval"),
        outcome=outcome,
        purpose=purpose[:100] if purpose else None,
        ref=ref[:100] if ref else None,
        run_id=run_id,
        user_id=user_id or (actor.user_id if actor is not None else None),
        provider=provider,
        model=model[:120] if model else None,
        at=datetime.now(UTC),
        detail=dict(detail or {}),
    )
    # And in the audit trail (LEKA-407).
    session.add_all([row, ai_audited(row)])


class AIControlService:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._repo = AIControlRepository(session, workspace_id)

    async def controls(self) -> Sequence[AIControl]:
        return await self._repo.controls()

    async def active(self) -> tuple[Control, ...]:
        return tuple(control_of_row(r) for r in await self._repo.controls(enabled_only=True))

    async def _checked(self, said: ControlInput, kept: Sequence[str] = ()) -> Control:
        """The control — a role it already named, since deleted, does not
        stop it being changed or turned off."""
        control = checked_control(
            control_of(
                said.name.strip(), said.kind, said.config, purposes=said.purposes, roles=said.roles
            )
        )
        known = {r.value for r in Role} | {
            r.key for r in await PolicyRepository(self._session, self._workspace_id).roles()
        }
        unknown = sorted(set(said.roles) - known - set(kept))
        if unknown:
            raise ControlError("roles", f"No such role: {', '.join(unknown)}.")
        return control

    async def save(
        self, said: ControlInput, *, by: uuid.UUID, control_id: uuid.UUID | None = None
    ) -> AIControl | None:
        """Created, or changed — None for a control this workspace does not
        have; ControlError when it cannot be. Only its kind's settings are
        kept."""
        row = await self._repo.control(control_id) if control_id is not None else None
        if control_id is not None and row is None:
            return None
        control = await self._checked(said, row.roles if row is not None else ())
        if row is not None and row.kind != said.kind:
            raise ControlError("kind", "A control keeps its kind: create another.")
        before = _said(row) if row is not None else None
        if row is None:
            row = AIControl(workspace_id=self._workspace_id, id=uuid.uuid4(), created_by=by)
            self._repo.add(row)
        row.name = control.name
        row.description = said.description
        row.kind = control.kind
        row.purposes = list(dict.fromkeys(control.purposes))
        row.roles = sorted(control.roles)
        row.config = control.config()
        row.enabled = said.enabled
        await self._session.flush()
        self._event(str(row.id), "updated" if before else "created", by, before, _said(row))
        await self._session.flush()
        # What the database set (its updated_at), read back now.
        await self._session.refresh(row)
        return row

    async def delete(self, control_id: uuid.UUID, *, by: uuid.UUID) -> bool:
        row = await self._repo.control(control_id)
        if row is None:
            return False
        self._event(str(row.id), "deleted", by, _said(row), None)
        await self._repo.remove(row)
        await self._session.flush()
        return True

    async def events(
        self, *, outcome: str | None = None, run_id: uuid.UUID | None = None, limit: int = 100
    ) -> Sequence[AIControlEvent]:
        return await self._repo.events(outcome=outcome, run_id=run_id, limit=limit)

    def _event(
        self,
        subject_id: str,
        kind: str,
        by: uuid.UUID | None,
        before: Mapping[str, object] | None,
        after: Mapping[str, object] | None,
    ) -> None:
        row = GovernanceEvent(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            subject_type="ai_control",
            subject_id=subject_id[:100],
            kind=kind,
            by=by,
            at=datetime.now(UTC),
            before=dict(before) if before is not None else None,
            after=dict(after) if after is not None else None,
        )
        self._session.add_all([row, governance_audited(row)])
