"""What the API says of a demonstration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from leka.platform import WorkspaceSummary


class DemoRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace: WorkspaceSummary
    created: bool = Field(description="Made now: its sources are being read.")
