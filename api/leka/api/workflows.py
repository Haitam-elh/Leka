"""Workflows (LEKA-397), over HTTP.

    GET    /workflows                      every workflow, its steps in order,
                                           whether it can run here and why not
    GET    /workflows/{key}                one — its versions and history:
                                           GET /capabilities/{key}
    POST   /workflow-runs                  run one: 202, queued — or refused,
                                           said why (404, 403, 422)
    GET    /workflow-runs?key&status       the workspace's runs, the latest first
    GET    /workflow-runs/{id}             one: each step's state, every event
    POST   /workflow-runs/{id}/cancel      cancelled — by who asked, or who may
                                           approve
    POST   /workflow-runs/{id}/retry       a failed run, from where it failed

Running one takes `intention:create`, and the workflow's own permission;
each step's capability is checked for the person when it runs. Reading takes
`intention:read`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    CapabilityInputRead,
    CapabilityReason,
    CatalogueService,
    Entry,
    NotYoursError,
    RunFinishedError,
    RunRefusedError,
    Workflow,
    WorkflowRead,
    WorkflowRun,
    WorkflowRunCreate,
    WorkflowRunDetail,
    WorkflowRunEventRead,
    WorkflowRunRead,
    WorkflowRunStepRead,
    WorkflowService,
    WorkflowStepRead,
    capability_resource,
    find,
    find_workflow,
    queue_workflow,
    workflow_catalogue,
)
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, authorize, require_permission
from leka.intentions import IntentionRepository

router = APIRouter(tags=["workflows"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Runner = Annotated[Principal, Depends(require_permission(Permission.INTENTION_CREATE))]
StatusWord = Literal["queued", "running", "succeeded", "failed", "cancelled"]
ACTION = "workflow:run"
# Failures a retry cannot mend.
FINAL = frozenset({"not_permitted", "gone"})

REFUSED = {
    "not_found": (status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such workflow."),
    "not_a_workflow": (
        status.HTTP_404_NOT_FOUND,
        ErrorCode.NOT_FOUND,
        "No such workflow.",
    ),
    "not_permitted": (
        status.HTTP_403_FORBIDDEN,
        ErrorCode.PERMISSION_DENIED,
        "Your role may not run this workflow.",
    ),
    "unavailable": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_FAILED,
        "This workflow cannot run here now.",
    ),
    "invalid_input": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_FAILED,
        "What the workflow was given is not what it takes.",
    ),
    "needs_intention": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_FAILED,
        "LEKA's own steps read an intention: run it for one.",
    ),
}


def _permissions(principal: Principal) -> frozenset[str]:
    return frozenset(p.value for p in principal.permissions)


def _missing() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such run.")


def _refused(error: RunRefusedError) -> ApiError:
    refusal = error.refusal
    code, kind, message = REFUSED[refusal.code]
    details: list[FieldError] = []
    for reason in refusal.reasons:
        if refusal.code == "invalid_input":
            details.append(
                FieldError(field=f"inputs.{reason['name']}", message=str(reason["code"]))
            )
        elif refusal.code == "needs_intention":
            details.append(FieldError(field="intention_id", message="required"))
        else:
            details.append(FieldError(field="key", message=str(reason["code"])))
    return ApiError(code, kind, message, details=details or None)


def workflow_read(workflow: Workflow, entry: Entry) -> WorkflowRead:
    d = entry.definition
    able = entry.availability
    spec = workflow.spec()["steps"]
    return WorkflowRead(
        key=d.key,
        title=d.title,
        summary=d.summary,
        category=d.category,
        version=d.version,
        lifecycle=d.lifecycle.value,
        inputs=[
            CapabilityInputRead(
                name=i.name,
                type=i.type,
                required=i.required,
                description=i.description,
                choices=list(i.choices),
                entity_types=list(i.entity_types),
            )
            for i in d.contract.inputs
        ],
        steps=[
            WorkflowStepRead(
                id=said["id"],
                title=said["title"],
                uses=said["uses"],
                uses_title=used.title if (used := find(said["uses"])) else None,
                uses_kind=used.kind.value if used else None,
                after=said["after"],
                when=said["when"],
                given=said["given"],
                attempts=said["attempts"],
                on_failure=said["on_failure"],
            )
            for said in spec
        ],
        available=able.available,
        reasons=[CapabilityReason(code=r.code, detail=dict(r.detail)) for r in able.reasons],
        notes=[CapabilityReason(code=r.code, detail=dict(r.detail)) for r in able.notes],
    )


def run_read(run: WorkflowRun, principal: Principal) -> WorkflowRunRead:
    definition = find(run.key)
    return WorkflowRunRead(
        id=run.id,
        key=run.key,
        title=definition.title if definition is not None else None,
        version=run.version,
        status=run.status,
        inputs=run.inputs,
        requested_by=run.requested_by,
        mine=run.requested_by == principal.user_id,
        intention_id=run.intention_id,
        error=run.error,
        failed_step=run.failed_step,
        retries=run.retries,
        retryable=run.status == "failed" and (run.error or "") not in FINAL,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


@router.get("/workflows", response_model=list[WorkflowRead], summary="Every workflow")
async def workflows(session: SessionDep, principal: Reader) -> list[WorkflowRead]:
    entries = {
        e.definition.key: e
        for e in await CatalogueService(session, principal.workspace_id).entries(
            permissions=_permissions(principal)
        )
    }
    return [
        workflow_read(w, entries[key])
        for key, w in sorted(workflow_catalogue().items())
        if key in entries
    ]


@router.get("/workflows/{key}", response_model=WorkflowRead, summary="One workflow")
async def workflow(key: str, session: SessionDep, principal: Reader) -> WorkflowRead:
    found = find_workflow(key)
    entry = await CatalogueService(session, principal.workspace_id).entry(
        key, permissions=_permissions(principal)
    )
    if found is None or entry is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such workflow.")
    return workflow_read(found, entry)


@router.post(
    "/workflow-runs",
    response_model=WorkflowRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a workflow",
)
async def start_run(
    body: WorkflowRunCreate, session: SessionDep, principal: Runner
) -> WorkflowRunRead:
    if body.intention_id is not None and (
        await IntentionRepository(session, principal.workspace_id).intention(body.intention_id)
        is None
    ):
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such intention.")
    # The capability's own permission, decided and kept before it runs
    # (LEKA-402).
    capability = find(body.key)
    if capability is not None:
        decided = await authorize(
            session,
            principal,
            Permission(capability.permission),
            action=ACTION,
            resource=capability_resource(capability),
        )
        if not decided.allowed:
            raise ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.PERMISSION_DENIED, decided.message)
    try:
        run = await WorkflowService(session, principal.workspace_id).start(
            body.key,
            body.inputs,
            by=principal.user_id,
            permissions=_permissions(principal),
            intention_id=body.intention_id,
        )
    except RunRefusedError as error:
        raise _refused(error) from error
    read = run_read(run, principal)
    await session.commit()
    await queue_workflow(principal.workspace_id, run.id)
    return read


@router.get("/workflow-runs", response_model=list[WorkflowRunRead], summary="Workflow runs")
async def list_runs(
    session: SessionDep,
    principal: Reader,
    key: Annotated[str | None, Query(max_length=100)] = None,
    run_status: Annotated[StatusWord | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[WorkflowRunRead]:
    runs = await WorkflowService(session, principal.workspace_id).runs(
        key=key, status=run_status, limit=limit
    )
    return [run_read(run, principal) for run in runs]


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunDetail, summary="One workflow run")
async def get_run(run_id: uuid.UUID, session: SessionDep, principal: Reader) -> WorkflowRunDetail:
    found = await WorkflowService(session, principal.workspace_id).run(run_id)
    if found is None:
        raise _missing()
    run, steps, events = found
    return WorkflowRunDetail(
        **run_read(run, principal).model_dump(),
        steps=[WorkflowRunStepRead.model_validate(s) for s in steps],
        events=[WorkflowRunEventRead.model_validate(e) for e in events],
    )


def _not_yours() -> ApiError:
    return ApiError(
        status.HTTP_403_FORBIDDEN,
        ErrorCode.PERMISSION_DENIED,
        "Only who asked it, or who may approve, may do this.",
    )


@router.post(
    "/workflow-runs/{run_id}/cancel", response_model=WorkflowRunRead, summary="Cancel a run"
)
async def cancel_run(run_id: uuid.UUID, session: SessionDep, principal: Runner) -> WorkflowRunRead:
    try:
        run = await WorkflowService(session, principal.workspace_id).cancel(
            run_id, by=principal.user_id, anyones=principal.has(Permission.INTENTION_APPROVE)
        )
    except NotYoursError as error:
        raise _not_yours() from error
    except RunFinishedError as error:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "It already ended.") from error
    if run is None:
        raise _missing()
    return run_read(run, principal)


@router.post(
    "/workflow-runs/{run_id}/retry",
    response_model=WorkflowRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a failed run from where it failed",
)
async def retry_run(run_id: uuid.UUID, session: SessionDep, principal: Runner) -> WorkflowRunRead:
    """Queued again: its failed and not reached steps pending again, what
    succeeded kept. 409 when it did not fail, or failed for what trying
    again cannot mend (the person no longer allowed)."""
    try:
        run = await WorkflowService(session, principal.workspace_id).retry(
            run_id, by=principal.user_id, anyones=principal.has(Permission.INTENTION_APPROVE)
        )
    except NotYoursError as error:
        raise _not_yours() from error
    except RunFinishedError as error:
        raise ApiError(
            status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "Only a run that failed can be retried."
        ) from error
    if run is None:
        raise _missing()
    read = run_read(run, principal)
    await session.commit()
    await queue_workflow(principal.workspace_id, run.id)
    return read
