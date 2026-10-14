"""Agents, run (LEKA-395), over HTTP.

    POST   /agent-runs                  run an agent: 202, queued — or refused,
                                        said why (404, 403, 422)
    GET    /agent-runs?key&status       the workspace's runs, the latest first
    GET    /agent-runs/{id}             one: what it delivered, every step,
                                        what its model calls took
    GET    /agent-runs/{id}/deliverables/{format}
                                        a file LEKA drew of it (the
                                        architect's pptx, pdf): to download
    POST   /agent-runs/{id}/cancel      cancelled — by who asked, or who may
                                        approve
    POST   /agent-runs/{id}/approve     held for approval (LEKA-406): queued
    POST   /agent-runs/{id}/reject      held for approval: cancelled, never run

Running one takes `intention:create`, and whatever the agent's own
permission is: the catalogue says it (`not_permitted`). Reading takes
`intention:read`. The workspace is read from the session, never from the
path or the payload (rule 3).

An approval control (LEKA-406) holds a run of an agent at or above its risk:
202 still, `awaiting_approval`, nothing queued. Who may approve
(`intention:approve`) — never who asked it — approves or rejects it; each
outcome is kept with what the controls did.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    AgentRun,
    AgentRunCreate,
    AgentRunDecision,
    AgentRunDetail,
    AgentRunEventRead,
    AgentRunRead,
    AgentRuntime,
    AgentRunUsage,
    CapabilityRunRepository,
    CodeReviewRead,
    DeliverableRead,
    NotAwaitingError,
    NotYoursError,
    OwnRunError,
    RunFinishedError,
    RunRefusedError,
    capability_resource,
    deliverable_of,
    find,
    queue_run,
    read_deliverable,
    without_block,
)
from leka.capabilities.deliverables import MEDIA_TYPES
from leka.core.errors import ErrorCode, FieldError
from leka.governance import (
    AIControlService,
    Permission,
    Principal,
    Target,
    ai_event,
    audit_as,
    authorize,
    current_actor,
    holding,
    require_permission,
)
from leka.intentions import IntentionRepository
from leka.platform import ObjectNotFoundError

router = APIRouter(prefix="/agent-runs", tags=["capabilities"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Runner = Annotated[Principal, Depends(require_permission(Permission.INTENTION_CREATE))]
Approver = Annotated[Principal, Depends(require_permission(Permission.INTENTION_APPROVE))]
StatusWord = Literal["awaiting_approval", "queued", "running", "succeeded", "failed", "cancelled"]
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


def review_read(detail: Mapping[str, object]) -> CodeReviewRead | None:
    """A code review's deliverable, from what its run kept (review.py)."""
    review = detail.get("review")
    pulls = detail.get("pulls")
    if not isinstance(review, dict) or not isinstance(pulls, list):
        return None
    repository, number = review.get("repository"), review.get("number")
    pull = next(
        (
            p
            for p in pulls
            if isinstance(p, dict)
            and p.get("repository") == repository
            and p.get("number") == number
        ),
        None,
    )
    if pull is None:
        return None
    listed = detail.get("listed")
    others = listed.get(str(repository)) if isinstance(listed, dict) else None
    return CodeReviewRead.model_validate(
        {
            "repository": repository,
            "number": number,
            "verdict": review.get("verdict"),
            "pull": pull,
            "pulls": others if isinstance(others, list) else [pull],
            "comments": review.get("comments") or [],
            "dropped": review.get("dropped") or 0,
        }
    )


def run_read(run: AgentRun, principal: Principal) -> AgentRunRead:
    definition = find(run.key)
    failure = run.detail.get("failure")
    reasons = failure.get("reasons", []) if isinstance(failure, dict) else []
    pending = run.detail.get("pending", [])
    files = run.detail.get("deliverables", [])
    files = files if isinstance(files, list) else []
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
        deliverables=[
            DeliverableRead(
                format=f["format"],
                name=str(f["name"]),
                size=int(f["size"]),
                slides=int(f["slides"]),
            )
            for f in files
            if isinstance(f, dict) and f.get("format") in ("pptx", "pdf")
        ],
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
            resource=capability_resource(capability),
        )
        if not decided.allowed:
            raise ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.PERMISSION_DENIED, decided.message)
    # An approval control covering it holds it until someone approves
    # (LEKA-406).
    actor = current_actor()
    held = (
        holding(
            await AIControlService(session, principal.workspace_id).active(),
            capability.key,
            capability.risk,
            actor,
        )
        if capability is not None
        else None
    )
    runtime = AgentRuntime(session, principal.workspace_id)
    try:
        run = await runtime.start(
            body.key,
            body.inputs,
            by=principal.user_id,
            permissions=frozenset(p.value for p in principal.permissions),
            intention_id=body.intention_id,
            context_id=context_id,
            held_by=held.name if held is not None else None,
        )
    except RunRefusedError as error:
        raise _refused(error) from error
    if held is not None:
        ai_event(
            session,
            principal.workspace_id,
            held,
            "held",
            actor=actor,
            purpose=f"agent:{run.key}",
            ref=run.key,
            run_id=run.id,
            detail={"risk": capability.risk if capability is not None else None},
        )
    audit_as(
        session,
        principal,
        "ai",
        "agent_run.requested",
        target=Target("agent_run", run.id, run.key),
        detail={
            "agent": run.key,
            "version": run.version,
            "inputs": sorted(body.inputs),
            **({"held_by": held.name} if held is not None else {}),
        },
    )
    read = run_read(run, principal)
    # What the worker reads, committed before it hears of it.
    await session.commit()
    if held is None:
        await queue_run(principal.workspace_id, run.id)
    return read


