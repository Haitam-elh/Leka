"""What an agent reads of its own method while it runs — the guides of the
library its front matter names (`method:`, agents/_library/README.md): their
index, or one guide's text. LEKA's content, not a workspace's: the same for
every company, read from agents/ as the agent itself is. Offered only to an
agent that names the tool (`tools:`) and has a library, never by default.

    read_method   no path: the library's files, each with what it is for;
                  a path from that index: the file's text — a .md file under
                  the library, never anything outside it

Too long to be an agent's instructions, a library is read a guide at a time,
when the agent needs it — as a designer opens the right book.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from leka.capabilities.definition import Definition
from leka.capabilities.runtime import AgentTool
from leka.capabilities.tools import Answer, Handler

# What a guide gives the model, at most: the longest is 41 KB.
MOST_CHARS = 60_000
# What the index says a guide is for, at most.
MOST_ABOUT = 400

READ_METHOD = AgentTool(
    name="read_method",
    description=(
        "Your method's guides — the library your instructions name. Without a path: every "
        "file, with what it is for. With a path from that index: the file's text. Load a "
        "guide before you judge in its domain; take its values from it, never from memory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "A file of the index, e.g. « skills/animate/SKILL.md »; "
                "empty for the index.",
            }
        },
    },
    permission="workspace:read",
)

METHOD_TOOLS: tuple[AgentTool, ...] = (READ_METHOD,)
METHOD_NAMES = frozenset(t.name for t in METHOD_TOOLS)


def _said(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


def guide(root: Path, asked: str) -> Path | None:
    """A guide of the library: a .md file under it — None for anything else:
    a path that leaves it (`..`, absolute, a link out), a directory, another
    kind of file, nothing."""
    said = asked.strip()
    if not said or said.startswith(("/", "~")) or "\\" in said or "\x00" in said:
        return None
    base = root.resolve()
    path = (base / said).resolve()
    if not path.is_relative_to(base) or path.suffix != ".md" or not path.is_file():
        return None
    return path


def about(text: str) -> str:
    """What a guide is for: its front matter's description, or else its
    title and first line."""
    if text.startswith("---"):
        head = text.split("---", 2)
        if len(head) == 3:
            try:
                said = yaml.safe_load(head[1])
            except yaml.YAMLError:
                said = None
            described = said.get("description") if isinstance(said, dict) else None
            if isinstance(described, str):
                return described[:MOST_ABOUT]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = next((line.lstrip("# ") for line in lines if line.startswith("#")), "")
    first = next((line for line in lines if not line.startswith(("#", "<", "!", "["))), "")
    return ": ".join(part for part in (title, first) if part)[:MOST_ABOUT]


@cache
def index(root: Path) -> tuple[Mapping[str, object], ...]:
    """Every guide of a library, by path, with what it is for and its
    length — read once: a library changes only with a deployment."""
    base = root.resolve()
    found: list[Mapping[str, object]] = []
    for path in sorted(base.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        found.append(
            {
                "path": path.relative_to(base).as_posix(),
                "about": about(text),
                "lines": text.count("\n") + 1,
            }
        )
    return tuple(found)


def method_handlers(definition: Definition, agents_dir: Path) -> dict[str, Handler]:
    """read_method, bound to the library the agent names — none without one."""
    if definition.method is None:
        return {}
    root = agents_dir / definition.method

    async def read_method(arguments: Mapping[str, Any]) -> Answer:
        asked = str(arguments.get("path") or "").strip()
        if not asked:
            return Answer(_said({"library": definition.method, "files": list(index(root))}), "ok")
        path = guide(root, asked)
        if path is None:
            return Answer(
                _said({"error": "not_in_method", "path": asked[:200]}),
                "refused",
                "not_in_method",
            )
        text = path.read_text(encoding="utf-8")
        return Answer(
            _said(
                {
                    "path": path.relative_to(root.resolve()).as_posix(),
                    "text": text[:MOST_CHARS],
                    "truncated": len(text) > MOST_CHARS,
                }
            ),
            "ok",
        )

    return {READ_METHOD.name: read_method}
