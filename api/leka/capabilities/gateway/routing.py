"""Which model answers (LEKA-394, LEKA-530): the one assigned to the work —
never one chosen per task while it runs.

    1. the workspace's own model, under an Enterprise contract that brings
       it — its account; when it said "ours only", nothing else
    2. the model the LEKA team validated for the agent, or for LEKA's own
       work (agents/models.yaml, gateway/assignment.py)
    3. the fallbacks approved for that same agent, in their order — none:
       the agent tries its model again, then says it failed

A model that cannot do what a step asks — a structured answer, tools, a
context that long, a quality that high — is not tried, and why is kept: the
route says what it passed over. The assignment is checked against what each
agent needs (tests/test_model_assignments.py), so that never happens to a
validated agent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from leka.capabilities.gateway.assignment import Assignment
from leka.capabilities.gateway.contract import Endpoint
from leka.capabilities.gateway.profiles import Profile, of_provider, profile


@dataclass(frozen=True)
class Needs:
    """What a task asks of the model that answers it."""

    structured: bool = False
    tools: bool = False
    # Tokens it must take in: the instructions, the context, the question.
    context: int = 0
    # The least quality it accepts (profiles.py: 1 to 3).
    quality: int = 1
    # Images to read: only a model that reads them.
    vision: bool = False

    def unmet(self, model: Profile) -> str | None:
        """Why this model cannot answer — None when it can."""
        if self.structured and not model.structured:
            return "structured"
        if self.tools and not model.tools:
            return "tools"
        if self.context and self.context > model.context:
            return "context"
        if model.quality < self.quality:
            return "quality"
        if self.vision and not model.vision:
            return "vision"
        return None


@dataclass(frozen=True)
class Route:
    endpoint: Endpoint
    profile: Profile
    # own, own_stronger (its provider's best, for what its own model cannot
    # do), assigned, fallback (approved for the agent), trial
    why: str


@dataclass(frozen=True)
class Passed:
    """A model not offered, and why."""

    provider: str
    model: str
    reason: str  # structured, tools, context, quality, vision, exclusive, no_key


@dataclass(frozen=True)
class Routing:
    routes: tuple[Route, ...]
    passed: tuple[Passed, ...]


@dataclass(frozen=True)
class Own:
    """A workspace's own model, as routing sees it."""

    endpoint: Endpoint
    model: str
    # Ours only: never LEKA's, even when ours fails.
    exclusive: bool = False


def _strongest_first(model: Profile) -> tuple[float, ...]:
    price = model.price()
    cost = (price.per_million_in + price.per_million_out) if price else float("inf")
    return (-model.quality, -model.speed, cost)


def route(
    needs: Needs,
    *,
    own: Own | None,
    keys: dict[str, str | None],
    assignment: Assignment | None,
    urls: Mapping[str, str] | None = None,
) -> Routing:
    """The models to try, in order, for what is needed."""
    routes: list[Route] = []
    passed: list[Passed] = []

    def offer(endpoint: Endpoint, model: str, why: str) -> None:
        if (endpoint.provider, model, endpoint.owner) in {
            (r.endpoint.provider, r.profile.model, r.endpoint.owner) for r in routes
        }:
            return
        found = profile(endpoint.provider, model)
        reason = needs.unmet(found)
        if reason is not None:
            passed.append(Passed(endpoint.provider, model, reason))
            return
        routes.append(Route(endpoint, found, why))

    if own is not None:
        offer(own.endpoint, own.model, "own")
        if not routes:
            # Its own model cannot do this step — a code change, a mock-up
            # drawn, asked of a mid-range model (2026-10-29: Mistral Medium):
            # the strongest of the same provider that can, on the same key —
            # its account, its contract.
            for stronger in sorted(of_provider(own.endpoint.provider), key=_strongest_first):
                if stronger.model != own.model and needs.unmet(stronger) is None:
                    offer(own.endpoint, stronger.model, "own_stronger")
                    break
        if own.exclusive:
            passed.append(Passed("leka", "*", "exclusive"))
            return Routing(tuple(routes), tuple(passed))

    if assignment is None:
        return Routing(tuple(routes), tuple(passed))
    first = "trial" if assignment.trial else "assigned"
    for index, (name, model) in enumerate(assignment.models()):
        key = keys.get(name)
        if key is None:
            passed.append(Passed(name, model, "no_key"))
            continue
        offer(
            Endpoint(provider=name, api_key=key, base_url=(urls or {}).get(name), owner="leka"),
            model,
            first if index == 0 else "fallback",
        )
    return Routing(tuple(routes), tuple(passed))
