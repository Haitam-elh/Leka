"""Types the platform module exposes over its boundary.

Request and response shapes for tenancy. Deliberately not mirrors of the
tables: `Workspace` carries a deletion timestamp and a settings blob that no
client needs to see, and a client must never be able to set a status by
sending one.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from leka.core import languages
from leka.platform.models import InvitationStatus, Role, WorkspaceStatus


class WorkspaceCreate(BaseModel):
    """What a client may say when creating a workspace.

    A name, and nothing else. The slug is derived, the status is `active` by
    definition, and the owner is whoever is making the request — a field for
    any of those would be a field a client could get wrong or abuse.
    """

    name: str = Field(min_length=1, max_length=200)
    # The language of what is shared in it; its creator's when not said.
    default_language: str | None = Field(default=None, max_length=35)

    @field_validator("default_language")
    @classmethod
    def _language(cls, value: str | None) -> str | None:
        return languages.listed(value) if value is not None else None


class DefaultPeriod(BaseModel):
    """The period an analysis looks at unless told otherwise: a preset, or
    its own dates."""

    model_config = ConfigDict(extra="forbid")

    preset: Literal["24h", "7d", "30d", "custom"]
    start: date | None = Field(default=None, alias="from")
    end: date | None = Field(default=None, alias="to")

    @model_validator(mode="after")
    def _dated(self) -> DefaultPeriod:
        if self.preset == "custom" and (
            self.start is None or self.end is None or self.start > self.end
        ):
            msg = "a custom period takes a start no later than its end"
            raise ValueError(msg)
        return self


class WorkspacePreferences(BaseModel):
    """The preferences an admin sets in Paramètres → Votre espace (LEKA-502).
    Only these: the policies kept in the same column have their own routes,
    their own permission and their own checks."""

    model_config = ConfigDict(extra="forbid")

    timezone: str | None = None
    default_environment: Literal["production", "staging", "dev"] | None = None
    default_period: DefaultPeriod | None = None

    @field_validator("timezone")
    @classmethod
    def _zone(cls, value: str | None) -> str | None:
        if value is not None and value not in available_timezones():
            msg = f"unknown time zone {value!r}"
            raise ValueError(msg)
        return value


class WorkspaceUpdate(BaseModel):
    """What may be changed later.

    Not the slug: it is already in links, bookmarks and other people's
    documentation. Not the status: lifecycle transitions have their own
    routes, with their own permissions.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    settings: WorkspacePreferences | None = None
    default_language: str | None = Field(default=None, max_length=35)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            msg = "a name is not only spaces"
            raise ValueError(msg)
        return value.strip()

    @field_validator("default_language")
    @classmethod
    def _language(cls, value: str | None) -> str | None:
        return languages.listed(value) if value is not None else None


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    status: WorkspaceStatus
    settings: dict[str, object]
    default_language: str
    created_at: datetime
    # A demonstration, its data fictive (LEKA-449).
    demo: bool = False


class WorkspaceSummary(BaseModel):
    """A workspace as it appears in the switcher: where I may go, and as what."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    slug: str
    status: WorkspaceStatus
    role: Role
    demo: bool = False


class CurrentWorkspace(BaseModel):
    """The active workspace and the caller's standing in it."""

    model_config = ConfigDict(frozen=True)

    workspace: WorkspaceRead
    role: Role
    permissions: list[str]


class MemberRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    role: Role
    created_at: datetime


class MemberRoleUpdate(BaseModel):
    role: Role


class InvitationCreate(BaseModel):
    """An invitation request.

    The address is checked shallowly on purpose. Pydantic's EmailStr would
    need the email-validator package, and RFC-correct validation buys little
    here: the real test of an address is whether the invitation arrives, and
    an invitation nobody receives is visibly pending. What this rejects is
    the typo that is obviously not an address.
    """

    email: str = Field(min_length=3, max_length=320)
    role: Role = Role.MEMBER

    @field_validator("email")
    @classmethod
    def _looks_like_an_address(cls, value: str) -> str:
        candidate = value.strip().lower()
        local, separator, domain = candidate.partition("@")
        # No whitespace inside: « a@b.com\nxyz » was taken, then mailed (LEKA-469).
        blank = any(char.isspace() or not char.isprintable() for char in candidate)
        if blank or not separator or not local or "." not in domain or domain.startswith("."):
            msg = f"{value!r} is not an email address"
            raise ValueError(msg)
        return candidate


class InvitationRead(BaseModel):
    """An invitation as anyone but the invitee sees it.

    No token, not even hashed. The clear value is returned exactly once, by
    the route that creates it, so it can be emailed.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    email: str
    role: Role
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime


class InvitationCreated(BaseModel):
    """The one response that carries the clear token.

    It exists so the caller can send the email. Nothing persists it, and no
    other route will ever return it again.
    """

    model_config = ConfigDict(frozen=True)

    invitation: InvitationRead
    token: str


class DeletionScheduled(BaseModel):
    """What a customer gets back when they ask to be erased."""

    model_config = ConfigDict(frozen=True)

    workspace_id: uuid.UUID
    deletion_requested_at: datetime
    erasure_due_at: datetime