@router.get("", response_model=list[AgentRunRead], summary="The workspace's agent runs")
async def list_runs(
    session: SessionDep,
    principal: Reader,
    key: Annotated[str | None, Query(max_length=100)] = None,
    run_status: Annotated[StatusWord | None, Query(alias="status")] = None,
    intention_id: Annotated[
        uuid.UUID | None, Query(description="An intention's runs: the agents at work on it.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AgentRunRead]:
    runs = await AgentRuntime(session, principal.workspace_id).runs(
        key=key, status=run_status, intention_id=intention_id, limit=limit
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
        report=without_block(run.output) if run.output else None,
        review=review_read(run.detail),
        events=[AgentRunEventRead.model_validate(e) for e in events],
        usage=AgentRunUsage(calls=calls, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost),
    )


@router.get(
    "/{run_id}/deliverables/{fmt}",
    response_class=StreamingResponse,
    summary="A file an agent run delivered: its PowerPoint or its PDF",
    responses={200: {"content": {MEDIA_TYPES["pptx"]: {}, MEDIA_TYPES["pdf"]: {}}}},
)
async def get_deliverable(
    run_id: uuid.UUID, fmt: Literal["pptx", "pdf"], session: SessionDep, principal: Reader
) -> StreamingResponse:
    """What LEKA drew of what the run delivered (the architect's deck), as
    an attachment. 404 when the run, or that file, is not there."""
    run = await CapabilityRunRepository(session, principal.workspace_id).run(run_id)
    if run is None:
        raise _missing()
    found = deliverable_of(run, fmt)
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such file for this run.")
    chunks = read_deliverable(str(found["key"]))
    try:
        first = await anext(chunks)
    except (StopAsyncIteration, ObjectNotFoundError):
        raise ApiError(
            status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "This file is no longer kept."
        ) from None

    async def body() -> AsyncIterator[bytes]:
        yield first
        async for chunk in chunks:
            yield chunk

    name = str(found.get("name") or f"deck.{fmt}")
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    return StreamingResponse(
        body(),
        media_type=MEDIA_TYPES[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(name)}",
            "Cache-Control": "private, no-store",
        },
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
    audit_as(
        session, principal, "ai", "agent_run.cancelled", target=Target("agent_run", run.id, run.key)
    )
    return run_read(run, principal)


async def _decide(
    run_id: uuid.UUID,
    body: AgentRunDecision,
    session: SessionDep,
    principal: Principal,
    *,
    approve: bool,
) -> AgentRunRead:
    try:
        run = await AgentRuntime(session, principal.workspace_id).decide(
            run_id, by=principal.user_id, approve=approve, note=body.note
        )
    except OwnRunError as error:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.PERMISSION_DENIED,
            "Who asked a run does not approve it.",
        ) from error
    except NotAwaitingError as error:
        raise ApiError(
            status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "It is not waiting for approval."
        ) from error
    if run is None:
        raise _missing()
    held_by = run.detail.get("held_by")
    ai_event(
        session,
        principal.workspace_id,
        None,
        "approved" if approve else "rejected",
        kind="approval",
        user_id=principal.user_id,
        purpose=f"agent:{run.key}",
        ref=run.key,
        run_id=run.id,
        detail={
            "control": held_by,
            "requested_by": str(run.requested_by),
            **({"note": body.note} if body.note else {}),
        },
    )
    read = run_read(run, principal)
    await session.commit()
    if approve:
        await queue_run(principal.workspace_id, run.id)
    return read


@router.post(
    "/{run_id}/approve", response_model=AgentRunRead, summary="Approve an agent run held for it"
)
async def approve_run(
    run_id: uuid.UUID,
    session: SessionDep,
    principal: Approver,
    body: AgentRunDecision | None = None,
) -> AgentRunRead:
    """Queued, as if never held. 403 for who asked it; 409 when it is not
    waiting for approval."""
    return await _decide(run_id, body or AgentRunDecision(), session, principal, approve=True)


@router.post(
    "/{run_id}/reject", response_model=AgentRunRead, summary="Reject an agent run held for it"
)
async def reject_run(
    run_id: uuid.UUID,
    session: SessionDep,
    principal: Approver,
    body: AgentRunDecision | None = None,
) -> AgentRunRead:
    """Cancelled, never run. 403 for who asked it; 409 when it is not
    waiting for approval."""
    return await _decide(run_id, body or AgentRunDecision(), session, principal, approve=False)
