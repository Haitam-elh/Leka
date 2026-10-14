"""Agents and bundles, sold besides a plan (2026-10-14, the product call).

    GET  /billing/add-ons             every agent sold — its tier, its price,
                                      whether this workspace owns it, why it
                                      may not run it — and the bundles
                                      (workspace:read)
    GET  /billing/entitlements        what it owns: agents, bundles, or every
                                      one (« Mes compétences ») (workspace:read)
    POST /billing/add-ons/checkout    a Stripe Checkout for an agent or a
                                      bundle — opened from an intention's
                                      decision, its agents launched once paid
                                      (workspace:update)

Owned comes only from a verified Stripe event, or LEKA's grant — never from
the browser coming back from Checkout.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.api.subscriptions import _refused, _stripe_failed, _unavailable
from leka.billing import (
    AddOnCheckoutCreate,
    AddOnsRead,
    AgentOfferRead,
    BillingUnavailableError,
    BundleOfferRead,
    CheckoutRefusedError,
    EntitlementRead,
    PortalRead,
    StripeError,
    add_on,
    catalogue,
    checkout_add_on,
    entitlements,
    owned,
    plan_runs_agents,
    stripe,
)
from leka.capabilities import find
from leka.core.errors import ErrorCode
from leka.governance import Permission, Principal, require_permission

router = APIRouter(prefix="/billing", tags=["billing"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Payer = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_UPDATE))]


def _title(key: str) -> str:
    found = find(key)
    return found.title if found is not None else key


@router.get("/add-ons", response_model=AddOnsRead, summary="Agents and bundles, sold")
async def read_add_ons(principal: Reader, session: SessionDep) -> AddOnsRead:
    sold = catalogue().add_ons
    has = await owned(session, principal.workspace_id)
    prices = sold.prices
    agents = []
    for key, tier in sold.agents.items():
        definition = find(key)
        if definition is None:
            continue
        agents.append(
            AgentOfferRead(
                key=key,
                title=definition.title,
                summary=definition.summary,
                category=definition.category,
                tier=tier,
                monthly_price=prices[key],
                owned=has.every or key in has.agents,
                why=has.why(key),
                bundles=[b.key for b in sold.bundles if key in b.agents],
            )
        )
    bundles = []
    for bundle in sold.bundles:
        alone = sum(prices[a] for a in bundle.agents)
        bundles.append(
            BundleOfferRead(
                key=bundle.key,
                name=bundle.name,
                value=bundle.value,
                agents=list(bundle.agents),
                monthly_price=bundle.monthly_price,
                alone_price=alone,
                discount_percent=round(100 * (1 - bundle.monthly_price / alone)),
                owned=has.every or bundle.key in has.bundles,
            )
        )
    return AddOnsRead(
        available=sold.available,
        provisional=sold.provisional,
        currency=catalogue().currency,
        minimum_plan=sold.minimum_plan,
        plan=has.plan,
        runs_agents=has.every or plan_runs_agents(has.plan),
        every=has.every,
        agents=agents,
        bundles=bundles,
    )


@router.get("/entitlements", response_model=list[EntitlementRead], summary="What it owns")
async def read_entitlements(principal: Reader, session: SessionDep) -> list[EntitlementRead]:
    sold = catalogue().add_ons
    found = []
    for row in await entitlements(session, principal.workspace_id):
        if row.kind == "all":
            agents = list(sold.agents)
        elif row.kind == "bundle":
            bundle = sold.bundle(row.key)
            agents = list(bundle.agents) if bundle is not None else []
        else:
            agents = [row.key]
        found.append(
            EntitlementRead(
                key=row.key,
                kind=row.kind,
                origin=row.origin,
                started_at=row.started_at,
                agents=agents,
            )
        )
    return found


@router.post(
    "/add-ons/checkout", response_model=PortalRead, summary="Buy an agent or a bundle, with Stripe"
)
async def buy_add_on(
    body: AddOnCheckoutCreate, principal: Payer, session: SessionDep
) -> PortalRead:
    found = add_on(body.kind, body.key)
    if found is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "No such agent or bundle on sale."
        )
    sold = catalogue().add_ons
    bundle = sold.bundle(body.key) if body.kind == "bundle" else None
    name = f"LEKA — {bundle.name.fr}" if bundle is not None else f"LEKA — {_title(body.key)}"
    try:
        url = await checkout_add_on(
            session,
            principal.workspace_id,
            kind=body.kind,
            key=body.key,
            name=name,
            by=principal.user_id,
            client=stripe(),
            intention_id=body.intention_id,
            launch=body.launch,
        )
    except BillingUnavailableError:
        raise _unavailable() from None
    except CheckoutRefusedError as error:
        raise _refused(error) from None
    except StripeError as error:
        raise _stripe_failed(error) from None
    return PortalRead(url=url)
