"""The governance a workspace keeps over consequential actions (LEKA-404):
its exceptions, its delegations, the trail of every change, and the
decisions escalated when they wait too long. The rules are governance.py's,
pure; here they are read, kept and acted on.

    exceptions    granted by an admin — a freeze or a waiver, on what, from
                  when to when, why — revoked by an admin; both kept
    delegations   an approver lends their authority to another member, up
                  to a risk, for a time — revoked by them or an admin
    the trail     decision_governance_events: the policy changed, an exception or a
                  delegation granted or revoked, a decision escalated,
                  waived or frozen — who, when, on what. Append-only.
    escalation    a decision still waiting past its requirement's hours:
                  marked, kept, its intention's asker and the workspace's
                  owners told by email
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.db import session_factory, system_scope, workspace_scope
from leka.identity import EmailMessage, User, build_email_sender
from leka.intentions.decisions import Requirement
from leka.intentions.governance import (
    Delegation,
    GovernanceError,
    GovernanceException,
    Scope,
    checked_delegation,
    checked_exception,
    escalation_due,
)
from leka.intentions.models import (
    ApprovalDelegation,
    DecisionGovernanceEvent,
    GovernanceExceptionRow,
    Intention,
    IntentionDecision,
)
from leka.platform import Membership, Role, Workspace

logger = structlog.get_logger(__name__)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def exception_of(row: GovernanceExceptionRow) -> GovernanceException:
    return GovernanceException(
        id=row.id,
        kind=row.kind,
        scope=Scope(
            actions=frozenset(row.actions),
            environments=frozenset(row.environments),
            targets=frozenset(uuid.UUID(str(t)) for t in row.targets),
        ),
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        reason=row.reason,
        granted_by=row.granted_by,
        max_risk=row.max_risk,
        revoked_at=row.revoked_at,
    )


def delegation_of(row: ApprovalDelegation) -> Delegation:
    return Delegation(
        id=row.id,
        by=row.delegated_by,
        to=row.delegated_to,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        max_risk=row.max_risk,
        reason=row.reason,
        revoked_at=row.revoked_at,
    )


class OversightRefusedError(Exception):
    """What cannot be done as asked: its code, said."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ExceptionAsk:
    kind: str
    reason: str
    starts_at: datetime
    ends_at: datetime
    actions: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()
    targets: tuple[uuid.UUID, ...] = ()
    max_risk: str = "low"


