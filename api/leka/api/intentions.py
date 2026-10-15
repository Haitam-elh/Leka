"""Intentions, approvals, and the actions that follow (LEKA-384).

    POST   /intentions                   ask: the intention kept and its
                                         context assembled (LEKA-373) — 422
                                         when nothing can start it — and
                                         understood (LEKA-385)
    POST   /intentions/understand        what LEKA would understand of these
                                         words; nothing kept
    GET    /intentions                   the intentions, the latest changed
                                         first — by phase (active, scheduled,
                                         finished, archived), status, mine,
                                         words, what they are linked to
    GET    /intentions/counts            how many by phase, for the tabs
    GET    /intentions/{id}              one, with what it is linked to and
                                         where it may go next
    GET    /intentions/{id}/history      everything that happened to it
    GET    /intentions/{id}/context      its context (LEKA-387): the context
                                         engine's contract, and whether it
                                         can ground an analysis
    GET    /intentions/{id}/analysis     its latest analysis (LEKA-388): the
                                         capabilities chosen and why, what
                                         each did, the result and its
                                         evidence — 404 before any
    GET    /intentions/{id}/analyses     every analysis, the latest first
    POST   /intentions/{id}/analyse      analysed again — retried, failed
    POST   /intentions/{id}/ask          asked again: its context made again
    POST   /intentions/{id}/cancel       withdrawn
    POST   /intentions/{id}/archive, /restore
    POST   /intentions/{id}/links        linked to a context, a finding, an
                                         entity
    DELETE /intentions/{id}/links/{link_id}

Read by every member (`intention:read`); asking, and handling what one
asked, is `intention:create` — handling another's intention is its asker's
or an approver's (`intention:approve`), else 403. A move the lifecycle does
not allow is 409. Deciding — approving, rejecting — is LEKA-390's.

A route validates, calls one service, and returns (architecture rule 6).
Permissions come from a FastAPI dependency, never an `if` in the body
(rule 5). The workspace is read from the session, never from the path or the
payload (rule 3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.capabilities import CapabilityRouter, RoutingRead, routing_read
from leka.connectors import SourceRepository
from leka.context import (
    ContextArchivedError,
    ContextRefusedError,
    ContextRepository,
    ContextService,
)
from leka.core.errors import ErrorCode, FieldError
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission
from leka.ingestion import ContentRepository, ResolutionRepository
from leka.intelligence import IntelligenceRepository
from leka.intentions import (
    Actor,
    AgentsLaunchRequest,
    FeasibilityRead,
    IllegalTransitionError,
    Intention,
    IntentionAnalysisRead,
    IntentionAnalysisRequested,
    IntentionAnswers,
    IntentionArchivedError,
    IntentionAsked,
    IntentionContext,
    IntentionCounts,
    IntentionCreated,
    IntentionDetail,
    IntentionEventRead,
    IntentionFilters,
    IntentionLinkCreate,
    IntentionLinkRead,
    IntentionPreview,
    IntentionRead,
    IntentionRepository,
    IntentionRequest,
    IntentionService,
    IntentionStatus,
    LinkRefusedError,
    ModelReading,
    NothingToStartError,
    NotYoursError,
    OffTopicError,
    SourceToReadRead,
    Understanding,
    Withdrawal,
    queue_analysis,
    route_intention,
)
from leka.intentions import agents as agent_steps
from leka.intentions.brief import brief_of, tidy
from leka.intentions.feasibility import Feasibility, feasibility_of
from leka.knowledge import GraphRepository, GraphService

router = APIRouter(prefix="/intentions", tags=["intentions"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Asker = Annotated[Principal, Depends(require_permission(Permission.INTENTION_CREATE))]

SORTS = SortCatalogue(
    fields=(
        SortableField("updated_at", Intention.updated_at, "ix_intentions_workspace_updated"),
        SortableField("created_at", Intention.created_at, "a workspace's intentions: hundreds"),
    ),
    default="updated_at",
)
NOTHING = (
    "Nothing to start from: the intention names nothing in the company model and says no word "
    "to search."
)


def _service(session: SessionDep, principal: Principal) -> IntentionService:
    workspace = principal.workspace_id
    return IntentionService(
        IntentionRepository(session, workspace),
        contexts=ContextService(
            ContextRepository(session, workspace),
            GraphService(GraphRepository(session, workspace)),
            content=ContentRepository(session, workspace),
            resolution=ResolutionRepository(session, workspace),
            sources=SourceRepository(session, workspace),
        ),
        context_repository=ContextRepository(session, workspace),
        findings=IntelligenceRepository(session, workspace),
        entities=GraphRepository(session, workspace),
        # A model reads it with the rules, when one can (LEKA-394).
        reading=ModelReading(session, workspace),
    )


def _reading(session: SessionDep, principal: Reader) -> IntentionService:
    return _service(session, principal)


def _asking(session: SessionDep, principal: Asker) -> IntentionService:
    return _service(session, principal)


Reading = Annotated[IntentionService, Depends(_reading)]
Asking = Annotated[IntentionService, Depends(_asking)]


def _missing() -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such intention.")


def _steward(principal: Principal) -> bool:
    """May handle anyone's intention: who may approve."""
    return principal.has(Permission.INTENTION_APPROVE)


