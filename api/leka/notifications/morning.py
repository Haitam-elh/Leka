"""The morning report (2026-10-29): the night's review, e-mailed to the
workspace's members in the morning — what LEKA went through, each point to
look at, and the way to Mon environnement.

Sent once a review (`reported_at`), only when there is something to look
at — a quiet night writes to no one — to each member in their language,
unless they muted the watch (`monitoring`) in their notification settings.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from leka.core.config import settings
from leka.db import session_factory, system_scope, workspace_scope
from leka.identity import (
    EmailMessage,
    User,
    branded_layout,
    build_email_sender,
    email_language,
    email_paragraphs,
)
from leka.monitoring import NightReview, night_standing
from leka.notifications.models import NotificationPreference
from leka.platform import Membership, Workspace

logger = structlog.get_logger(__name__)

# A review older than this, its morning gone: never sent.
FRESH = timedelta(hours=18)
MOST_SAID = 10

WORDS: dict[str, dict[str, str]] = {
    "fr": {
        "subject": "LEKA · Revue de la nuit : {count} point{s} à regarder sur {workspace}",
        "title": "Revue de la nuit : {count} point{s} à regarder",
        "checked": (
            "Cette nuit, LEKA a passé en revue {things} éléments, {sources} sources, "
            "{alerts} alertes et {findings} constats. Voici ce qui mérite votre attention :"
        ),
        "more": "… et {count} de plus.",
        "end": "Tout le détail, et une question prête pour chaque point : Mon environnement.",
        "open": "Ouvrir Mon environnement",
        "alert": "{name} : {trouble}",
        "trouble.unavailable": "indisponible",
        "trouble.degraded": "dégradé",
        "trouble.source_failing": "source en échec",
        "source": "Source « {name} » : {why}",
        "why.error": "en erreur",
        "why.degraded": "lecture en échec",
        "why.unread": "non lue depuis plus de 24 h",
        "findings": "{count} constat(s) important(s) de LEKA{on}",
        "finding": "Constat important de LEKA sur {name}",
        "run": "L'agent « {name} » a échoué {count} fois depuis hier",
        "on": ", sur {names}",
        "decisions": "{count} décision(s) attendent votre validation",
        "conflicts": "{count} conflit(s) de connaissance à trancher",
        "change": "La pull request #{number} est rouge : {name}",
        "runs": "{count} exécution(s) d'agent ont échoué depuis hier",
        "nameless": "votre espace",
    },
    "en": {
        "subject": "LEKA · Night review: {count} point{s} to look at on {workspace}",
        "title": "Night review: {count} point{s} to look at",
        "checked": (
            "Overnight, LEKA went through {things} things, {sources} sources, {alerts} alerts "
            "and {findings} findings. Here is what deserves your attention:"
        ),
        "more": "… and {count} more.",
        "end": "Every detail, and a question ready for each point: My environment.",
        "open": "Open My environment",
        "alert": "{name}: {trouble}",
        "trouble.unavailable": "unavailable",
        "trouble.degraded": "degraded",
        "trouble.source_failing": "source failing",
        "source": "Source « {name} »: {why}",
        "why.error": "in error",
        "why.degraded": "reading failed",
        "why.unread": "not read for over 24 h",
        "findings": "{count} important finding(s) from LEKA{on}",
        "finding": "Important finding from LEKA on {name}",
        "run": "The agent « {name} » failed {count} time(s) since yesterday",
        "on": ", on {names}",
        "decisions": "{count} decision(s) wait for your approval",
        "conflicts": "{count} knowledge conflict(s) to settle",
        "change": "Pull request #{number} is red: {name}",
        "runs": "{count} agent run(s) failed since yesterday",
        "nameless": "your workspace",
    },
}


def _words(language: str) -> dict[str, str]:
    return WORDS.get(language.split("-")[0]) or WORDS["en"]


def point_said(point: Mapping[str, object], words: Mapping[str, str]) -> str:
    """One point, in words — as Mon environnement says it."""
    kind = str(point.get("kind"))
    params = point.get("params") if isinstance(point.get("params"), dict) else {}
    assert isinstance(params, dict)
    name = str(point.get("name") or "")
    count = point.get("count", 1)
    if kind == "alert":
        trouble = str(params.get("trouble"))
        return words["alert"].format(name=name, trouble=words.get(f"trouble.{trouble}", trouble))
    if kind == "source":
        why = str(params.get("why"))
        return words["source"].format(name=name, why=words.get(f"why.{why}", why))
    if kind == "findings":
        names = params.get("names")
        on = words["on"].format(names=", ".join(map(str, names))) if names else ""
        return words["findings"].format(count=count, on=on)
    if kind == "change":
        return words["change"].format(number=params.get("number") or "", name=name)
    if kind in ("finding", "run"):
        return words[kind].format(name=name, count=count)
    return words.get(kind, kind).format(count=count)


def report(
    review: NightReview,
    workspace: str | None,
    language: str,
    points: Sequence[Mapping[str, object]] | None = None,
) -> EmailMessage:
    """The morning's e-mail of a review, in `language`, LEKA's dress — its
    points as they stand when it is sent (`points`), when given."""
    words = _words(language)
    points = list(review.points if points is None else points)
    count = len(points)
    plural = "" if count == 1 else "s"
    checked = {k: review.checked.get(k, 0) for k in ("things", "sources", "alerts", "findings")}
    lines = [
        words["checked"].format(**checked),
        "",
        *(f"- {point_said(p, words)}" for p in points[:MOST_SAID]),
    ]
    if count > MOST_SAID:
        lines.append(words["more"].format(count=count - MOST_SAID))
    lines += ["", words["end"]]
    title = words["title"].format(count=count, s=plural)
    where = f"{settings.web_url}/environment"
    return EmailMessage(
        to="",
        subject=words["subject"].format(
            count=count, s=plural, workspace=workspace or words["nameless"]
        )[:200],
        body="\n".join([*lines, "", where]),
        html=branded_layout(
            title,
            email_paragraphs(lines),
            language=language,
            preheader=lines[0],
            action=(words["open"], where),
        ),
        language=language,
    )


async def _recipients(
    workspace_id: uuid.UUID,
) -> Sequence[tuple[str, str | None]]:
    """Each member's address and language — but those who muted the watch."""
    with system_scope():
        async with session_factory() as session:
            people = (
                await session.execute(
                    select(User.id, User.email, User.language)
                    .join(Membership, Membership.user_id == User.id)
                    .where(Membership.workspace_id == workspace_id)
                )
            ).all()
            muted = {
                row.user_id
                for row in (
                    await session.scalars(
                        select(NotificationPreference).where(
                            NotificationPreference.workspace_id == workspace_id
                        )
                    )
                ).all()
                if "monitoring" in (row.muted or [])
            }
    return sorted({(email, chosen) for uid, email, chosen in people if uid not in muted and email})


