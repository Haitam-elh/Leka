"""LEKA ADMIN's lists taken away as CSV files (LEKA-557).

AS FILTERED, NOTHING ELSE: an export is its list's own query, with the very
filters the list took (the routes share them), read page by page in the
list's order. What the screen showed, the file has, every row of it.

AS THE ROLE READS: an export needs the list's permission and `exports:create`
on top; each one is kept in the admin trail (`admin.exported`): which list,
its filters, how many rows.

NEVER A SECRET NOR A CONNECTION: the columns are chosen here, one by one,
never a row dumped. No password, token, session, IP address nor sign-in
date; no link that opens an invoice (Stripe's hosted page lets whoever holds
it pay it); no word a customer wrote (an intention's description, its
deliverables). An incident's detail is names and codes, diagnostics already
scanned for secrets.

A FILE A SPREADSHEET OPENS SAFELY: UTF-8 with its byte order mark, RFC 4180
(commas, CRLF), dates in ISO 8601 UTC, decimals with a point. A text that
starts as a formula would (`=`, `+`, `-`, `@`) is written after a quote, so
that a spreadsheet shows it and never runs it.

AT MOST EXPORT_MAX_ROWS: more is refused before anything is read, with the
count, to narrow the filters (by period, by organisation).
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from leka.admin.access import AdminPermission
from leka.admin.schemas import (
    AdminIntentionRow,
    CreditMovement,
    IncidentRow,
    InvoiceRow,
    OrganisationRow,
    PaymentRow,
    RefundRow,
    SubscriptionRow,
    UserRow,
)
from leka.db.pagination import MAX_PAGE_SIZE, Direction, SortableField, paginate

P = AdminPermission

EXPORT_MAX_ROWS = 50_000

Cell = str | int | float | bool | datetime | None
Column = tuple[str, Callable[[Any], Cell]]

_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _joined(values: Sequence[str]) -> str:
    return "; ".join(values)


# Whose row it is: an id to join on, a name to read.
_ORGANISATION: tuple[Column, ...] = (
    ("organisation_id", lambda r: r.organisation.id if r.organisation else None),
    ("organisation", lambda r: r.organisation.name if r.organisation else None),
)


def _fields(*names: str) -> tuple[Column, ...]:
    return tuple((name, lambda r, name=name: getattr(r, name)) for name in names)


def _organisations() -> tuple[Column, ...]:
    def owner(r: OrganisationRow) -> str | None:
        return r.owner.email if r.owner else None

    return (
        ("id", lambda r: r.id),
        ("name", lambda r: r.name),
        ("slug", lambda r: r.slug),
        ("status", lambda r: r.status),
        ("plan", lambda r: r.plan),
        ("demo", lambda r: r.demo),
        ("created_at", lambda r: r.created_at),
        ("owner_email", owner),
        ("owner_name", lambda r: r.owner.name if r.owner else None),
        ("country", lambda r: r.country),
        ("size", lambda r: r.size),
        ("size_declared", lambda r: r.size_declared),
        ("members", lambda r: r.members),
        ("intentions", lambda r: r.intentions),
        ("last_activity_at", lambda r: r.last_activity_at),
    )


def _users() -> tuple[Column, ...]:
    def seats(r: UserRow) -> str:
        return _joined([f"{m.organisation.name} ({m.role})" for m in r.organisations])

    return (
        ("id", lambda r: r.id),
        ("email", lambda r: r.email),
        ("name", lambda r: r.name),
        ("status", lambda r: r.status),
        ("verified", lambda r: r.verified),
        ("created_at", lambda r: r.created_at),
        ("organisations", seats),
        ("organisation_ids", lambda r: _joined([str(m.organisation.id) for m in r.organisations])),
        ("intentions", lambda r: r.intentions),
        ("last_active_at", lambda r: r.last_active_at),
        ("active_days_30d", lambda r: r.active_days_30d),
        ("actions_30d", lambda r: r.actions_30d),
        ("activity_level", lambda r: r.activity_level),
    )


def _intentions() -> tuple[Column, ...]:
    def asked_by(r: AdminIntentionRow) -> str | None:
        return r.created_by.email if r.created_by else None

    return (
        ("id", lambda r: r.id),
        *_ORGANISATION,
        ("created_by", asked_by),
        ("title", lambda r: r.title),
        ("kind", lambda r: r.kind),
        ("status", lambda r: r.admin_status),
        ("leka_status", lambda r: r.status),
        ("created_at", lambda r: r.created_at),
        ("status_changed_at", lambda r: r.status_changed_at),
        ("agents", lambda r: _joined(r.agents)),
        ("duration_ms", lambda r: r.duration_ms),
        ("credits", lambda r: r.credits),
    )


def _credit_movements() -> tuple[Column, ...]:
    return (
        ("id", lambda r: r.id),
        *_ORGANISATION,
        *_fields(
            "kind",
            "credits",
            "period",
            "at",
            "origin",
            "reference",
            "execution",
            "subject",
            "by",
            "reason",
            "cost_usd",
            "cost_status",
        ),
    )


def _subscriptions() -> tuple[Column, ...]:
    def discount(r: SubscriptionRow) -> Any:
        return r.discount

    return (
        *_ORGANISATION,
        ("plan", lambda r: r.plan),
        ("interval", lambda r: r.interval),
        ("status", lambda r: r.status),
        ("price_eur", lambda r: r.price_eur),
        ("mrr_eur", lambda r: r.mrr_eur),
        ("discount_percent", lambda r: discount(r).percent_off if discount(r) else None),
        ("discount_eur", lambda r: discount(r).amount_off_eur if discount(r) else None),
        ("discount_ends", lambda r: discount(r).ends if discount(r) else None),
        ("since", lambda r: r.since),
        ("current_period_end", lambda r: r.current_period_end),
        ("cancel_at_period_end", lambda r: r.cancel_at_period_end),
        ("launch_offer_used", lambda r: r.launch_offer_used),
        ("add_ons", lambda r: r.add_ons),
        ("stripe_subscription_id", lambda r: r.stripe_subscription_id),
        ("updated_at", lambda r: r.updated_at),
    )


def _invoices() -> tuple[Column, ...]:
    # Never `hosted_url`: Stripe's page of an invoice lets whoever holds it pay.
    return (
        ("id", lambda r: r.id),
        *_ORGANISATION,
        *_fields(
            "number",
            "status",
            "billing_reason",
            "currency",
            "subtotal",
            "discount",
            "tax",
            "total",
            "amount_paid",
            "amount_remaining",
            "proration",
            "period_start",
            "period_end",
            "issued_at",
            "paid_at",
            "attempts",
        ),
    )


def _payments() -> tuple[Column, ...]:
    return (
        ("id", lambda r: r.id),
        *_ORGANISATION,
        *_fields("outcome", "amount", "currency", "invoice", "attempt", "next_attempt_at", "at"),
    )


def _refunds() -> tuple[Column, ...]:
    return (
        ("id", lambda r: r.id),
        *_ORGANISATION,
        *_fields("charge", "invoice", "amount", "charged", "currency", "reason", "at"),
    )


def _incidents() -> tuple[Column, ...]:
    def detail(r: IncidentRow) -> str:
        return json.dumps(r.detail, sort_keys=True, ensure_ascii=False, default=str)

    return (
        ("number", lambda r: f"INC-{r.number}"),
        *_ORGANISATION,
        *_fields(
            "category",
            "severity",
            "status",
            "recurring",
            "occurrences",
            "technical_id",
            "first_seen_at",
            "last_seen_at",
        ),
        ("assignee", lambda r: r.assignee.email if r.assignee else None),
        ("resolved_at", lambda r: r.resolved_at),
        ("closed_at", lambda r: r.closed_at),
        ("detail", detail),
    )


# Each list that may be exported (the ticket's): the permission that reads
# it, and its columns. Transactions are three: invoices, payments, refunds;
# consumption is the credits ledger, line by line.
DATASETS: dict[str, tuple[AdminPermission, tuple[Column, ...]]] = {
    "organisations": (P.ORGANISATIONS_READ, _organisations()),
    "users": (P.USERS_READ, _users()),
    "intentions": (P.INTENTIONS_READ, _intentions()),
    "credit-movements": (P.CREDITS_READ, _credit_movements()),
    "subscriptions": (P.BILLING_READ, _subscriptions()),
    "invoices": (P.BILLING_READ, _invoices()),
    "payments": (P.BILLING_READ, _payments()),
    "refunds": (P.BILLING_READ, _refunds()),
    "incidents": (P.INCIDENTS_READ, _incidents()),
}

# The row each dataset is made of, for the tests to hold its columns to it.
ROW_OF: dict[str, type[BaseModel]] = {
    "organisations": OrganisationRow,
    "users": UserRow,
    "intentions": AdminIntentionRow,
    "credit-movements": CreditMovement,
    "subscriptions": SubscriptionRow,
    "invoices": InvoiceRow,
    "payments": PaymentRow,
    "refunds": RefundRow,
    "incidents": IncidentRow,
}


def cell(value: Cell) -> str:
    """One value as a spreadsheet reads it, and never runs it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        said = f"{value:.6f}".rstrip("0").rstrip(".")
        return "0" if said in ("-0", "") else said
    text = str(value)
    return "'" + text if text.startswith(_FORMULA) else text


