"""Which model answers (LEKA-394): what a task needs, matched against the
models that can be reached — in an order that is a policy, not a guess.

    1. the workspace's own model, when it set one and it is on — its
       account, its contract; when it said "ours only", nothing else
    2. LEKA's default (LEKA_LLM_PROVIDER, LEKA_LLM_MODEL: Gemini 3.8 Flash)
    3. the fallbacks configured (LEKA_LLM_FALLBACKS), in their order
    4. every other model LEKA holds a key for, by what the task prefers:
       the cheapest, the fastest, the best

A model that cannot do what is asked — a structured answer, tools, a
context that long, a quality that high — is not offered, and why is kept:
the route says what it passed over. A task never names a model; it says
what it needs, and a capability's needs come with its definition.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from leka.capabilities.gateway.contract import Endpoint
from leka.capabilities.gateway.profiles import DEFAULTS, Profile, of_provider, profile


class Prefer(enum.StrEnum):
    """How the models beyond the default and the fallbacks are ordered."""

    COST = "cost"
    SPEED = "speed"
    QUALITY = "quality"


@dataclass(frozen=True)
class Needs:
    """What a task asks of the model that answers it."""

    structured: bool = False
    tools: bool = False
    # Tokens it must take in: the instructions, the context, the question.
    context: int = 0
    # The least quality it accepts (profiles.py: 1 to 3).
    quality: int = 1
    prefer: Prefer = Prefer.QUALITY
    # What kind of work it is (LEKA-491): code, architecture, writing, data,
    # vision — LEKA_LLM_TASK_ROUTES may name the models for it.
    task: str | None = None
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
    # do), task (LEKA-491), default, fallback, alternative
    why: str


@dataclass(frozen=True)
class Passed:
    """A model not offered, and why."""

    provider: str
    model: str
    reason: str  # structured, tools, context, quality, exclusive, no_key


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


def fallbacks_of(said: str) -> list[tuple[str, str]]:
    """LEKA_LLM_FALLBACKS — "mistral:mistral-large-latest, anthropic" — as
    (provider, model) pairs; a provider alone means its default."""
    pairs: list[tuple[str, str]] = []
    for item in said.split(","):
        item = item.strip()
        if not item:
            continue
        name, _, model = item.partition(":")
        model = model.strip() or DEFAULTS.get(name.strip(), "")
        if model:
            pairs.append((name.strip(), model))
    return pairs


def task_routes_of(said: str) -> dict[str, list[tuple[str, str]]]:
    """LEKA_LLM_TASK_ROUTES — "code=anthropic:claude-sonnet-5;
    vision=openai:gpt-4.1, google" — each kind of work and the models to
    try first for it, in order (LEKA-491). Configured, never written where
    it is used; empty: no kind of work has its own."""
    routes: dict[str, list[tuple[str, str]]] = {}
    for part in said.split(";"):
        task, _, models = part.partition("=")
        if task.strip() and models.strip():
            routes[task.strip()] = fallbacks_of(models)
    return routes


def _rank(model: Profile, prefer: Prefer) -> tuple[float, ...]:
    price = model.price()
    cost = (price.per_million_in + price.per_million_out) if price else float("inf")
    if prefer is Prefer.COST:
        return (cost, -model.quality, -model.speed)
    if prefer is Prefer.SPEED:
        return (-model.speed, -model.quality, cost)
    return (-model.quality, -model.speed, cost)


def route(
    needs: Needs,
    *,
    own: Own | None,
    keys: dict[str, str | None],
    default: tuple[str, str],
    fallbacks: Sequence[tuple[str, str]] = (),
    urls: Mapping[str, str] | None = None,
    tasks: Mapping[str, Sequence[tuple[str, str]]] | None = None,
) -> Routing:
    """The models to try, in order, for what is needed."""
    routes: list[Route] = []
    passed: list[Passed] = []
    tried: set[tuple[str, str]] = set()

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
            # the strongest of the same provider that can, on the same key.
            for stronger in sorted(
                of_provider(own.endpoint.provider), key=lambda p: _rank(p, Prefer.QUALITY)
            ):
                if stronger.model != own.model and needs.unmet(stronger) is None:
                    offer(own.endpoint, stronger.model, "own_stronger")
                    break
        if own.exclusive:
            passed.append(Passed("leka", "*", "exclusive"))
            return Routing(tuple(routes), tuple(passed))

    def leka(provider: str, model: str, why: str) -> None:
        if (provider, model) in tried:
            return
        tried.add((provider, model))
        key = keys.get(provider)
        if key is None:
            passed.append(Passed(provider, model, "no_key"))
            return
        offer(
            Endpoint(
                provider=provider, api_key=key, base_url=(urls or {}).get(provider), owner="leka"
            ),
            model,
            why,
        )

    # The models its kind of work is given first (LEKA-491), when LEKA holds
    # their key and they can do what is asked — else on to the default.
    for provider, model in (tasks or {}).get(needs.task or "", ()):
        leka(provider, model, "task")
    leka(*default, "default")
    for provider, model in fallbacks:
        leka(provider, model, "fallback")
    if not fallbacks:
        # None configured: every other provider LEKA holds a key for.
        for provider in keys:
            if provider != default[0] and provider in DEFAULTS:
                leka(provider, DEFAULTS[provider], "fallback")
    others = sorted(
        (p for name, key in keys.items() if key is not None for p in of_provider(name)),
        key=lambda p: _rank(p, needs.prefer),
    )
    for other in others:
        if (other.provider, other.model) in tried:
            continue
        tried.add((other.provider, other.model))
        offer(
            Endpoint(
                provider=other.provider,
                api_key=keys[other.provider],
                base_url=(urls or {}).get(other.provider),
                owner="leka",
            ),
            other.model,
            "alternative",
        )
    return Routing(tuple(routes), tuple(passed))
