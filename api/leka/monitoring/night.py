"""The night review (2026-10-29): every hour of the night, LEKA goes through
what it watches, and in the morning Mon environnement says what it went
through and what to look at.

    what it reads             what it keeps as a point
    the alerts open           each: unavailable, degraded, a source failing
    the sources               each in error, failing its checks, or unread
                              for a day
    LEKA's findings           each serious one, where its subject is seen
    the decisions             how many wait for someone
    the knowledge conflicts   how many wait to be settled
    LEKA's pull requests      each whose checks are red — never one whose
                              intention was deleted
    the agents' runs          each agent whose runs failed in the day, where
                              its runs are

Only what is there: no model asked, nothing guessed, nothing that costs. A
point says where it is seen (`href`, a page of the web) and whether LEKA
can be asked about it (`ask`): the morning's screen and e-mail make the
words, in the reader's language.

What is shown is what still stands (`standing`, 2026-10-31): a point settled
since the review — an intention deleted, a finding closed, a pull request
green — is gone at once, never left until the next night.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import AgentRun, CodeChange, find
from leka.connectors import Source, SourceStatus
from leka.db import session_factory, system_scope, workspace_scope
from leka.intelligence import Finding, KnowledgeConflict
from leka.intentions import Intention, IntentionDecision
from leka.knowledge import Entity
from leka.monitoring.models import MonitoringAlert, NightReview
from leka.platform import Workspace

logger = structlog.get_logger(__name__)

# A source not read for this long is said unread.
UNREAD = timedelta(hours=24)
# The day the agents' failures are counted over.
DAY = timedelta(hours=24)
# The things named in a point, at most.
MOST_NAMED = 3
# Each kind's points, at most: the rest counted.
MOST_EACH = 8
RANK = {"high": 0, "medium": 1, "low": 2}


def _point(
    kind: str,
    severity: str,
    *,
    href: str,
    name: str = "",
    count: int = 1,
    ask: bool = False,
    **params: object,
) -> dict[str, object]:
    return {
        "kind": kind,
        "severity": severity,
        "name": name[:300],
        "count": count,
        "href": href,
        "ask": ask,
        "params": params,
    }


async def _count(session: AsyncSession, query: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(query.subquery())) or 0)


async def _living(session: AsyncSession, ids: Sequence[uuid.UUID | None]) -> set[uuid.UUID]:
    """The intentions among these that still are: neither deleted nor
    archived (2026-10-31: a deleted intention's red pull request stayed in
    the review, its « Voir » leading nowhere)."""
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return set()
    return set(
        (
            await session.scalars(
                select(Intention.id).where(
                    Intention.id.in_(wanted), Intention.archived_at.is_(None)
                )
            )
        ).all()
    )


async def checked_and_points(
    session: AsyncSession, *, now: datetime
) -> tuple[dict[str, int], list[dict[str, object]]]:
    """What a workspace holds, read — and what in it needs someone. Read in
    the workspace's scope (workspace_scope)."""
    points: list[dict[str, object]] = []
    checked: dict[str, int] = {}

    alerts = (
        await session.scalars(
            select(MonitoringAlert)
            .where(MonitoringAlert.status == "open")
            .order_by(MonitoringAlert.opened_at.desc())
        )
    ).all()
    checked["alerts"] = len(alerts)
    for alert in alerts[:MOST_EACH]:
        points.append(
            _point(
                "alert",
                alert.severity,
                # The alerts' card on Mon environnement, scrolled to.
                href="/environment#alerts",
                name=alert.subject_name,
                ask=True,
                trouble=alert.kind,
                since=alert.opened_at.isoformat(),
            )
        )

    sources = (await session.scalars(select(Source))).all()
    checked["sources"] = len(sources)
    for source in sources:
        if source.status in (SourceStatus.DRAFT, SourceStatus.DISABLED):
            continue
        why: str | None = None
        if source.status is SourceStatus.ERROR or source.health_status.value == "unhealthy":
            why = "error"
        elif source.status is SourceStatus.DEGRADED or source.sync_status.value == "failed":
            why = "degraded"
        elif source.last_synced_at is not None and now - source.last_synced_at > UNREAD:
            why = "unread"
        if why is None:
            continue
        points.append(
            _point(
                "source",
                "high" if why == "error" else "medium",
                href=f"/sources/{source.id}",
                name=source.name,
                why=why,
                since=source.last_synced_at.isoformat() if source.last_synced_at else None,
            )
        )

    checked["things"] = await _count(session, select(Entity.id).where(Entity.removed_at.is_(None)))
    serious = (
        await session.scalars(
            select(Finding)
            .where(Finding.status == "open", Finding.severity == "high")
            .order_by(Finding.rank)
        )
    ).all()
    checked["findings"] = await _count(session, select(Finding.id).where(Finding.status == "open"))
    # Each serious finding its own point, seen where its subject is
    # (2026-10-31: one point for three findings led to the page already open).
    for finding in serious[:MOST_EACH]:
        points.append(
            _point(
                "finding",
                "high",
                href="/environment?tab=applications",
                name=finding.subject_name,
                ask=True,
                finding=str(finding.id),
                code=finding.code,
                category=finding.category,
                subject_type=finding.subject_type,
                subject_id=str(finding.subject_id) if finding.subject_id else None,
                subject_kind=finding.subject_kind,
            )
        )

    waiting = await _count(
        session, select(IntentionDecision.id).where(IntentionDecision.status == "proposed")
    )
    checked["decisions"] = waiting
    if waiting:
        points.append(_point("decisions", "medium", href="/approvals", count=waiting))

    conflicts = await _count(
        session, select(KnowledgeConflict.id).where(KnowledgeConflict.status == "open")
    )
    checked["conflicts"] = conflicts
    if conflicts:
        points.append(_point("conflicts", "low", href="/approvals", count=conflicts))

    applied = (
        await session.scalars(select(CodeChange).where(CodeChange.status == "applied"))
    ).all()
    checked["changes"] = len(applied)
    red = [c for c in applied if (c.follow or {}).get("stage") == "checks_failed"]
    alive = await _living(session, [c.intention_id for c in red])
    for change in red:
        if change.intention_id is not None and change.intention_id not in alive:
            continue
        points.append(
            _point(
                "change",
                "high",
                href=f"/intentions/{change.intention_id}/deliverable"
                if change.intention_id
                else (change.pull_request_url or "/capabilities"),
                name=change.title,
                number=change.pull_request_number,
            )
        )

    failed = (
        await session.execute(
            select(AgentRun.key, AgentRun.intention_id).where(
                AgentRun.status == "failed", AgentRun.finished_at > now - DAY
            )
        )
    ).all()
    checked["runs"] = await _count(
        session, select(AgentRun.id).where(AgentRun.finished_at > now - DAY)
    )
    # Each agent whose runs failed, where its runs are — never a run whose
    # intention was deleted.
    alive = await _living(session, [intention for _key, intention in failed])
    by_agent: dict[str, int] = {}
    for key, intention in failed:
        if intention is None or intention in alive:
            by_agent[key] = by_agent.get(key, 0) + 1
    for key, count in sorted(by_agent.items(), key=lambda kv: -kv[1])[:MOST_EACH]:
        definition = find(key)
        points.append(
            _point(
                "run",
                "medium",
                href=f"/capabilities/{key}",
                name=definition.title if definition is not None else key,
                count=count,
                agent=key,
            )
        )

    points.sort(key=lambda p: RANK.get(str(p["severity"]), 3))
    return checked, points


