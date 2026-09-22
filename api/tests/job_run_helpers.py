"""Helpers the job-run tests share: a workspace, and a run inserted in any state.

Runs are inserted with raw SQL on purpose, in states no code path would reach on demand
(a `running` run whose lease expired an hour ago), and read back the same way — so what a
test asserts about is the database, not the ORM's idea of it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import (
    JobStatus,
)
from leka.platform import Workspace

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
PATH = "tests.background_jobs"


async def make_workspace(session: AsyncSession) -> uuid.UUID:
    workspace = Workspace(name="run", slug=f"run-{uuid.uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    return workspace.id


async def insert_run(
    session: AsyncSession,
    workspace: uuid.UUID | None,
    *,
    status: JobStatus = JobStatus.QUEUED,
    attempts: int = 0,
    max_attempts: int = 3,
    locked_until: datetime | None = None,
    next_run_at: datetime | None = None,
    enqueued_at: datetime | None = None,
    job: str = f"{PATH}.succeed",
    args: str = "[]",
    request_id: str | None = None,
) -> uuid.UUID:
    result = await session.execute(
        text(
            "INSERT INTO job_runs (for_workspace_id, job, status, attempts, max_attempts, "
            "locked_until, next_run_at, enqueued_at, args, request_id) "
            "VALUES (:w, :j, :s, :a, :m, :l, :n, :e, CAST(:args AS jsonb), :r) RETURNING id"
        ),
        {
            "w": workspace,
            "j": job,
            "s": status.value,
            "a": attempts,
            "m": max_attempts,
            "l": locked_until,
            "n": next_run_at,
            "e": enqueued_at,
            "args": args,
            "r": request_id,
        },
    )
    identifier: uuid.UUID = result.scalar_one()
    return identifier


async def row_of(session: AsyncSession, run_id: uuid.UUID) -> dict[str, Any]:
    result = await session.execute(text("SELECT * FROM job_runs WHERE id = :i"), {"i": run_id})
    return dict(result.mappings().one())


async def status_of(session: AsyncSession, run_id: uuid.UUID) -> JobStatus:
    return JobStatus((await row_of(session, run_id))["status"])


# ── The shape of the state machine ────────────────────────────────────────


# ── Claiming: exactly one worker wins ─────────────────────────────────────


# ── Finishing ─────────────────────────────────────────────────────────────


# ── Failing, and trying again ─────────────────────────────────────────────


# ── Recovery: a worker that died ──────────────────────────────────────────


# ── Creating a run ────────────────────────────────────────────────────────


# ── Enqueueing ────────────────────────────────────────────────────────────


# ── The runner ────────────────────────────────────────────────────────────


# ── History: what a customer may see ──────────────────────────────────────
