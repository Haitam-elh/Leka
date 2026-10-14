"""The demonstration (LEKA-449): opened, or started afresh — and entered.

No principal: like creating a workspace, it is asked by someone who may be
in none yet. The demonstration is theirs alone; once it exists the session
is moved into it, as /workspaces/{id}/switch would, so the next screen is
Nova Retail's. Leaving it is switching back to one's own workspace.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from leka.api.dependencies import SessionDep, SessionStoreDep, UserIdDep
from leka.demo import DemoRead, DemoService
from leka.identity import UserRepository
from leka.platform import Role, WorkspaceId, WorkspaceSummary

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
