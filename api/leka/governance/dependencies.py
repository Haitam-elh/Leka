"""The FastAPI dependencies every protected route declares.

Architecture rule 5: permissions go through a dependency, never through an
`if` in a route body. A dependency sits in the signature where a reviewer
sees it; an `if` is forgotten in the fourteenth route by someone in a hurry,
and nothing fails until a customer reads another customer's incidents.

This is also where the workspace scope is entered. Every route served behind
get_current_principal runs inside `workspace_scope(...)`, so the guard in
leka.db filters its queries whether or not the code remembers to.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from leka.db import DatabaseSession, hidden_entities, workspace_scope
from leka.governance.ai import Actor, acting
from leka.governance.policies import standing
from leka.governance.policy import Subject, evaluate
from leka.governance.repository import AuditRepository
from leka.governance.schemas import Permission, Principal
from leka.governance.service import (
    AuthorisationError,
    GovernanceService,
    check_role,
    hidden_for,
    record,
    record_apart,
    worth_keeping,
)
from leka.platform import (
    MembershipResolver,
    Role,
    SessionStore,
    UserId,
    Workspace,
    get_current_user_id,
    get_session_store,
)

SessionDep = DatabaseSession
UserIdDep = Annotated[UserId, Depends(get_current_user_id)]
SessionStoreDep = Annotated[SessionStore, Depends(get_session_store)]


def get_governance_service(session: SessionDep) -> GovernanceService:
    return GovernanceService(MembershipResolver(session), AuditRepository(session))


GovernanceDep = Annotated[GovernanceService, Depends(get_governance_service)]


async def get_current_principal(
    request: Request,
    session: SessionDep,
    user_id: UserIdDep,
    store: SessionStoreDep,
) -> AsyncIterator[Principal]:
    """Who is asking, where, and as what — resolved fresh on every request.

    Four steps, in this order:

    1. The active workspace comes from the server-side session. Never from a
       URL, a header or a body (architecture rule 3). A client may ASK to
       switch, through POST /workspaces/{id}/switch; it can never ASSERT
       where it already is.
    2. The membership is read from the database, now. Not from the session,
       not from a cache. This is what makes removing someone take effect on
       their next request rather than at their next sign-in.
    3. The workspace's lifecycle state is attached, so the route-level checks
       can refuse writes on a suspended workspace without querying again.
    4. The request body runs inside `workspace_scope`, so every query it
       makes is filtered by the scope guard — and inside `hidden_entities`
       (LEKA-402): what this person's role may not see of the company model
       is left out of every query, whichever route serves it.

    A dependency with `yield`, because step 4 has to wrap the handler. When
    the response is done the scope is released — it never leaks onto the next
    request sharing this worker.
    """
    workspace_id = await store.get_active_workspace(request)
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("No active workspace. Choose one with POST /api/v1/workspaces/{id}/switch."),
        )

    memberships = MembershipResolver(session)
    membership = await memberships.get_for_user_in_workspace(user_id, workspace_id)
    if membership is None:
        # Deliberately the same answer as "this workspace does not exist":
        # distinguishing them would tell an outsider which workspace ids are
        # real.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this workspace.",
        )

    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:  # pragma: no cover - a membership cannot outlive it
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this workspace.",
        )

    with workspace_scope(workspace_id):
        # A role of the workspace's own, the policies in force (LEKA-403):
        # read now, like the seat.
        held = await standing(session, workspace_id, user_id, membership.role)
        principal = Principal(
            user_id=user_id,
            workspace_id=workspace_id,
            role=membership.role,
            workspace_status=workspace.status,
            workspace_demo=workspace.demo,
            custom_role=held.custom_role,
            granted=held.granted,
            policies=held.policies,
        )
        hidden = await hidden_for(session, workspace_id, principal.permissions)
        # What the request has models do is done for them (LEKA-406).
        with hidden_entities(hidden), acting(Actor.of(Subject.of(principal))):
            yield principal


# Ends with the handler, like the database session it depends on — FastAPI
# refuses a dependency that outlives one it depends on. It is also what the
# docstring above always meant: the workspace scope wraps the handler.
PrincipalDep = Annotated[Principal, Depends(get_current_principal, scope="function")]


def _refuse(error: AuthorisationError) -> HTTPException:
    """403 with a reason, never 404.

    A suspended customer told "not found" goes looking for lost data. Told
    "suspended", they go and pay the invoice.
    """
    return HTTPException(status_code=error.status_code, detail=error.reason)


def require_role(
    minimum: Role,
) -> Callable[[Principal], Coroutine[Any, Any, Principal]]:
    """Require a role at or above `minimum`.

        @router.delete("/current")
        async def delete(principal: Annotated[Principal, Depends(require_role(Role.OWNER))]):

    Roles are a chain, so require_role(ADMIN) admits an owner too. Listing
    both at every call site is how OWNER eventually gets left out of one.
    """

    async def dependency(principal: PrincipalDep) -> Principal:
        try:
            check_role(principal, minimum)
        except AuthorisationError as error:
            raise _refuse(error) from error
        return principal

    return dependency


def require_permission(
    permission: Permission,
) -> Callable[..., Coroutine[Any, Any, Principal]]:
    """Require one named permission, and a workspace able to serve it.

    Preferred over require_role for anything that writes: it also runs the
    lifecycle check, so a suspended workspace refuses the write here rather
    than in whichever service remembered to look.
    """

    async def dependency(
        request: Request, principal: PrincipalDep, session: SessionDep
    ) -> Principal:
        decided = evaluate(Subject.of(principal), permission)
        route = f"{request.method} {request.url.path}"
        if not decided.allowed:
            # Kept apart: the refusal rolls the request back, not the trail.
            await record_apart(
                principal.workspace_id, principal.user_id, principal.role, decided, route=route
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decided.message)
        if worth_keeping(decided):
            record(
                session,
                principal.workspace_id,
                principal.user_id,
                principal.role,
                decided,
                route=route,
            )
        return principal

    return dependency
