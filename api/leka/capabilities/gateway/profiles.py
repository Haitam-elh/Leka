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
    # A token read from the provider's cache; unknown: as any token in.
    per_million_cached: float | None = None


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
    # Reads images given to it (LEKA-491) — never confused with making them.
    vision: bool = False
    # Takes a tool it is made to call. Claude 5.5 refuses it (400): its
    # structured answer is asked as one, its tools left to it.
    forces_tools: bool = True
    known: bool = True

    def price(self, at: datetime | None = None) -> Price | None:
        day = (at or datetime.now(UTC)).date()
        current = [p for p in self.prices if p.since <= day]
        return max(current, key=lambda p: p.since) if current else None

    def cost(
        self,
        tokens_in: int,
        tokens_out: int,
        at: datetime | None = None,
        *,
        cached: int = 0,
    ) -> float | None:
        """What a call cost at list price — the tokens read from the
        provider's cache at their own price; None when the price is not
        known."""
        price = self.price(at)
        return None if price is None else cost_at(price, tokens_in, tokens_out, cached=cached)


def cost_at(price: Price, tokens_in: int, tokens_out: int, *, cached: int = 0) -> float:
    """What tokens cost at a price: those read from the provider's cache at
    their own price, or as any token in when it has none."""
    cached = max(0, min(cached, tokens_in))
    cache = price.per_million_in if price.per_million_cached is None else price.per_million_cached
    return round(
        (
            (tokens_in - cached) * price.per_million_in
            + cached * cache
            + tokens_out * price.per_million_out
        )
        / 1_000_000,
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
        # ai.google.dev/gemini-api/docs/pricing, read 2026-10-09: thinking
        # billed as output; a token from the implicit cache a tenth of one in.
        prices=(
            Price(_LONG_AGO, 0.75, 3.75, 0.075),
            Price(date(2027, 1, 1), 1.50, 7.50, 0.15),
        ),
        sends_temperature=False,
        vision=True,
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
        vision=True,
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
        vision=True,
    ),
    # Claude 5.5 (platform.claude.com/docs/en/about-claude/pricing, read
    # 2026-10-20): always thinking, no temperature, no forced tool.
    Profile(
        "anthropic",
        "claude-opus-5-5",
        "Claude Opus 5.5",
        context=1_000_000,
        output=128_000,
        quality=3,
        speed=2,
        prices=(Price(_LONG_AGO, 4.0, 20.0, 0.2),),
        sends_temperature=False,
        vision=True,
        forces_tools=False,
    ),
    Profile(
        "anthropic",
        "claude-sonnet-5-5",
        "Claude Sonnet 5.5",
        context=1_000_000,
        output=128_000,
        quality=3,
        speed=3,
        prices=(Price(_LONG_AGO, 2.0, 10.0, 0.1),),
        sends_temperature=False,
        vision=True,
        forces_tools=False,
    ),
    Profile(
        "anthropic",
        "claude-haiku-5-5",
        "Claude Haiku 5.5",
        context=1_000_000,
        output=128_000,
        quality=2,
        speed=3,
        # shortcut: its price up to 100,000 tokens read — five times more
        # beyond; a price by prompt size when a call of LEKA's reaches it.
        prices=(Price(_LONG_AGO, 0.1, 0.5, 0.01),),
        sends_temperature=False,
        vision=True,
        forces_tools=False,
    ),
    # OpenAI, held by LEKA (LEKA-491): text and images in, text out — never
    # image generation. Prices: openai.com/api/pricing, per million tokens.
    Profile(
        "openai",
        "gpt-4.1",
        "GPT-4.1",
        context=1_047_576,
        output=32_768,
        quality=3,
        speed=2,
        prices=(Price(_LONG_AGO, 2.0, 8.0, 0.5),),
        vision=True,
    ),
    Profile(
        "openai",
        "gpt-4.1-mini",
        "GPT-4.1 mini",
        context=1_047_576,
        output=32_768,
        quality=2,
        speed=3,
        prices=(Price(_LONG_AGO, 0.4, 1.6, 0.1),),
        vision=True,
    ),
    # GPT-5.6 (developers.openai.com/api/docs/pricing, read 2026-10-20):
    # reasoning models, at their own temperature. GPT-6 calls no tool in chat
    # completions — only in the Responses API, which LEKA does not speak yet.
    Profile(
        "openai",
        "gpt-5.6-sol",
        "GPT-5.6 Sol",
        context=1_050_000,
        output=128_000,
        quality=3,
        speed=2,
        prices=(Price(_LONG_AGO, 4.0, 20.0, 0.4),),
        sends_temperature=False,
        vision=True,
    ),
    Profile(
        "openai",
        "gpt-5.6-luna",
        "GPT-5.6 Luna",
        context=1_050_000,
        output=128_000,
        quality=2,
        speed=3,
        prices=(Price(_LONG_AGO, 0.2, 1.2, 0.02),),
        sends_temperature=False,
        vision=True,
    ),
)

# Each provider's own default, when LEKA falls back on it.
DEFAULTS: dict[str, str] = {
    "google": "gemini-3.8-flash",
    "mistral": "mistral-large-latest",
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-4.1",
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
    mine = [known for known in profiles() if known.provider == provider]
    # Its own name first: « gpt-4.1-mini » is not « gpt-4.1 » dated.
    for known in mine:
        if known.model == model:
            return known
    for known in mine:
        if model.startswith(f"{known.model}-"):
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
