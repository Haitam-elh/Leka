"""Paying for LEKA CORE, over HTTP (LEKA-431, LEKA-446).

    GET  /billing/subscription        the workspace's subscription, as Stripe
                                      last said it (workspace:read)
    POST /billing/checkout            a Stripe Checkout for a plan: its URL,
                                      and what will be charged — the page's
                                      price (workspace:update)
    POST /billing/portal              Stripe's customer portal: card, invoices,
                                      plan change, cancellation — in the
                                      person's language (workspace:update)
    POST /billing/subscription/renewal  « Ne pas renouveler » / « Réactiver le
                                      renouvellement »: kept until its period's
                                      end either way (workspace:update)
    POST /billing/stripe/webhook      Stripe's events — no session: believed
                                      only when signed (400 otherwise), kept
                                      once by id

Who may pay is who may change the workspace: its owners and admins. A plan
comes only from a verified Stripe event — never from the browser coming
back from Checkout. No AI capacity is sold apart: there is no route for it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.billing import (
    BillingUnavailableError,
    CheckoutCreate,
    CheckoutRead,
    CheckoutRefusedError,
    PortalRead,
    SignatureError,
    StripeError,
    SubscriptionRead,
    account_of,
    catalogue,
    checkout,
    launch_eligible,
    payments_open,
    portal,
    receive,
    renewal,
    stripe,
    stripe_locale,
)
from leka.core.errors import ErrorCode, FieldError
from leka.governance import Permission, Principal, require_permission
from leka.identity import spoken_language

router = APIRouter(prefix="/billing", tags=["billing"])

Reader = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_READ))]
Payer = Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_UPDATE))]
# A webhook's body, at most.
MAX_EVENT_BYTES = 512 * 1024


def _unavailable() -> ApiError:
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorCode.SERVICE_UNAVAILABLE,
        "Online payment is not available yet.",
    )


def _refused(error: CheckoutRefusedError) -> ApiError:
    code = status.HTTP_409_CONFLICT if error.code == "subscribed" else 422
    return ApiError(
        code,
        ErrorCode.CONFLICT if code == status.HTTP_409_CONFLICT else ErrorCode.VALIDATION_FAILED,
        str(error),
        details=[FieldError(field="checkout", message=error.code)],
    )


def _stripe_failed(error: StripeError) -> ApiError:
    return ApiError(
        status.HTTP_502_BAD_GATEWAY,
        ErrorCode.SERVICE_UNAVAILABLE,
        "Stripe could not be reached: try again in a moment.",
        details=[FieldError(field="stripe", message=str(error.code or error.status))],
    )


@router.get("/subscription", response_model=SubscriptionRead, summary="The subscription")
async def read_subscription(principal: Reader, session: SessionDep) -> SubscriptionRead:
    account = await account_of(session, principal.workspace_id)
    await session.commit()
    offer = catalogue()
    today = datetime.now(UTC).date()
    return SubscriptionRead(
        available=payments_open(),
        plan=account.plan,
        interval=account.interval,
        status=account.status,
        current_period_end=account.current_period_end,
        cancel_at_period_end=account.cancel_at_period_end,
        launch_offer_available=launch_eligible(account, offer, "growth", "month", today),
        trial_available=not account.launch_offer_used,
        last_invoice=account.last_invoice,
        has_customer=account.stripe_customer_id is not None,
    )


async def _locale(session: SessionDep, principal: Principal) -> str:
    """Stripe's pages in the person's language (2026-10-14)."""
    return stripe_locale(await spoken_language(session, principal.user_id, principal.workspace_id))


@router.post("/checkout", response_model=CheckoutRead, summary="Pay for a plan, with Stripe")
async def start_checkout(
    body: CheckoutCreate, principal: Payer, session: SessionDep
) -> CheckoutRead:
    try:
        done = await checkout(
            session,
            principal.workspace_id,
            body.plan,
            body.interval,
            client=stripe(),
            today=datetime.now(UTC).date(),
            locale=await _locale(session, principal),
        )
    except BillingUnavailableError:
        raise _unavailable() from None
    except CheckoutRefusedError as error:
        raise _refused(error) from None
    except StripeError as error:
        raise _stripe_failed(error) from None
    return CheckoutRead(url=done.url, quote=done.quote)


@router.post("/portal", response_model=PortalRead, summary="Stripe's customer portal")
async def open_portal(principal: Payer, session: SessionDep) -> PortalRead:
    try:
        url = await portal(
            session,
            principal.workspace_id,
            client=stripe(),
            locale=await _locale(session, principal),
        )
    except BillingUnavailableError:
        raise _unavailable() from None
    except CheckoutRefusedError as error:
        raise _refused(error) from None
    except StripeError as error:
        raise _stripe_failed(error) from None
    return PortalRead(url=url)


class RenewalChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    renew: bool


@router.post(
    "/subscription/renewal",
    response_model=SubscriptionRead,
    summary="Renew at the period's end, or not",
)
async def change_renewal(
    body: RenewalChange, principal: Payer, session: SessionDep
) -> SubscriptionRead:
    try:
        await renewal(session, principal.workspace_id, renew=body.renew, client=stripe())
    except BillingUnavailableError:
        raise _unavailable() from None
    except CheckoutRefusedError as error:
        raise _refused(error) from None
    except StripeError as error:
        raise _stripe_failed(error) from None
    return await read_subscription(principal, session)


@router.post(
    "/stripe/webhook",
    summary="Stripe's events, verified by their signature",
    responses={400: {"description": "Not signed by Stripe"}},
)
async def stripe_webhook(request: Request) -> dict[str, str]:
    payload = await request.body()
    if len(payload) > MAX_EVENT_BYTES:
        raise ApiError(status.HTTP_400_BAD_REQUEST, ErrorCode.VALIDATION_FAILED, "Too large.")
    try:
        client = stripe()
    except BillingUnavailableError:
        client = None
    try:
        said = await receive(
            payload,
            request.headers.get("stripe-signature", ""),
            now=datetime.now(UTC),
            client=client,
        )
    except SignatureError:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, ErrorCode.VALIDATION_FAILED, "Not signed by Stripe."
        ) from None
    return {"received": said}