def _refused(error: Exception) -> ApiError:
    """What the lifecycle, the archive or the asker refuses, as an answer."""
    if isinstance(error, NotYoursError):
        return ApiError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.PERMISSION_DENIED,
            "Only who asked it, or who may approve, may do this.",
        )
    if isinstance(error, IntentionArchivedError | ContextArchivedError):
        return ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, "Archived: restore it first.")
    if isinstance(error, OffTopicError):
        return ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.OFF_TOPIC,
            "LEKA answers questions about your technology stack.",
        )
    if isinstance(error, NothingToStartError | ContextRefusedError):
        return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, NOTHING)
    if isinstance(error, LinkRefusedError):
        return ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            "Nothing of that kind and id in this workspace — or the context it is analysed "
            "from, which stays linked.",
        )
    return ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, str(error))


REFUSED = (
    IllegalTransitionError,
    IntentionArchivedError,
    ContextArchivedError,
    NothingToStartError,
    OffTopicError,
    ContextRefusedError,
    NotYoursError,
    LinkRefusedError,
)


@router.post("", response_model=IntentionCreated, status_code=status.HTTP_201_CREATED)
async def create(
    body: IntentionRequest,
    service: Asking,
    principal: Asker,
    session: SessionDep,
    request_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            max_length=100,
            description="The same key sent again — a click twice, a request retried — answers "
            "the intention it made, never a second one (LEKA-443).",
        ),
    ] = None,
) -> IntentionCreated:
    """Ask LEKA: the intention kept — submitted, then analysing — and the
    context it asks for assembled, its subject the intention (LEKA-373).
    `intention_id` in the body is ignored: it is the new intention's. 422
    when nothing can start it — and nothing is kept. Analysing, its
    analysis is queued (LEKA-388). `answers`: what its asker answered to
    LEKA's questions before asking (LEKA-439), kept and read with it."""
    try:
        if request_key:
            replayed = await service.replayed(principal.user_id, request_key)
            if replayed is not None:
                return IntentionCreated(
                    intention=await service.detail_now(replayed[0]), context=replayed[1]
                )
        intention, context = await service.create(
            body, by=principal.user_id, request_key=request_key or None
        )
    except REFUSED as error:
        raise _refused(error) from error
    created = IntentionCreated(intention=await service.detail_now(intention), context=context)
    await _analyse(session, principal, intention, trigger="created")
    return created


async def _analyse(
    session: SessionDep, principal: Principal, intention: Intention, *, trigger: str
) -> None:
    """Its analysis queued, once what it reads is committed (LEKA-388)."""
    if intention.status != IntentionStatus.ANALYSING.value:
        return
    await session.commit()
    await queue_analysis(
        principal.workspace_id, intention.id, trigger=trigger, by=principal.user_id
    )


