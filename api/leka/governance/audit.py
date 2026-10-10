"""The audit trail (LEKA-407): one record per event that matters — who did
what, to what, with what outcome, from where — in one shape whatever
produced it, searched in one place, kept as long as the workspace says.

    audit()          one event, added to the session it happened in:
                     committed with what it records, or not at all
    audit_apart()    events kept on their own, committed now: a refusal, a
                     failed sign-in — what is recorded must outlive the
                     request's rollback
    audit_account()  an event of a person's account — a sign-in, a password
                     changed — kept in every workspace they belong to
    AuditTrail       one workspace's trail: searched, read, its retention
    sweep_audit()    the retention: what has outlived it, deleted — and said

What is kept is what happened, never the data it touched: an entity's id
and name, not its attributes; a source's kind, not its credentials.

The specialised trails stay where they are — access decisions (LEKA-402),
governance changes (LEKA-403), AI control outcomes (LEKA-406) — each also
writing its line here, so that one search answers "what happened".
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import Text, and_, cast, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from leka.core.request_context import current_request_id, current_request_origin
from leka.db import session_factory, system_scope, workspace_scope
from leka.governance.models import AIControlEvent, AuditEvent, AuditSettings, GovernanceEvent
from leka.governance.schemas import Principal
from leka.identity import truncate_ip
from leka.platform import MembershipResolver, Workspace

logger = structlog.get_logger(__name__)

CATEGORIES = (
    "user",  # signing in and out, a password, the account
    "team",  # invitations, roles of seats, members removed
    "workspace",  # its settings, its deletion
    "data",  # sources, their credentials and settings; restricted entities
    "access",  # access decisions: refusals, writes and runs allowed (LEKA-402)
    "governance",  # roles, policies, AI controls changed (LEKA-403, 406)
    "decision",  # a decision approved or rejected, its policy
    "action",  # actions planned, started, cancelled; their endpoints
    "ai",  # agents and workflows run; what the AI controls did (LEKA-406)
    "audit",  # the trail itself: its retention changed, what expired
)
OUTCOMES = ("success", "failure", "denied")

RETENTION_DEFAULT = 365
RETENTION_MIN = 90
RETENTION_MAX = 2555  # seven years

# What one search reads at most, and an export.
PAGE_MAX = 200
EXPORT_MAX = 10_000


@dataclass(frozen=True)
class Target:
    """What it was done to: its kind, its id, a name to read it by."""

    type: str
    id: str | uuid.UUID | None = None
    label: str | None = None


def audit_row(
    workspace_id: uuid.UUID,
    category: str,
    action: str,
    *,
    outcome: str = "success",
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    target: Target | None = None,
    detail: Mapping[str, object] | None = None,
    at: datetime | None = None,
) -> AuditEvent:
    """One event, in the trail's shape. Who: a person — or, none, LEKA
    itself. From where: the request being served, if one is."""
    ip, agent = current_request_origin()
    return AuditEvent(
        workspace_id=workspace_id,
        id=uuid.uuid4(),
        at=at or datetime.now(UTC),
        category=category,
        action=action[:60],
        outcome=outcome,
        actor_type="user" if actor_id is not None else "system",
        actor_id=actor_id,
        actor_role=actor_role[:60] if actor_role else None,
        target_type=target.type[:40] if target is not None else None,
        target_id=str(target.id)[:100] if target is not None and target.id is not None else None,
        target_label=target.label[:200] if target is not None and target.label else None,
        request_id=current_request_id(),
        ip=truncate_ip(ip),
        user_agent=agent[:200] if agent else None,
        detail=dict(detail or {}),
    )


def audit(
    session: AsyncSession, workspace_id: uuid.UUID, category: str, action: str, **said: object
) -> None:
    """One event, kept with what it records — committed with it, or not at
    all: a change rolled back leaves no trace of having happened."""
    session.add(audit_row(workspace_id, category, action, **said))  # type: ignore[arg-type]


def audit_as(
    session: AsyncSession, principal: Principal, category: str, action: str, **said: object
) -> None:
    """One event done by the request's person, as their role — kept with the
    request's transaction."""
    audit(
        session,
        principal.workspace_id,
        category,
        action,
        actor_id=principal.user_id,
        actor_role=principal.custom_role or principal.role.value,
        **said,
    )


async def audit_apart(rows: Sequence[AuditEvent]) -> None:
    """Kept on their own, committed now — whatever becomes of the request.
    A trail that cannot be written is logged, never a reason to fail what
    it records."""
    if not rows:
        return
    try:
        with system_scope():
            async with session_factory() as session:
                session.add_all(rows)
                await session.commit()
    except Exception:
        logger.exception("audit_unrecorded", actions=sorted({r.action for r in rows}))


