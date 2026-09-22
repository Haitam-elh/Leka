"""Which environment this is, and how it talks about itself."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from leka.core.settings.paths import REPO_ROOT


class RuntimeSettings:
    """Environment, logging, CORS, and where the agent files live."""

    environment: Literal["local", "ci", "staging", "production"] = "local"
    debug: bool = False

    api_v1_prefix: str = "/api/v1"
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"

    # Where the agent markdown files live. Content, not code — see
    # agents/README.md.
    agents_dir: Path = REPO_ROOT / "agents"


__all__ = ["RuntimeSettings"]
