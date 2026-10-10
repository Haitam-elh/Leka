"""Who may do what, over HTTP (LEKA-402): the authorisation model, the
entities an admin restricted, and the trail of access decisions.

    GET    /governance/access                   every role's permissions, and yours
    GET    /governance/restrictions             the restricted entities
    PUT    /governance/restrictions/{entity}    restricted, saying why
    DELETE /governance/restrictions/{entity}    visible to everyone again
    GET    /governance/decisions                the access decisions kept
    GET    /governance/roles · PUT · DELETE /{key}       roles of its own (LEKA-403)
    GET    /governance/assignments · PUT /{user}         who holds which
    GET    /governance/policies · POST · PUT · DELETE    its policies
    GET    /governance/history                  roles, policies, AI controls, changed
    POST   /governance/evaluate                 a decision, asked without acting

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
    AssignmentRead,
    AssignmentUpdate,
    AuditRepository,
    EvaluationAsk,
    EvaluationRead,
    GovernanceEventRead,
    Permission,
    PolicyInput,
    PolicyRead,
    PolicyService,
    PolicyUpdate,
    Principal,
    Resource,
    RestrictionRead,
    RestrictionService,
    RestrictionUpdate,
    RoleError,
    RolePermissionsRead,
    RoleRead,
    RoleUpdate,
    Subject,
    WorkspacePolicy,
    WorkspaceRole,
    evaluate,
    require_permission,
    role_of,
)
from leka.knowledge import GraphRepository, GraphService
from leka.platform import MembershipResolver, Role

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
        custom_role=principal.custom_role,
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


# ── roles of the workspace's own, policies (LEKA-403) ──────────────────────

Manager = Annotated[Principal, Depends(require_permission(Permission.POLICY_MANAGE))]


def _invalid(error: RoleError) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, str(error))


def _role_read(row: WorkspaceRole, holders: int) -> RoleRead:
    granted = role_of(row).permissions
    return RoleRead(
        key=row.key,
        name=row.name,
        description=row.description,
        base=row.base,
        added=list(row.added),
        removed=list(row.removed),
        permissions=[p for p in Permission if p in granted],
        holders=holders,
    )


def _policy_read(row: WorkspacePolicy) -> PolicyRead:
    said = row.conditions or {}
    return PolicyRead(
        id=row.id,
        updated_at=row.updated_at,
        name=row.name,
        description=row.description,
        effect=row.effect,
        actions=list(row.actions),
        roles=list(row.roles),
        resource_types=list(said.get("resource_types") or []),  # type: ignore[call-overload]
        risk_at_least=said.get("risk_at_least"),
        kinds=list(said.get("kinds") or []),  # type: ignore[call-overload]
        categories=list(said.get("categories") or []),  # type: ignore[call-overload]
        priority=row.priority,
        enabled=row.enabled,
    )


def _input(body: PolicyUpdate) -> PolicyInput:
    return PolicyInput(
        name=body.name,
        description=body.description,
        effect=body.effect,
        actions=body.actions,
        roles=body.roles,
        resource_types=body.resource_types,
        risk_at_least=body.risk_at_least,
        kinds=body.kinds,
        categories=body.categories,
        priority=body.priority,
        enabled=body.enabled,
    )


@router.get("/roles", response_model=list[RoleRead], summary="The workspace's own roles")
async def roles(session: SessionDep, principal: Reader) -> list[RoleRead]:
    found = await PolicyService(session, principal.workspace_id).roles()
    return [_role_read(row, holders) for row, holders in found]


@router.put("/roles/{key}", response_model=RoleRead, summary="Create or change a role")
async def save_role(
    key: str, body: RoleUpdate, session: SessionDep, principal: Manager
) -> RoleRead:
    """Its base's permissions, with what it adds, less what it takes away:
    never what only an owner may, never reading the workspace taken away —
    422, said why."""
    service = PolicyService(session, principal.workspace_id)
    try:
        row = await service.save_role(
            key,
            name=body.name,
            base=body.base,
            added=body.added,
            removed=body.removed,
            description=body.description,
            by=principal.user_id,
        )
    except RoleError as error:
        raise _invalid(error) from error
    held = sum(1 for k in (await service.holders()).values() if k == key)
    return _role_read(row, held)


@router.delete("/roles/{key}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a role")
async def delete_role(key: str, session: SessionDep, principal: Manager) -> Response:
    try:
        deleted = await PolicyService(session, principal.workspace_id).delete_role(
            key, by=principal.user_id
        )
    except RoleError as error:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, str(error)) from error
    if not deleted:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such role.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/assignments", response_model=list[AssignmentRead], summary="Who holds which role")
async def assignments(session: SessionDep, principal: Reader) -> list[AssignmentRead]:
    held = await PolicyService(session, principal.workspace_id).holders()
    return [AssignmentRead(user_id=u, role=k) for u, k in held.items()]


@router.put(
    "/assignments/{user_id}", response_model=AccessModelRead, summary="Give a person a role"
)
async def assign(
    user_id: uuid.UUID, body: AssignmentUpdate, session: SessionDep, principal: Manager
) -> AccessModelRead:
    """A role of the workspace's own — on the base their seat has (409
    otherwise: change their seat first) — or back to their seat's (none).
    In force at their next request. Answers the model as it stands."""
    seat = await MembershipResolver(session).get_for_user_in_workspace(
        user_id, principal.workspace_id
    )
    if seat is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such member.")
    try:
        await PolicyService(session, principal.workspace_id).assign(
            user_id, body.role, seat=seat.role, by=principal.user_id
        )
    except RoleError as error:
        raise ApiError(status.HTTP_409_CONFLICT, ErrorCode.CONFLICT, str(error)) from error
    return await access_model(principal)


@router.get("/policies", response_model=list[PolicyRead], summary="The workspace's policies")
async def policies(session: SessionDep, principal: Reader) -> list[PolicyRead]:
    return [
        _policy_read(p) for p in await PolicyService(session, principal.workspace_id).policies()
    ]


@router.post(
    "/policies",
    response_model=PolicyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a policy",
)
async def create_policy(body: PolicyUpdate, session: SessionDep, principal: Manager) -> PolicyRead:
    try:
        row = await PolicyService(session, principal.workspace_id).save_policy(
            _input(body), by=principal.user_id
        )
    except RoleError as error:
        raise _invalid(error) from error
    assert row is not None
    return _policy_read(row)


@router.put("/policies/{policy_id}", response_model=PolicyRead, summary="Change a policy")
async def update_policy(
    policy_id: uuid.UUID, body: PolicyUpdate, session: SessionDep, principal: Manager
) -> PolicyRead:
    try:
        row = await PolicyService(session, principal.workspace_id).save_policy(
            _input(body), by=principal.user_id, policy_id=policy_id
        )
    except RoleError as error:
        raise _invalid(error) from error
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such policy.")
    return _policy_read(row)


@router.delete(
    "/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a policy"
)
async def delete_policy(policy_id: uuid.UUID, session: SessionDep, principal: Manager) -> Response:
    if not await PolicyService(session, principal.workspace_id).delete_policy(
        policy_id, by=principal.user_id
    ):
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such policy.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/history", response_model=list[GovernanceEventRead], summary="Roles and policies, changed"
)
async def history(
    session: SessionDep,
    principal: Auditor,
    subject_type: Annotated[
        Literal["role", "policy", "assignment", "ai_control"] | None, Query()
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[GovernanceEventRead]:
    rows = await PolicyService(session, principal.workspace_id).history(
        subject_type=subject_type, limit=limit
    )
    return [GovernanceEventRead.model_validate(r) for r in rows]


@router.post("/evaluate", response_model=EvaluationRead, summary="Ask a decision, without acting")
async def evaluate_ask(
    body: EvaluationAsk, session: SessionDep, principal: Auditor
) -> EvaluationRead:
    """As `role` — or a role of the workspace's own — would be answered for
    `permission` (and `action`) on such a resource, under the policies in
    force. Nothing is done, nothing is kept."""
    service = PolicyService(session, principal.workspace_id)
    try:
        permission = Permission(body.permission)
    except ValueError as error:
        raise _invalid(RoleError(f"no permission {body.permission!r}")) from error
    custom = await service.custom(body.custom_role) if body.custom_role else None
    if body.custom_role and custom is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such role.")
    role = custom.base if custom is not None else Role(body.role)
    attributes = {
        k: v
        for k, v in {"risk": body.risk, "kind": body.kind, "category": body.category}.items()
        if v
    }
    resource = Resource(body.resource_type, attributes=attributes) if body.resource_type else None
    decided = evaluate(
        Subject(
            principal.user_id,
            role,
            principal.workspace_status,
            custom.key if custom else None,
            custom.permissions if custom else None,
            await service.rules(),
        ),
        permission,
        resource,
        action=body.action,
    )
    return EvaluationRead(
        allowed=decided.allowed,
        rule=decided.rule,
        reason=decided.reason,
        policy=decided.policy,
        message=decided.message,
    )
