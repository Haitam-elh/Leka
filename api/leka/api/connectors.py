"""Connecting a customer system: the catalogue of connectors, and the sources.

    GET  /connectors/catalog           what can be connected, with the JSON
                                       Schemas a form is generated from
    /sources[/{id}[/...]]              the sources of the active workspace

A route validates, calls one service, and returns (architecture rule 6).
Permissions come from a dependency (rule 5): reading needs source:read,
which every member holds; anything that writes or calls the vendor needs
source:manage, which admins and owners hold. The workspace is the
principal's (rule 3): another workspace's source is a 404, never a 403,
so its existence is not confirmed to anyone outside.

Credentials are write-only: accepted on create and on rotation, answered
with a masked hint, never returned.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Response, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.pagination import PageEnvelope, PageParams, SortCatalogue, serve_page
from leka.connectors import (
    ActivationRefusedError,
    CatalogEntry,
    CredentialsRead,
    CredentialsUpdate,
    Diagnostic,
    DuplicateSourceError,
    HealthRead,
    InvalidSourceInputError,
    InvalidTransitionError,
    Source,
    SourceCreate,
    SourceEvent,
    SourceEventRead,
    SourceNotFoundError,
    SourceRead,
    SourceService,
    SourceTestOutcome,
    SourceUpdate,
    UnknownConnectorError,
    manifests,
)
from leka.core.errors import ErrorCode, FieldError
from leka.db import SortableField
from leka.governance import Permission, Principal, require_permission

router = APIRouter(tags=["connectors"])

Reader = Annotated[Principal, Depends(require_permission(Permission.SOURCE_READ))]
Manager = Annotated[Principal, Depends(require_permission(Permission.SOURCE_MANAGE))]

SOURCE_SORTS = SortCatalogue(
    fields=(
        SortableField("created_at", Source.created_at, "bounded by ix_sources_workspace_id"),
        SortableField("name", Source.name, "uq_sources_workspace_kind_name"),
    ),
    default="created_at",
)
EVENT_SORTS = SortCatalogue(
    fields=(
        SortableField(
            "created_at", SourceEvent.created_at, "ix_source_events_source_id_created_at"
        ),
    ),
    default="created_at",
)


def get_connector_transport() -> httpx.AsyncBaseTransport | None:
    """None: the real network. The tests replace it with httpx.MockTransport."""
    return None


def _service(
    session: SessionDep,
    principal: Principal,
    transport: httpx.AsyncBaseTransport | None,
) -> SourceService:
    return SourceService(
        session, principal.workspace_id, actor_user_id=principal.user_id, transport=transport
    )


def reading_service(session: SessionDep, principal: Reader) -> SourceService:
    return _service(session, principal, None)


def managing_service(
    session: SessionDep,
    principal: Manager,
    transport: Annotated[httpx.AsyncBaseTransport | None, Depends(get_connector_transport)],
) -> SourceService:
    return _service(session, principal, transport)


ReadingService = Annotated[SourceService, Depends(reading_service)]
ManagingService = Annotated[SourceService, Depends(managing_service)]


async def _source(service: SourceService, source_id: uuid.UUID) -> Source:
    try:
        return await service.get(source_id)
    except SourceNotFoundError as error:
        raise ApiError(404, ErrorCode.NOT_FOUND, "No such source in this workspace.") from error


async def _read(service: SourceService, source: Source) -> SourceRead:
    stored = await service.secrets.describe(source.id)
    return SourceRead(
        id=source.id,
        type=source.kind,
        display_name=source.name,
        status=source.status,
        config=source.config,
        capabilities=source.capabilities,
        source_metadata=source.source_metadata,
        health_status=source.health_status,
        last_health_check_at=source.last_health_check_at,
        last_error=Diagnostic.model_validate(source.last_error) if source.last_error else None,
        sync_status=source.sync_status,
        last_sync_at=source.last_synced_at,
        credentials=CredentialsRead(hint=stored.hint, rotated_at=stored.rotated_at)
        if stored
        else None,
        created_by=source.created_by,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _refused(error: Exception) -> ApiError:
    """The framework's refusals, in the API's one error shape."""
    if isinstance(error, InvalidSourceInputError):
        return ApiError(
            422,
            ErrorCode.VALIDATION_FAILED,
            "The connector refused these settings.",
            details=[FieldError(field=field, message=message) for field, message in error.fields],
        )
    if isinstance(error, UnknownConnectorError):
        return ApiError(
            422,
            ErrorCode.VALIDATION_FAILED,
            "No connector exists for this type.",
            details=[FieldError(field="type", message="Not an available connector.")],
        )
    if isinstance(error, DuplicateSourceError):
        return ApiError(409, ErrorCode.CONFLICT, "A source of this type already has this name.")
    if isinstance(error, ActivationRefusedError):
        return ApiError(
            409,
            ErrorCode.CONFLICT,
            "Test the connection first: activation needs a successful test of the current "
            "settings and credentials.",
        )
    if isinstance(error, InvalidTransitionError):
        return ApiError(409, ErrorCode.CONFLICT, f"Not possible now: {error}.")
    raise error


_REFUSALS = (
    InvalidSourceInputError,
    UnknownConnectorError,
    DuplicateSourceError,
    ActivationRefusedError,
    InvalidTransitionError,
)


# ── the catalogue ────────────────────────────────────────────────────────────


@router.get("/connectors/catalog", response_model=list[CatalogEntry])
async def catalog(_principal: Reader) -> list[CatalogEntry]:
    """Every connector that can be used, and the forms to configure it."""
    return [
        CatalogEntry(
            key=manifest.key,
            display_name=manifest.display_name,
            category=manifest.category,
            auth_type=manifest.auth_type,
            capabilities=sorted(manifest.capabilities),
            read_only=manifest.read_only,
            config_schema=manifest.config_schema.model_json_schema(),
            credentials_schema=manifest.credentials_schema.model_json_schema(),
        )
        for manifest in manifests()
    ]


# ── sources ──────────────────────────────────────────────────────────────────


@router.get("/sources", response_model=PageEnvelope[SourceRead])
async def list_sources(
    service: ReadingService, session: SessionDep, page: PageParams
) -> PageEnvelope[SourceRead]:
    result = await serve_page(
        session,
        service.repository.list_statement(),
        request=page,
        catalogue=SOURCE_SORTS,
        id_column=Source.id,
    )
    return PageEnvelope(
        data=[await _read(service, source) for source in result.items],
        next_cursor=result.next_cursor,
    )


@router.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(body: SourceCreate, service: ManagingService) -> SourceRead:
    """A new source, in draft. It reads nothing until it is tested and activated."""
    try:
        source = await service.create(body.type, body.display_name, body.config, body.credentials)
    except _REFUSALS as error:
        raise _refused(error) from error
    return await _read(service, source)


@router.get("/sources/{source_id}", response_model=SourceRead)
async def get_source(source_id: uuid.UUID, service: ReadingService) -> SourceRead:
    return await _read(service, await _source(service, source_id))


@router.patch("/sources/{source_id}", response_model=SourceRead)
async def update_source(
    source_id: uuid.UUID, body: SourceUpdate, service: ManagingService
) -> SourceRead:
    """Rename, or reconfigure. New settings put the source back in draft."""
    source = await _source(service, source_id)
    try:
        await service.update(source, name=body.display_name, config=body.config)
    except _REFUSALS as error:
        raise _refused(error) from error
    return await _read(service, source)


@router.put("/sources/{source_id}/credentials", response_model=SourceRead)
async def rotate_credentials(
    source_id: uuid.UUID, body: CredentialsUpdate, service: ManagingService
) -> SourceRead:
    """Replace the secret. The source goes back to draft: the new one is unproven."""
    source = await _source(service, source_id)
    try:
        await service.rotate_credentials(source, body.credentials)
    except _REFUSALS as error:
        raise _refused(error) from error
    return await _read(service, source)


@router.post("/sources/{source_id}/test", response_model=SourceTestOutcome)
async def test_source(source_id: uuid.UUID, service: ManagingService) -> SourceTestOutcome:
    """Try the connection. 200 either way: a failed test is an answer, with its diagnostic."""
    source = await _source(service, source_id)
    result, diagnostic = await service.test(source)
    return SourceTestOutcome(
        ok=diagnostic is None,
        result=result,
        diagnostic=diagnostic,
        source=await _read(service, source),
    )


@router.post("/sources/{source_id}/activate", response_model=SourceRead)
async def activate_source(source_id: uuid.UUID, service: ManagingService) -> SourceRead:
    source = await _source(service, source_id)
    try:
        await service.activate(source)
    except _REFUSALS as error:
        raise _refused(error) from error
    return await _read(service, source)


@router.post("/sources/{source_id}/disable", response_model=SourceRead)
async def disable_source(source_id: uuid.UUID, service: ManagingService) -> SourceRead:
    source = await _source(service, source_id)
    try:
        await service.disable(source)
    except _REFUSALS as error:
        raise _refused(error) from error
    return await _read(service, source)


@router.post("/sources/{source_id}/health-check", response_model=HealthRead)
async def check_source_health(source_id: uuid.UUID, service: ManagingService) -> HealthRead:
    """Check now rather than wait for the schedule. Calls the vendor, lightly."""
    source = await service.check_health(await _source(service, source_id))
    return _health(source)


@router.get("/sources/{source_id}/health", response_model=HealthRead)
async def source_health(source_id: uuid.UUID, service: ReadingService) -> HealthRead:
    """What the last check found. Calls nothing."""
    return _health(await _source(service, source_id))


def _health(source: Source) -> HealthRead:
    return HealthRead(
        status=source.status,
        health_status=source.health_status,
        last_health_check_at=source.last_health_check_at,
        last_error=Diagnostic.model_validate(source.last_error) if source.last_error else None,
    )


@router.get("/sources/{source_id}/events", response_model=PageEnvelope[SourceEventRead])
async def source_events(
    source_id: uuid.UUID, service: ReadingService, session: SessionDep, page: PageParams
) -> PageEnvelope[SourceEventRead]:
    await _source(service, source_id)
    result = await serve_page(
        session,
        service.events.list_statement(source_id),
        request=page,
        catalogue=EVENT_SORTS,
        id_column=SourceEvent.id,
    )
    return PageEnvelope(
        data=[
            SourceEventRead(
                id=event.id,
                type=event.type,
                actor_user_id=event.actor_user_id,
                payload=event.payload,
                created_at=event.created_at,
            )
            for event in result.items
        ],
        next_cursor=result.next_cursor,
    )


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: uuid.UUID, service: ManagingService) -> Response:
    """Gone, with its credential. Its history stays, and says it was deleted."""
    await service.delete(await _source(service, source_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