async def audit_account(
    user_id: uuid.UUID,
    category: str,
    action: str,
    *,
    outcome: str = "success",
    detail: Mapping[str, object] | None = None,
    only: uuid.UUID | None = None,
    by_them: bool = True,
) -> None:
    """An event of a person's account — kept in every workspace they belong
    to (or `only` one): each workspace's administrators see what happened to
    their members' access. Not `by_them` — a failed sign-in, which anyone
    may attempt — the person is its target, never its author."""
    try:
        with system_scope():
            async with session_factory() as session:
                pairs = await MembershipResolver(session).list_workspaces_for_user(user_id)
    except Exception:
        logger.exception("audit_unrecorded", action=action)
        return
    at = datetime.now(UTC)
    await audit_apart(
        [
            audit_row(
                workspace.id,
                category,
                action,
                outcome=outcome,
                actor_id=user_id if by_them else None,
                actor_role=str(getattr(membership.role, "value", membership.role))
                if by_them
                else None,
                target=Target("user", user_id),
                detail=detail,
                at=at,
            )
            for workspace, membership in pairs
            if only is None or workspace.id == only
        ]
    )


def governance_audited(row: GovernanceEvent) -> AuditEvent:
    """A role, a policy, an assignment, an AI control changed — as the audit
    trail says it: `policy.created`, `ai_control.deleted`…"""
    said = row.after or row.before or {}
    label = said.get("name") or said.get("role")
    return audit_row(
        row.workspace_id,
        "governance",
        f"{row.subject_type}.{row.kind}",
        actor_id=row.by,
        target=Target(row.subject_type, row.subject_id, str(label) if label else None),
        detail={"before": row.before, "after": row.after},
        at=row.at,
    )


# What an AI control did, as an outcome: what it stopped, refused.
_AI_DENIED = frozenset({"refused", "limited", "blocked", "rejected"})


def ai_audited(row: AIControlEvent) -> AuditEvent:
    """What an AI control did (LEKA-406), as the audit trail says it:
    `ai_control.blocked`… — what it found, never the text."""
    return audit_row(
        row.workspace_id,
        "ai",
        f"ai_control.{row.outcome}",
        outcome="denied" if row.outcome in _AI_DENIED else "success",
        actor_id=row.user_id,
        target=(
            Target("agent_run", row.run_id)
            if row.run_id
            else Target("ai_control", row.control_id, row.control_name)
        ),
        detail={
            "control": row.control_name,
            "purpose": row.purpose,
            "ref": row.ref,
            "provider": row.provider,
            "model": row.model,
            **dict(row.detail or {}),
        },
        at=row.at,
    )


# ── one workspace's trail ──────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditQuery:
    """What is searched for: every field narrows; none, everything."""

    categories: Sequence[str] = ()
    action: str | None = None
    outcome: str | None = None
    actor_id: uuid.UUID | None = None
    target_type: str | None = None
    target_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    text: str | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class AuditPage:
    events: Sequence[AuditEvent]
    next: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


def _cursor(row: AuditEvent) -> str:
    raw = f"{row.at.isoformat()}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


class CursorError(ValueError):
    """A cursor this trail did not hand out."""


def _uncursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        at, _, row_id = raw.partition("|")
        return datetime.fromisoformat(at), uuid.UUID(row_id)
    except (ValueError, UnicodeDecodeError) as error:
        raise CursorError("not a cursor of this trail") from error


