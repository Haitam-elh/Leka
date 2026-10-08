"""The models LEKA knows (LEKA-394): what each takes in and gives back,
what it can do, how good and how fast it is, what it costs — what the router
matches a task's needs against.

    quality   1 enough to classify · 2 good analysis · 3 the best LEKA uses
    speed     1 slow · 2 · 3 fast

Prices are list prices, per million tokens, in US dollars, as each provider
published them — with the date a published change takes effect (Gemini 3.8
Flash's introductory price ends on 2027-01-01). A model whose price is not
published has none: its cost is not estimated rather than guessed. An
estimate, said so: a contract's price is the provider's invoice.

A model the table does not know — a workspace's Azure deployment, its
self-hosted model — gets a cautious profile: what it can do is assumed from
its provider, its cost unknown.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime


@dataclass(frozen=True)
class Price:
    since: date
    per_million_in: float
    per_million_out: float


@dataclass(frozen=True)
class Profile:
    provider: str
    model: str
    title: str
    context: int  # tokens it takes in
    output: int  # tokens it gives back, at most
    structured: bool = True
    tools: bool = True
    # The thinking levels it accepts, for the tiers (fast, standard, deep).
    thinking: tuple[str, ...] = ()
    quality: int = 2
    speed: int = 2
    prices: tuple[Price, ...] = ()
    # Gemini 3 asks to be left at its default temperature.
    sends_temperature: bool = True
    known: bool = True

    def price(self, at: datetime | None = None) -> Price | None:
        day = (at or datetime.now(UTC)).date()
        current = [p for p in self.prices if p.since <= day]
        return max(current, key=lambda p: p.since) if current else None

    def cost(self, tokens_in: int, tokens_out: int, at: datetime | None = None) -> float | None:
        """What a call cost at list price; None when the price is not known."""
        price = self.price(at)
        if price is None:
            return None
        return round(
            (tokens_in * price.per_million_in + tokens_out * price.per_million_out) / 1_000_000,
            6,
        )


_LONG_AGO = date(2025, 1, 1)

PROFILES: tuple[Profile, ...] = (
    # LEKA's default for the MVP.
    Profile(
        "google",
        "gemini-3.8-flash",
        "Gemini 3.8 Flash",
        context=1_048_576,
        output=65_536,
        thinking=("low", "medium", "high"),
        quality=3,
        speed=3,
        prices=(Price(_LONG_AGO, 0.75, 3.75), Price(date(2027, 1, 1), 1.50, 7.50)),
        sends_temperature=False,
    ),
    Profile(
        "mistral",
        "mistral-large-latest",
        "Mistral Large",
        context=256_000,
        output=32_000,
        quality=3,
        speed=2,
        prices=(Price(_LONG_AGO, 0.5, 1.5),),
    ),
    Profile(
        "mistral",
        "mistral-medium-latest",
        "Mistral Medium",
        context=128_000,
        output=32_000,
        quality=2,
        speed=3,
    ),
    Profile(
        "mistral",
        "mistral-small-latest",
        "Mistral Small",
        context=128_000,
        output=32_000,
        quality=1,
        speed=3,
    ),
    Profile(
        "anthropic",
        "claude-sonnet-5",
        "Claude Sonnet 5",
        context=1_000_000,
        output=128_000,
        quality=3,
        speed=2,
        prices=(Price(_LONG_AGO, 2.0, 10.0),),
    ),
    Profile(
        "anthropic",
        "claude-haiku-4-5",
        "Claude Haiku 4.5",
        context=200_000,
        output=64_000,
        quality=2,
        speed=3,
        prices=(Price(_LONG_AGO, 1.0, 5.0),),
    ),
)

# Each provider's own default, when LEKA falls back on it.
DEFAULTS: dict[str, str] = {
    "google": "gemini-3.8-flash",
    "mistral": "mistral-large-latest",
    "anthropic": "claude-sonnet-5",
}

_EXTRA: list[Profile] = []


def register_model(profile: Profile) -> None:
    """A model LEKA knows, beside the built-in ones."""
    _EXTRA.append(profile)


def profiles() -> Sequence[Profile]:
    return (*PROFILES, *_EXTRA)


def profile(provider: str, model: str) -> Profile:
    """What a model can do — a cautious guess for one the table does not
    know: 128k tokens in, structured output and tools as its provider's API
    offers them, middling quality, no price."""
    for known in profiles():
        if known.provider == provider and (
            known.model == model or model.startswith(f"{known.model}-")
        ):
            return known
    return Profile(
        provider,
        model,
        model,
        context=128_000,
        output=8_192,
        quality=2,
        speed=2,
        known=False,
    )


def of_provider(provider: str) -> list[Profile]:
    return [p for p in profiles() if p.provider == provider]
