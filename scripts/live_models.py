"""Ask every model LEKA knows, for real, whether it still answers the way
the gateway asks it — a provider changing its API shows here before a
customer's run fails on it.

    api/.venv/bin/python scripts/live_models.py [--only anthropic,openai]

Per model whose provider LEKA holds a key for (LEKA_ANTHROPIC_API_KEY, … in
.env or the environment): one call made to use a tool, one asked a
structured answer — a few cents in all. The tests stand in for the
providers (tests/test_model_providers.py); this is the only check against
the real ones. Run by hand, never in CI: it costs, and needs the keys.

Exit 1 when a model fails either call; what it said is printed, never a key.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx
from pydantic import BaseModel

from leka.capabilities.gateway import (
    Endpoint,
    Message,
    Output,
    ProviderError,
    Request,
    Tool,
    ToolChoice,
    leka_keys,
    provider,
)
from leka.capabilities.gateway.contract import Call
from leka.capabilities.gateway.profiles import PROFILES

LOOKUP = Tool(
    "lookup",
    "Look a service up by its name.",
    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)


class Verdict(BaseModel):
    goal: str
    confidence: float


# Room to think before answering: Claude 5.5 and GPT-5.6 always do.
TOKENS = 4_000


async def _check(call: Call, client: httpx.AsyncClient) -> tuple[str | None, str]:
    """What went wrong with this model, or None — and the version that
    answered: where a -latest name points today."""
    vendor = provider(call.endpoint.provider)
    if vendor is None:
        return "no provider", ""
    version = ""
    asks = (
        Request(
            purpose="live-check",
            messages=[Message.user("Who owns payment-api? Look it up.")],
            tools=[LOOKUP],
            tool_choice=ToolChoice.REQUIRED,
            max_tokens=TOKENS,
        ),
        Request(
            purpose="live-check",
            messages=[Message.user("Goal of « fix the login bug », and your confidence.")],
            output=Output.of(Verdict),
            max_tokens=TOKENS,
        ),
    )
    for asked in asks:
        try:
            done = await vendor.complete(
                Call(
                    call.endpoint,
                    call.model,
                    asked,
                    thinking=call.thinking,
                    sends_temperature=call.sends_temperature,
                    forces_tools=call.forces_tools,
                ),
                client,
            )
        except ProviderError as error:
            return str(error)[:300], version
        version = done.version
        if asked.tools and not any(c.name == "lookup" for c in done.tool_calls):
            return f"no tool call (finish: {done.finish})", version
        if asked.output is not None:
            try:
                Verdict.model_validate(json.loads(done.text))
            except ValueError:
                return f"not the shape asked: {done.text[:120]!r}", version
    return None, version


async def main(only: set[str]) -> int:
    keys = leka_keys()
    failed = 0
    async with httpx.AsyncClient(timeout=120) as client:
        for found in PROFILES:
            if (only and found.provider not in only) or not keys.get(found.provider):
                continue
            call = Call(
                Endpoint(provider=found.provider, api_key=keys[found.provider]),
                found.model,
                Request(purpose="live-check", messages=[]),
                thinking=found.thinking,
                sends_temperature=found.sends_temperature,
                forces_tools=found.forces_tools,
            )
            wrong, version = await _check(call, client)
            failed += wrong is not None
            answered = f" ({version})" if version and version != found.model else ""
            print(
                f"{'FAIL' if wrong else 'ok  '}  {found.provider}:{found.model}{answered}  "
                f"{wrong or ''}"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", default="", help="providers, comma-separated")
    args = parser.parse_args()
    sys.exit(asyncio.run(main({p.strip() for p in args.only.split(",") if p.strip()})))
