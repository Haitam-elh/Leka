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
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.connectors import SourceRepository
from leka.context import (
    ContextArchivedError,
    ContextRefusedError,
    ContextRepository,
    ContextService,
    IntentAsk,
)
from leka.core.errors import ErrorCode
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission
from leka.ingestion import ContentRepository, ResolutionRepository
from leka.intelligence import IntelligenceRepository
from leka.intentions import (
    Actor,
    IllegalTransitionError,
    Intention,
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
    IntentionRead,
    IntentionRepository,
    IntentionService,
    IntentionStatus,
    LinkRefusedError,
    NothingToStartError,
    NotYoursError,
    Understanding,
    Withdrawal,
    intention_read,
)
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
    ContextRefusedError,
    NotYoursError,
    LinkRefusedError,
)


@router.post("", response_model=IntentionCreated, status_code=status.HTTP_201_CREATED)
async def create(body: IntentAsk, service: Asking, principal: Asker) -> IntentionCreated:
    """Ask LEKA: the intention kept — submitted, then analysing — and the
    context it asks for assembled, its subject the intention (LEKA-373).
    `intention_id` in the body is ignored: it is the new intention's. 422
    when nothing can start it — and nothing is kept."""
    try:
        intention, context = await service.create(body, by=principal.user_id)
    except REFUSED as error:
        raise _refused(error) from error
    return IntentionCreated(intention=await service.detail_now(intention), context=context)


@router.post("/understand", response_model=Understanding)
async def understand(body: IntentAsk, service: Asking) -> Understanding:
    """What LEKA would understand of these words (LEKA-385) — its goal,
    whether it asks or requests, the actions, the things it is about, what
    is ambiguous, each with the words it came from. Nothing is kept."""
    return await service.understand(body)


@router.get("", response_model=PageEnvelope[IntentionRead])
async def intentions(
    session: SessionDep,
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
        )
    )
    result = await serve_page(
        session, statement, request=page, catalogue=SORTS, id_column=Intention.id
    )
    return PageEnvelope(
        data=[intention_read(found) for found in result.items], next_cursor=result.next_cursor
    )


@router.get("/counts", response_model=IntentionCounts)
async def counts(
    service: Reading, principal: Reader, mine: Annotated[bool, Query()] = False
) -> IntentionCounts:
    """How many active, scheduled, finished, archived — mockup 07's tabs."""
    return await service.counts(created_by=principal.user_id if mine else None)


@router.get("/{intention_id}", response_model=IntentionDetail)
async def intention(intention_id: uuid.UUID, service: Reading) -> IntentionDetail:
    """One intention: where it stands, where it may go next, what it is
    linked to."""
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


@router.post("/{intention_id}/ask", response_model=IntentionAsked)
async def ask_again(
    intention_id: uuid.UUID, body: IntentAsk, service: Asking, principal: Asker
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
    return IntentionAsked(intention=await service.detail_now(intention), context=context)


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
