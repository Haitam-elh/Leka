"""The history of a workspace's background jobs.

Read-only, and admin-only (`job:read`). Every route validates, calls the repository, and returns
(architecture rule 6); permissions come from a dependency in the signature, never an `if` (rule 5);
the workspace comes from the principal and from nowhere else (rule 3).

WHAT IT WITHHOLDS. `job_runs` is the one table the session guard does not protect: a sweep belongs
to no customer, so its owner is NULL, and the column is `for_workspace_id` rather than
`workspace_id` for that reason (ADR 012). So the guard cannot save a mistake here — the filter is
written once, in JobRunRepository.for_workspace, and this route only ever builds its query from
that. It never returns the system's own runs, and it answers "not found", not "forbidden", for a
run that is someone else's or nobody's: 403 would confirm the run exists.

It also never returns an error message. The API refuses to say what went wrong inside (a 500 says
only that it did), and an exception text is exactly that; `last_error` is left out of JobRunRead.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.background import JobRun, JobRunRead, JobRunRepository, JobStatus
from leka.core.errors import ErrorCode
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission

router = APIRouter(prefix="/jobs", tags=["jobs"])

# What /jobs may be sorted by. created_at is what a history is read in, and
# ix_job_runs_for_workspace_id_created_at is exactly (workspace, created_at): nothing else is
# offered, so nothing else can put the database on its knees the first time a busy workspace asks.
JOB_SORTS = SortCatalogue(
    fields=(
        SortableField("created_at", JobRun.created_at, "ix_job_runs_for_workspace_id_created_at"),
    ),
    default="created_at",
)

ReadPrincipal = Annotated[Principal, Depends(require_permission(Permission.JOB_READ))]


@router.get("", response_model=PageEnvelope[JobRunRead])
async def list_job_runs(
    principal: ReadPrincipal,
    page: PageParams,
    db: SessionDep,
    status: Annotated[JobStatus | None, Query(description="Only runs in this status.")] = None,
) -> PageEnvelope[JobRunRead]:
    """The background jobs run for this workspace, newest first."""
    statement = JobRunRepository.for_workspace(principal.workspace_id)
    if status is not None:
        statement = statement.where(JobRun.status == status)

    result = await serve_page(db, statement, request=page, catalogue=JOB_SORTS, id_column=JobRun.id)
    return PageEnvelope(
        data=[JobRunRead.model_validate(run) for run in result.items],
        next_cursor=result.next_cursor,
    )


@router.get("/{run_id}", response_model=JobRunRead)
async def get_job_run(run_id: uuid.UUID, principal: ReadPrincipal, db: SessionDep) -> JobRunRead:
    """One run of this workspace's. Not found if it is someone else's, or nobody's."""
    run = await JobRunRepository(db).get_for_workspace(principal.workspace_id, run_id)
    if run is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "No such job run.")
    return JobRunRead.model_validate(run)