@router.post("/understand", response_model=Understanding)
async def understand(body: IntentionRequest, service: Asking) -> Understanding:
    """What LEKA would understand of these words (LEKA-385) — its goal,
    whether it asks or requests, the actions, the things it is about, what
    is ambiguous, each with the words it came from. Nothing is kept."""
    return await service.understand(body)


def feasibility_read(found: Feasibility) -> FeasibilityRead:
    return FeasibilityRead.model_validate(
        {
            "verdict": found.verdict,
            "needed": [
                {**n.__dict__, "reasons": [dict(r) for r in n.reasons]} for n in found.needed
            ],
            "credits": found.credits,
            "estimate": found.estimate,
            "path": [
                {"kind": step.kind, "detail": dict(step.detail), "consent": step.consent}
                for step in found.path
            ],
        }
    )


async def _sources(
    session: SessionDep, workspace_id: uuid.UUID, chosen: list[uuid.UUID]
) -> list[SourceToReadRead]:
    """What LEKA would read: the sources chosen, else every one it can."""
    rows = await session.scalars(SourceRepository(session, workspace_id).list_statement())
    return [
        SourceToReadRead(id=s.id, name=s.name, kind=s.kind.value, status=s.status.value)
        for s in rows.all()
        if (s.id in chosen if chosen else s.status.value in ("active", "degraded"))
    ]


@router.post("/brief", response_model=IntentionPreview)
async def brief(
    body: IntentionRequest, service: Asking, principal: Asker, session: SessionDep
) -> IntentionPreview:
    """Before it is asked (LEKA-439): what LEKA understood, its brief — each
    part of what it must know, its questions, what follows (analyse,
    clarify, continue with its limits, block) — what it would read, and
    what it takes to carry it through here: the capabilities, the credits,
    the least it takes. Nothing is kept."""
    try:
        understood, _plan = await service.read(body)
    except REFUSED as error:
        raise _refused(error) from error
    briefed = brief_of(understood, tidy(body.answers))
    found = await feasibility_of(
        session,
        principal.workspace_id,
        understood,
        briefed,
        permissions=frozenset(p.value for p in principal.permissions),
        now=datetime.now(UTC),
    )
    return IntentionPreview(
        understanding=understood,
        brief=briefed,
        sources=await _sources(session, principal.workspace_id, list(body.sources)),
        feasibility=feasibility_read(found),
    )


@router.get("", response_model=PageEnvelope[IntentionRead])
async def intentions(
    session: SessionDep,
    service: Reading,
    principal: Reader,
    page: PageParams,
    phase: Annotated[
        Literal["active", "scheduled", "finished", "archived"] | None,
        Query(description="Every one not archived when none."),
    ] = None,
    state: Annotated[IntentionStatus | None, Query(alias="status")] = None,
    mine: Annotated[bool, Query(description="Those I asked.")] = False,
    q: Annotated[str | None, Query(max_length=200, description="In its title or words.")] = None,
    linked: Annotated[
        uuid.UUID | None, Query(description="Linked to this context, finding or entity.")
    ] = None,
    agent: Annotated[
        str | None, Query(max_length=100, description="An agent ran for it: its key.")
    ] = None,
    source: Annotated[
        uuid.UUID | None, Query(description="Asked about this source, or its analyses cite it.")
    ] = None,
    since: Annotated[datetime | None, Query(description="Asked at or after.")] = None,
    until: Annotated[datetime | None, Query(description="Asked before.")] = None,
) -> PageEnvelope[IntentionRead]:
    """The intentions, the latest changed first (`sort=updated_at`) or the
    latest asked (`sort=created_at`)."""
    statement = IntentionRepository(session, principal.workspace_id).intentions(
        IntentionFilters(
            phase=phase,
            status=state.value if state else None,
            created_by=principal.user_id if mine else None,
            words=q,
            linked=linked,
            agent=agent,
            source=source,
            since=since,
            until=until,
        )
    )
    result = await serve_page(
        session, statement, request=page, catalogue=SORTS, id_column=Intention.id
    )
    return PageEnvelope(data=await service.reads(result.items), next_cursor=result.next_cursor)


