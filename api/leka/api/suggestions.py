"""« Demander une compétence » (LEKA-501): an agent or a skill someone wishes
LEKA had, sent to LEKA's team — never an intention, nothing run on it.

    POST /capability-suggestions   one more (422 empty, 409 duplicate, 429
                                   too many today)
    GET  /capability-suggestions   the workspace's, newest first, where each
                                   stands

Every member may suggest and read them (`workspace:read`). LEKA's team
reads and moves them on the server: leka/capabilities/suggestions.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.capabilities import suggestions
from leka.core.errors import ErrorCode
from leka.governance import Permission, Principal, require_permission

router = APIRouter(prefix="/capability-suggestions", tags=["capabilities"])

Member = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]

REFUSED = {
    "empty": (422, ErrorCode.VALIDATION_FAILED),
    "duplicate": (status.HTTP_409_CONFLICT, ErrorCode.CONFLICT),
    "rate_limited": (status.HTTP_429_TOO_MANY_REQUESTS, ErrorCode.RATE_LIMITED),
}


@router.post("", response_model=suggestions.SuggestionRead, status_code=status.HTTP_201_CREATED)
async def suggest(
    body: suggestions.SuggestionWrite, session: SessionDep, principal: Member
) -> suggestions.SuggestionRead:
    try:
        row = await suggestions.suggest(
            session, principal.workspace_id, principal.user_id, body, now=datetime.now(UTC)
        )
    except suggestions.SuggestionRefusedError as error:
        code, kind = REFUSED[error.code]
        raise ApiError(code, kind, str(error)) from None
    return suggestions.SuggestionRead.model_validate(row)


@router.get("", response_model=list[suggestions.SuggestionRead])
async def read(session: SessionDep, principal: Member) -> list[suggestions.SuggestionRead]:
    rows = await suggestions.listed(session, principal.workspace_id)
    return [suggestions.SuggestionRead.model_validate(r) for r in rows]
