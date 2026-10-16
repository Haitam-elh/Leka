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
from dataclasses import replace
from datetime import UTC, datetime, time

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import ModelCall, leka_cost
from leka.core.config import settings
from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import allowance, credits_of, next_month
from leka.identity import EmailMessage, User, build_email_sender, email_language
from leka.metering.models import CreditWarning
from leka.metering.schemas import CreditsRead, CreditWarningRead
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
    warned = (
        await session.scalars(
            select(CreditWarning)
            .where(CreditWarning.workspace_id == workspace_id, CreditWarning.period == given.period)
            .order_by(CreditWarning.threshold)
        )
    ).all()
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
        warned=[CreditWarningRead(threshold=w.threshold, at=w.at, used=w.used) for w in warned],
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


# What the warnings say, in each language e-mails are translated into
# (leka/core/languages.yaml, `ui.emails`).
_WORDS: dict[str, dict[str, str]] = {
    "fr": {
        "nameless": "votre espace",
        "date": "%d/%m/%Y",
        "spent.subject": "LEKA — les crédits IA de {name} sont épuisés",
        "spent.body": (
            "{name} a utilisé tous ses crédits IA du mois ({allowance} crédits, plan {plan}). "
        ),
        "spent.enforced": "L'IA de LEKA est suspendue jusqu'au {end}, ",
        "spent.open": "Rien n'est bloqué pour l'instant, ",
        "spent.end": (
            "sauf ajout d'un pack de crédits ou passage à un plan supérieur : "
            "contactez-nous. Aucun dépassement n'est jamais facturé."
        ),
        "near.subject": "LEKA — {threshold} % des crédits IA de {name} utilisés",
        "near.body": (
            "{name} a utilisé {threshold} % de ses crédits IA du mois "
            "({used} sur {allowance}, plan {plan}). "
            "Il en reste {remaining} jusqu'au {end}. Au-delà, l'IA de LEKA "
            "s'arrête jusqu'au mois suivant, sauf ajout d'un pack ou passage à un plan "
            "supérieur — aucun dépassement n'est facturé."
        ),
    },
    "en": {
        "nameless": "your workspace",
        "date": "%d %b %Y",
        "spent.subject": "LEKA — {name} has used all its AI credits",
        "spent.body": (
            "{name} has used all its AI credits for the month ({allowance} credits, {plan} plan). "
        ),
        "spent.enforced": "LEKA's AI is paused until {end}, ",
        "spent.open": "Nothing is blocked for now, ",
        "spent.end": (
            "unless a credit pack is added or the plan is upgraded: contact us. "
            "Overage is never charged."
        ),
        "near.subject": "LEKA — {name} has used {threshold}% of its AI credits",
        "near.body": (
            "{name} has used {threshold}% of its AI credits for the month "
            "({used} of {allowance}, {plan} plan). "
            "{remaining} are left until {end}. Beyond that, LEKA's AI stops until the "
            "next month, unless a pack is added or the plan is upgraded — overage is "
            "never charged."
        ),
    },
}


def _warning(read: CreditsRead, threshold: int, name: str | None, language: str) -> EmailMessage:
    words = _WORDS.get(language) or _WORDS["en"]
    said = {
        "name": name or words["nameless"],
        "allowance": read.allowance,
        "plan": read.plan,
        "threshold": threshold,
        "used": f"{read.used:g}",
        "remaining": f"{read.remaining:g}",
        "end": read.period_end.strftime(words["date"]),
    }
    if threshold >= 100:
        subject = words["spent.subject"].format(**said)
        body = (
            words["spent.body"].format(**said)
            + words["spent.enforced" if read.enforced else "spent.open"].format(**said)
            + words["spent.end"]
        )
    else:
        subject = words["near.subject"].format(**said)
        body = words["near.body"].format(**said)
    return EmailMessage(to="", subject=subject[:200], body=body, language=language)


async def _tell(
    session: AsyncSession, workspace_id: uuid.UUID, read: CreditsRead, threshold: int
) -> None:
    """Its owners and admins, told — each in their language, else the
    workspace's."""
    to = (
        await session.execute(
            select(User.email, User.language)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.workspace_id == workspace_id,
                Membership.role.in_([Role.OWNER, Role.ADMIN]),
            )
        )
    ).all()
    workspace = await session.get(Workspace, workspace_id)
    name = workspace.name if workspace is not None else None
    sender = build_email_sender()
    for address, chosen in sorted(set(to)):
        language = email_language(
            chosen, workspace=workspace.default_language if workspace else None
        )
        try:
            await sender.send(replace(_warning(read, threshold, name, language), to=address))
        except Exception:
            logger.warning(
                "credit_warning_email_failed", workspace=str(workspace_id), exc_info=True
            )
