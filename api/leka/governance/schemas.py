"""Types governance exposes.

Permissions are expressed as a role plus an action, resolved server side.
The caller never states its own workspace — rule 3.
"""

from __future__ import annotations

import enum
import uuid

from pydantic import BaseModel, ConfigDict


class Role(enum.StrEnum):
    """Matches the membership_role enum in migration 001.

    LEKA-330 may extend this list; it does so in a migration and here, in the
    same pull request.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Principal(BaseModel):
    """Who is making this request, and in which workspace.

    Built server side from the session. Never from a URL or a request body —
    a client that can name its own workspace can name someone else's.
    """

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: Role
