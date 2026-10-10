"""AI credits (LEKA-430): what a workspace's plan gives it to spend on
LEKA's models each month — apart from what they cost LEKA.

A credit is worth `credit_usd` of LEKA's model cost at the rates in force:
what a workspace consumes is what its work cost LEKA, said in credits. Each
plan's monthly allowance, and the shares of it past which the workspace's
owners and admins are told, are configured here — never written where they
are used. A workspace's own model (Enterprise, its account) consumes none.

`credits_enforced`: whether a workspace whose credits are spent is refused
LEKA's models until the month ends, a pack is added or its plan changes —
never billed past it. Off, the credits are counted, shown and warned of all
the same.
"""

from __future__ import annotations

from pydantic import Field

PLANS = ("free", "starter", "growth", "business", "enterprise")


class CreditSettings:
    credit_usd: float = Field(default=0.01, gt=0)
    plan_credits: dict[str, int] = Field(
        default_factory=lambda: {
            "free": 200,
            "starter": 2_000,
            "growth": 10_000,
            "business": 40_000,
            "enterprise": 100_000,
        }
    )
    # Percentages of the month's credits; each told once a month.
    credit_warnings: list[int] = Field(default_factory=lambda: [80, 100])
    credits_enforced: bool = True
    # Each plan's price a month, in US dollars — list and promotional — for
    # the margins of the internal reports (python -m leka.metering.cli report
    # plans). A plan without one has no margin: not known, never 0.
    plan_prices_usd: dict[str, float] = Field(default_factory=dict)
    plan_promo_prices_usd: dict[str, float] = Field(default_factory=dict)
