"""The notification centre (LEKA-476).

    GET    /notifications               one's notifications, the latest first,
                                        a page at a time — by category, the
                                        unread only — and how many are unread
    GET    /notifications/unread        how many are unread: the bell's count
    POST   /notifications/{id}/read     read
    DELETE /notifications/{id}/read     unread again
    POST   /notifications/read          every one shown read — of a
                                        category, or all
    GET    /notifications/preferences   what one does not want told here
    PUT    /notifications/preferences

Every member reads their own (`workspace:read`). What is new in the
workspace is read into notifications first — from what its systems kept,
once each (leka.notifications.projector). What one may see is judged as
they read: them by name, a permission they hold now, or every member.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.core.errors import ErrorCode
from leka.governance import Permission, Principal, require_permission
from leka.notifications import (
    Category,
    CursorError,
    MarkAll,
    Marked,
    NotificationPage,
    NotificationPreferences,
    Notifications,
    UnreadCount,
    project,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]


def _missing() -> ApiError:
    return ApiError(
        status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such notification of yours."
    )


@router.get("", response_model=NotificationPage)
async def list_notifications(
    principal: Reader,
    session: SessionDep,
    category: Category | None = None,
    unread: Annotated[bool, Query(description="The unread only.")] = False,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> NotificationPage:
    """One's notifications, the latest first. What is new is read in first."""
    await project(session, principal.workspace_id)
    try:
        return await Notifications(session, principal).page(
            category=category, unread=unread, cursor=cursor, limit=limit
        )
    except CursorError as error:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_CURSOR, "Not a cursor of this list."
        ) from error


@router.get("/unread", response_model=UnreadCount)
async def unread_count(principal: Reader, session: SessionDep) -> UnreadCount:
    """How many are unread — the bell's count. What is new is read in first."""
    await project(session, principal.workspace_id)
    return UnreadCount(unread=await Notifications(session, principal).unread())


@router.post("/read", response_model=Marked)
async def mark_all_read(body: MarkAll, principal: Reader, session: SessionDep) -> Marked:
    """Every one shown to them, unread, read now — of a category, or all."""
    return Marked(marked=await Notifications(session, principal).mark_all(category=body.category))


@router.post(
    "/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def mark_read(notification_id: uuid.UUID, principal: Reader, session: SessionDep) -> Response:
    """Read. 404 when it is not one of theirs."""
    if not await Notifications(session, principal).mark(notification_id, read=True):
        raise _missing()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def mark_unread(
    notification_id: uuid.UUID, principal: Reader, session: SessionDep
) -> Response:
    """Unread again. 404 when it is not one of theirs."""
    if not await Notifications(session, principal).mark(notification_id, read=False):
        raise _missing()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/preferences", response_model=NotificationPreferences)
async def preferences(principal: Reader, session: SessionDep) -> NotificationPreferences:
    """What one does not want told here, by category."""
    return NotificationPreferences.model_validate(
        {"muted": await Notifications(session, principal).muted()}
    )


@router.put("/preferences", response_model=NotificationPreferences)
async def set_preferences(
    body: NotificationPreferences, principal: Reader, session: SessionDep
) -> NotificationPreferences:
    """Muted here, told no more in the centre; the rest, told."""
    muted = await Notifications(session, principal).set_muted(list(body.muted))
    return NotificationPreferences.model_validate({"muted": muted})
