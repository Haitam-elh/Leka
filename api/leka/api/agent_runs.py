"""Agents, run (LEKA-395), over HTTP.

    POST   /agent-runs                  run an agent: 202, queued — or refused,
                                        said why (404, 403, 422)
    GET    /agent-runs?key&status       the workspace's runs, the latest first
    GET    /agent-runs/{id}             one: what it delivered, every step,
                                        what its model calls took
    GET    /agent-runs/{id}/deliverables/{format}
                                        a file LEKA drew of it (the
                                        architect's pptx, pdf): to download
    GET    /agent-runs/{id}/design      the screens the designer drew of its
                                        review: today's, then each proposal
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
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import (
    DECK_FILES,
    DRAWING_LOST,
    AgentRun,
    AgentRunCreate,
    AgentRunDecision,
    AgentRunDetail,
    AgentRunEventRead,
    AgentRunFiles,
    AgentRunRead,
    AgentRuntime,
    AgentRunUsage,
    CapabilityRunRepository,
    CodeChange,
    CodeReviewRead,
    DeliverableRead,
    DesignChangeRead,
    DesignCorrection,
    DesignCorrectionRead,
    DesignMockup,
    DesignMockupRead,
    DesignRead,
    DesignSummaryRead,
    NotAwaitingError,
    NotYoursError,
    OwnRunError,
    RunFinishedError,
    RunRefusedError,
    capability_resource,
    deliverable_of,
    find,
    page,
    proposes,
    queue_change,
    queue_correction,
    queue_files,
    queue_redraw,
    queue_run,
    read_deliverable,
    read_design,
    without_block,
    without_mark,
)
from leka.capabilities.definition import Definition
from leka.capabilities.deliverables import MEDIA_TYPES, report_pdf
from leka.capabilities.runtime import DRAWN
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
    said = {str(r["code"]) for r in refusal.reasons}
    # What it pays for, said as such: the screens offer what it takes.
    if "plan_required" in said:
        kind, message = ErrorCode.PLAN_REQUIRED, "Agents run from the Starter plan."
    elif "not_owned" in said:
        kind, message = ErrorCode.AGENT_NOT_OWNED, "This agent is not bought here."
    details = [
        FieldError(field=f"inputs.{r['name']}", message=str(r["code"]))
        if refusal.code == "invalid_input"
        else FieldError(field="key", message=str(r["code"]))
        for r in refusal.reasons
    ]
    return ApiError(code, kind, message, details=details or None)


def design_read(detail: Mapping[str, object]) -> DesignSummaryRead | None:
    """The designer's mock-ups, said in short, when its run kept them."""
    kept = detail.get("design")
    if not isinstance(kept, Mapping):
        return None
    return DesignSummaryRead.model_validate(
        {k: kept.get(k) for k in ("screen", "viewport", "proposals", "recommended")}
    )


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


def _expected(run: AgentRun, definition: Definition | None) -> list[str]:
    """The files a run is to deliver: those asked when it was launched — or,
    launched without saying, every one its agent draws."""
    asked = run.detail.get("formats")
    if isinstance(asked, list):
        return [str(f) for f in asked]
    drawn = DRAWN.get(definition.renders or "", ()) if definition is not None else ()
    return [f for f in drawn if f in ("pdf", "pptx")]


def _drawable(run: AgentRun, definition: Definition | None, files: list[object]) -> list[str]:
    """Finished, the files its agent draws that it does not have."""
    if run.status != "succeeded" or not run.output or definition is None:
        return []
    if definition.renders != "architecture_deck":
        return []
    have = {f.get("format") for f in files if isinstance(f, dict)}
    return [f for f in DECK_FILES if f not in have]


def _designable(run: AgentRun, definition: Definition | None) -> list[str]:
    """A finished design review whose review proposes a design it did not
    draw: « design », to draw on asking (POST /agent-runs/{id}/design) —
    whatever left it undrawn, its mark forgotten included."""
    if (
        run.status != "succeeded"
        or not run.output
        or definition is None
        or definition.renders != "design_mockups"
        or run.detail.get("design")
    ):
        return []
    return ["design"] if proposes(run.output) else []


