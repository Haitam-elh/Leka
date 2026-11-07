"""The filters of LEKA ADMIN's lists, declared once (LEKA-557).

Each is a dependency that reads a list's query parameters and makes its
query. The list and its CSV export (GET /admin/exports/...) both take it: an
export is the list as filtered, never a filter more nor a filter less, and a
filter added to a list is added to its export by the same line.

The filters combine: each narrows what the others left.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, Query
from sqlalchemy import Select

from leka.admin import (
    AdminPrincipalDep,
    Incident,
    UserStatus,
    incidents_query,
    intentions_query,
    invoices_query,
    movements_query,
    organisations_query,
    payments_query,
    refunds_query,
    subscriptions_query,
    users_query,
)
from leka.billing import BillingAccount, BillingInvoice, BillingPayment, BillingRefund
from leka.governance import CreditTransaction
from leka.identity import User
from leka.intentions import Intention
from leka.platform import Workspace

Text = Annotated[str | None, Query(max_length=200)]
Named = Annotated[str | None, Query(max_length=200, description="An organisation's name or slug.")]


async def organisations_found(
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="Name, slug, id, an owner's email, a Stripe customer or subscription id.",
        ),
    ] = None,
    plan: str | None = None,
    organisation_status: Annotated[str | None, Query(alias="status")] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    include_demo: bool = False,
    country: Annotated[
        str | None, Query(pattern=r"^[A-Za-z]{2}$", description="ISO 3166-1 alpha-2.")
    ] = None,
    size: Annotated[
        str | None,
        Query(description="1-10, 11-50, 51-200, 201-1000, 1000+: kept by LEKA, else declared."),
    ] = None,
    activity: Annotated[
        Literal["active", "inactive", "never"] | None,
        Query(description="Something done in the last 30 days, before only, or never."),
    ] = None,
) -> Select[tuple[Workspace]]:
    return organisations_query(
        q=q,
        plan=plan,
        status=organisation_status,
        created_from=created_from,
        created_to=created_to,
        include_demo=include_demo,
        country=country,
        size=size,
        activity=activity,
    )


async def users_found(
    q: Annotated[str | None, Query(max_length=200, description="Email, name or id.")] = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Named = None,
    role: Annotated[
        Literal["owner", "admin", "member"] | None,
        Query(description="Their role in an organisation (the one asked, if any)."),
    ] = None,
    verified: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    user_status: Annotated[UserStatus | None, Query(alias="status")] = None,
    active_from: Annotated[
        datetime | None, Query(description="Their last intention, run or source from then on.")
    ] = None,
    active_to: Annotated[datetime | None, Query(description="…before then.")] = None,
    never_active: Annotated[
        bool, Query(description="No intention, run nor source connected, ever.")
    ] = False,
) -> Select[tuple[User]]:
    return users_query(
        q=q,
        organisation_id=organisation_id,
        organisation=organisation,
        role=role,
        verified=verified,
        created_from=created_from,
        created_to=created_to,
        status=user_status,
        active_from=active_from,
        active_to=active_to,
        never_active=never_active,
    )


async def intentions_found(
    q: Annotated[
        str | None, Query(max_length=200, description="Its id, or words of its title.")
    ] = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Named = None,
    user_id: uuid.UUID | None = None,
    user: Annotated[
        str | None, Query(max_length=200, description="Who asked it: their address or name.")
    ] = None,
    intention_status: Annotated[
        str | None,
        Query(
            alias="status",
            description="pending, running, completed, failed, cancelled, or LEKA's own",
        ),
    ] = None,
    kind: Annotated[str | None, Query(max_length=30)] = None,
    agent: Annotated[str | None, Query(max_length=100, description="An agent's key.")] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Select[tuple[Intention]]:
    return intentions_query(
        q=q,
        organisation_id=organisation_id,
        organisation=organisation,
        user_id=user_id,
        user=user,
        status=intention_status,
        kind=kind,
        agent=agent,
        created_from=created_from,
        created_to=created_to,
    )


async def movements_found(
    organisation_id: uuid.UUID | None = None,
    organisation: Named = None,
    kind: Literal["grant", "consumption", "refund", "adjustment", "expiration"] | None = None,
    origin: Literal["plan", "pack", "metering", "admin", "close"] | None = None,
    period: Annotated[
        str | None, Query(pattern=r"^\d{4}-\d{2}$", description="A month, YYYY-MM.")
    ] = None,
    execution: Annotated[str | None, Query(max_length=160)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select[tuple[CreditTransaction]]:
    return movements_query(
        organisation_id=organisation_id,
        organisation=organisation,
        kind=kind,
        origin=origin,
        period=period,
        execution=execution,
        since=since,
        until=until,
    )


async def subscriptions_found(
    plan: str | None = None,
    subscription_status: Annotated[str | None, Query(alias="status")] = None,
    interval: str | None = None,
    organisation: Named = None,
) -> Select[tuple[BillingAccount]]:
    return subscriptions_query(
        plan=plan, status=subscription_status, interval=interval, organisation=organisation
    )


StripeIds = Annotated[
    str | None,
    Query(max_length=200, description="Its number, or Stripe's id of it (LEKA-557)."),
]


async def invoices_found(
    q: StripeIds = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Text = None,
    invoice_status: Annotated[
        Literal["draft", "open", "paid", "uncollectible", "void"] | None, Query(alias="status")
    ] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select[tuple[BillingInvoice]]:
    return invoices_query(
        q=q,
        organisation_id=organisation_id,
        organisation=organisation,
        status=invoice_status,
        since=since,
        until=until,
    )


async def payments_found(
    q: StripeIds = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Text = None,
    outcome: Literal["succeeded", "failed"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select[tuple[BillingPayment]]:
    return payments_query(
        q=q,
        organisation_id=organisation_id,
        organisation=organisation,
        outcome=outcome,
        since=since,
        until=until,
    )


async def refunds_found(
    q: StripeIds = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Text = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Select[tuple[BillingRefund]]:
    return refunds_query(
        q=q, organisation_id=organisation_id, organisation=organisation, since=since, until=until
    )


def statuses_of(said: Sequence[str] | None) -> tuple[str, ...]:
    """`open` said as what it is: new and in progress."""
    found: list[str] = []
    for status_ in said or ():
        found += ["new", "in_progress"] if status_ == "open" else [status_]
    return tuple(dict.fromkeys(found))


async def incidents_found(
    principal: AdminPrincipalDep,
    q: Annotated[
        str | None,
        Query(
            max_length=200,
            description="INC-<number>, its id or technical id, or words of what names its problem.",
        ),
    ] = None,
    incident_status: Annotated[
        list[Literal["open", "new", "in_progress", "resolved", "closed"]] | None,
        Query(
            alias="status",
            description="One or several; `open`: new and in progress; every one when none.",
        ),
    ] = None,
    severity: Literal["critical", "high", "medium", "low"] | None = None,
    category: Literal[
        "intention_failed",
        "agent_failed",
        "api_error",
        "integration_disconnected",
        "sync_failed",
        "credits",
        "payment_failed",
        "platform",
    ]
    | None = None,
    recurring: Annotated[bool | None, Query(description="Three times in a day.")] = None,
    organisation_id: uuid.UUID | None = None,
    organisation: Named = None,
    mine: Annotated[bool, Query(description="Given to me.")] = False,
    unassigned: Annotated[bool, Query(description="Given to no one.")] = False,
    since: datetime | None = None,
    until: datetime | None = None,
    number: Annotated[int | None, Query(ge=1, description="INC-<number>.")] = None,
) -> Select[tuple[Incident]]:
    return incidents_query(
        q=q,
        status=statuses_of(incident_status),
        severity=severity,
        category=category,
        recurring=recurring,
        organisation_id=organisation_id,
        organisation=organisation,
        assignee_id=principal.admin_id if mine else None,
        unassigned=unassigned,
        since=since,
        until=until,
        number=number,
    )


OrganisationsFound = Annotated[Select[tuple[Workspace]], Depends(organisations_found)]
UsersFound = Annotated[Select[tuple[User]], Depends(users_found)]
IntentionsFound = Annotated[Select[tuple[Intention]], Depends(intentions_found)]
MovementsFound = Annotated[Select[tuple[CreditTransaction]], Depends(movements_found)]
SubscriptionsFound = Annotated[Select[tuple[BillingAccount]], Depends(subscriptions_found)]
InvoicesFound = Annotated[Select[tuple[BillingInvoice]], Depends(invoices_found)]
PaymentsFound = Annotated[Select[tuple[BillingPayment]], Depends(payments_found)]
RefundsFound = Annotated[Select[tuple[BillingRefund]], Depends(refunds_found)]
IncidentsFound = Annotated[Select[tuple[Incident]], Depends(incidents_found)]

__all__ = [
    "IncidentsFound",
    "IntentionsFound",
    "InvoicesFound",
    "MovementsFound",
    "OrganisationsFound",
    "PaymentsFound",
    "RefundsFound",
    "SubscriptionsFound",
    "UsersFound",
    "statuses_of",
]
