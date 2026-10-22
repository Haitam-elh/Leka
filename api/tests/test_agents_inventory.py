"""The agents' inventory (LEKA-454): docs/billing/agents-inventory.md is what
the registry and the catalogue say — regenerated, never typed by hand.

What this protects: a change to the catalogue or to an agent changes the
committed inventory with it, in the same pull request.
"""

from __future__ import annotations

from leka.capabilities.inventory import DOCUMENT, markdown, rows


def test_the_committed_inventory_is_what_the_sources_say() -> None:
    assert DOCUMENT.read_text(encoding="utf-8") == markdown(), (
        "Regenerate it: python -m leka.capabilities.inventory --write"
    )


def test_every_agent_on_sale_is_built_and_every_reference_one_unbuilt_is_never_sold() -> None:
    found = rows()
    on_sale = [r for r in found if r.status == "on_sale"]
    # Thirteen, Frontend Craft's and Engineering's four each (LEKA-461), the
    # acceptance (2026-10-21), the API review, the reliability and the
    # dependency analyses, the database review (2026-10-22).
    assert len(on_sale) == 26
    assert all(r.agent is not None and r.lifecycle == "active" for r in on_sale)
    # The reference's price is the catalogue's, where the reference names one.
    assert all(r.price is not None for r in on_sale)
    assert all(r.agent is None for r in found if r.status in ("not_built", "unpriced"))
    # Named by a bundle, priced nowhere, and not built: the reliability
    # analyst, built (2026-10-22), is priced at its agent's tier.
    assert {r.reference for r in found if r.status == "unpriced"} == {"Migration Planner"}
