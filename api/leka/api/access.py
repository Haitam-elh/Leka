"""Who may do what, over HTTP (LEKA-402): the authorisation model, the
entities an admin restricted, and the trail of access decisions.

    GET    /governance/access                   every role's permissions, and yours
    GET    /governance/restrictions             the restricted entities
    PUT    /governance/restrictions/{entity}    restricted, saying why
    DELETE /governance/restrictions/{entity}    visible to everyone again
    GET    /governance/decisions                the access decisions kept

Reading the model is any member's; the restrictions and the decisions take
`access:read`; restricting takes `entity:restrict`. The workspace is the
session's (rule 3).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.core.errors import ErrorCode
from leka.governance import (
    ROLE_PERMISSIONS,
    WRITE_PERMISSIONS,
    AccessDecisionRead,
    AccessModelRead,
    AuditRepository,
    Permission,
    Principal,
    RestrictionRead,
    RestrictionService,
    RestrictionUpdate,
    RolePermissionsRead,
    require_permission,
)
from leka.knowledge import GraphRepository, GraphService
from leka.platform import Role

router = APIRouter(prefix="/governance", tags=["governance"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Auditor = Annotated[Principal, Depends(require_permission(Permission.ACCESS_READ))]
Restricter = Annotated[Principal, Depends(require_permission(Permission.ENTITY_RESTRICT))]


@router.get("/access", response_model=AccessModelRead, summary="Who may do what here")
async def access_model(principal: Reader) -> AccessModelRead:
    order = list(Permission)
    return AccessModelRead(
        roles=[
            RolePermissionsRead(
                role=role, permissions=[p for p in order if p in ROLE_PERMISSIONS[role]]
            )
            for role in (Role.MEMBER, Role.ADMIN, Role.OWNER)
        ],
        permissions=order,
        writes=[p for p in order if p in WRITE_PERMISSIONS],
        mine=[p for p in order if principal.has(p)],
        role=principal.role,
    )


async def _named(
    session: SessionDep, principal: Principal, rows: list[tuple[uuid.UUID, object]]
) -> dict[uuid.UUID, tuple[str, str]]:
    briefs = await GraphService(GraphRepository(session, principal.workspace_id)).briefs(
        [entity_id for entity_id, _ in rows]
    )
    return {k: (b.name, b.type.value) for k, b in briefs.items()}


@router.get(
    "/restrictions", response_model=list[RestrictionRead], summary="The restricted entities"
)
async def restrictions(session: SessionDep, principal: Auditor) -> list[RestrictionRead]:
    found = await RestrictionService(session, principal.workspace_id).all()
    names = await _named(session, principal, [(r.entity_id, r) for r in found])
    return [
        RestrictionRead(
            entity_id=r.entity_id,
            name=names.get(r.entity_id, (None, None))[0],
            type=names.get(r.entity_id, (None, None))[1],
            reason=r.reason,
            restricted_by=r.restricted_by,
            restricted_at=r.restricted_at,
        )
        for r in found
    ]


@router.put(
    "/restrictions/{entity_id}",
    response_model=RestrictionRead,
    summary="Restrict an entity to the administrators",
)
async def restrict(
    entity_id: uuid.UUID, body: RestrictionUpdate, session: SessionDep, principal: Restricter
) -> RestrictionRead:
    """From the next request on, no role that may not read restricted
    entities sees it, nor what refers to it. 404 for an entity this
    workspace does not have."""
    names = await _named(session, principal, [(entity_id, None)])
    if entity_id not in names:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such entity.")
    row = await RestrictionService(session, principal.workspace_id).restrict(
        entity_id, reason=body.reason, by=principal.user_id
    )
    name, kind = names[entity_id]
    return RestrictionRead(
        entity_id=row.entity_id,
        name=name,
        type=kind,
        reason=row.reason,
        restricted_by=row.restricted_by,
        restricted_at=row.restricted_at,
    )


@router.delete(
    "/restrictions/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Lift a restriction",
)
async def lift(entity_id: uuid.UUID, session: SessionDep, principal: Restricter) -> Response:
    if not await RestrictionService(session, principal.workspace_id).lift(entity_id):
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "Not restricted.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/decisions", response_model=list[AccessDecisionRead], summary="The access decisions kept"
)
async def decisions(
    session: SessionDep,
    principal: Auditor,
    decision: Annotated[Literal["allow", "deny"] | None, Query()] = None,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    before: Annotated[datetime | None, Query(description="Older than this.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AccessDecisionRead]:
    """Every refusal, and every write and run allowed — the latest first."""
    rows = await AuditRepository(session).decisions(
        principal.workspace_id,
        decision=decision,
        user_id=user_id,
        action=action,
        before=before,
        limit=limit,
    )
    return [AccessDecisionRead.model_validate(r) for r in rows]
