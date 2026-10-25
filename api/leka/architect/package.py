"""The downloadable architect, packed: a zip a person unpacks and installs
with `pip install ./leka-architect`, or builds with Docker — the code of
this very package, renamed leka_architect, and what ships with it
(distribution.py). LEKA builds it on the fly for an organisation the agent
is dedicated to (GET /capabilities/application-architecture/package);
scripts/build_architect.py writes it to disk.

No secret is ever in it: its .env is an example, empty.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from . import __version__
from .distribution import CLAUDE_CODE, DOCKERFILE, ENV_EXAMPLE, MCP, PYPROJECT, README, prompt_pack

ROOT = "leka-architect"
HERE = Path(__file__).resolve().parent


def files() -> dict[str, bytes]:
    """Every file of the package, by its path in the zip."""
    found: dict[str, bytes] = {}
    for source in sorted(HERE.glob("*.py")):
        found[f"{ROOT}/leka_architect/{source.name}"] = source.read_bytes()
    found[f"{ROOT}/pyproject.toml"] = PYPROJECT.encode()
    found[f"{ROOT}/README.md"] = README.encode()
    found[f"{ROOT}/.env.example"] = ENV_EXAMPLE.encode()
    found[f"{ROOT}/Dockerfile"] = DOCKERFILE.encode()
    for name, config in MCP.items():
        found[f"{ROOT}/mcp/{name}"] = (json.dumps(config, indent=2) + "\n").encode()
    found[f"{ROOT}/mcp/claude-code.txt"] = (CLAUDE_CODE + "\n").encode()
    for name, text in prompt_pack().items():
        found[f"{ROOT}/prompts/{name}"] = text.encode()
    return found


def build_zip() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path, data in files().items():
            zipped.writestr(path, data)
    return out.getvalue()


def file_name() -> str:
    return f"leka-architect-{__version__}.zip"


__all__ = ["ROOT", "build_zip", "file_name", "files"]