def _corrections(run: AgentRun) -> list[DesignCorrectionRead]:
    """The corrections asked of its mock-ups, the latest last."""
    had = run.detail.get("corrections")
    return [
        DesignCorrectionRead.model_validate(h)
        for h in (had if isinstance(had, list) else [])
        if isinstance(h, dict)
    ]


def _correcting(run: AgentRun, now: datetime | None = None) -> str | None:
    """The mock-up a worker is correcting — none once asked so long ago it
    is lost (a worker gone)."""
    asked = run.detail.get("correcting")
    if not isinstance(asked, dict):
        return None
    try:
        since = datetime.fromisoformat(str(asked.get("since")))
    except ValueError:
        return None
    if (now or datetime.now(UTC)) - since > DRAWING_LOST:
        return None
    return str(asked.get("target") or "") or None


def _drawing(run: AgentRun, now: datetime | None = None) -> list[str]:
    """The files a worker is drawing — none once asked so long ago it is
    lost (a worker gone): asked again."""
    drawing = run.detail.get("drawing")
    if not isinstance(drawing, list) or not drawing:
        return []
    since = run.detail.get("drawing_since")
    try:
        asked = datetime.fromisoformat(str(since)) if since else None
    except ValueError:
        asked = None
    if asked is None or (now or datetime.now(UTC)) - asked > DRAWING_LOST:
        return []
    return [str(f) for f in drawing]


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
        expected=_expected(run, definition),
        drawable=_drawable(run, definition, files) + _designable(run, definition),
        drawing=_drawing(run),
        draw_failed=str(failed) if (failed := run.detail.get("deliverables_error")) else None,
        draw_said=str(said)[:300] if (said := run.detail.get("deliverables_said")) else None,
        correcting=_correcting(run),
        correction_failed=str(c) if (c := run.detail.get("correction_failed")) else None,
        correction_said=str(c)[:300] if (c := run.detail.get("correction_said")) else None,
        corrections=_corrections(run),
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
        report=without_mark(without_block(run.output)) if run.output else None,
        review=review_read(run.detail),
        design=design_read(run.detail),
        events=[AgentRunEventRead.model_validate(e) for e in events],
        usage=AgentRunUsage(calls=calls, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost),
    )


@router.get(
    "/{run_id}/report.pdf",
    response_class=StreamingResponse,
    summary="Any agent's deliverable as a PDF",
    responses={200: {"content": {MEDIA_TYPES["pdf"]: {}}}},
)
async def get_report_pdf(
    run_id: uuid.UUID, session: SessionDep, principal: Reader
) -> StreamingResponse:
    """What the agent delivered, laid out as a PDF (Karim, 2026-10-23: « un
    vrai livrable ») — drawn from the report it kept, never stored. 404 when
    the run is not there or delivered nothing yet."""
    run = await CapabilityRunRepository(session, principal.workspace_id).run(run_id)
    if run is None:
        raise _missing()
    if run.status != "succeeded" or not run.output:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "Nothing delivered yet.")
    definition = find(run.key)
    agent = definition.title if definition is not None else run.key
    intention = (
        await IntentionRepository(session, principal.workspace_id).intention(run.intention_id)
        if run.intention_id is not None
        else None
    )
    title = intention.title if intention is not None else agent
    drawn = report_pdf(
        title=title,
        agent=agent,
        when=run.finished_at,
        markdown=without_mark(without_block(run.output)),
    )
    name = f"{agent} — {run.finished_at:%Y-%m-%d}.pdf" if run.finished_at else f"{agent}.pdf"
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")

    async def body() -> AsyncIterator[bytes]:
        yield drawn

    return StreamingResponse(
        body(),
        media_type=MEDIA_TYPES["pdf"],
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(name)}",
            "Cache-Control": "private, no-store",
        },
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


