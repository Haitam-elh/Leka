"""A workspace's AI credits, read and watched (LEKA-430).

    credits_now()      its plan, its allowance this month, what was used, what
                       is left — what Facturation shows
    watch_credits()    every workspace that used LEKA's models this month:
                       each share of its credits passed (80 %, 100 %…) told
                       to its owners and admins, once a month — the schedule's
                       every quarter of an hour

What is used is what its work cost LEKA on LEKA's models, in credits; what
may be used, its plan's and its packs' (leka.governance.plans). Refusing
LEKA's models once they are spent is the gateway's (AI controls).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, time

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import ModelCall, leka_cost
from leka.core.config import settings
from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import allowance, credits_of, next_month
from leka.identity import EmailMessage, User, build_email_sender
from leka.metering.models import CreditWarning
from leka.metering.schemas import CreditsRead
from leka.platform import Membership, Role, Workspace

logger = structlog.get_logger(__name__)


def _start(day: object) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)  # type: ignore[arg-type]


def warnings_at() -> list[int]:
    return sorted({int(t) for t in settings.credit_warnings if 0 < int(t) <= 100})


async def credits_now(
    session: AsyncSession, workspace_id: uuid.UUID, *, now: datetime
) -> CreditsRead:
    given = await allowance(session, workspace_id, now)
    start = _start(given.period)
    used = round(credits_of(await leka_cost(session, workspace_id, since=start)), 2)
    total = given.credits
    percent = round(used / total * 100, 1) if total else (100.0 if used else 0.0)
    thresholds = warnings_at()
    state = (
        "exhausted"
        if used >= total
        else "warning"
        if thresholds and percent >= thresholds[0]
        else "ok"
    )
    return CreditsRead(
        plan=given.plan.name,
        plan_since=given.plan.since,
        monthly=given.plan.monthly_credits,
        packs=given.packs,
        allowance=total,
        used=used,
        remaining=round(max(total - used, 0.0), 2),
        percent=percent,
        period_start=start,
        period_end=_start(next_month(given.period)),
        state=state,
        warn_at=thresholds,
        enforced=settings.credits_enforced,
        credit_usd=settings.credit_usd,
    )


def run_credit_watch() -> dict[str, list[int]]:
    """Entry point for the schedule."""
    return asyncio.run(watch_credits())


async def watch_credits(*, now: datetime | None = None) -> dict[str, list[int]]:
    """Each workspace's shares of this month's credits passed and not yet
    told: kept, then told. Kept first, once (unique): a watch run twice, or
    two at once, tells once. One that fails is logged; the others are
    watched all the same."""
    moment = now or datetime.now(UTC)
    start = moment.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with system_scope():
        async with session_factory() as session:
            workspaces = (
                await session.scalars(
                    select(ModelCall.workspace_id)
                    .where(ModelCall.at >= start, ModelCall.owner == "leka")
                    .distinct()
                )
            ).all()
    told: dict[str, list[int]] = {}
    for workspace_id in workspaces:
        try:
            passed = await _watch(workspace_id, moment)
        except Exception:
            logger.exception("credit_watch_failed", workspace=str(workspace_id))
            continue
        if passed:
            told[str(workspace_id)] = passed
    return told


async def _watch(workspace_id: uuid.UUID, now: datetime) -> list[int]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            read = await credits_now(session, workspace_id, now=now)
            passed: list[int] = []
            for threshold in read.warn_at:
                if read.percent < threshold:
                    continue
                kept = await session.scalar(
                    insert(CreditWarning)
                    .values(
                        workspace_id=workspace_id,
                        id=uuid.uuid4(),
                        period=read.period_start.date(),
                        threshold=threshold,
                        credits=read.allowance,
                        used=read.used,
                        at=now,
                    )
                    .on_conflict_do_nothing(constraint="uq_credit_warnings_once")
                    .returning(CreditWarning.id)
                )
                if kept is not None:
                    passed.append(threshold)
            await session.commit()
            if passed:
                await _tell(session, workspace_id, read, max(passed))
    return passed


async def _tell(
    session: AsyncSession, workspace_id: uuid.UUID, read: CreditsRead, threshold: int
) -> None:
    """Its owners and admins, told — in French, as LEKA speaks to them."""
    to = (
        await session.scalars(
            select(User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.workspace_id == workspace_id,
                Membership.role.in_([Role.OWNER, Role.ADMIN]),
            )
        )
    ).all()
    workspace = await session.get(Workspace, workspace_id)
    name = workspace.name if workspace is not None else "votre espace"
    end = read.period_end.strftime("%d/%m/%Y")
    if threshold >= 100:
        subject = f"LEKA — les crédits IA de {name} sont épuisés"
        body = (
            f"{name} a utilisé tous ses crédits IA du mois ({read.allowance} crédits, plan "
            f"{read.plan}). "
            + (
                "L'IA de LEKA est suspendue jusqu'au " + end + ", "
                if read.enforced
                else "Rien n'est bloqué pour l'instant, "
            )
            + "sauf ajout d'un pack de crédits ou passage à un plan supérieur : "
            "contactez-nous. Aucun dépassement n'est jamais facturé."
        )
    else:
        subject = f"LEKA — {threshold} % des crédits IA de {name} utilisés"
        body = (
            f"{name} a utilisé {threshold} % de ses crédits IA du mois "
            f"({read.used:g} sur {read.allowance}, plan {read.plan}). "
            f"Il en reste {read.remaining:g} jusqu'au {end}. Au-delà, l'IA de LEKA "
            "s'arrête jusqu'au mois suivant, sauf ajout d'un pack ou passage à un plan "
            "supérieur — aucun dépassement n'est facturé."
        )
    sender = build_email_sender()
    for address in sorted(set(to)):
        try:
            await sender.send(EmailMessage(to=address, subject=subject[:200], body=body))
        except Exception:
            logger.warning(
                "credit_warning_email_failed", workspace=str(workspace_id), exc_info=True
            )
