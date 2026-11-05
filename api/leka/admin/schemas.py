"""The Admin API's contracts (LEKA-544): what LEKA ADMIN sends and receives.

Independent of any screen: the Android app reads them, a web app will, and
docs/admin/api.md says each in words. Lists come in the API's one envelope
(`{"data": [...], "next_cursor": ...}`), errors in its one error shape
(leka/core/errors.py). A figure LEKA does not have is null and said
unavailable, never 0.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from leka.admin.access import AdminPermission, AdminRole

# ── Signing in ───────────────────────────────────────────────────────────────


class AdminSignIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    # Not length-checked beyond a ceiling: a wrong password of any length is
    # refused by the same answer, never by a 422 saying its shape was wrong.
    password: str = Field(max_length=256)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()


class AdminMe(BaseModel):
    """Who is signed in, and what their role lets them do."""

    id: uuid.UUID
    email: str
    name: str
    role: AdminRole
    permissions: list[AdminPermission] = Field(
        description="What this admin may do; a screen shows only what is in here."
    )


class AdminSignedIn(BaseModel):
    token: str = Field(
        description=(
            "Sent as `Authorization: Bearer <token>` on every call. Shown once: "
            "kept in the device's secure storage, never in the code."
        )
    )
    expires_at: datetime = Field(description="When this session ends, whatever happens.")
    idle_minutes: int = Field(description="It also ends after this long unused.")
    admin: AdminMe


class AdminPrincipal(BaseModel):
    """Who is asking, resolved from the bearer token on every request."""

    model_config = ConfigDict(frozen=True)

    admin_id: uuid.UUID
    email: str
    name: str
    role: AdminRole
    permissions: frozenset[AdminPermission]
    session_id: uuid.UUID
    ip_prefix: str | None = None

    def me(self) -> AdminMe:
        return AdminMe(
            id=self.admin_id,
            email=self.email,
            name=self.name,
            role=self.role,
            permissions=sorted(self.permissions),
        )
