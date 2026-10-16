"""Reads agents/, validates them, registers them.

The loader reads CONTENT from agents/ — it never contains an agent
(architecture rule 8). Adding an agent is adding a file, not deploying code.

This is the skeleton: reading, parsing, validating and registering. Running
an agent is not here and is not implemented.
"""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml
from pydantic import ValidationError

from leka.capabilities.schemas import Agent, AgentFrontMatter

logger = structlog.get_logger(__name__)

FRONT_MATTER_DELIMITER = "---"
SKILL_FILENAME = "SKILL.md"
INDEX_FILENAME = "registry.yaml"


class AgentLoadError(Exception):
    """An agent file exists but cannot be trusted.

    Raised rather than logged-and-skipped when loading is strict: an agent
    silently missing from the registry is a feature that stops working with
    no error anywhere.
    """


def split_front_matter(text: str) -> tuple[str, str]:
    """Separate the YAML header from the markdown body.

    Returns (yaml_text, body). Raises if the file does not open with a
    front-matter block — a SKILL.md without a header is not an agent.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        msg = "file does not start with a '---' front matter block"
        raise AgentLoadError(msg)

    try:
        closing = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == FRONT_MATTER_DELIMITER
        )
    except StopIteration:
        msg = "front matter block is never closed with '---'"
        raise AgentLoadError(msg) from None

    return "\n".join(lines[1:closing]), "\n".join(lines[closing + 1 :]).strip()


def parse_agent(path: Path) -> Agent:
    """Read one SKILL.md and validate its header."""
    yaml_text, body = split_front_matter(path.read_text(encoding="utf-8"))

    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        msg = f"front matter is not valid YAML: {exc}"
        raise AgentLoadError(msg) from exc

    if not isinstance(raw, dict):
        msg = f"front matter must be a mapping, got {type(raw).__name__}"
        raise AgentLoadError(msg)

    try:
        front_matter = AgentFrontMatter(**raw)
    except ValidationError as exc:
        msg = f"invalid front matter: {exc}"
        raise AgentLoadError(msg) from exc

    return Agent(front_matter=front_matter, body=body, path=str(path))


def discover(agents_dir: Path) -> list[Path]:
    """Every SKILL.md under agents/, except under a directory named `_…`.

    _template/ is skipped: it is a file to copy, not an agent, and its
    placeholder header would fail validation — which is what we want it to
    do if someone forgets to fill it in. _library/ is skipped too: the
    guides an agent reads while it runs (`method:`, `read_method`), never
    agents of their own (agents/_library/README.md).
    """
    return sorted(
        path
        for path in agents_dir.rglob(SKILL_FILENAME)
        if not any(part.startswith("_") for part in path.relative_to(agents_dir).parts)
    )


class AgentRegistry:
    """Every valid agent, indexed by name.

    Built once on startup. An agent is matched against a situation on its
    `description` — which is why that field is the one this module validates
    most strictly.
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        name = agent.front_matter.name
        if name in self._agents:
            msg = f"duplicate agent name {name!r}: {self._agents[name].path} and {agent.path}"
            raise AgentLoadError(msg)
        self._agents[name] = agent

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def all(self) -> list[Agent]:
        return list(self._agents.values())

    def __len__(self) -> int:
        return len(self._agents)


def read_index(agents_dir: Path) -> dict[str, tuple[str, str]]:
    """registry.yaml: each agent's path, relative to agents/, with the
    version and the status (LEKA-393: its lifecycle) recorded there."""
    path = agents_dir / INDEX_FILENAME
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        msg = f"{INDEX_FILENAME} is not valid YAML: {exc}"
        raise AgentLoadError(msg) from exc
    found: dict[str, tuple[str, str]] = {}
    for entry in raw.get("agents") or []:
        if not isinstance(entry, dict) or "path" not in entry:
            msg = f"{INDEX_FILENAME}: an entry without its path"
            raise AgentLoadError(msg)
        found[str(entry["path"])] = (str(entry.get("version", "")), str(entry.get("status", "")))
    return found


def load_all(agents_dir: Path, *, strict: bool = True) -> AgentRegistry:
    """Load every agent under agents_dir.

    strict=True (the default, and what the application uses on startup):
    one bad file stops the process. A platform that boots with half its
    agents missing is worse than one that refuses to boot.

    strict=False is for tooling that wants to report on every file rather
    than stop at the first problem.
    """
    registry = AgentRegistry()
    for path in discover(agents_dir):
        try:
            registry.register(parse_agent(path))
        except AgentLoadError:
            logger.exception("agent_load_failed", path=str(path))
            if strict:
                raise
    logger.info("agents_loaded", count=len(registry), directory=str(agents_dir))
    return registry