async def send_morning_reports(*, now: datetime | None = None) -> dict[str, int]:
    """Every workspace's night review with points, sent once, this morning."""
    moment = now or datetime.now(UTC)
    with system_scope():
        async with session_factory() as session:
            workspaces = (await session.scalars(select(Workspace))).all()
    sent = workspaces_told = 0
    sender = build_email_sender()
    for workspace in workspaces:
        try:
            with workspace_scope(workspace.id):
                async with session_factory() as session:
                    review = (
                        await session.scalars(
                            select(NightReview)
                            .where(
                                NightReview.trigger == "night",
                                NightReview.at > moment - FRESH,
                                NightReview.reported_at.is_(None),
                            )
                            .order_by(NightReview.at.desc())
                            .limit(1)
                        )
                    ).first()
                    if review is None:
                        continue
                    review.reported_at = moment
                    await session.commit()
                    # What still stands this morning (2026-10-31).
                    points, _settled = await night_standing(session, review, now=moment)
                    if not points:
                        continue
                    for address, chosen in await _recipients(workspace.id):
                        language = email_language(chosen, workspace=workspace.default_language)
                        message = report(review, workspace.name, language, points)
                        try:
                            await sender.send(
                                EmailMessage(
                                    to=address,
                                    subject=message.subject,
                                    body=message.body,
                                    html=message.html,
                                    language=language,
                                )
                            )
                            sent += 1
                        except Exception:
                            logger.warning(
                                "morning_report_failed", workspace=str(workspace.id), exc_info=True
                            )
                    workspaces_told += 1
        except Exception:
            logger.exception("morning_reports_failed", workspace=str(workspace.id))
    return {"workspaces": workspaces_told, "sent": sent}


def run_morning_reports() -> dict[str, int]:
    """Entry point for the scheduler, which is synchronous."""
    return asyncio.run(send_morning_reports())