class OversightService:
    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    # ── the trail ──────────────────────────────────────────────────────────

    def record(
        self,
        kind: str,
        *,
        by: uuid.UUID | None,
        subject_id: uuid.UUID | None = None,
        detail: Mapping[str, object] | None = None,
        now: datetime | None = None,
    ) -> DecisionGovernanceEvent:
        event = DecisionGovernanceEvent(
            workspace_id=self._workspace_id,
            id=uuid.uuid4(),
            kind=kind,
            by=by,
            at=_now(now),
            subject_id=subject_id,
            detail=dict(detail or {}),
        )
        self._session.add(event)
        return event

    async def trail(self, *, limit: int = 100) -> list[DecisionGovernanceEvent]:
        rows = await self._session.scalars(
            select(DecisionGovernanceEvent)
            .where(DecisionGovernanceEvent.workspace_id == self._workspace_id)
            .order_by(DecisionGovernanceEvent.at.desc(), DecisionGovernanceEvent.created_at.desc())
            .limit(limit)
        )
        return list(rows)

    # ── exceptions ─────────────────────────────────────────────────────────

    async def exception_rows(
        self, *, live_only: bool = False, now: datetime | None = None
    ) -> list[GovernanceExceptionRow]:
        query = select(GovernanceExceptionRow).where(
            GovernanceExceptionRow.workspace_id == self._workspace_id
        )
        if live_only:
            moment = _now(now)
            query = query.where(
                GovernanceExceptionRow.revoked_at.is_(None),
                GovernanceExceptionRow.ends_at > moment,
            )
        rows = await self._session.scalars(query.order_by(GovernanceExceptionRow.starts_at.desc()))
        return list(rows)

    async def exceptions(self, now: datetime | None = None) -> list[GovernanceException]:
        """Those that still may hold: not revoked, not ended."""
        return [exception_of(r) for r in await self.exception_rows(live_only=True, now=now)]

    async def grant(
        self, ask: ExceptionAsk, *, by: uuid.UUID, now: datetime | None = None
    ) -> GovernanceExceptionRow:
        candidate = GovernanceException(
            id=uuid.uuid4(),
            kind=ask.kind,
            scope=Scope(
                actions=frozenset(ask.actions),
                environments=frozenset(ask.environments),
                targets=frozenset(ask.targets),
            ),
            starts_at=ask.starts_at,
            ends_at=ask.ends_at,
            reason=ask.reason.strip(),
            granted_by=by,
            max_risk=ask.max_risk,
        )
        try:
            checked_exception(candidate)
        except GovernanceError as error:
            raise OversightRefusedError("invalid_exception", str(error)) from error
        row = GovernanceExceptionRow(
            workspace_id=self._workspace_id,
            id=candidate.id,
            kind=candidate.kind,
            actions=sorted(candidate.scope.actions),
            environments=sorted(candidate.scope.environments),
            targets=sorted(str(t) for t in candidate.scope.targets),
            max_risk=candidate.max_risk,
            starts_at=candidate.starts_at,
            ends_at=candidate.ends_at,
            reason=candidate.reason,
            granted_by=by,
        )
        self._session.add(row)
        self.record(
            "exception_granted",
            by=by,
            subject_id=row.id,
            detail={
                "kind": row.kind,
                "actions": row.actions,
                "environments": row.environments,
                "targets": row.targets,
                "max_risk": row.max_risk,
                "starts_at": row.starts_at.isoformat(),
                "ends_at": row.ends_at.isoformat(),
                "reason": row.reason,
            },
            now=now,
        )
        await self._session.flush()
        return row

    async def revoke_exception(
        self, exception_id: uuid.UUID, *, by: uuid.UUID, now: datetime | None = None
    ) -> GovernanceExceptionRow | None:
        row = await self._session.get(GovernanceExceptionRow, exception_id)
        if row is None or row.workspace_id != self._workspace_id:
            return None
        if row.revoked_at is not None:
            raise OversightRefusedError("already_revoked", "It is revoked already.")
        row.revoked_at, row.revoked_by = _now(now), by
        self.record(
            "exception_revoked", by=by, subject_id=row.id, detail={"kind": row.kind}, now=now
        )
        await self._session.flush()
        return row

    # ── delegations ────────────────────────────────────────────────────────

    async def delegation_rows(
        self, *, live_only: bool = False, now: datetime | None = None
    ) -> list[ApprovalDelegation]:
        query = select(ApprovalDelegation).where(
            ApprovalDelegation.workspace_id == self._workspace_id
        )
        if live_only:
            moment = _now(now)
            query = query.where(
                ApprovalDelegation.revoked_at.is_(None), ApprovalDelegation.ends_at > moment
            )
        rows = await self._session.scalars(query.order_by(ApprovalDelegation.starts_at.desc()))
        return list(rows)

    async def delegations(self, now: datetime | None = None) -> list[Delegation]:
        return [delegation_of(r) for r in await self.delegation_rows(live_only=True, now=now)]

    async def role_of(self, user_id: uuid.UUID) -> str | None:
        """A member's role in this workspace, now — none without a seat."""
        role = await self._session.scalar(
            select(Membership.role).where(
                Membership.workspace_id == self._workspace_id, Membership.user_id == user_id
            )
        )
        return role.value if role is not None else None

    async def delegate(
        self,
        *,
        by: uuid.UUID,
        to: uuid.UUID,
        max_risk: str,
        starts_at: datetime,
        ends_at: datetime,
        reason: str,
        now: datetime | None = None,
    ) -> ApprovalDelegation:
        """Their authority lent: only to a member of the workspace."""
        if await self.role_of(to) is None:
            raise OversightRefusedError("not_a_member", "Delegate to a member of the workspace.")
        candidate = Delegation(
            id=uuid.uuid4(),
            by=by,
            to=to,
            starts_at=starts_at,
            ends_at=ends_at,
            max_risk=max_risk,
            reason=reason.strip(),
        )
        try:
            checked_delegation(candidate)
        except GovernanceError as error:
            raise OversightRefusedError("invalid_delegation", str(error)) from error
        row = ApprovalDelegation(
            workspace_id=self._workspace_id,
            id=candidate.id,
            delegated_by=by,
            delegated_to=to,
            max_risk=max_risk,
            starts_at=starts_at,
            ends_at=ends_at,
            reason=candidate.reason,
        )
        self._session.add(row)
        self.record(
            "delegation_granted",
            by=by,
            subject_id=row.id,
            detail={
                "to": str(to),
                "max_risk": max_risk,
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "reason": row.reason,
            },
            now=now,
        )
        await self._session.flush()
        return row

    async def revoke_delegation(
        self,
        delegation_id: uuid.UUID,
        *,
        by: uuid.UUID,
        anyones: bool,
        now: datetime | None = None,
    ) -> ApprovalDelegation | None:
        """Revoked by who lent it — or by an admin (`anyones`)."""
        row = await self._session.get(ApprovalDelegation, delegation_id)
        if row is None or row.workspace_id != self._workspace_id:
            return None
        if row.delegated_by != by and not anyones:
            raise OversightRefusedError("not_yours", "Only who lent it, or an admin, revokes it.")
        if row.revoked_at is not None:
            raise OversightRefusedError("already_revoked", "It is revoked already.")
        row.revoked_at, row.revoked_by = _now(now), by
        self.record(
            "delegation_revoked",
            by=by,
            subject_id=row.id,
            detail={"to": str(row.delegated_to)},
            now=now,
        )
        await self._session.flush()
        return row

    # ── escalation ─────────────────────────────────────────────────────────

    async def escalate(self, *, now: datetime | None = None) -> list[IntentionDecision]:
        """The decisions waiting past their requirement's hours, escalated
        — each once, kept, and told by email to the asker and the owners."""
        moment = _now(now)
        # Still the one: its intention awaits it, not archived.
        waiting = (
            await self._session.scalars(
                select(IntentionDecision)
                .join(
                    Intention,
                    (Intention.id == IntentionDecision.intention_id)
                    & (Intention.workspace_id == IntentionDecision.workspace_id),
                )
                .where(
                    IntentionDecision.workspace_id == self._workspace_id,
                    IntentionDecision.status == "proposed",
                    IntentionDecision.escalated_at.is_(None),
                    Intention.status == "awaiting_decision",
                    Intention.archived_at.is_(None),
                )
            )
        ).all()
        escalated: list[IntentionDecision] = []
        for decision in waiting:
            said = (decision.governance or {}).get("requirement") or {}
            hours = said.get("escalate_hours") if isinstance(said, Mapping) else None
            requirement = Requirement(
                approvals=decision.required_approvals,
                separate=decision.separate_asker,
                escalate_hours=hours if isinstance(hours, int) else None,
            )
            if not escalation_due(
                decision.created_at, requirement, moment, escalated_at=decision.escalated_at
            ):
                continue
            decision.escalated_at = moment
            self.record(
                "decision_escalated",
                by=None,
                subject_id=decision.id,
                detail={
                    "intention_id": str(decision.intention_id),
                    "risk": decision.risk,
                    "waiting_hours": hours,
                },
                now=moment,
            )
            escalated.append(decision)
        await self._session.flush()
        for decision in escalated:
            await self._tell(decision)
        return escalated

    async def _tell(self, decision: IntentionDecision) -> None:
        """The asker and the owners, told: a decision waits."""
        intention = await self._session.get(Intention, decision.intention_id)
        owners = (
            await self._session.scalars(
                select(User.email)
                .join(Membership, Membership.user_id == User.id)
                .where(
                    Membership.workspace_id == self._workspace_id,
                    Membership.role == Role.OWNER,
                )
            )
        ).all()
        asker = (
            await self._session.scalar(select(User.email).where(User.id == decision.asked_by))
            if decision.asked_by
            else None
        )
        workspace = await self._session.get(Workspace, self._workspace_id)
        title = intention.title if intention is not None else "une intention"
        sender = build_email_sender()
        for to in sorted({*owners, *([asker] if asker else [])}):
            try:
                await sender.send(
                    EmailMessage(
                        to=to,
                        subject=f"LEKA — une décision attend : {title}"[:200],
                        body=(
                            f"La décision sur « {title} » "
                            f"({workspace.name if workspace else 'votre espace'}) attend "
                            f"toujours, au risque {decision.risk}. Elle est escaladée : "
                            "ouvrez À valider dans LEKA pour la trancher."
                        ),
                    )
                )
            except Exception:
                logger.warning("escalation_email_failed", decision=str(decision.id), exc_info=True)


async def escalate_due(*, now: datetime | None = None) -> dict[str, int]:
    """Every workspace's decisions waiting too long, escalated."""
    with system_scope():
        async with session_factory() as session:
            workspaces: Sequence[uuid.UUID] = (
                await session.scalars(
                    select(IntentionDecision.workspace_id)
                    .where(
                        IntentionDecision.status == "proposed",
                        IntentionDecision.escalated_at.is_(None),
                    )
                    .distinct()
                )
            ).all()
    escalated = 0
    for workspace_id in workspaces:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                escalated += len(await OversightService(session, workspace_id).escalate(now=now))
                await session.commit()
    return {"workspaces": len(workspaces), "escalated": escalated}


def run_escalation() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(escalate_due())