class AuditTrail:
    """One workspace's audit trail: searched, read, its retention."""

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    def _where(self, query: AuditQuery) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [AuditEvent.workspace_id == self._workspace_id]
        if query.categories:
            conditions.append(AuditEvent.category.in_(list(query.categories)))
        if query.action:
            # "source.*": every action of a kind.
            if query.action.endswith("*"):
                conditions.append(AuditEvent.action.startswith(query.action[:-1], autoescape=True))
            else:
                conditions.append(AuditEvent.action == query.action)
        if query.outcome:
            conditions.append(AuditEvent.outcome == query.outcome)
        if query.actor_id:
            conditions.append(AuditEvent.actor_id == query.actor_id)
        if query.target_type:
            conditions.append(AuditEvent.target_type == query.target_type)
        if query.target_id:
            conditions.append(AuditEvent.target_id == query.target_id)
        if query.since:
            conditions.append(AuditEvent.at >= query.since)
        if query.until:
            conditions.append(AuditEvent.at < query.until)
        if query.request_id:
            conditions.append(AuditEvent.request_id == query.request_id)
        if query.text:
            said = query.text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            words = f"%{said}%"
            conditions.append(
                or_(
                    AuditEvent.action.ilike(words, escape="\\"),
                    AuditEvent.target_label.ilike(words, escape="\\"),
                    AuditEvent.target_id.ilike(words, escape="\\"),
                    cast(AuditEvent.detail, Text).ilike(words, escape="\\"),
                )
            )
        return conditions

    async def search(
        self, query: AuditQuery, *, cursor: str | None = None, limit: int = 50
    ) -> AuditPage:
        """The latest first, a page at a time: `next` reads on from the last."""
        conditions = self._where(query)
        if cursor:
            at, row_id = _uncursor(cursor)
            conditions.append(
                or_(AuditEvent.at < at, and_(AuditEvent.at == at, AuditEvent.id < row_id))
            )
        size = max(1, min(limit, PAGE_MAX))
        rows = (
            await self._session.scalars(
                select(AuditEvent)
                .where(*conditions)
                .order_by(AuditEvent.at.desc(), AuditEvent.id.desc())
                .limit(size + 1)
            )
        ).all()
        more = len(rows) > size
        page = rows[:size]
        return AuditPage(page, _cursor(page[-1]) if more and page else None)

    async def export(self, query: AuditQuery) -> Sequence[AuditEvent]:
        """Every event the search finds, the latest first — at most
        EXPORT_MAX."""
        return (
            await self._session.scalars(
                select(AuditEvent)
                .where(*self._where(query))
                .order_by(AuditEvent.at.desc(), AuditEvent.id.desc())
                .limit(EXPORT_MAX)
            )
        ).all()

    async def event(self, event_id: uuid.UUID) -> AuditEvent | None:
        found: AuditEvent | None = await self._session.scalar(
            select(AuditEvent).where(
                AuditEvent.workspace_id == self._workspace_id, AuditEvent.id == event_id
            )
        )
        return found

    async def related(self, row: AuditEvent, *, limit: int = 20) -> Sequence[AuditEvent]:
        """What else the same request did."""
        if not row.request_id:
            return []
        return (
            await self._session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.workspace_id == self._workspace_id,
                    AuditEvent.request_id == row.request_id,
                    AuditEvent.id != row.id,
                )
                .order_by(AuditEvent.at, AuditEvent.id)
                .limit(limit)
            )
        ).all()

    async def retention(self) -> tuple[int, AuditSettings | None]:
        """How many days the trail is kept, and the setting saying so (none:
        the default)."""
        row = await self._session.scalar(
            select(AuditSettings).where(AuditSettings.workspace_id == self._workspace_id)
        )
        return (row.retention_days if row is not None else RETENTION_DEFAULT), row

    async def oldest(self) -> datetime | None:
        found: datetime | None = await self._session.scalar(
            select(func.min(AuditEvent.at)).where(AuditEvent.workspace_id == self._workspace_id)
        )
        return found

    async def set_retention(self, days: int, *, by: uuid.UUID, role: str | None) -> int:
        """Kept `days` from now on — between RETENTION_MIN and RETENTION_MAX
        (ValueError otherwise); the change itself in the trail."""
        if not RETENTION_MIN <= days <= RETENTION_MAX:
            msg = f"between {RETENTION_MIN} and {RETENTION_MAX} days"
            raise ValueError(msg)
        before, row = await self.retention()
        if row is None:
            row = AuditSettings(workspace_id=self._workspace_id, id=uuid.uuid4())
            self._session.add(row)
        row.retention_days = days
        row.updated_by = by
        audit(
            self._session,
            self._workspace_id,
            "audit",
            "audit.retention_changed",
            actor_id=by,
            actor_role=role,
            target=Target("audit_settings", self._workspace_id),
            detail={"before": before, "after": days},
        )
        await self._session.flush()
        return days


def run_audit_sweep() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(sweep_audit())


async def sweep_audit(*, now: datetime | None = None) -> dict[str, int]:
    """Every workspace's events older than its retention, deleted — the one
    deletion the trail allows, said in the trail itself (`audit.expired`).
    One workspace at a time: one that fails is logged, and the others are
    swept all the same. Idempotent: run again, nothing more is old enough."""
    moment = now or datetime.now(UTC)
    swept: dict[str, int] = {}
    with system_scope():
        async with session_factory() as session:
            rows = await session.execute(
                select(AuditSettings.workspace_id, AuditSettings.retention_days)
            )
            # A list of pairs: a result has keys(), which dict() would take it by.
            kept = dict(rows.tuples().all())
            workspaces = (await session.scalars(select(Workspace.id))).all()
    for workspace_id in workspaces:
        try:
            count = await _sweep_one(
                workspace_id, kept.get(workspace_id, RETENTION_DEFAULT), moment
            )
        except Exception:
            logger.exception("audit_sweep_failed", workspace=str(workspace_id))
            continue
        if count:
            swept[str(workspace_id)] = count
    if swept:
        logger.info("audit_swept", workspaces=len(swept), events=sum(swept.values()))
    return swept


async def _sweep_one(workspace_id: uuid.UUID, days: int, moment: datetime) -> int:
    before = moment - timedelta(days=days)
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            # The trigger lets this transaction, and no other, delete.
            await session.execute(text("SET LOCAL leka.audit_sweep = 'on'"))
            result = await session.execute(
                delete(AuditEvent).where(
                    AuditEvent.workspace_id == workspace_id, AuditEvent.at < before
                )
            )
            count = int(getattr(result, "rowcount", 0) or 0)
            if count:
                audit(
                    session,
                    workspace_id,
                    "audit",
                    "audit.expired",
                    target=Target("audit_events"),
                    detail={"count": count, "before": before.isoformat(), "days": days},
                )
            await session.commit()
    return count