@router.get("/counts", response_model=IntentionCounts)
async def counts(
    service: Reading, principal: Reader, mine: Annotated[bool, Query()] = False
) -> IntentionCounts:
    """How many active, scheduled, finished, archived — mockup 07's tabs."""
    return await service.counts(created_by=principal.user_id if mine else None)


@router.get("/{intention_id}", response_model=IntentionDetail)
async def intention(
    intention_id: uuid.UUID, service: Reading, session: SessionDep, principal: Reader
) -> IntentionDetail:
    """One intention: where it stands, where it may go next, what it is
    linked to. Its agents all ended: settled first — verified or failed —
    never left executing (2026-10-14)."""
    if await agent_steps.settle(session, principal.workspace_id, intention_id):
        await session.commit()
    found = await service.detail(intention_id)
    if found is None:
        raise _missing()
    return found


@router.get("/{intention_id}/history", response_model=list[IntentionEventRead])
async def history(intention_id: uuid.UUID, service: Reading) -> list[IntentionEventRead]:
    """Everything that happened to it, in order: who — a person, or LEKA —
    when, from where to where, why. Never rewritten."""
    found = await service.history(intention_id)
    if found is None:
        raise _missing()
    return found


@router.get("/{intention_id}/context", response_model=IntentionContext)
async def context(
    intention_id: uuid.UUID,
    service: Reading,
    version: Annotated[int | None, Query(ge=1, description="Its latest when none.")] = None,
) -> IntentionContext:
    """Its context, as downstream capabilities read it (LEKA-387): the
    context engine's contract — every element with its provenance, the
    quality and confidence, the gaps and conflicts — and whether it can
    ground an analysis: ready, limited, blocked by what."""
    found = await service.context(intention_id, version=version)
    if found is None:
        raise _missing()
    assembled, ready = found
    return IntentionContext(context=assembled, readiness=ready)


@router.get("/{intention_id}/routing", response_model=RoutingRead)
async def routing(intention_id: uuid.UUID, session: SessionDep, principal: Reader) -> RoutingRead:
    """Where it was last routed, and why (LEKA-398): every capability it
    could go to, ranked by its signals; every one it cannot, said why; or
    LEKA's own analysis, or what to ask. Never routed yet: routed now, for
    whoever reads it."""
    found = await CapabilityRouter(session, principal.workspace_id).latest(intention_id)
    if found is None:
        found = await route_intention(
            session,
            principal.workspace_id,
            intention_id,
            permissions=frozenset(p.value for p in principal.permissions),
            by=principal.user_id,
        )
    if found is None:
        raise _missing()
    return routing_read(found)


@router.post("/{intention_id}/routing", response_model=RoutingRead)
async def route_again(
    intention_id: uuid.UUID, session: SessionDep, principal: Asker
) -> RoutingRead:
    """Routed again, as it and the catalogue now stand — a source connected,
    a capability turned on — for this person; kept beside the earlier."""
    found = await route_intention(
        session,
        principal.workspace_id,
        intention_id,
        permissions=frozenset(p.value for p in principal.permissions),
        by=principal.user_id,
    )
    if found is None:
        raise _missing()
    return routing_read(found)


