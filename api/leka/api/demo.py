"""The demonstration (LEKA-449): opened, or started afresh — and entered.

No principal: like creating a workspace, it is asked by someone who may be
in none yet. The demonstration is theirs alone; once it exists the session
is moved into it, as /workspaces/{id}/switch would, so the next screen is
Nova Retail's. Leaving it is switching back to one's own workspace.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from leka.api.dependencies import SessionDep, SessionStoreDep, UserIdDep
from leka.api.errors import ApiError
from leka.core.errors import ErrorCode
from leka.demo import DemoRead, DemoService
from leka.governance import Permission, Principal, require_permission
from leka.identity import UserRepository
from leka.platform import Role, WorkspaceId, WorkspaceRepository, WorkspaceSummary

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("", response_model=DemoRead, status_code=status.HTTP_200_OK)
async def open_demo(
    request: Request,
    user_id: UserIdDep,
    store: SessionStoreDep,
    db: SessionDep,
    fresh: bool = False,
) -> DemoRead:
    """My demonstration, made when I have none — `fresh`: the one before
    erased, a new one made — and the session moved into it."""
    person = await UserRepository(db).get(user_id)
    workspace, created = await DemoService(db).open(
        user_id, language=person.language if person else None, fresh=fresh
    )
    await store.set_active_workspace(request, WorkspaceId(workspace.id))
    return DemoRead(
        workspace=WorkspaceSummary(
            id=workspace.id,
            name=workspace.name,
            slug=workspace.slug,
            status=workspace.status,
            role=Role.OWNER,
            demo=True,
        ),
        created=created,
    )


class DemoActivated(BaseModel):
    activated: bool


@router.post("/activate", response_model=DemoActivated)
async def simulate_payment(
    db: SessionDep,
    principal: Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))],
) -> DemoActivated:
    """« Paiement simulé » (LEKA-498): in the demonstration one is in, what a
    payment would give — a plan that runs agents, every agent — so an
    analysis goes on to its result. No payment, nothing outside it; done
    twice, the same. 403 anywhere else: a real workspace pays with Stripe."""
    workspace = await WorkspaceRepository(db).get(principal.workspace_id)
    if workspace is None or not await DemoService(db).activate(workspace, by=principal.user_id):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.PERMISSION_DENIED,
            "Only a demonstration is activated without paying.",
        )
    await db.commit()
    return DemoActivated(activated=True)
