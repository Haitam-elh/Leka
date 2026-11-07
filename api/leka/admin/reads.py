"""What every LEKA ADMIN module reads, across every customer (LEKA-544).

Run inside `system_scope()`, which only an admin's request opens
(leka/admin/dependencies.py). Nothing here writes, and nothing is copied:
each answer is read from the module that keeps it — the organisations and
their seats from platform, the people from identity, the plans and credits
from governance and metering, the subscriptions from billing, the
intentions and runs from intentions and capabilities, the sources from
connectors.

A list is a statement (`*_query`) the API pages with the signed cursor of
leka/db/pagination.py, and a page is completed (`*_rows`) by one grouped
query per figure — never a query per row.

What LEKA does not know is null, never 0: an organisation's country (not
collected), a cost with no rate, a duration of a run still going.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Select, String, cast, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.models import ActivityEvent, AdminAccount, AdminAuditEvent, AdminNote
from leka.admin.schemas import (
    ActivityLevel,
    ActivityRow,
    AdminIntentionRow,
    AdminIntentionStatus,
    AdminInvitationRow,
    AgentCost,
    AlertRow,
    BillingState,
    CreditsBreakdown,
    CreditsState,
    InvitationRow,
    MemberRow,
    ModelCost,
    NoteRow,
    OrganisationCounts,
    OrganisationDetail,
    OrganisationHistoryRow,
    OrganisationMembers,
    OrganisationRef,
    OrganisationRow,
    PersonRef,
    SourceDiagnostic,
    SourceRow,
    StripeEventRow,
    UserAccess,
    UserDetail,
    UserRow,
    UserStatus,
)
from leka.admin.schemas import (
    AdminMembership as MembershipRead,
)
from leka.billing import BillingAccount, StripeEvent
from leka.capabilities import AgentRun, ModelCall
from leka.connectors import HealthStatus, Source, SourceStatus, SyncStatus
from leka.core.config import settings
from leka.core.sensitive import guarded
from leka.db import workspace_scope
from leka.governance import WorkspacePlan, plan_of, subject_of
from leka.identity import User
from leka.intentions import Intention, IntentionAnalysis
from leka.metering import CreditsRead, UsageRecord, credits_now
from leka.monitoring import MonitoringAlert
from leka.platform import (
    Invitation,
    InvitationStatus,
    Membership,
    Role,
    Workspace,
    WorkspaceStatus,
)

FREE = "free"

ADMIN_STATUS: dict[str, AdminIntentionStatus] = {
    "submitted": "pending",
    "needs_clarification": "pending",
    "awaiting_decision": "pending",
    "analysing": "running",
    "approved": "running",
    "scheduled": "running",
    "executing": "running",
    "verifying": "running",
    "completed": "completed",
    "failed": "failed",
    "rejected": "cancelled",
    "cancelled": "cancelled",
}
FINAL = {"completed", "failed", "rejected", "cancelled"}

# What counts as using LEKA, for a person's status (LEKA-550): doing, not
# signing in.
MEANINGFUL = ("intention.created", "agent_run.succeeded", "agent_run.failed", "source.connected")
ACTIVE_WINDOW = timedelta(days=30)
# An analysis that ended with a result, whole or in part (LEKA-548's rule).
ANALYSED = ("complete", "partial", "inconclusive")
NEW_WINDOW = timedelta(days=7)
DESCRIPTION_CHARACTERS = 200


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        return None


def _name(user: User) -> str | None:
    return " ".join(part for part in (user.first_name, user.last_name) if part) or None


def _person(user: User | None) -> PersonRef | None:
    return PersonRef(id=user.id, email=user.email, name=_name(user)) if user else None


def _credits(cost_usd: float | None) -> float | None:
    return round(cost_usd / settings.credit_usd, 2) if cost_usd is not None else None


def _ms(start: datetime | None, end: datetime | None) -> int | None:
    """Milliseconds between two moments; None if one is missing, or if the
    clocks that wrote them disagree (an end before its start)."""
    if start is None or end is None or end < start:
        return None
    return int((end - start).total_seconds() * 1000)


def _like(text: str) -> str:
    return "%" + text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def _counts(
    session: AsyncSession, column: Any, ids: Sequence[uuid.UUID], *where: Any
) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = await session.execute(
        select(column, func.count()).where(column.in_(ids), *where).group_by(column)
    )
    return {key: int(count) for key, count in rows.all()}


async def _organisation_names(
    session: AsyncSession, ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await session.execute(
        select(Workspace.id, Workspace.name).where(Workspace.id.in_(wanted))
    )
    return {row.id: row.name for row in rows}


def _ref(names: dict[uuid.UUID, str], workspace_id: uuid.UUID | None) -> OrganisationRef | None:
    if workspace_id is None or workspace_id not in names:
        return None
    return OrganisationRef(id=workspace_id, name=names[workspace_id])


def _latest_plan() -> Any:
    return (
        select(WorkspacePlan.plan)
        .where(WorkspacePlan.workspace_id == Workspace.id)
        .order_by(WorkspacePlan.at.desc(), WorkspacePlan.created_at.desc())
        .limit(1)
        .correlate(Workspace)
        .scalar_subquery()
    )


# ── Organisations ────────────────────────────────────────────────────────────


def _declared_size() -> Any:
    """The size its first owner gave when signing up."""
    return (
        select(cast(User.company_size, String))
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == Workspace.id, Membership.role == Role.OWNER)
        .order_by(Membership.created_at)
        .limit(1)
        .correlate(Workspace)
        .scalar_subquery()
    )


def _last_at() -> Any:
    return (
        select(func.max(ActivityEvent.at))
        .where(ActivityEvent.for_workspace_id == Workspace.id)
        .correlate(Workspace)
        .scalar_subquery()
    )


Activity = Literal["active", "inactive", "never"]


def organisations_query(
    *,
    q: str | None = None,
    plan: str | None = None,
    status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    include_demo: bool = False,
    country: str | None = None,
    size: str | None = None,
    activity: Activity | None = None,
    now: datetime | None = None,
) -> Select[tuple[Workspace]]:
    """Every organisation, or those that match: its name, slug, id or an
    owner's email; its plan, status, creation; its country and size (the
    size LEKA keeps, else the one its owner declared); its activity in the
    last 30 days (active), before (inactive), or none at all (never)."""
    statement = select(Workspace)
    if not include_demo:
        statement = statement.where(Workspace.demo.is_(False))
    if q and q.strip():
        as_id = _uuid(q)
        if as_id is not None:
            statement = statement.where(Workspace.id == as_id)
        else:
            pattern = _like(q)
            owners = (
                select(Membership.workspace_id)
                .join(User, User.id == Membership.user_id)
                .where(User.email.ilike(pattern))
            )
            statement = statement.where(
                or_(
                    Workspace.name.ilike(pattern),
                    Workspace.slug.ilike(pattern),
                    Workspace.id.in_(owners),
                )
            )
    if plan:
        statement = statement.where(func.coalesce(_latest_plan(), FREE) == plan)
    if status:
        statement = statement.where(Workspace.status == status)
    if created_from:
        statement = statement.where(Workspace.created_at >= created_from)
    if created_to:
        statement = statement.where(Workspace.created_at < created_to)
    if country:
        statement = statement.where(Workspace.country == country.upper())
    if size:
        statement = statement.where(func.coalesce(Workspace.size, _declared_size()) == size)
    if activity:
        last = _last_at()
        recent = (now or datetime.now(UTC)) - ACTIVE_WINDOW
        statement = statement.where(
            last >= recent
            if activity == "active"
            else (last < recent)
            if activity == "inactive"
            else last.is_(None)
        )
    return statement


async def _plans(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(WorkspacePlan.workspace_id, WorkspacePlan.plan)
        .where(WorkspacePlan.workspace_id.in_(ids))
        .distinct(WorkspacePlan.workspace_id)
        .order_by(
            WorkspacePlan.workspace_id, WorkspacePlan.at.desc(), WorkspacePlan.created_at.desc()
        )
    )
    return {row.workspace_id: row.plan for row in rows}


async def _owners(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Membership.workspace_id, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id.in_(ids), Membership.role == Role.OWNER)
        .distinct(Membership.workspace_id)
        .order_by(Membership.workspace_id, Membership.created_at)
    )
    owners: dict[uuid.UUID, User] = dict(rows.tuples().all())
    return owners


async def _last_activity(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    if not ids:
        return {}
    rows = await session.execute(
        select(ActivityEvent.for_workspace_id, func.max(ActivityEvent.at))
        .where(ActivityEvent.for_workspace_id.in_(ids))
        .group_by(ActivityEvent.for_workspace_id)
    )
    return {key: at for key, at in rows.all() if key is not None}


async def organisation_rows(
    session: AsyncSession, workspaces: Sequence[Workspace]
) -> list[OrganisationRow]:
    ids = [w.id for w in workspaces]
    plans = await _plans(session, ids)
    owners = await _owners(session, ids)
    members = await _counts(session, Membership.workspace_id, ids)
    intentions = await _counts(session, Intention.workspace_id, ids)
    last = await _last_activity(session, ids)
    return [
        OrganisationRow(
            id=w.id,
            name=w.name,
            slug=w.slug,
            status=str(w.status),
            demo=w.demo,
            plan=plans.get(w.id, FREE),
            created_at=w.created_at,
            owner=_person(owners.get(w.id)),
            country=w.country,
            size=w.size,
            size_declared=_size(owners.get(w.id)),
            members=members.get(w.id, 0),
            intentions=intentions.get(w.id, 0),
            last_activity_at=last.get(w.id),
        )
        for w in workspaces
    ]


def _size(owner: User | None) -> str | None:
    said = owner.company_size if owner is not None else None
    return str(said) if said is not None else None


def _credits_state(read: CreditsRead) -> CreditsState:
    return CreditsState(
        period=read.period_start.strftime("%Y-%m"),
        plan=read.plan,
        monthly=read.monthly,
        packs=read.packs,
        adjustments=read.adjustments,
        allowance=read.allowance,
        used=read.used,
        remaining=read.remaining,
        state=read.state,
    )


async def credits_of(
    session: AsyncSession, workspace_id: uuid.UUID, now: datetime | None = None
) -> CreditsState:
    with workspace_scope(workspace_id):
        return _credits_state(
            await credits_now(session, workspace_id, now=now or datetime.now(UTC))
        )


async def organisation_detail(
    session: AsyncSession, workspace_id: uuid.UUID
) -> OrganisationDetail | None:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return None
    (row,) = await organisation_rows(session, [workspace])
    ids = [workspace_id]
    plan = await plan_of(session, workspace_id)
    account = await session.scalar(
        select(BillingAccount).where(BillingAccount.workspace_id == workspace_id)
    )
    since = datetime.now(UTC) - ACTIVE_WINDOW
    active = await session.scalar(
        select(func.count(distinct(ActivityEvent.user_id))).where(
            ActivityEvent.for_workspace_id == workspace_id,
            ActivityEvent.kind.in_(MEANINGFUL),
            ActivityEvent.at >= since,
        )
    )
    counts = OrganisationCounts(
        members=row.members,
        pending_invitations=(
            await _counts(
                session, Invitation.workspace_id, ids, Invitation.status == InvitationStatus.PENDING
            )
        ).get(workspace_id, 0),
        intentions=row.intentions,
        intentions_completed=(
            await _counts(session, Intention.workspace_id, ids, Intention.status == "completed")
        ).get(workspace_id, 0),
        intentions_failed=(
            await _counts(session, Intention.workspace_id, ids, Intention.status == "failed")
        ).get(workspace_id, 0),
        agent_runs=(await _counts(session, AgentRun.workspace_id, ids)).get(workspace_id, 0),
        agent_runs_failed=(
            await _counts(session, AgentRun.workspace_id, ids, AgentRun.status == "failed")
        ).get(workspace_id, 0),
        sources=(await _counts(session, Source.workspace_id, ids)).get(workspace_id, 0),
        sources_in_error=(
            await _counts(
                session,
                Source.workspace_id,
                ids,
                or_(
                    Source.status == SourceStatus.ERROR,
                    Source.health_status == HealthStatus.UNHEALTHY,
                ),
            )
        ).get(workspace_id, 0),
        active_users_30d=int(active or 0),
        analyses_completed=(
            await _counts(
                session,
                IntentionAnalysis.workspace_id,
                ids,
                IntentionAnalysis.status.in_(ANALYSED),
            )
        ).get(workspace_id, 0),
        analyses_failed=(
            await _counts(
                session, IntentionAnalysis.workspace_id, ids, IntentionAnalysis.status == "failed"
            )
        ).get(workspace_id, 0),
        alerts_open=(
            await _counts(
                session, MonitoringAlert.workspace_id, ids, MonitoringAlert.status == "open"
            )
        ).get(workspace_id, 0),
    )
    agents = (
        await session.scalars(
            select(distinct(AgentRun.key))
            .where(AgentRun.workspace_id == workspace_id)
            .order_by(AgentRun.key)
        )
    ).all()
    return OrganisationDetail(
        **row.model_dump(),
        default_language=workspace.default_language,
        suspended_at=workspace.suspended_at,
        deletion_requested_at=workspace.deletion_requested_at,
        plan_since=plan.since,
        billing=BillingState(
            plan=account.plan,
            interval=account.interval,
            status=account.status,
            current_period_end=account.current_period_end,
            cancel_at_period_end=account.cancel_at_period_end,
            launch_offer_used=account.launch_offer_used,
            applied_at=account.applied_at,
        )
        if account
        else None,
        credits=await credits_of(session, workspace_id),
        counts=counts,
        agents_used=list(agents),
    )


async def organisation_members(
    session: AsyncSession, workspace_id: uuid.UUID
) -> OrganisationMembers:
    seats = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == workspace_id)
        .order_by(Membership.created_at)
    )
    invitations = await session.scalars(
        select(Invitation)
        .where(
            Invitation.workspace_id == workspace_id, Invitation.status == InvitationStatus.PENDING
        )
        .order_by(Invitation.created_at.desc())
    )
    return OrganisationMembers(
        members=[
            MemberRow(
                user=PersonRef(id=user.id, email=user.email, name=_name(user)),
                role=str(seat.role),
                since=seat.created_at,
                last_login_at=user.last_login_at,
            )
            for seat, user in seats.all()
        ],
        invitations=[
            InvitationRow(
                email=i.email,
                role=str(i.role),
                status=str(i.status),
                invited_at=i.created_at,
                expires_at=i.expires_at,
            )
            for i in invitations.all()
        ],
    )


# ── People ───────────────────────────────────────────────────────────────────


def _last_meaningful_at() -> Any:
    """Their last intention, run or source connected (the activity journal)."""
    return (
        select(func.max(ActivityEvent.at))
        .where(ActivityEvent.user_id == User.id, ActivityEvent.kind.in_(MEANINGFUL))
        .correlate(User)
        .scalar_subquery()
    )


def _suspended() -> Any:
    """In at least one organisation, and none of theirs still active."""
    seats = select(Membership.user_id).where(Membership.user_id == User.id).correlate(User)
    working = (
        select(Membership.user_id)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.user_id == User.id, Workspace.status == WorkspaceStatus.ACTIVE)
        .correlate(User)
    )
    return seats.exists() & ~working.exists()


def _status_is(status: UserStatus, now: datetime) -> Any:
    """status_of, as SQL: the same rules in the same order."""
    suspended = _suspended()
    if status == "suspended":
        return suspended
    unverified = User.email_verified_at.is_(None)
    if status == "unverified":
        return ~suspended & unverified
    new = User.created_at >= now - NEW_WINDOW
    if status == "new":
        return ~suspended & ~unverified & new
    last = _last_meaningful_at()
    active = last >= now - ACTIVE_WINDOW
    if status == "active":
        return ~suspended & ~unverified & ~new & active
    return ~suspended & ~unverified & ~new & (last.is_(None) | (last < now - ACTIVE_WINDOW))


def users_query(
    *,
    q: str | None = None,
    organisation_id: uuid.UUID | None = None,
    organisation: str | None = None,
    role: str | None = None,
    verified: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    status: UserStatus | None = None,
    active_from: datetime | None = None,
    active_to: datetime | None = None,
    never_active: bool = False,
    now: datetime | None = None,
) -> Select[tuple[User]]:
    """Every person, or those that match: their email, name or id; an
    organisation (by id, or by name or slug) and their role in it; their
    sign-up; their status (status_of's rules); their last intention, run or
    source connected, between two dates or never."""
    moment = now or datetime.now(UTC)
    statement = select(User)
    if q and q.strip():
        as_id = _uuid(q)
        if as_id is not None:
            statement = statement.where(User.id == as_id)
        else:
            pattern = _like(q)
            statement = statement.where(
                or_(
                    User.email.ilike(pattern),
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                )
            )
    if organisation_id or (organisation and organisation.strip()) or role:
        # One seat that says all of it: in that organisation, with that role.
        seats = select(Membership.user_id)
        if organisation_id:
            seats = seats.where(Membership.workspace_id == organisation_id)
        if organisation and organisation.strip():
            pattern = _like(organisation)
            seats = seats.join(Workspace, Workspace.id == Membership.workspace_id).where(
                or_(Workspace.name.ilike(pattern), Workspace.slug.ilike(pattern))
            )
        if role:
            seats = seats.where(Membership.role == role)
        statement = statement.where(User.id.in_(seats))
    if verified is not None:
        statement = statement.where(
            User.email_verified_at.is_not(None) if verified else User.email_verified_at.is_(None)
        )
    if created_from:
        statement = statement.where(User.created_at >= created_from)
    if created_to:
        statement = statement.where(User.created_at < created_to)
    if status:
        statement = statement.where(_status_is(status, moment))
    if active_from or active_to or never_active:
        last = _last_meaningful_at()
        if never_active:
            statement = statement.where(last.is_(None))
        if active_from:
            statement = statement.where(last >= active_from)
        if active_to:
            statement = statement.where(last < active_to)
    return statement


def status_of(
    user: User, last_meaningful: datetime | None, now: datetime, *, suspended: bool = False
) -> UserStatus:
    if suspended:
        return "suspended"
    if user.email_verified_at is None:
        return "unverified"
    if user.created_at >= now - NEW_WINDOW:
        return "new"
    if last_meaningful is not None and last_meaningful >= now - ACTIVE_WINDOW:
        return "active"
    return "inactive"


def level_of(active_days: int, actions: int) -> ActivityLevel:
    """How much they use LEKA, from the last 30 days: the days they were
    seen in the product (the journal's user.active, one a day) and what they
    did (intentions asked, runs, sources connected). A sign-in alone is
    never a day seen, nor an action."""
    if actions >= 20 or active_days >= 12:
        return "high"
    if actions >= 5 or active_days >= 4:
        return "medium"
    if actions >= 1 or active_days >= 1:
        return "low"
    return "none"


async def _memberships(
    session: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[MembershipRead]]:
    found: dict[uuid.UUID, list[MembershipRead]] = defaultdict(list)
    if not user_ids:
        return found
    rows = await session.execute(
        select(
            Membership.user_id,
            Membership.role,
            Membership.created_at,
            Workspace.id,
            Workspace.name,
            Workspace.status,
        )
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.user_id.in_(user_ids))
        .order_by(Membership.created_at)
    )
    for user_id, role, since, workspace_id, name, status in rows.all():
        found[user_id].append(
            MembershipRead(
                organisation=OrganisationRef(id=workspace_id, name=name),
                organisation_status=str(status),
                role=str(role),
                since=since,
            )
        )
    return found


async def _last_meaningful(
    session: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    if not user_ids:
        return {}
    rows = await session.execute(
        select(ActivityEvent.user_id, func.max(ActivityEvent.at))
        .where(ActivityEvent.user_id.in_(user_ids), ActivityEvent.kind.in_(MEANINGFUL))
        .group_by(ActivityEvent.user_id)
    )
    return {key: at for key, at in rows.all() if key is not None}


async def _activity(
    session: AsyncSession, user_ids: Sequence[uuid.UUID], since: datetime
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    """Per person, since then: the days seen in the product, the actions."""
    if not user_ids:
        return {}, {}
    days = await session.execute(
        select(ActivityEvent.user_id, func.count(distinct(func.date(ActivityEvent.at))))
        .where(
            ActivityEvent.user_id.in_(user_ids),
            ActivityEvent.kind == "user.active",
            ActivityEvent.at >= since,
        )
        .group_by(ActivityEvent.user_id)
    )
    actions = await session.execute(
        select(ActivityEvent.user_id, func.count())
        .where(
            ActivityEvent.user_id.in_(user_ids),
            ActivityEvent.kind.in_(MEANINGFUL),
            ActivityEvent.at >= since,
        )
        .group_by(ActivityEvent.user_id)
    )
    return (
        {key: int(n) for key, n in days.tuples().all() if key is not None},
        {key: int(n) for key, n in actions.tuples().all() if key is not None},
    )


async def user_rows(
    session: AsyncSession, users: Sequence[User], now: datetime | None = None
) -> list[UserRow]:
    moment = now or datetime.now(UTC)
    ids = [u.id for u in users]
    seats = await _memberships(session, ids)
    intentions = await _counts(session, Intention.created_by, ids)
    last = await _last_meaningful(session, ids)
    days, actions = await _activity(session, ids, moment - ACTIVE_WINDOW)
    rows: list[UserRow] = []
    for u in users:
        held = seats.get(u.id, [])
        suspended = bool(held) and all(
            seat.organisation_status != WorkspaceStatus.ACTIVE for seat in held
        )
        rows.append(
            UserRow(
                id=u.id,
                email=u.email,
                name=_name(u),
                created_at=u.created_at,
                verified=u.email_verified_at is not None,
                last_login_at=u.last_login_at,
                organisations=held,
                intentions=intentions.get(u.id, 0),
                status=status_of(u, last.get(u.id), moment, suspended=suspended),
                last_active_at=last.get(u.id),
                active_days_30d=days.get(u.id, 0),
                actions_30d=actions.get(u.id, 0),
                activity_level=level_of(days.get(u.id, 0), actions.get(u.id, 0)),
            )
        )
    return rows


async def user_detail(session: AsyncSession, user_id: uuid.UUID) -> UserDetail | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    (row,) = await user_rows(session, [user])
    since = datetime.now(UTC) - ACTIVE_WINDOW
    runs = await session.scalar(select(func.count()).where(AgentRun.requested_by == user_id))
    cost = await session.scalar(
        select(func.sum(UsageRecord.leka_cost_usd)).where(
            UsageRecord.user_id == user_id, UsageRecord.started_at >= since
        )
    )
    sign_ins = (
        await session.scalars(
            select(ActivityEvent.at)
            .where(ActivityEvent.user_id == user_id, ActivityEvent.kind == "user.signed_in")
            .order_by(ActivityEvent.at.desc())
            .limit(20)
        )
    ).all()
    return UserDetail(
        **row.model_dump(),
        company=user.company,
        job_title=user.job_title,
        company_size=user.company_size,
        language=user.language,
        region=user.region,
        agent_runs=int(runs or 0),
        credits_used_30d=_credits(float(cost) if cost is not None else None),
        sign_ins=list(sign_ins),
        access=[await _access(session, user_id, seat) for seat in row.organisations],
        analyses_completed=int(
            await session.scalar(
                select(func.count()).where(
                    IntentionAnalysis.requested_by == user_id,
                    IntentionAnalysis.status.in_(ANALYSED),
                )
            )
            or 0
        ),
        agents_used=list(
            (
                await session.scalars(
                    select(distinct(AgentRun.key))
                    .where(AgentRun.requested_by == user_id)
                    .order_by(AgentRun.key)
                )
            ).all()
        ),
    )


async def _access(session: AsyncSession, user_id: uuid.UUID, seat: MembershipRead) -> UserAccess:
    """What they may do there, as LEKA decides it on each of their requests."""
    with workspace_scope(seat.organisation.id):
        subject = await subject_of(session, seat.organisation.id, user_id)
    return UserAccess(
        organisation=seat.organisation,
        role=seat.role,
        custom_role=subject.custom_role if subject else None,
        permissions=sorted(p.value for p in subject.permissions) if subject else [],
    )


# ── Invitations (LEKA-550) ───────────────────────────────────────────────────


def invitations_query(
    *,
    q: str | None = None,
    organisation_id: uuid.UUID | None = None,
    include_expired: bool = False,
    now: datetime | None = None,
) -> Select[tuple[Invitation]]:
    """The invitations not yet accepted nor revoked: those invited, « invité »."""
    statement = select(Invitation).where(Invitation.status == InvitationStatus.PENDING)
    if not include_expired:
        statement = statement.where(Invitation.expires_at > (now or datetime.now(UTC)))
    if q and q.strip():
        statement = statement.where(Invitation.email.ilike(_like(q)))
    if organisation_id:
        statement = statement.where(Invitation.workspace_id == organisation_id)
    return statement


async def invitation_rows(
    session: AsyncSession, invitations: Sequence[Invitation], now: datetime | None = None
) -> list[AdminInvitationRow]:
    moment = now or datetime.now(UTC)
    names = await _organisation_names(session, [i.workspace_id for i in invitations])
    emails = {i.email.lower() for i in invitations}
    known = (
        set(
            (
                await session.scalars(
                    select(func.lower(User.email)).where(func.lower(User.email).in_(emails))
                )
            ).all()
        )
        if emails
        else set()
    )
    return [
        AdminInvitationRow(
            id=i.id,
            email=i.email,
            organisation=OrganisationRef(id=i.workspace_id, name=names.get(i.workspace_id, "")),
            role=str(i.role),
            invited_at=i.created_at,
            expires_at=i.expires_at,
            expired=i.expires_at <= moment,
            has_account=i.email.lower() in known,
        )
        for i in invitations
    ]


# ── Intentions ───────────────────────────────────────────────────────────────


def intentions_query(
    *,
    q: str | None = None,
    organisation_id: uuid.UUID | None = None,
    organisation: str | None = None,
    user_id: uuid.UUID | None = None,
    user: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    agent: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Select[tuple[Intention]]:
    """Every intention, or those that match: its id or title; its
    organisation (by id, or by name or slug); who asked it (by id, or by
    address or name); its status, kind, agents, date (LEKA-551)."""
    statement = select(Intention)
    if q and q.strip():
        as_id = _uuid(q)
        statement = statement.where(
            Intention.id == as_id if as_id is not None else Intention.title.ilike(_like(q))
        )
    if organisation_id:
        statement = statement.where(Intention.workspace_id == organisation_id)
    if organisation and organisation.strip():
        pattern = _like(organisation)
        statement = statement.where(
            Intention.workspace_id.in_(
                select(Workspace.id).where(
                    or_(Workspace.name.ilike(pattern), Workspace.slug.ilike(pattern))
                )
            )
        )
    if user_id:
        statement = statement.where(Intention.created_by == user_id)
    if user and user.strip():
        pattern = _like(user)
        statement = statement.where(
            Intention.created_by.in_(
                select(User.id).where(
                    or_(
                        User.email.ilike(pattern),
                        User.first_name.ilike(pattern),
                        User.last_name.ilike(pattern),
                    )
                )
            )
        )
    if status:
        mapped = [raw for raw, admin in ADMIN_STATUS.items() if admin == status]
        statement = statement.where(Intention.status.in_(mapped or [status]))
    if kind:
        statement = statement.where(Intention.kind == kind)
    if agent:
        statement = statement.where(
            Intention.id.in_(select(AgentRun.intention_id).where(AgentRun.key == agent))
        )
    if created_from:
        statement = statement.where(Intention.created_at >= created_from)
    if created_to:
        statement = statement.where(Intention.created_at < created_to)
    return statement


async def _intention_costs(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, float]:
    if not ids:
        return {}
    rows = await session.execute(
        select(UsageRecord.intention_id, func.sum(UsageRecord.leka_cost_usd))
        .where(UsageRecord.intention_id.in_(ids), UsageRecord.leka_cost_usd.is_not(None))
        .group_by(UsageRecord.intention_id)
    )
    return {key: float(total) for key, total in rows.all() if key is not None and total is not None}


def short(text: str | None, characters: int = DESCRIPTION_CHARACTERS) -> str | None:
    """A text on one line, cut at a word under `characters`."""
    if not text or not text.strip():
        return None
    flat = " ".join(text.split())
    if len(flat) <= characters:
        return flat
    cut = flat[: characters - 1].rsplit(" ", 1)[0] or flat[: characters - 1]
    return cut.rstrip(" ,;:.") + "…"


async def intention_rows(
    session: AsyncSession, intentions: Sequence[Intention], *, with_content: bool = False
) -> list[AdminIntentionRow]:
    ids = [i.id for i in intentions]
    names = await _organisation_names(session, (i.workspace_id for i in intentions))
    people = {
        u.id: u
        for u in (
            await session.scalars(
                select(User).where(User.id.in_({i.created_by for i in intentions if i.created_by}))
            )
        ).all()
    }
    agents: dict[uuid.UUID, list[str]] = defaultdict(list)
    if ids:
        for intention_id, key in (
            await session.execute(
                select(AgentRun.intention_id, AgentRun.key)
                .where(AgentRun.intention_id.in_(ids))
                .distinct()
                .order_by(AgentRun.intention_id, AgentRun.key)
            )
        ).all():
            if intention_id is not None:
                agents[intention_id].append(key)
    costs = await _intention_costs(session, ids)
    return [
        AdminIntentionRow(
            id=i.id,
            organisation=OrganisationRef(id=i.workspace_id, name=names.get(i.workspace_id, "")),
            created_by=_person(people.get(i.created_by)) if i.created_by else None,
            title=i.title,
            description=short(i.summary or i.text) if with_content else None,
            kind=str(i.kind) if i.kind else None,
            status=str(i.status),
            admin_status=ADMIN_STATUS.get(str(i.status), "pending"),
            created_at=i.created_at,
            status_changed_at=i.status_changed_at,
            agents=agents.get(i.id, []),
            duration_ms=_ms(i.created_at, i.status_changed_at) if str(i.status) in FINAL else None,
            credits=_credits(costs.get(i.id)),
        )
        for i in intentions
    ]


# ── Credits ──────────────────────────────────────────────────────────────────


async def credits_breakdown(
    session: AsyncSession, workspace_id: uuid.UUID, *, since: datetime
) -> CreditsBreakdown | None:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return None
    by_agent = (
        await session.execute(
            select(UsageRecord.subject, func.count(), func.sum(UsageRecord.leka_cost_usd))
            .where(
                UsageRecord.workspace_id == workspace_id,
                UsageRecord.kind == "agent_run",
                UsageRecord.started_at >= since,
            )
            .group_by(UsageRecord.subject)
        )
    ).all()
    by_model = (
        await session.execute(
            select(ModelCall.provider, ModelCall.model, func.count(), func.sum(ModelCall.cost_usd))
            .where(ModelCall.workspace_id == workspace_id, ModelCall.at >= since)
            .group_by(ModelCall.provider, ModelCall.model)
        )
    ).all()
    return CreditsBreakdown(
        organisation=OrganisationRef(id=workspace.id, name=workspace.name),
        credits=await credits_of(session, workspace_id),
        by_agent=sorted(
            (
                AgentCost(
                    key=key,
                    runs=runs,
                    credits=_credits(float(total) if total is not None else None),
                    cost_usd=float(total) if total is not None else None,
                )
                for key, runs, total in by_agent
            ),
            key=lambda c: (-(c.credits or 0), c.key),
        ),
        by_model=sorted(
            (
                ModelCost(
                    provider=provider,
                    model=model_name,
                    calls=calls,
                    cost_usd=float(total) if total is not None else None,
                )
                for provider, model_name, calls, total in by_model
            ),
            key=lambda c: (-(c.cost_usd or 0), c.provider, c.model),
        ),
    )


# ── Billing ──────────────────────────────────────────────────────────────────


def stripe_events_query(
    *,
    type_: str | None = None,
    outcome: str | None = None,
    organisation_id: uuid.UUID | None = None,
    received_from: datetime | None = None,
    received_to: datetime | None = None,
    linked: bool | None = None,
) -> Select[tuple[StripeEvent]]:
    statement = select(StripeEvent)
    if linked is not None:
        statement = statement.where(
            StripeEvent.for_workspace_id.is_not(None)
            if linked
            else StripeEvent.for_workspace_id.is_(None)
        )
    if type_:
        statement = statement.where(StripeEvent.type.like(type_.replace("*", "%")))
    if outcome:
        statement = statement.where(StripeEvent.outcome == outcome)
    if organisation_id:
        statement = statement.where(StripeEvent.for_workspace_id == organisation_id)
    if received_from:
        statement = statement.where(StripeEvent.received_at >= received_from)
    if received_to:
        statement = statement.where(StripeEvent.received_at < received_to)
    return statement


async def stripe_event_rows(
    session: AsyncSession, events: Sequence[StripeEvent]
) -> list[StripeEventRow]:
    names = await _organisation_names(session, (e.for_workspace_id for e in events))
    return [
        StripeEventRow(
            event_id=e.event_id,
            type=e.type,
            outcome=e.outcome,
            received_at=e.received_at,
            organisation=_ref(names, e.for_workspace_id),
            detail=dict(e.detail),
        )
        for e in events
    ]


# ── Environments ─────────────────────────────────────────────────────────────


def sources_query(
    *,
    organisation_id: uuid.UUID | None = None,
    kind: str | None = None,
    status: str | None = None,
    health: str | None = None,
    in_error: bool = False,
) -> Select[tuple[Source]]:
    statement = select(Source)
    if organisation_id:
        statement = statement.where(Source.workspace_id == organisation_id)
    if kind:
        statement = statement.where(Source.kind == kind)
    if status:
        statement = statement.where(Source.status == status)
    if health:
        statement = statement.where(Source.health_status == health)
    if in_error:
        statement = statement.where(
            or_(
                Source.status == SourceStatus.ERROR,
                Source.health_status == HealthStatus.UNHEALTHY,
                Source.sync_status == SyncStatus.FAILED,
            )
        )
    return statement


def diagnostic_of(said: object) -> SourceDiagnostic | None:
    """A failure as LEKA CORE kept it (a Diagnostic, cleaned of secrets when
    written), scanned again before it is said (LEKA-555). Said in words
    alone, as earlier writers kept it: its words, its code unknown."""
    if isinstance(said, str) and said.strip():
        return SourceDiagnostic(
            code="UNKNOWN",
            message=guarded(said.strip()),
            remediation=None,
            retryable=None,
            provider_status=None,
            detail=None,
        )
    if not isinstance(said, dict) or not said:
        return None

    def text(key: str) -> str | None:
        value = said.get(key)
        return guarded(str(value)) if value not in (None, "") else None

    said_status = said.get("provider_status")
    status = (
        said_status if isinstance(said_status, int) and not isinstance(said_status, bool) else None
    )
    retryable = said.get("retryable")
    return SourceDiagnostic(
        code=str(said.get("code") or "UNKNOWN"),
        message=text("message") or "",
        remediation=text("remediation"),
        retryable=retryable if isinstance(retryable, bool) else None,
        provider_status=status,
        detail=text("detail"),
    )


async def source_rows(session: AsyncSession, sources: Sequence[Source]) -> list[SourceRow]:
    names = await _organisation_names(session, (s.workspace_id for s in sources))
    return [
        SourceRow(
            id=s.id,
            organisation=OrganisationRef(id=s.workspace_id, name=names.get(s.workspace_id, "")),
            kind=str(s.kind),
            name=s.name,
            status=str(s.status),
            health=str(s.health_status),
            last_health_check_at=s.last_health_check_at,
            last_error=diagnostic_of(s.last_error),
            sync_status=str(s.sync_status),
            last_synced_at=s.last_synced_at,
            created_at=s.created_at,
        )
        for s in sources
    ]


# ── The activity journal ─────────────────────────────────────────────────────


def activity_query(
    *,
    kind: str | None = None,
    organisation_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    at_from: datetime | None = None,
    at_to: datetime | None = None,
) -> Select[tuple[ActivityEvent]]:
    statement = select(ActivityEvent)
    if kind:
        statement = statement.where(ActivityEvent.kind.like(kind.replace("*", "%")))
    if organisation_id:
        statement = statement.where(ActivityEvent.for_workspace_id == organisation_id)
    if user_id:
        statement = statement.where(ActivityEvent.user_id == user_id)
    if at_from:
        statement = statement.where(ActivityEvent.at >= at_from)
    if at_to:
        statement = statement.where(ActivityEvent.at < at_to)
    return statement


def activity_row(event: ActivityEvent) -> ActivityRow:
    return ActivityRow(
        id=event.id,
        kind=event.kind,
        at=event.at,
        organisation_id=event.for_workspace_id,
        user_id=event.user_id,
        ref=event.ref,
        request_id=event.request_id,
        properties=dict(event.properties),
    )


# ── The admin trail ──────────────────────────────────────────────────────────


async def admin_emails(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The address of each admin a page of the trail names (LEKA-547): most
    rows keep the admin's id only, and a screen says who by their address."""
    if not ids:
        return {}
    rows = await session.execute(
        select(AdminAccount.id, AdminAccount.email).where(AdminAccount.id.in_(ids))
    )
    return dict(rows.tuples().all())


def admin_audit_query(
    *,
    admin_id: uuid.UUID | None = None,
    action: str | None = None,
    organisation_id: uuid.UUID | None = None,
    outcome: str | None = None,
    at_from: datetime | None = None,
    at_to: datetime | None = None,
) -> Select[tuple[AdminAuditEvent]]:
    statement = select(AdminAuditEvent)
    if admin_id:
        statement = statement.where(AdminAuditEvent.admin_id == admin_id)
    if action:
        statement = statement.where(AdminAuditEvent.action.like(action.replace("*", "%")))
    if organisation_id:
        statement = statement.where(AdminAuditEvent.for_workspace_id == organisation_id)
    if outcome:
        statement = statement.where(AdminAuditEvent.outcome == outcome)
    if at_from:
        statement = statement.where(AdminAuditEvent.at >= at_from)
    if at_to:
        statement = statement.where(AdminAuditEvent.at < at_to)
    return statement


__all__ = [
    "ADMIN_STATUS",
    "MEANINGFUL",
    "activity_query",
    "activity_row",
    "admin_audit_query",
    "admin_emails",
    "credits_breakdown",
    "credits_of",
    "intention_rows",
    "intentions_query",
    "organisation_detail",
    "organisation_members",
    "organisation_rows",
    "organisations_query",
    "source_rows",
    "sources_query",
    "status_of",
    "stripe_event_rows",
    "stripe_events_query",
    "user_detail",
    "user_rows",
    "users_query",
]


# ── An organisation's notes, history and alerts (LEKA-549) ───────────────────

# What LEKA's team did to an organisation: its changes, never what it read.
HISTORY_ACTIONS = (
    "admin.organisation_suspended",
    "admin.organisation_reactivated",
    "admin.organisation_updated",
    "admin.credits_added",
    "admin.note_added",
)


def notes_query(
    *, organisation_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None
) -> Select[tuple[AdminNote]]:
    """The notes about an organisation, or about a person (LEKA-550)."""
    if organisation_id is not None:
        return select(AdminNote).where(AdminNote.for_workspace_id == organisation_id)
    return select(AdminNote).where(AdminNote.for_user_id == user_id)


async def note_rows(session: AsyncSession, notes: Sequence[AdminNote]) -> list[NoteRow]:
    ids = {n.admin_id for n in notes if n.admin_id is not None}
    names = (
        dict(
            (
                await session.execute(
                    select(AdminAccount.id, AdminAccount.name).where(AdminAccount.id.in_(ids))
                )
            )
            .tuples()
            .all()
        )
        if ids
        else {}
    )
    return [
        NoteRow(
            id=n.id,
            at=n.created_at,
            admin_email=n.admin_email,
            admin_name=names.get(n.admin_id) if n.admin_id else None,
            body=n.body,
        )
        for n in notes
    ]


def history_query(organisation_id: uuid.UUID) -> Select[tuple[AdminAuditEvent]]:
    return select(AdminAuditEvent).where(
        AdminAuditEvent.for_workspace_id == organisation_id,
        AdminAuditEvent.action.in_(HISTORY_ACTIONS),
        AdminAuditEvent.outcome == "succeeded",
    )


async def history_rows(
    session: AsyncSession, events: Sequence[AdminAuditEvent]
) -> list[OrganisationHistoryRow]:
    emails = await admin_emails(session, {e.admin_id for e in events if e.admin_id is not None})
    return [
        OrganisationHistoryRow(
            id=e.id,
            at=e.at,
            action=e.action,
            admin_email=e.admin_email or (emails.get(e.admin_id) if e.admin_id else None),
            detail=e.detail,
        )
        for e in events
    ]


def alerts_query(organisation_id: uuid.UUID) -> Select[tuple[MonitoringAlert]]:
    return select(MonitoringAlert).where(MonitoringAlert.workspace_id == organisation_id)


def alert_row(alert: MonitoringAlert) -> AlertRow:
    return AlertRow(
        id=alert.id,
        subject_type=alert.subject_type,
        subject_name=alert.subject_name,
        kind=alert.kind,
        severity=alert.severity,
        certainty=alert.certainty,
        status=alert.status,
        opened_at=alert.opened_at,
        last_seen_at=alert.last_seen_at,
        resolved_at=alert.resolved_at,
        acknowledged_at=alert.acknowledged_at,
    )
