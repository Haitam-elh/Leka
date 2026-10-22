"""Which environment this is, and how it talks about itself."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator

from leka.core.settings.paths import REPO_ROOT


class RuntimeSettings:
    """Environment, logging, CORS, and where the agent files live."""

    environment: Literal["local", "ci", "staging", "production"] = "local"
    debug: bool = False

    api_v1_prefix: str = "/api/v1"
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    # Where people open LEKA — the frontend, not this API. Every link the API
    # sends out (a verification, a password reset) is built on it, so a
    # wrong value is a mailbox full of links to nowhere. In staging and
    # production it must be https and must not be localhost: refused at
    # startup (core/config.py).
    web_url: str = "http://localhost:3000"

    @field_validator("web_url")
    @classmethod
    def _web_url_has_no_trailing_slash(cls, value: str) -> str:
        """ "https://app.leka-core.com/" and without the slash are one address;
        storing one form keeps every link from growing a double slash."""
        if not value.startswith(("http://", "https://")):
            msg = f"LEKA_WEB_URL must start with http:// or https://, got {value!r}"
            raise ValueError(msg)
        return value.rstrip("/")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"

    # Where the agent markdown files live. Content, not code — see
    # agents/README.md.
    agents_dir: Path = REPO_ROOT / "agents"
    # Where the agents look third-party packages' known vulnerabilities up:
    # the public OSV database, free, no key — only public packages' names
    # and versions are sent (capabilities/advisories.py). Empty: never looked
    # up, said not checked.
    advisories_url: str = "https://api.osv.dev"


__all__ = ["RuntimeSettings"]
