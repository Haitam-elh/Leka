"""Agents, run (LEKA-395), over HTTP.

    POST   /agent-runs                  run an agent: 202, queued — or refused,
                                        said why (404, 403, 422)
    GET    /agent-runs?key&status       the workspace's runs, the latest first
    GET    /agent-runs/{id}             one: what it delivered, every step,
                                        what its model calls took
    POST   /agent-runs/{id}/cancel      cancelled — by who asked, or who may
                                        approve

Running one takes `intention:create`, and whatever the agent's own
permission is: the catalogue says it (`not_permitted`). Reading takes
`intention:read`. The workspace is read from the session, never from the
path or the payload (rule 3).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    AgentRun,
    AgentRunCreate,
    AgentRunDetail,
    AgentRunEventRead,
    AgentRunRead,
    AgentRuntime,
    AgentRunUsage,
    NotYoursError,
    RunFinishedError,
    RunRefusedError,
    find,
    queue_run,
)
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, Resource, authorize, require_permission
from leka.intentions import IntentionRepository

router = APIRouter(prefix="/agent-runs", tags=["capabilities"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Runner = Annotated[Principal, Depends(require_permission(Permission.INTENTION_CREATE))]
StatusWord = Literal["queued", "running", "succeeded", "failed", "cancelled"]
ACTION = "agent:run"

REFUSED = {
    "not_found": (status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such agent."),
    "not_an_agent": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_FAILED,
        "Only an agent runs here: LEKA's own capabilities run in an analysis.",
    ),
    "not_permitted": (
        status.HTTP_403_FORBIDDEN,
        ErrorCode.PERMISSION_DENIED,
        "Your role may not use this agent.",
    ),
    "unavailable": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_FAILED,
        "This agent cannot run here now.",
    ),
    "invalid_input": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_FAILED,
        "What the agent was given is not what it takes.",
    ),
    "unknown_context": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_FAILED,
        "No such context in this workspace.",
    ),
}


def _missing() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such run.")


def _refused(error: RunRefusedError) -> ApiError:
    refusal = error.refusal
    code, kind, message = REFUSED[refusal.code]
    details = [
        FieldError(field=f"inputs.{r['name']}", message=str(r["code"]))
        if refusal.code == "invalid_input"
        else FieldError(field="key", message=str(r["code"]))
        for r in refusal.reasons
    ]
    return ApiError(code, kind, message, details=details or None)


def run_read(run: AgentRun, principal: Principal) -> AgentRunRead:
    definition = find(run.key)
    failure = run.detail.get("failure")
    reasons = failure.get("reasons", []) if isinstance(failure, dict) else []
    pending = run.detail.get("pending", [])
    return AgentRunRead(
        id=run.id,
        key=run.key,
        title=definition.title if definition is not None else None,
        version=run.version,
        status=run.status,
        inputs=run.inputs,
        requested_by=run.requested_by,
        mine=run.requested_by == principal.user_id,
        intention_id=run.intention_id,
        context_id=run.context_id,
        context_version=run.context_version,
        format=run.format,
        pending=[str(p) for p in pending] if isinstance(pending, list) else [],
        error=run.error,
        reasons=[r for r in reasons if isinstance(r, dict)],
        provider=run.provider,
        model=run.model,
        model_version=run.model_version,
        tool_calls=run.tool_calls,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


@router.post(
    "",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run an agent",
)
async def start_run(body: AgentRunCreate, session: SessionDep, principal: Runner) -> AgentRunRead:
    """Queued for a worker — or refused, said why: no such agent (404), the
    person's role may not use it (403), it cannot run here now, or what it
    was given is not what it takes (422, each reason in `details`)."""
    context_id = body.context_id
    if body.intention_id is not None:
        intention = await IntentionRepository(session, principal.workspace_id).intention(
            body.intention_id
        )
        if intention is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such intention.")
        context_id = context_id or intention.context_id
    # The capability's own permission, decided and kept before it runs
    # (LEKA-402).
    capability = find(body.key)
    if capability is not None:
        decided = await authorize(
            session,
            principal,
            Permission(capability.permission),
            action=ACTION,
            resource=Resource("capability", capability.key),
        )
        if not decided.allowed:
            raise ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.PERMISSION_DENIED, decided.message)
    runtime = AgentRuntime(session, principal.workspace_id)
    try:
        run = await runtime.start(
            body.key,
            body.inputs,
            by=principal.user_id,
            permissions=frozenset(p.value for p in principal.permissions),
            intention_id=body.intention_id,
            context_id=context_id,
        )
    except RunRefusedError as error:
        raise _refused(error) from error
    read = run_read(run, principal)
    # What the worker reads, committed before it hears of it.
    await session.commit()
    await queue_run(principal.workspace_id, run.id)
    return read


@router.get("", response_model=list[AgentRunRead], summary="The workspace's agent runs")
async def list_runs(
    session: SessionDep,
    principal: Reader,
    key: Annotated[str | None, Query(max_length=100)] = None,
    run_status: Annotated[StatusWord | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AgentRunRead]:
    runs = await AgentRuntime(session, principal.workspace_id).runs(
        key=key, status=run_status, limit=limit
    )
    return [run_read(run, principal) for run in runs]


@router.get("/{run_id}", response_model=AgentRunDetail, summary="One agent run, every step")
async def get_run(run_id: uuid.UUID, session: SessionDep, principal: Reader) -> AgentRunDetail:
    found = await AgentRuntime(session, principal.workspace_id).run(run_id)
    if found is None:
        raise _missing()
    run, events, (calls, tokens_in, tokens_out, cost) = found
    return AgentRunDetail(
        **run_read(run, principal).model_dump(),
        output=run.output,
        events=[AgentRunEventRead.model_validate(e) for e in events],
        usage=AgentRunUsage(calls=calls, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost),
    )


@router.post("/{run_id}/cancel", response_model=AgentRunRead, summary="Cancel an agent run")
async def cancel_run(run_id: uuid.UUID, session: SessionDep, principal: Runner) -> AgentRunRead:
    """Queued, it never runs; running, what it delivers is not kept. 403 for
    another's run, unless one may approve; 409 once it ended."""
    try:
        run = await AgentRuntime(session, principal.workspace_id).cancel(
            run_id,
            by=principal.user_id,
            anyones=principal.has(Permission.INTENTION_APPROVE),
        )
    except NotYoursError as error:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.PERMISSION_DENIED,
            "Only who asked it, or who may approve, may cancel a run.",
        ) from error
    except RunFinishedError as error:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "It already ended.") from error
    if run is None:
        raise _missing()
    return run_read(run, principal)