@router.post("/{intention_id}/ask", response_model=IntentionAsked)
async def ask_again(
    intention_id: uuid.UUID,
    body: IntentionRequest,
    service: Asking,
    principal: Asker,
    session: SessionDep,
) -> IntentionAsked:
    """Asked again, its words or scope as they now stand: its context made
    again — a new version that says what LEKA reads differently (LEKA-374)
    — and analysed again. 409 when cancelled, archived, or while its actions
    run."""
    try:
        found = await service.ask_again(
            intention_id, body, by=principal.user_id, steward=_steward(principal)
        )
    except REFUSED as error:
        raise _refused(error) from error
    if found is None:
        raise _missing()
    intention, context = found
    asked = IntentionAsked(intention=await service.detail_now(intention), context=context)
    await _analyse(session, principal, intention, trigger="asked_again")
    return asked


@router.post("/{intention_id}/answers", response_model=IntentionAsked)
async def answer(
    intention_id: uuid.UUID,
    body: IntentionAnswers,
    service: Asking,
    principal: Asker,
    session: SessionDep,
) -> IntentionAsked:
    """What its asker answers to LEKA's questions (LEKA-439) — a choice,
    their words, « je ne sais pas » — kept with what they answered before,
    the latest for each: it is asked again with them, its words and scope as
    they are; analysing, its analysis queued. 409 when cancelled, archived,
    or while its actions run."""
    try:
        found = await service.answer(
            intention_id, body.answers, by=principal.user_id, steward=_steward(principal)
        )
    except REFUSED as error:
        raise _refused(error) from error
    if found is None:
        raise _missing()
    intention, context = found
    asked = IntentionAsked(intention=await service.detail_now(intention), context=context)
    await _analyse(session, principal, intention, trigger="asked_again")
    return asked


@router.get("/{intention_id}/feasibility", response_model=FeasibilityRead)
async def feasibility(
    intention_id: uuid.UUID, service: Asking, principal: Reader, session: SessionDep
) -> FeasibilityRead:
    """What it takes to carry it through here, now (LEKA-439): the
    capabilities it needs and how each is offered — included, beta, add-on,
    planned — whether each is usable, the credits left and what it should
    cost, and the least it takes when it cannot."""
    detail = await service.detail(intention_id)
    if detail is None or detail.understanding is None or detail.brief is None:
        raise _missing()
    found = await feasibility_of(
        session,
        principal.workspace_id,
        detail.understanding,
        detail.brief,
        permissions=frozenset(p.value for p in principal.permissions),
        now=datetime.now(UTC),
    )
    return feasibility_read(found)


@router.post("/{intention_id}/cancel", response_model=IntentionDetail)
async def cancel(
    intention_id: uuid.UUID, body: Withdrawal, service: Asking, principal: Asker
) -> IntentionDetail:
    """Withdrawn, with a reason if one is given. 409 once closed, or while
    its actions run."""
    try:
        found = await service.cancel(
            intention_id, by=principal.user_id, steward=_steward(principal), reason=body.reason
        )
    except REFUSED as error:
        raise _refused(error) from error
    if found is None:
        raise _missing()
    return await service.detail_now(found)


@router.post("/{intention_id}/stop", response_model=IntentionDetail)
async def stop(intention_id: uuid.UUID, service: Asking, principal: Asker) -> IntentionDetail:
    """« Arrêter l'analyse » (LEKA-443): its analysis stopped — the intention
    kept, ready to analyse again (POST …/analyse resumes it); what the
    analysis running finds is kept, never its result. Stopped twice, the
    same. 409 when it is not being analysed."""
    try:
        found = await service.stop(intention_id, by=principal.user_id, steward=_steward(principal))
    except REFUSED as error:
        raise _refused(error) from error
    if found is None:
        raise _missing()
    return await service.detail_now(found)