@router.get(
    "/{run_id}/design",
    response_model=DesignRead,
    summary="The screens the designer drew of its review: today's, then each proposal",
)
async def get_design(run_id: uuid.UUID, session: SessionDep, principal: Reader) -> DesignRead:
    """Each mock-up as the page to show — sandboxed, it runs nothing and
    reaches nothing (capabilities/deliverables/design.py). 404 when the run,
    or its mock-ups, are not there."""
    run = await CapabilityRunRepository(session, principal.workspace_id).run(run_id)
    if run is None:
        raise _missing()
    found = await read_design(run)
    if found is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "This run drew no screen.")

    def shown(mockup: DesignMockup) -> DesignMockupRead:
        return DesignMockupRead(
            name=mockup.name,
            axis=mockup.axis,
            when=mockup.when,
            cost=mockup.cost,
            page=page(mockup),
        )

    return DesignRead(
        screen=found.screen,
        viewport=found.viewport,
        before=shown(found.before),
        after=[shown(m) for m in found.after],
        recommended=found.recommended,
        why=found.why,
        changes=[DesignChangeRead.model_validate(c.model_dump()) for c in found.changes],
    )


@router.post(
    "/{run_id}/files",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Draw a finished run's files",
)
async def draw_run_files(
    run_id: uuid.UUID, body: AgentRunFiles, session: SessionDep, principal: Runner
) -> AgentRunRead:
    """Its deck drawn as PDF or PowerPoint from the analysis it delivered —
    the run never done again (2026-10-16: launched without asking, the
    architect gave its report alone). 202, a worker draws it; 409 when it
    is not finished, or is being drawn; 422 when its agent draws no file."""
    run = await CapabilityRunRepository(session, principal.workspace_id).run(run_id, lock=True)
    if run is None:
        raise _missing()
    definition = find(run.key)
    files = run.detail.get("deliverables", [])
    if run.status != "succeeded" or not run.output:
        raise ApiError(
            status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "Its analysis is not delivered yet."
        )
    if not _drawable(run, definition, files if isinstance(files, list) else []):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            "This agent draws no more file.",
            details=[FieldError(field="formats", message="not_drawn")],
        )
    if _drawing(run):
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "Its files are being drawn.")
    wanted = [f for f in dict.fromkeys(body.formats) if f in DECK_FILES]
    run.detail = {
        **{
            k: v
            for k, v in run.detail.items()
            if k not in ("deliverables_error", "deliverables_said")
        },
        "drawing": wanted,
        "drawing_since": datetime.now(UTC).isoformat(),
    }
    audit_as(
        session,
        principal,
        "ai",
        "agent_run.files_asked",
        target=Target("agent_run", run.id, run.key),
        detail={"formats": wanted},
    )
    await session.commit()
    await queue_files(principal.workspace_id, run.id, wanted)
    return run_read(run, principal)


async def _moved_change(session: SessionDep, run: AgentRun) -> CodeChange | None:
    """Its change, when still proposed and refused because its branch moved
    where it changes."""
    said = run.detail.get("code_change")
    try:
        change = await session.get(CodeChange, uuid.UUID(str(said))) if said else None
    except ValueError:
        return None
    if (
        change is None
        or change.workspace_id != run.workspace_id
        or change.status != "proposed"
        or change.error != "changed_since"
    ):
        return None
    return change


@router.post(
    "/{run_id}/change",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Write a finished run's code change again",
)
async def rewrite_run_change(
    run_id: uuid.UUID, session: SessionDep, principal: Runner
) -> AgentRunRead:
    """Its change written again from the analysis it delivered and the files
    it read, read again — the run never done again (2026-10-18: its change
    was not written, the analysis alone shown). 202, a worker writes it;
    409 when it is not finished, already has its change, or is being
    written; 422 when its agent proposes no code change. A change refused
    because its branch moved where it changes (`changed_since`) is written
    again on the branch as it is now, the old one failed (2026-10-20)."""
    run = await CapabilityRunRepository(session, principal.workspace_id).run(run_id, lock=True)
    if run is None:
        raise _missing()
    definition = find(run.key)
    if definition is None or definition.renders != "code_change":
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            "This agent proposes no code change.",
            details=[FieldError(field="run_id", message="not_a_change")],
        )
    if run.status != "succeeded" or not run.output:
        raise ApiError(
            status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "Its analysis is not delivered yet."
        )
    moved = await _moved_change(session, run)
    if run.detail.get("code_change") and moved is None:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "Its change is there.")
    if _drawing(run):
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "Its change is being written.")
    if moved is not None:
        moved.status = "failed"
    run.detail = {
        **{
            k: v
            for k, v in run.detail.items()
            if k not in ("deliverables_error", "deliverables_said", "code_change")
        },
        "drawing": ["change"],
        "drawing_since": datetime.now(UTC).isoformat(),
    }
    audit_as(
        session,
        principal,
        "ai",
        "agent_run.change_asked",
        target=Target("agent_run", run.id, run.key),
        detail={},
    )
    await session.commit()
    await queue_change(principal.workspace_id, run.id)
    return run_read(run, principal)