async def review(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    trigger: str = "night",
    by: uuid.UUID | None = None,
    now: datetime | None = None,
) -> NightReview:
    """One review, kept."""
    moment = now or datetime.now(UTC)
    checked, points = await checked_and_points(session, now=moment)
    row = NightReview(
        workspace_id=workspace_id,
        id=uuid.uuid4(),
        at=moment,
        trigger=trigger,
        checked=checked,
        points=points,
        asked_by=by,
    )
    session.add(row)
    await session.flush()
    logger.info("night_reviewed", workspace=str(workspace_id), points=len(points))
    return row


async def latest(session: AsyncSession) -> NightReview | None:
    """The last review, in the workspace's scope."""
    return (
        await session.scalars(select(NightReview).order_by(NightReview.at.desc()).limit(1))
    ).first()


def _key(point: dict[str, Any]) -> tuple[object, ...]:
    """What makes a point the same from one review to the next."""
    kind = point.get("kind")
    params = point.get("params") or {}
    if kind == "finding":
        return (kind, params.get("finding"))
    if kind == "change":
        return (kind, params.get("number"), point.get("name"))
    if kind == "run":
        return (kind, params.get("agent"))
    if kind in ("alert", "source"):
        return (kind, point.get("name"), params.get("trouble") or params.get("why"))
    # Counted: the same while there is any.
    return (kind,)


# Kinds a review kept counted before 2026-10-31, one point each since.
_COUNTED_BEFORE = {"findings": "finding", "runs": "run"}


def still(
    kept: Sequence[dict[str, Any]], now: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """A review's points that still stand, as they stand now — and how many
    were settled since."""
    fresh = {_key(p): p for p in now}
    shown: list[dict[str, Any]] = []
    seen: set[tuple[object, ...]] = set()
    settled = 0
    for point in kept:
        kind = str(point.get("kind"))
        group = (
            [p for p in now if p.get("kind") == _COUNTED_BEFORE[kind]]
            if kind in _COUNTED_BEFORE
            else [fresh[_key(point)]]
            if _key(point) in fresh
            else []
        )
        if not group:
            settled += 1
        for found in group:
            if _key(found) not in seen:
                seen.add(_key(found))
                shown.append(found)
    shown.sort(key=lambda p: RANK.get(str(p["severity"]), 3))
    return shown, settled


async def standing(
    session: AsyncSession, review: NightReview, *, now: datetime | None = None
) -> tuple[list[dict[str, Any]], int]:
    """A review's points as they stand now: those settled since gone (an
    intention deleted, a finding closed, a pull request green) — and how
    many. Read in the workspace's scope; nothing asked of a model."""
    _checked, fresh = await checked_and_points(session, now=now or datetime.now(UTC))
    return still(review.points, fresh)


async def review_every_workspace(*, now: datetime | None = None) -> dict[str, int]:
    """Every workspace reviewed — one failing never stops the others."""
    with system_scope():
        async with session_factory() as session:
            ids: Sequence[uuid.UUID] = (await session.scalars(select(Workspace.id))).all()
    done = failed = 0
    for workspace_id in ids:
        try:
            with workspace_scope(workspace_id):
                async with session_factory() as session:
                    await review(session, workspace_id, now=now)
                    await session.commit()
            done += 1
        except Exception:
            failed += 1
            logger.exception("night_review_failed", workspace=str(workspace_id))
    return {"reviewed": done, "failed": failed}


def run_night_reviews() -> dict[str, int]:
    """Entry point for the scheduler, which is synchronous."""
    return asyncio.run(review_every_workspace())