def _not_launched(error: agent_steps.AgentsRefusedError) -> ApiError:
    """Why its agents are not launched, in words a screen can act on."""
    agent = str(error.detail.get("agent") or "")
    if error.code == "unavailable":
        codes = [str(r) for r in error.detail.get("reasons") or []]  # type: ignore[attr-defined]
        if "plan_required" in codes:
            return ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                ErrorCode.PLAN_REQUIRED,
                f"{agent} runs from the Starter plan.",
            )
        if "not_owned" in codes:
            return ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                ErrorCode.AGENT_NOT_OWNED,
                f"{agent} is not bought here.",
            )
        reasons = ", ".join(codes)
        return ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.AGENT_UNAVAILABLE,
            f"{agent} cannot run here: {reasons}.",
        )
    if error.code == "missing_inputs":
        missing = [str(m) for m in error.detail.get("missing") or []]  # type: ignore[attr-defined]
        return ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.AGENT_INPUTS_MISSING,
            f"{agent} needs: {', '.join(missing)}.",
            details=[
                FieldError(field=f"agents.{agent}.inputs.{name}", message="missing")
                for name in missing
            ],
        )
    if error.code == "credits":
        return ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.CREDITS_SHORT,
            "This month's credits are short of what these agents take.",
        )
    if error.code in ("not_proposed", "unknown_agent"):
        return ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.AGENT_NOT_PROPOSED,
            "Only the agents its analysis proposed are launched from it.",
        )
    return ApiError(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.VALIDATION_FAILED,
        f"Its agents cannot be launched: {error.code}.",
    )


@router.post("/{intention_id}/agents", response_model=IntentionDetail)
async def launch_agents(
    intention_id: uuid.UUID,
    body: AgentsLaunchRequest,
    service: Asking,
    principal: Asker,
    session: SessionDep,
) -> IntentionDetail:
    """« Lancer avec ces agents » (2026-10-14): the agents its analysis
    proposed that a person chose, started on it — never by LEKA alone — with
    the inputs they completed and only the files they asked for. Approved,
    then executing. 422 when one cannot run here, lacks an input, or the
    credits are short — nothing started; 409 when it cannot be decided."""
    try:
        launched = await agent_steps.launch(
            session,
            principal.workspace_id,
            intention_id,
            [agent_steps.Chosen(a.key, a.inputs, a.formats, a.sources) for a in body.agents],
            by=principal.user_id,
            steward=_steward(principal),
        )
    except agent_steps.AgentsRefusedError as error:
        raise _not_launched(error) from error
    except REFUSED as error:
        raise _refused(error) from error
    if launched is None:
        raise _missing()
    found, runs = launched
    await session.commit()
    await agent_steps.queue_all(principal.workspace_id, runs)
    return await service.detail_now(found)


@router.post("/{intention_id}/by-hand", response_model=IntentionDetail)
async def by_hand(
    intention_id: uuid.UUID, service: Asking, principal: Asker, session: SessionDep
) -> IntentionDetail:
    """« Je le fais moi-même » (2026-10-14): its asker does the work with the
    plan in hand — done, nothing for LEKA to run. 409 when it cannot be
    decided."""
    try:
        found = await agent_steps.by_hand(
            session,
            principal.workspace_id,
            intention_id,
            by=principal.user_id,
            steward=_steward(principal),
        )
    except REFUSED as error:
        raise _refused(error) from error
    if found is None:
        raise _missing()
    await session.commit()
    return await service.detail_now(found)


@router.post("/{intention_id}/agents/retry", response_model=IntentionDetail)
async def retry_agents(
    intention_id: uuid.UUID, service: Asking, principal: Asker, session: SessionDep
) -> IntentionDetail:
    """« Relancer »: the agents that failed, launched again with what they
    were given — those that delivered kept. 409 unless its agents failed."""
    try:
        launched = await agent_steps.retry(
            session,
            principal.workspace_id,
            intention_id,
            by=principal.user_id,
            steward=_steward(principal),
        )
    except agent_steps.AgentsRefusedError as error:
        raise _not_launched(error) from error
    except REFUSED as error:
        raise _refused(error) from error
    if launched is None:
        raise _missing()
    found, runs = launched
    await session.commit()
    await agent_steps.queue_all(principal.workspace_id, runs)
    return await service.detail_now(found)


