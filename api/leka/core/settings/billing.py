"""What billing needs that is not a price (LEKA-431): where an Enterprise
prospect goes, and Stripe's keys.

Prices, discounts and AI capacity live in leka/billing/catalogue.yaml, the
one source of truth. Stripe's secret key and its webhook's signing secret
live in the environment only — production.env on the box, test keys
locally — never in the repository, never sent to a browser. Without them,
checkout says it is not available and the webhook refuses everything.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import SecretStr, field_validator

from leka.core.settings._blank import blank_is_none
from leka.core.settings._rotation import RotateEvery


class BillingSettings:
    # Where an Enterprise prospect books a meeting with the team — a
    # Calendly link or any scheduling page, https. Empty: the pricing page
    # offers the contact form only, never a guessed address.
    sales_booking_url: str | None = None
    # The contact path that always works: the site's enquiry form.
    sales_contact_url: str = "https://leka-core.com/demo.html?type=enterprise"

    # Stripe: the secret key (sk_test_… in test, sk_live_… in production)
    # and the webhook endpoint's signing secret (whsec_…).
    stripe_secret_key: Annotated[SecretStr | None, RotateEvery(days=365)] = None
    stripe_webhook_secret: Annotated[SecretStr | None, RotateEvery(days=365)] = None
    # Stripe's API; replaced in the tests.
    stripe_api_url: str = "https://api.stripe.com"

    _blank_booking = field_validator("sales_booking_url", mode="before")(blank_is_none)
    _blank_stripe = field_validator("stripe_secret_key", "stripe_webhook_secret", mode="before")(
        blank_is_none
    )

    @field_validator("sales_booking_url", "sales_contact_url")
    @classmethod
    def _https(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            msg = "a booking or contact address is https"
            raise ValueError(msg)
        return value
