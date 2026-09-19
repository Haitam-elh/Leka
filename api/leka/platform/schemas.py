"""Types the platform module exposes."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class WorkspaceRead(BaseModel):
    """A workspace as it leaves the module."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
