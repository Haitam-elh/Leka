"""What the pricing page needs that is not a price (LEKA-431).

Prices, discounts and AI capacity live in leka/billing/catalogue.yaml, the
one source of truth; this is only where an Enterprise prospect goes.
"""

from __future__ import annotations

from pydantic import field_validator

from leka.core.settings._blank import blank_is_none


class BillingSettings:
    # Where an Enterprise prospect books a meeting with the team — a
    # Calendly link or any scheduling page, https. Empty: the pricing page
    # offers the contact form only, never a guessed address.
    sales_booking_url: str | None = None
    # The contact path that always works: the site's enquiry form.
    sales_contact_url: str = "https://leka-core.com/demo.html?type=enterprise"

    _blank_booking = field_validator("sales_booking_url", mode="before")(blank_is_none)

    @field_validator("sales_booking_url", "sales_contact_url")
    @classmethod
    def _https(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            msg = "a booking or contact address is https"
            raise ValueError(msg)
        return value