@router.post(
    "/{run_id}/design",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Draw a finished design review's mock-ups again",
)
async def redraw_run_design(
    run_id: uuid.UUID, session: SessionDep, principal: Runner
) -> AgentRunRead:
    """Its mock-ups drawn again from the review it delivered — the run never
    done again (2026-10-18: a review came alone, its mock-ups not drawn).
    202, a worker draws them; 409 when it is not finished, already has
    them, or they are being drawn; 422 when its agent draws none."""
    run = await CapabilityRunRepository(session, principal.workspace_id).run(run_id, lock=True)
    if run is None:
        raise _missing()
    definition = find(run.key)
    if definition is None or definition.renders != "design_mockups":
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            "This agent draws no mock-up.",
            details=[FieldError(field="run_id", message="not_a_design")],
        )
    if run.status != "succeeded" or not run.output:
        raise ApiError(
            status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "Its review is not delivered yet."
        )
    if run.detail.get("design"):
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "Its mock-ups are there.")
    if _drawing(run):
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "They are being drawn.")
    run.detail = {
        **{
            k: v
            for k, v in run.detail.items()
            if k not in ("deliverables_error", "deliverables_said")
        },
        "drawing": ["design"],
        "drawing_since": datetime.now(UTC).isoformat(),
    }
    audit_as(
        session,
        principal,
        "ai",
        "agent_run.design_asked",
        target=Target("agent_run", run.id, run.key),
        detail={},
    )
    await session.commit()
    await queue_redraw(principal.workspace_id, run.id, "design_mockups")
    return run_read(run, principal)


@router.post(
    "/{run_id}/design/corrections",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Correct one of a design review's mock-ups, as asked",
)
async def correct_run_design(
    run_id: uuid.UUID, body: DesignCorrection, session: SessionDep, principal: Runner
) -> AgentRunRead:
    """One mock-up — today's or a proposal — drawn again as asked, the rest
    as it was (2026-10-19, Karim: « lui demander de corriger certaines
    parties de l'écran depuis la proposition »). 202, a worker draws it; 409
    when it has no mock-up yet or one is being corrected; 422 when there is
    no such mock-up."""
    run = await CapabilityRunRepository(session, principal.workspace_id).run(run_id, lock=True)
    if run is None:
        raise _missing()
    kept = run.detail.get("design")
    if not isinstance(kept, dict):
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "It has no mock-up yet.")
    proposals = kept.get("proposals")
    count = len(proposals) if isinstance(proposals, list) else 0
    if body.target != "before" and int(body.target) >= count:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            "No such mock-up.",
            details=[FieldError(field="target", message="not_found")],
        )
    if _correcting(run):
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "One is being corrected.")
    note = body.note.strip()
    run.detail = {
        **run.detail,
        "correcting": {"target": body.target, "since": datetime.now(UTC).isoformat()},
        "correction_failed": None,
        "correction_said": None,
    }
    audit_as(
        session,
        principal,
        "ai",
        "agent_run.design_correction_asked",
        target=Target("agent_run", run.id, run.key),
        detail={"target": body.target},
    )
    await session.commit()
    await queue_correction(principal.workspace_id, run.id, body.target, note)
    return run_read(run, principal)


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
