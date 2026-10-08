"""Every capability LEKA has, as definitions (LEKA-393): the agents read
from agents/ (ADR 004) and what the modules above declare of their own —
the analysis's rules (LEKA-388) — each checked against what LEKA knows: its
entity types, its source kinds, its permissions.

    agents/**/SKILL.md ─┐
    registry.yaml ──────┤  (an agent's status: its lifecycle)
    provide(…) ─────────┴─▶ definitions() ─▶ the catalogue's history (catalogue.py)

A module above this one declares its capabilities with `provide`, when it
is imported — as leka/schema.py imports every module for its tables, every
process imports the modules whose capabilities it serves. Nothing here
imports them: capabilities sits below them (tests/test_module_boundaries.py).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import cache
from pathlib import Path

from leka.capabilities.definition import (
    Contract,
    Definition,
    DefinitionError,
    Input,
    Kind,
    Lifecycle,
    validated,
)
from leka.capabilities.loader import AgentLoadError, load_all, read_index
from leka.capabilities.schemas import Agent
from leka.connectors import SourceKind
from leka.core.config import settings
from leka.governance import Permission
from leka.knowledge import EntityType

Provider = Callable[[], Sequence[Definition]]
_providers: dict[str, Provider] = {}


def provide(name: str, provider: Provider) -> None:
    """A module's own capabilities, declared once by name."""
    _providers[name] = provider
    catalogue.cache_clear()


def model_ready() -> bool:
    """Whether an agent can be run by a model now. Not before the model
    gateway (LEKA-394): an agent is registered, described, never run."""
    return False


def agent_definition(agent: Agent, lifecycle: Lifecycle) -> Definition:
    head = agent.front_matter
    return Definition(
        key=head.name,
        title=head.title or head.name.replace("-", " ").capitalize(),
        summary=head.description,
        category=head.category,
        kind=Kind.AGENT,
        version=head.version,
        lifecycle=lifecycle,
        origin=head.origin,
        contract=Contract(
            inputs=tuple(
                Input(
                    name=i.name,
                    type=i.type,
                    required=i.required,
                    description=i.description,
                    choices=i.choices,
                    entity_types=i.entity_types,
                )
                for i in head.inputs
            ),
            output=head.outputs,
            formats=head.deliverables or ("json",),
        ),
        sources=tuple(tuple(part.strip() for part in r.split("|")) for r in head.requires),
        model=True,
        permission=head.permission,
        mode=head.mode.value,
        risk=head.risk.value,
        goals=frozenset(head.goals),
        kinds=frozenset(head.kinds),
        entity_types=head.entity_types,
        examples=head.examples,
        instructions=agent.body,
        path=agent.path,
    )


def agents(agents_dir: Path) -> list[Definition]:
    """The agents under agents/, each with the status registry.yaml gives
    it — draft when it gives none: an agent goes live by being indexed. The
    index's version is the file's, or nothing loads."""
    index = read_index(agents_dir)
    found: list[Definition] = []
    for agent in load_all(agents_dir).all():
        relative = Path(agent.path).resolve().relative_to(agents_dir.resolve()).as_posix()
        version, status = index.get(relative, (agent.front_matter.version, "draft"))
        if version != agent.front_matter.version:
            msg = f"{relative}: registry.yaml says {version}, the file {agent.front_matter.version}"
            raise AgentLoadError(msg)
        try:
            lifecycle = Lifecycle(status or "draft")
        except ValueError as exc:
            msg = f"{relative}: unknown status {status!r} in registry.yaml"
            raise AgentLoadError(msg) from exc
        found.append(agent_definition(agent, lifecycle))
    return found


def definitions(agents_dir: Path | None = None) -> list[Definition]:
    """Every capability, checked — a duplicate key, or one that names what
    LEKA does not know, refuses them all: a catalogue with a capability
    silently missing is worse than one that does not load."""
    found = agents(agents_dir or settings.agents_dir)
    for name in sorted(_providers):
        found.extend(_providers[name]())
    keys: set[str] = set()
    for definition in found:
        if definition.key in keys:
            msg = f"two capabilities are called {definition.key!r}"
            raise DefinitionError(msg)
        keys.add(definition.key)
        validated(
            definition,
            entity_types=[t.value for t in EntityType],
            source_kinds=[k.value for k in SourceKind],
            permissions=[p.value for p in Permission],
        )
    return sorted(found, key=lambda d: d.key)


@cache
def catalogue() -> tuple[Definition, ...]:
    """The process's capabilities, read once."""
    return tuple(definitions())


def find(key: str) -> Definition | None:
    return next((d for d in catalogue() if d.key == key), None)