def csv_of(columns: Sequence[Column], rows: Sequence[BaseModel]) -> bytes:
    """The file: its header, then a line per row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([name for name, _ in columns])
    for row in rows:
        writer.writerow([cell(read(row)) for _, read in columns])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


async def count_of(session: AsyncSession, statement: Select[Any]) -> int:
    """How many rows a list's query has, before reading any."""
    counted = select(func.count()).select_from(statement.order_by(None).subquery())
    return int((await session.execute(counted)).scalar_one())


async def every_row[RowT](
    session: AsyncSession,
    statement: Select[tuple[RowT]],
    *,
    sort_by: SortableField,
    id_column: InstrumentedAttribute[Any],
    direction: Direction,
    to_rows: Callable[[Sequence[RowT]], Awaitable[Sequence[BaseModel]]],
) -> list[BaseModel]:
    """Every row of a list's query, in the list's order, page by page as the
    list reads them."""
    rows: list[BaseModel] = []
    cursor: str | None = None
    while True:
        page = await paginate(
            session,
            statement,
            sort_by=sort_by,
            id_column=id_column,
            direction=direction,
            limit=MAX_PAGE_SIZE,
            cursor=cursor,
        )
        rows.extend(await to_rows(page.items))
        if page.next_cursor is None:
            return rows
        cursor = page.next_cursor


def filename_of(dataset: str, now: datetime) -> str:
    return f"leka-{dataset}-{now.astimezone(UTC):%Y%m%d-%H%M}.csv"


__all__ = [
    "DATASETS",
    "EXPORT_MAX_ROWS",
    "ROW_OF",
    "cell",
    "count_of",
    "csv_of",
    "every_row",
    "filename_of",
]
