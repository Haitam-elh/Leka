"""The context engine (LEKA-370): contexts assembled, kept, inspected.

    POST /context                         a context, assembled from the company
                                          model around its roots: its first
                                          version, whole
    POST /context/intents/plan            what an intention asks for, read from
                                          its words and its scope: the context
                                          request it makes, what is missing —
                                          nothing kept (LEKA-373)
    POST /context/intents                 that context, assembled, kept with
                                          how the intention was read
    GET  /context                         the contexts, the latest changed first
                                          — by state, by subject, behind the
                                          model or not
    GET  /context/{id}                    one: what it is for, what it asks,
                                          where it stands, its latest version
    PATCH /context/{id}                   follows the model, or not (LEKA-374)
    POST /context/{id}/refresh            assembled again: a new version when
                                          what the model says of it changed
    POST /context/{id}/expand             its request widened — as asked, or
                                          one step — and made again (LEKA-374)
    POST /context/{id}/compress           narrowed — as asked, or half its
                                          budget — and made again
    POST /context/{id}/intent             its intention asked again: read
                                          again, the same context made again
    GET  /context/{id}/checks             every time it was made again: why,
                                          after which changes, what came of it
    GET  /context/{id}/quality            how good a version is (LEKA-375):
                                          its measures and what each rests on,
                                          what it lacks, what it disagrees on,
                                          what people said of it
    POST /context/{id}/feedback           an element useful, not useful, wrong
                                          — or what is missing
    GET  /context/feedback                what people said, counted by the
                                          retrievers that found it
    POST /context/{id}/archive            no longer reassembled; still read
    GET  /context/{id}/versions           its versions, the latest first
    GET  /context/{id}/assembled          one version whole — the latest that
                                          holds something, ?version=, or the
                                          one that stood ?at= a date — each
                                          element with its provenance and why
                                          it is there
    GET  /context/{id}/diff               what changed ?from= a version ?to=
                                          another

Read by every member (`intention:read`); made, reassembled and archived by
those who may make intentions (`intention:create`), refused to a suspended
workspace. A route validates, calls one service, and returns (architecture
rule 6). Permissions come from a FastAPI dependency, never an `if` in the
body (rule 5). The workspace is read from the session, never from the path
or the payload (rule 3): another workspace's context is 404.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.connectors import SourceRepository
from leka.context import (
    AssembledContext,
    Context,
    ContextArchivedError,
    ContextCheck,
    ContextCheckRead,
    ContextCompress,
    ContextCreate,
    ContextDetail,
    ContextDiff,
    ContextExpand,
    ContextFeedbackCreate,
    ContextFeedbackRead,
    ContextFilters,
    ContextRead,
    ContextRefresh,
    ContextRefusedError,
    ContextRepository,
    ContextRootError,
    ContextService,
    ContextStatus,
    ContextUpdate,
    ContextVersion,
    ContextVersionRead,
    IntentAsk,
    IntentPlan,
    NotAnIntentionError,
    QualityInspection,
    RefreshOutcome,
    RetrievalFeedback,
    SubjectType,
)
from leka.core.errors import ErrorCode
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission
from leka.ingestion import ContentRepository, ResolutionRepository
from leka.knowledge import GraphRepository, GraphService

router = APIRouter(prefix="/context", tags=["context"])

Reader = Annotated[Principal, Depends(require_permission(Permission.INTENTION_READ))]
Maker = Annotated[Principal, Depends(require_permission(Permission.INTENTION_CREATE))]

CONTEXT_SORTS = SortCatalogue(
    fields=(SortableField("updated_at", Context.updated_at, "ix_contexts_workspace_updated_at"),),
    default="updated_at",
)
VERSION_SORTS = SortCatalogue(
    fields=(
        SortableField("version", ContextVersion.version, "uq_context_versions_context_version"),
    ),
    default="version",
)
CHECK_SORTS = SortCatalogue(
    fields=(
        SortableField("checked_at", ContextCheck.checked_at, "ix_context_checks_workspace_context"),
    ),
    default="checked_at",
)
NOT_FOUND = "No such context."
ARCHIVED = "This context is archived: it is read, never reassembled."


def _service(session: SessionDep, principal: Principal) -> ContextService:
    return ContextService(
        ContextRepository(session, principal.workspace_id),
        GraphService(GraphRepository(session, principal.workspace_id)),
        content=ContentRepository(session, principal.workspace_id),
        resolution=ResolutionRepository(session, principal.workspace_id),
        sources=SourceRepository(session, principal.workspace_id),
    )


def _reading(session: SessionDep, principal: Reader) -> ContextService:
    return _service(session, principal)


def _making(session: SessionDep, principal: Maker) -> ContextService:
    return _service(session, principal)


Reading = Annotated[ContextService, Depends(_reading)]
Making = Annotated[ContextService, Depends(_making)]


def _missing(message: str = NOT_FOUND) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, message)


def _archived() -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, ARCHIVED)


def _refused(message: str) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, message)


@router.post("/intents/plan", response_model=IntentPlan)
async def plan_intent(body: IntentAsk, service: Reading) -> IntentPlan:
    """What an intention asks the company model for, read from its words
    and the scope it was given (LEKA-373): its kind; what it is about —
    chosen, named, or what that belongs to on the business side; when;
    where; under what constraints; the structured context request that
    makes; and what is missing. Nothing is kept."""
    return await service.plan_intent(body)


@router.post("/intents", response_model=AssembledContext, status_code=status.HTTP_201_CREATED)
async def assemble_intent(body: IntentAsk, service: Making, principal: Maker) -> AssembledContext:
    """The context an intention asks for, assembled and kept with how it was
    read — its `intent`, and what is missing for this version (LEKA-373).
    422 when nothing can start it: it names nothing in the company model
    and says no word to search."""
    made = await service.assemble_intent(body, by=principal.user_id)
    if made is None:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_FAILED,
            "Nothing to start from: the intention names nothing in the company model and "
            "says no word to search.",
        )
    return made


@router.post("", response_model=AssembledContext, status_code=status.HTTP_201_CREATED)
async def create_context(
    body: ContextCreate, service: Making, principal: Maker
) -> AssembledContext:
    """A context, assembled from the company model as it was last built:
    what its words find — in the model and in the records' own text — what
    surrounds its roots, what happened around them, the relationships among
    them; each with its sources, why it is there and how relevant, and what
    each retriever did (LEKA-371). 404 when a root is not the workspace's;
    422 when there is nothing to start from."""
    made = await service.create(body, by=principal.user_id)
    if made is None:
        raise _missing("A root of this context is not in the company model.")
    return made


@router.get("", response_model=PageEnvelope[ContextRead])
async def contexts(
    session: SessionDep,
    principal: Reader,
    page: PageParams,
    state: Annotated[ContextStatus | None, Query(alias="status")] = None,
    subject_type: SubjectType | None = None,
    subject_id: Annotated[str | None, Query(max_length=100)] = None,
    stale: Annotated[
        bool | None, Query(description="Behind the company model — or up to date (LEKA-374).")
    ] = None,
) -> PageEnvelope[ContextRead]:
    """The contexts, the latest changed first."""
    repository = ContextRepository(session, principal.workspace_id)
    statement = repository.contexts(
        ContextFilters(status=state, subject_type=subject_type, subject_id=subject_id, stale=stale)
    )
    result = await serve_page(
        session, statement, request=page, catalogue=CONTEXT_SORTS, id_column=Context.id
    )
    return PageEnvelope(data=ContextService.reads(result.items), next_cursor=result.next_cursor)


@router.get("/feedback", response_model=RetrievalFeedback)
async def retrieval_feedback(
    service: Reading,
    days: Annotated[int, Query(ge=1, le=365, description="How far back.")] = 30,
) -> RetrievalFeedback:
    """What people said of what LEKA retrieved (LEKA-375) — useful, not
    useful, wrong, missing — counted by the retrievers that found it, by
    why it was there, by kind of thing: what weighing them next time can
    learn from."""
    return await service.retrieval_feedback(days=days)


@router.get("/{context_id}", response_model=ContextDetail)
async def context(context_id: uuid.UUID, service: Reading) -> ContextDetail:
    found = await service.detail(context_id)
    if found is None:
        raise _missing()
    return found


@router.patch("/{context_id}", response_model=ContextRead)
async def update_context(
    context_id: uuid.UUID, body: ContextUpdate, service: Making
) -> ContextRead:
    """Whether it is made again on its own when the company model changes
    what it holds — or only when asked (LEKA-374). Behind or not, it says
    so either way."""
    updated = await service.set_follow(context_id, follow=body.follow)
    if updated is None:
        raise _missing()
    return updated


@router.post("/{context_id}/refresh", response_model=RefreshOutcome)
async def refresh_context(
    context_id: uuid.UUID, service: Making, principal: Maker, body: ContextRefresh | None = None
) -> RefreshOutcome:
    """Assembled again from the model as it is now — after what it was
    behind on, said with the check. A new version when what it holds
    changed — or failed, when a root is gone; none when nothing did. 409
    when the context is archived."""
    try:
        outcome = await service.refresh(
            context_id, reason=body.reason if body else None, by=principal.user_id
        )
    except ContextArchivedError as error:
        raise _archived() from error
    if outcome is None:
        raise _missing()
    return outcome


@router.post("/{context_id}/expand", response_model=RefreshOutcome)
async def expand_context(
    context_id: uuid.UUID, service: Making, principal: Maker, body: ContextExpand | None = None
) -> RefreshOutcome:
    """Widened, and made again (LEKA-374): further, more of it, further
    back, less relevant things kept, more roots, more kinds of relationship
    — or, nothing asked, one step: a step further, twice the budget and the
    window. A new version that says what of its request changed. 404 when
    a root added is not the workspace's; 409 when archived; 422 when it
    widens nothing."""
    try:
        outcome = await service.expand(context_id, body or ContextExpand(), by=principal.user_id)
    except ContextArchivedError as error:
        raise _archived() from error
    except ContextRefusedError as error:
        raise _refused(str(error)) from error
    except ContextRootError as error:
        raise _missing("A root added is not in the company model.") from error
    if outcome is None:
        raise _missing()
    return outcome


@router.post("/{context_id}/compress", response_model=RefreshOutcome)
async def compress_context(
    context_id: uuid.UUID, service: Making, principal: Maker, body: ContextCompress | None = None
) -> RefreshOutcome:
    """Narrowed to what its reader can take, and made again (LEKA-374):
    fewer elements — the most relevant kept, its roots always — nearer, a
    shorter window, only the more relevant; nothing asked, half its budget.
    409 when archived; 422 when it narrows nothing."""
    try:
        outcome = await service.compress(
            context_id, body or ContextCompress(), by=principal.user_id
        )
    except ContextArchivedError as error:
        raise _archived() from error
    except ContextRefusedError as error:
        raise _refused(str(error)) from error
    if outcome is None:
        raise _missing()
    return outcome


@router.post("/{context_id}/intent", response_model=AssembledContext)
async def reask_context(
    context_id: uuid.UUID, body: IntentAsk, service: Making, principal: Maker
) -> AssembledContext:
    """Its intention asked again, as it now stands (LEKA-374): read again,
    and the same context made again — a new version that says what LEKA
    reads differently, and how what it holds changed. 409 when archived, or
    not assembled for an intention; 422 when nothing can start it."""
    try:
        made = await service.reask(context_id, body, by=principal.user_id)
    except ContextArchivedError as error:
        raise _archived() from error
    except NotAnIntentionError as error:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.CONFLICT,
            "This context was not assembled for an intention: there is nothing to ask again.",
        ) from error
    except ContextRefusedError as error:
        raise _refused(str(error)) from error
    if made is None:
        raise _missing()
    return made


@router.get("/{context_id}/checks", response_model=PageEnvelope[ContextCheckRead])
async def context_checks(
    context_id: uuid.UUID, session: SessionDep, principal: Reader, page: PageParams
) -> PageEnvelope[ContextCheckRead]:
    """Every time it was made again, the latest first (LEKA-374): asked, or
    LEKA following the model; after which changes; and what came of it — a
    version, nothing new, a failure."""
    repository = ContextRepository(session, principal.workspace_id)
    if await repository.context(context_id) is None:
        raise _missing()
    result = await serve_page(
        session,
        repository.checks(context_id),
        request=page,
        catalogue=CHECK_SORTS,
        id_column=ContextCheck.id,
    )
    return PageEnvelope(
        data=ContextService.check_reads(result.items), next_cursor=result.next_cursor
    )


@router.post("/{context_id}/archive", response_model=ContextRead)
async def archive_context(context_id: uuid.UUID, service: Making) -> ContextRead:
    """No longer reassembled. Its versions stay readable."""
    archived = await service.archive(context_id)
    if archived is None:
        raise _missing()
    return archived


@router.get("/{context_id}/versions", response_model=PageEnvelope[ContextVersionRead])
async def context_versions(
    context_id: uuid.UUID, session: SessionDep, principal: Reader, page: PageParams
) -> PageEnvelope[ContextVersionRead]:
    """Its versions, the latest first: when, from which build of the model,
    by what, what each holds — or why it failed."""
    repository = ContextRepository(session, principal.workspace_id)
    if await repository.context(context_id) is None:
        raise _missing()
    result = await serve_page(
        session,
        repository.versions(context_id),
        request=page,
        catalogue=VERSION_SORTS,
        id_column=ContextVersion.id,
    )
    return PageEnvelope(
        data=ContextService.version_reads(result.items), next_cursor=result.next_cursor
    )


@router.get("/{context_id}/assembled", response_model=AssembledContext)
async def assembled_context(
    context_id: uuid.UUID,
    service: Reading,
    version: Annotated[int | None, Query(ge=1, description="This version.")] = None,
    at: Annotated[datetime | None, Query(description="The version that stood then.")] = None,
) -> AssembledContext:
    """One version whole, as it was made: by default the latest that holds
    something. Its elements in order, each with its provenance — its
    sources, its origin, its confidence — and why it is there."""
    if version is not None and at is not None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            ErrorCode.INVALID_FILTER,
            "Ask for a version or a date, not both.",
        )
    found = await service.assembled(context_id, version=version, at=at)
    if found is None:
        raise _missing("No such context, or no such version of it.")
    return found


@router.get("/{context_id}/diff", response_model=ContextDiff)
async def context_diff(
    context_id: uuid.UUID,
    service: Reading,
    before: Annotated[int, Query(alias="from", ge=1, description="The earlier version.")],
    after: Annotated[int, Query(alias="to", ge=1, description="The later version.")],
) -> ContextDiff:
    """What changed from one version to another: the elements added, those
    gone, those said differently — and what of them."""
    found = await service.diff(context_id, before, after)
    if found is None:
        raise _missing("No such context, or no such version of it.")
    return found


@router.get("/{context_id}/quality", response_model=QualityInspection)
async def context_quality(
    context_id: uuid.UUID,
    service: Reading,
    version: Annotated[int | None, Query(ge=1, description="This version.")] = None,
) -> QualityInspection:
    """How good a version is (LEKA-375) — by default the latest that holds
    something: its score and level; its completeness, freshness and
    confidence, each factor with the elements it was read from; what it
    lacks; what it disagrees on and how badly; what each retriever brought;
    whether the context is up to date now; what people said of it."""
    found = await service.inspect_quality(context_id, version=version)
    if found is None:
        raise _missing("No such context, or no such version of it.")
    return found


@router.post(
    "/{context_id}/feedback",
    response_model=ContextFeedbackRead,
    status_code=status.HTTP_201_CREATED,
)
async def give_feedback(
    context_id: uuid.UUID, body: ContextFeedbackCreate, service: Making, principal: Maker
) -> ContextFeedbackRead:
    """What someone says of a version (LEKA-375): an element useful, not
    useful or wrong — or what is missing, in a note. Kept with what the
    element was then, so that it can be counted by what found it. 404 when
    the context, the version or the element is not there."""
    given = await service.give_feedback(context_id, body, by=principal.user_id)
    if given is None:
        raise _missing("No such context, version of it, or element in that version.")
    return given