@router.post("/{intention_id}/archive", response_model=IntentionDetail)
async def archive(intention_id: uuid.UUID, service: Asking, principal: Asker) -> IntentionDetail:
    """Set aside, once done with — completed, rejected, cancelled; 409
    otherwise. Its history is kept."""
    try:
        found = await service.archive(
            intention_id, by=principal.user_id, steward=_steward(principal)
        )
    except REFUSED as error:
        raise _refused(error) from error
    if found is None:
        raise _missing()
    return await service.detail_now(found)


@router.post("/{intention_id}/restore", response_model=IntentionDetail)
async def restore(intention_id: uuid.UUID, service: Asking, principal: Asker) -> IntentionDetail:
    try:
        found = await service.restore(
            intention_id, by=principal.user_id, steward=_steward(principal)
        )
    except REFUSED as error:
        raise _refused(error) from error
    if found is None:
        raise _missing()
    return await service.detail_now(found)


@router.post(
    "/{intention_id}/links", response_model=IntentionLinkRead, status_code=status.HTTP_201_CREATED
)
async def link(
    intention_id: uuid.UUID, body: IntentionLinkCreate, service: Asking, principal: Asker
) -> IntentionLinkRead:
    """Linked to a context, a finding or an entity of this workspace —
    named as it is now, so the link says it when it is gone. Linked twice,
    the same link. 422 when there is no such thing."""
    try:
        found = await service.link(
            intention_id,
            body.kind,
            body.ref_id,
            actor=Actor.PERSON,
            by=principal.user_id,
            steward=_steward(principal),
        )
    except REFUSED as error:
        raise _refused(error) from error
    if found is None:
        raise _missing()
    return IntentionLinkRead.model_validate(found)


@router.delete("/{intention_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink(
    intention_id: uuid.UUID, link_id: uuid.UUID, service: Asking, principal: Asker
) -> None:
    """A link undone — never its context's: it is analysed from it (422)."""
    try:
        done = await service.unlink(
            intention_id, link_id, by=principal.user_id, steward=_steward(principal)
        )
    except REFUSED as error:
        raise _refused(error) from error
    if not done:
        raise _missing()


# ── its analysis (LEKA-388) ─────────────────────────────────────────────────

MAX_ANALYSES = 50


@router.get("/{intention_id}/analyses", response_model=list[IntentionAnalysisRead])
async def analyses(
    intention_id: uuid.UUID,
    service: Reading,
    limit: Annotated[int, Query(ge=1, le=MAX_ANALYSES)] = 20,
) -> list[IntentionAnalysisRead]:
    """Its analyses, the latest first: which capabilities ran and why, what
    each did, the result and its evidence."""
    found = await service.analyses(intention_id, limit=limit)
    if found is None:
        raise _missing()
    return found


@router.get("/{intention_id}/analysis", response_model=IntentionAnalysisRead)
async def analysis(intention_id: uuid.UUID, service: Reading) -> IntentionAnalysisRead:
    """Its latest analysis — running, complete, partial, inconclusive,
    failed, or blocked by its context. 404 before any."""
    found = await service.analyses(intention_id, limit=1)
    if found is None:
        raise _missing()
    if not found:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No analysis yet.")
    return found[0]


@router.post(
    "/{intention_id}/analyse",
    response_model=IntentionAnalysisRequested,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyse(
    intention_id: uuid.UUID, service: Asking, principal: Asker, session: SessionDep
) -> IntentionAnalysisRequested:
    """Analysed again, as it now stands — failed, it is retried first;
    stopped, resumed (LEKA-443). 409 in any other state than analysing,
    stopped or failed; `queued` false when one is already on its way."""
    try:
        found = await service.analyse_again(
            intention_id, by=principal.user_id, steward=_steward(principal)
        )
    except REFUSED as error:
        raise _refused(error) from error
    if found is None:
        raise _missing()
    await session.commit()
    queued = await queue_analysis(
        principal.workspace_id, found.id, trigger="requested", by=principal.user_id
    )
    return IntentionAnalysisRequested(queued=queued)
