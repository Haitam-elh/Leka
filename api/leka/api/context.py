"""The context engine (LEKA-370): contexts assembled, kept, inspected.

    POST /context                         a context, assembled from the company
                                          model around its roots: its first
                                          version, whole
    GET  /context                         the contexts, the latest changed first
                                          — by state, by subject
    GET  /context/{id}                    one: what it is for, what it asks,
                                          where it stands, its latest version
    POST /context/{id}/refresh            assembled again: a new version when
                                          what the model says of it changed
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
from leka.context import (
    AssembledContext,
    Context,
    ContextArchivedError,
    ContextCreate,
    ContextDetail,
    ContextDiff,
    ContextFilters,
    ContextRead,
    ContextRefresh,
    ContextRepository,
    ContextService,
    ContextStatus,
    ContextVersion,
    ContextVersionRead,
    RefreshOutcome,
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
NOT_FOUND = "No such context."


def _service(session: SessionDep, principal: Principal) -> ContextService:
    return ContextService(
        ContextRepository(session, principal.workspace_id),
        GraphService(GraphRepository(session, principal.workspace_id)),
        content=ContentRepository(session, principal.workspace_id),
        resolution=ResolutionRepository(session, principal.workspace_id),
    )


def _reading(session: SessionDep, principal: Reader) -> ContextService:
    return _service(session, principal)


def _making(session: SessionDep, principal: Maker) -> ContextService:
    return _service(session, principal)


Reading = Annotated[ContextService, Depends(_reading)]
Making = Annotated[ContextService, Depends(_making)]


def _missing(message: str = NOT_FOUND) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, message)


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
) -> PageEnvelope[ContextRead]:
    """The contexts, the latest changed first."""
    repository = ContextRepository(session, principal.workspace_id)
    statement = repository.contexts(
        ContextFilters(status=state, subject_type=subject_type, subject_id=subject_id)
    )
    result = await serve_page(
        session, statement, request=page, catalogue=CONTEXT_SORTS, id_column=Context.id
    )
    return PageEnvelope(data=ContextService.reads(result.items), next_cursor=result.next_cursor)


@router.get("/{context_id}", response_model=ContextDetail)
async def context(context_id: uuid.UUID, service: Reading) -> ContextDetail:
    found = await service.detail(context_id)
    if found is None:
        raise _missing()
    return found


@router.post("/{context_id}/refresh", response_model=RefreshOutcome)
async def refresh_context(
    context_id: uuid.UUID, service: Making, principal: Maker, body: ContextRefresh | None = None
) -> RefreshOutcome:
    """Assembled again from the model as it is now. A new version when what
    it holds changed — or failed, when a root is gone; none when nothing did.
    409 when the context is archived."""
    try:
        outcome = await service.refresh(
            context_id, reason=body.reason if body else None, by=principal.user_id
        )
    except ContextArchivedError as error:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.CONFLICT,
            "This context is archived: it is read, never reassembled.",
        ) from error
    if outcome is None:
        raise _missing()
    return outcome


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
