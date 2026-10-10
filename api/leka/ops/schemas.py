"""Types crossing the boundary of the operations module (LEKA-408)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ComponentRead(BaseModel):
    name: str
    status: Literal["ok", "degraded", "down"]
    detail: str | None


class OpsHealthRead(BaseModel):
    status: Literal["ok", "degraded", "down"]
    components: list[ComponentRead]
