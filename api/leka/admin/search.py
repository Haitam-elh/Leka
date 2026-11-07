"""The global search of LEKA ADMIN (LEKA-557): one query, every kind of record
the admin's role reads.

  part           read with                   matches (each list's own `q`)
  organisations  organisations:read          its name, slug, id, an owner's email, its
                                             Stripe customer or subscription id
  users          users:read                  their email, name, id
  intentions     intentions:read             its id, words of its title; never what the
                                             customer wrote
  transactions   billing:read                an invoice's number, Stripe's id of an
                                             invoice, a charge or a subscription
  incidents      incidents:read              its number (INC-42), id, technical id, what
                                             names its problem (an agent, a route)

Each part is its list's query with the same `q`, the first SEARCH_LIMIT rows:
what the search shows, the list shows, and « see all » finds the same rows.
A part the role does not read is not searched (`granted` false), and nothing
of it is said. Demonstration organisations are left out, as in the lists.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.admin.access import AdminPermission
from leka.admin.billing import (
    _eur,
    invoices_query,
    payments_query,
    refunds_query,
)
from leka.admin.incidents import incident_rows, incidents_query
from leka.admin.models import Incident
from leka.admin.reads import (
    _organisation_names,
    intention_rows,
    intentions_query,
    organisation_rows,
    organisations_query,
    user_rows,
    users_query,
)
from leka.admin.schemas import (
    AdminIntentionRow,
    AdminSearch,
    IncidentRow,
    OrganisationRef,
    OrganisationRow,
    SearchPart,
    TransactionHit,
    UserRow,
)
from leka.billing import BillingInvoice, BillingPayment, BillingRefund
from leka.identity import User
from leka.intentions import Intention
from leka.platform import Workspace

P = AdminPermission

MIN_QUERY = 2
SEARCH_LIMIT = 5


async def _first[T](
    session: AsyncSession, statement: Select[tuple[T]], *order: Any, limit: int
) -> tuple[list[T], bool]:
    """The first `limit` rows in `order`, and whether there are more."""
    found = list((await session.scalars(statement.order_by(*order).limit(limit + 1))).all())
    return found[:limit], len(found) > limit


async def search(
    session: AsyncSession,
    q: str,
    permissions: Collection[AdminPermission],
    *,
    limit: int = SEARCH_LIMIT,
) -> AdminSearch:
    """What `q` finds in each list the role reads (LEKA-557)."""
    term = q.strip()

    organisations = SearchPart[OrganisationRow](granted=False, rows=[], more=False)
    if P.ORGANISATIONS_READ in permissions:
        found, more = await _first(
            session,
            organisations_query(q=term),
            Workspace.name,
            Workspace.id,
            limit=limit,
        )
        organisations = SearchPart[OrganisationRow](
            granted=True, rows=await organisation_rows(session, found), more=more
        )

    users = SearchPart[UserRow](granted=False, rows=[], more=False)
    if P.USERS_READ in permissions:
        people, more = await _first(session, users_query(q=term), User.email, User.id, limit=limit)
        users = SearchPart[UserRow](granted=True, rows=await user_rows(session, people), more=more)

    intentions = SearchPart[AdminIntentionRow](granted=False, rows=[], more=False)
    if P.INTENTIONS_READ in permissions:
        asked, more = await _first(
            session,
            intentions_query(q=term),
            Intention.created_at.desc(),
            Intention.id.desc(),
            limit=limit,
        )
        # Never what the customer wrote: a search is not a reading of it.
        rows = await intention_rows(session, asked, with_content=False)
        intentions = SearchPart[AdminIntentionRow](granted=True, rows=rows, more=more)

    transactions = SearchPart[TransactionHit](granted=False, rows=[], more=False)
    if P.BILLING_READ in permissions:
        transactions = await _transactions(session, term, limit)

    incidents = SearchPart[IncidentRow](granted=False, rows=[], more=False)
    if P.INCIDENTS_READ in permissions:
        opened, more = await _first(
            session,
            incidents_query(q=term),
            Incident.last_seen_at.desc(),
            Incident.id.desc(),
            limit=limit,
        )
        incidents = SearchPart[IncidentRow](
            granted=True, rows=await incident_rows(session, opened), more=more
        )

    return AdminSearch(
        query=term,
        organisations=organisations,
        users=users,
        intentions=intentions,
        transactions=transactions,
        incidents=incidents,
    )


async def _transactions(session: AsyncSession, term: str, limit: int) -> SearchPart[TransactionHit]:
    """Invoices, payments and refunds together, the latest first."""
    invoices, more_invoices = await _first(
        session,
        invoices_query(q=term),
        BillingInvoice.issued_at.desc(),
        BillingInvoice.id.desc(),
        limit=limit,
    )
    payments, more_payments = await _first(
        session,
        payments_query(q=term),
        BillingPayment.at.desc(),
        BillingPayment.id.desc(),
        limit=limit,
    )
    refunds, more_refunds = await _first(
        session,
        refunds_query(q=term),
        BillingRefund.at.desc(),
        BillingRefund.id.desc(),
        limit=limit,
    )
    names = await _organisation_names(
        session,
        [
            *(i.workspace_id for i in invoices),
            *(p.workspace_id for p in payments),
            *(r.workspace_id for r in refunds),
        ],
    )

    def ref(workspace_id: Any) -> OrganisationRef:
        return OrganisationRef(id=workspace_id, name=names.get(workspace_id, ""))

    hits = [
        *(
            TransactionHit(
                kind="invoice",
                id=i.stripe_invoice_id,
                organisation=ref(i.workspace_id),
                reference=i.number or i.stripe_invoice_id,
                status=i.status,
                amount=_eur(i.total) or 0.0,
                currency=i.currency,
                at=i.issued_at,
            )
            for i in invoices
        ),
        *(
            TransactionHit(
                kind="payment",
                id=str(p.id),
                organisation=ref(p.workspace_id),
                reference=p.stripe_charge_id or p.stripe_invoice_id,
                status=p.outcome,
                amount=_eur(p.amount) or 0.0,
                currency=p.currency,
                at=p.at,
            )
            for p in payments
        ),
        *(
            TransactionHit(
                kind="refund",
                id=str(r.id),
                organisation=ref(r.workspace_id),
                reference=r.stripe_charge_id,
                status="refunded",
                amount=_eur(r.amount) or 0.0,
                currency=r.currency,
                at=r.at,
            )
            for r in refunds
        ),
    ]
    hits.sort(key=lambda hit: hit.at, reverse=True)
    more = more_invoices or more_payments or more_refunds or len(hits) > limit
    return SearchPart[TransactionHit](granted=True, rows=hits[:limit], more=more)


__all__ = ["MIN_QUERY", "SEARCH_LIMIT", "search"]
