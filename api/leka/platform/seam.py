"""The contract between LEKA-331 (where you may go) and LEKA-330 (who you are).

Two tickets are being built in parallel. This module is the only place they
touch, and neither of us edits the other's files.

**LEKA-330 owns the implementations.** Everything here is a Protocol plus a
default that refuses to work. Bilal replaces the defaults with FastAPI
dependency overrides — `app.dependency_overrides[get_current_user_id] = ...`
— without a single line of LEKA-331 changing.

It lives in leka.platform rather than leka.identity on purpose. The obvious
home would be identity's `__init__.py`, which is also the file LEKA-330 is
certain to rewrite: putting this there guarantees the merge conflict the
territory split exists to prevent. platform is below both modules in the
dependency order, so identity and governance can each import it without
reversing anything.
"""

from __future__ import annotations

import uuid
from typing import NewType, Protocol, runtime_checkable

from fastapi import Request

# A user's identifier, distinct from a workspace's. Both are UUIDs, and
# passing one where the other belongs is the kind of mistake a type checker
# should catch rather than a customer.
UserId = NewType("UserId", uuid.UUID)
WorkspaceId = NewType("WorkspaceId", uuid.UUID)


class SeamNotImplementedError(NotImplementedError):
    """Raised when LEKA-330 has not plugged in yet.

    Deliberately loud. The alternative — returning a placeholder user — is a
    platform that looks like it works and authorises everyone.
    """


@runtime_checkable
class CurrentUserProvider(Protocol):
    """Answers "who is making this request?".

    Implemented by LEKA-330 from its session. LEKA-331 never reads the users
    table and never parses a cookie.
    """

    async def __call__(self, request: Request) -> UserId: ...


@runtime_checkable
class SessionStore(Protocol):
    """Where the active workspace is kept, server side.

    Architecture rule 3: the workspace never comes from a URL, a header or a
    request body. A client may ASK to switch — that is what
    POST /workspaces/{id}/switch is for — but it can never ASSERT where it
    already is.

    Implemented by LEKA-330 on top of its real session.
    """

    async def get_active_workspace(self, request: Request) -> WorkspaceId | None: ...

    async def set_active_workspace(self, request: Request, workspace_id: WorkspaceId) -> None: ...


async def get_current_user_id(request: Request) -> UserId:
    """FastAPI dependency: the authenticated user.

    LEKA-330 overrides this. Until then, any route that needs a user fails
    with a message naming the ticket rather than a confusing 500.
    """
    msg = (
        "get_current_user_id has no implementation yet. It belongs to LEKA-330 "
        "(Identity & Authentication), which overrides it with "
        "app.dependency_overrides[get_current_user_id]. Tests override it with "
        "a fake user."
    )
    raise SeamNotImplementedError(msg)


async def get_session_store(request: Request) -> SessionStore:
    """FastAPI dependency: where the active workspace is read and written.

    LEKA-330 overrides this with a store backed by its real session.
    """
    msg = (
        "get_session_store has no implementation yet. It belongs to LEKA-330 "
        "(Identity & Authentication), which overrides it with a store backed "
        "by the real session."
    )
    raise SeamNotImplementedError(msg)
