"""The model each agent runs on, and LEKA's own work's (LEKA-530):
agents/models.yaml, chosen and validated by the LEKA team.

    assigned(purpose)   what a call runs on: `agent:<key>[:<step>]` its
                        agent's model and the fallbacks approved for it;
                        anything else, LEKA's own work's — the same model for
                        every step, never one chosen per task
    trial()             LEKA_LLM_TRIAL_MODEL: one model for all, outside
                        production — a candidate tried, a machine without the
                        assigned model's key
    problems()          what the file gets wrong: an agent of the registry
                        without its line, a model LEKA does not know —
                        said, for the test that keeps it whole

A model changes here, by a pull request that carries its comparative tests;
never by an environment variable, never by a customer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from leka.capabilities.gateway.contract import provider
from leka.capabilities.gateway.profiles import profile
from leka.core.config import settings

FILE = "models.yaml"
AGENT = "agent:"

Model = tuple[str, str]


class AssignmentError(ValueError):
    """agents/models.yaml cannot be read as it is: what is wrong."""


@dataclass(frozen=True)
class Assignment:
    """A model and the fallbacks approved for the same work, in order."""

    model: Model
    fallbacks: tuple[Model, ...] = ()
    # LEKA_LLM_TRIAL_MODEL in its place: said in what is kept of each call.
    trial: bool = False

    def models(self) -> tuple[Model, ...]:
        return (self.model, *self.fallbacks)


@dataclass(frozen=True)
class Assignments:
    operations: Assignment
    agents: Mapping[str, Assignment]


def model_of(said: object, where: str) -> Model:
    """A model said as provider:model, as a pair — refused when it is not one."""
    if not isinstance(said, str) or ":" not in said:
        msg = f"{where}: say a model as provider:model, not {said!r}"
        raise AssignmentError(msg)
    name, _, model = (part.strip() for part in said.partition(":"))
    if provider(name) is None or not model:
        msg = f"{where}: {said!r} is no provider:model LEKA can reach"
        raise AssignmentError(msg)
    return name, model


def _assignment(entry: object, where: str) -> Assignment:
    if not isinstance(entry, Mapping):
        msg = f"{where}: a model and its fallbacks, not {entry!r}"
        raise AssignmentError(msg)
    fallbacks = entry.get("fallbacks") or []
    if not isinstance(fallbacks, list):
        msg = f"{where}: fallbacks are a list"
        raise AssignmentError(msg)
    return Assignment(
        model=model_of(entry.get("model"), f"{where}.model"),
        fallbacks=tuple(model_of(f, f"{where}.fallbacks") for f in fallbacks),
    )


def read(path: Path) -> Assignments:
    """agents/models.yaml as LEKA uses it — refused whole when wrong."""
    try:
        said: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        msg = f"{path}: cannot be read ({error})"
        raise AssignmentError(msg) from error
    if not isinstance(said, Mapping) or said.get("version") != 1:
        msg = f"{path}: version 1 expected"
        raise AssignmentError(msg)
    agents = said.get("agents") or {}
    if not isinstance(agents, Mapping):
        msg = f"{path}: agents are a mapping of each agent's key to its model"
        raise AssignmentError(msg)
    return Assignments(
        operations=_assignment(said.get("operations"), "operations"),
        agents={str(key): _assignment(entry, f"agents.{key}") for key, entry in agents.items()},
    )


@cache
def assignments() -> Assignments:
    """The file, read once per process."""
    return read(settings.agents_dir / FILE)


def trial() -> Assignment | None:
    """LEKA_LLM_TRIAL_MODEL, outside production only (config.py refuses it
    there): every agent on it, no fallback."""
    if not settings.llm_trial_model:
        return None
    return Assignment(model=model_of(settings.llm_trial_model, "LEKA_LLM_TRIAL_MODEL"), trial=True)


def agent_of(purpose: str | None) -> str | None:
    """The agent a call is made for — `agent:code-change:repair` is
    code-change's — or None: LEKA's own work."""
    if not purpose or not purpose.startswith(AGENT):
        return None
    return purpose[len(AGENT) :].split(":", 1)[0] or None


def assigned(purpose: str | None = None) -> Assignment:
    """The model a call runs on, and its approved fallbacks."""
    tried = trial()
    if tried is not None:
        return tried
    found = assignments()
    agent = agent_of(purpose)
    return found.agents.get(agent, found.operations) if agent else found.operations


def every_model() -> set[Model]:
    """Every model the file names: those LEKA must be able to reach."""
    found = assignments()
    tried = trial()
    if tried is not None:
        return {tried.model}
    return {model for each in (found.operations, *found.agents.values()) for model in each.models()}


def problems(agents: Iterable[str]) -> list[str]:
    """What the file gets wrong against these agents — none when whole."""
    found = assignments()
    said = [f"{key}: no model assigned" for key in sorted(set(agents) - set(found.agents))]
    said += [f"{key}: no such agent" for key in sorted(set(found.agents) - set(agents))]
    for where, each in (("operations", found.operations), *found.agents.items()):
        for name, model in each.models():
            if not profile(name, model).known:
                said.append(f"{where}: {name}:{model} is a model LEKA does not know")
    return said


__all__ = [
    "Assignment",
    "AssignmentError",
    "Assignments",
    "agent_of",
    "assigned",
    "assignments",
    "every_model",
    "problems",
    "read",
    "trial",
]
