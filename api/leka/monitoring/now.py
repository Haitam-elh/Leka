"""What LEKA is working on, now (2026-10-29): every piece of work under way
in the workspace, the latest first, each with its step and where to follow
it.

    an intention          being analysed, its actions carried out, checked
    an agent's run        queued, at work, or drawing what it delivers — its
                          change, its mock-ups, its deck
    a source              being read
    a pull request        being repaired

Read from what each module keeps, nothing kept here; the screen polls it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.capabilities import AgentRun, CodeChange, find
from leka.connectors import Source
from leka.intentions import Intention

WORKING = ("analysing", "executing", "verifying")
MOST = 12


def _item(kind: str, title: str, step: str, since: datetime | None, href: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title[:300],
        "step": step,
        "since": since.isoformat() if since else None,
        "href": href,
    }


def _run_step(run: AgentRun) -> str:
    said = (run.detail or {}).get("drawing")
    drawing = [str(d) for d in said] if isinstance(said, list) else []
    if "change" in drawing:
        return "writing_change"
    if "design" in drawing:
        return "drawing_design"
    if drawing:
        return "drawing_files"
    # Writing its change itself, in its draft (workshop.py, 2026-10-30).
    if run.status == "running" and (run.detail or {}).get("drafting"):
        return "editing"
    return "queued" if run.status == "queued" else "working"


async def working_now(session: AsyncSession) -> list[dict[str, Any]]:
    """Everything under way, in the workspace's scope, the latest first."""
    found: list[dict[str, Any]] = []
    intentions = (
        await session.scalars(
            select(Intention)
            .where(Intention.status.in_(WORKING), Intention.archived_at.is_(None))
            .order_by(Intention.status_changed_at.desc())
            .limit(MOST)
        )
    ).all()
    for intention in intentions:
        found.append(
            _item(
                "intention",
                intention.title,
                intention.status,
                intention.status_changed_at,
                f"/intentions/{intention.id}",
            )
        )
    runs = (
        await session.scalars(
            select(AgentRun)
            .where(AgentRun.status.in_(("queued", "running", "succeeded")))
            .order_by(AgentRun.queued_at.desc())
            .limit(MOST * 4)
        )
    ).all()
    for run in runs:
        if run.status == "succeeded" and not (run.detail or {}).get("drawing"):
            continue
        definition = find(run.key)
        found.append(
            _item(
                "agent",
                definition.title if definition is not None else run.key,
                _run_step(run),
                run.started_at or run.queued_at,
                f"/intentions/{run.intention_id}/deliverable"
                if run.intention_id
                else f"/capabilities/{run.key}",
            )
        )
    for source in (await session.scalars(select(Source))).all():
        if source.sync_status.value == "running":
            found.append(
                _item(
                    "source", source.name, "reading", source.last_synced_at, f"/sources/{source.id}"
                )
            )
    for change in (
        await session.scalars(select(CodeChange).where(CodeChange.status == "applied"))
    ).all():
        repairs = change.repairs or []
        if repairs and repairs[-1].get("state") == "running":
            asked = repairs[-1].get("asked_at")
            found.append(
                _item(
                    "repair",
                    change.title,
                    "repairing",
                    datetime.fromisoformat(str(asked)) if asked else None,
                    f"/intentions/{change.intention_id}/deliverable"
                    if change.intention_id
                    else (change.pull_request_url or "/capabilities"),
                )
            )
    found.sort(key=lambda i: i["since"] or "", reverse=True)
    return found[:MOST]
