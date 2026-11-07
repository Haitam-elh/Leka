"""The global search, the filters and the CSV exports of LEKA ADMIN (LEKA-557).

What these protect:
- One query finds organisations (by a Stripe customer id too), people,
  intentions, transactions and incidents, each kind only for a role that
  reads its list, never what a customer wrote; « see all » finds the same.
- An export is its list as filtered: the same filters (declared once, held
  here against the OpenAPI), the same rows, in the same order.
- An export wants the list's permission and exports:create; a refusal is
  kept, and so is each export, with its filters and rows, never its content.
- No secret nor connection in a file: no sign-in, session, link that pays an
  invoice, nor what a customer wrote; a formula is never run; past the
  ceiling, refused before any row is read.
- The filters combine, the journal's by an organisation's and a person's name.
"""

# ruff: noqa: F811 — the admin world's fixtures are imported to be requested by name.
from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, or_, select, update

from leka.admin import (
    DATASETS,
    AdminAccount,
    AdminAuditEvent,
    AdminRole,
    Incident,
    cell,
    search,
)
from leka.admin.incidents import Signal, apply
from leka.api import admin as admin_api
from leka.billing import BillingAccount, BillingInvoice, BillingPayment, BillingRefund
from leka.db import session_factory, system_scope
from leka.intentions import Intention
from leka.main import app
from leka.metering import post_ledger
from tests.test_admin_api import API, NOW, SUPER, World, as_, world  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

OPS = AdminRole.OPERATIONS
SUPPORT = AdminRole.SUPPORT
FINANCE = AdminRole.FINANCE


async def _money(world: World) -> int:
    """An invoice, a payment, a refund and a Stripe customer for Alpha; an
    incident about it, whose number is returned."""
    marker = world.marker
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                update(BillingAccount)
                .where(BillingAccount.workspace_id == world.alpha)
                .values(stripe_customer_id=f"cus_{marker}", stripe_subscription_id=f"sub_{marker}")
            )
            session.add_all(
                [
                    BillingInvoice(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        stripe_invoice_id=f"in_{marker}",
                        stripe_subscription_id=f"sub_{marker}",
                        number=f"LEKA-{marker}-0001",
                        status="paid",
                        billing_reason="subscription_cycle",
                        currency="eur",
                        subtotal=17900,
                        discount=0,
                        tax=3580,
                        total=21480,
                        amount_paid=21480,
                        amount_due=21480,
                        amount_remaining=0,
                        proration=0,
                        issued_at=NOW - timedelta(hours=2),
                        attempts=1,
                        hosted_url=f"https://invoice.stripe.com/i/pay-{marker}",
                        lines=[],
                        said_at=NOW - timedelta(hours=2),
                        said_by=f"evt_in_{marker}",
                    ),
                    BillingPayment(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        reference=f"in_{marker}:paid",
                        stripe_invoice_id=f"in_{marker}",
                        stripe_charge_id=f"ch_{marker}",
                        outcome="succeeded",
                        amount=21480,
                        currency="eur",
                        attempt=1,
                        at=NOW - timedelta(hours=1),
                    ),
                    BillingRefund(
                        workspace_id=world.alpha,
                        id=uuid.uuid4(),
                        stripe_charge_id=f"ch_{marker}",
                        stripe_invoice_id=f"in_{marker}",
                        amount=500,
                        charged=21480,
                        currency="eur",
                        reason="requested_by_customer",
                        at=NOW - timedelta(minutes=30),
                        said_at=NOW - timedelta(minutes=30),
                    ),
                ]
            )
            await post_ledger(session, world.alpha, now=NOW)
            await apply(
                session,
                Signal(
                    category="agent_failed",
                    fingerprint=f"agent:{world.alpha}:agent-{marker}",
                    workspace_id=world.alpha,
                    severity="medium",
                    at=NOW - timedelta(minutes=20),
                    technical_id=f"run-{marker}",
                    detail={"agent": f"agent-{marker}"},
                    dedupe_key=f"test:{marker}",
                ),
            )
            await session.commit()
            number = await session.scalar(
                select(Incident.number).where(Incident.technical_id == f"run-{marker}")
            )
    assert number is not None
    return int(number)


async def _forget_incidents(world: World) -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(delete(Incident).where(Incident.for_workspace_id == world.alpha))
            await session.commit()


def _rows(response: Any) -> list[dict[str, str]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    body = response.content.decode("utf-8")
    assert body.startswith("\ufeff")
    return list(csv.DictReader(io.StringIO(body.removeprefix("\ufeff"))))


async def _trail(action: str, email: str) -> list[AdminAuditEvent]:
    """What an admin's rows of the trail say: kept by their id, or by their
    address when apart (a refusal)."""
    async with session_factory() as session:
        admin = select(AdminAccount.id).where(AdminAccount.email == email).scalar_subquery()
        return list(
            (
                await session.scalars(
                    select(AdminAuditEvent)
                    .where(
                        AdminAuditEvent.action == action,
                        or_(
                            AdminAuditEvent.admin_email == email, AdminAuditEvent.admin_id == admin
                        ),
                    )
                    .order_by(AdminAuditEvent.at)
                )
            ).all()
        )


def _email(world: World, role: AdminRole) -> str:
    return f"{role.value}-{world.marker}@leka.test"


# ── The global search ────────────────────────────────────────────────────────


async def test_one_search_finds_each_kind_the_role_reads(client: AsyncClient, world: World) -> None:
    number = await _money(world)
    try:

        async def found(q: str, role: AdminRole = SUPER) -> dict[str, Any]:
            response = await client.get(f"{API}/search", params={"q": q}, headers=as_(world, role))
            assert response.status_code == 200, response.text
            return dict(response.json())

        said = await found(world.marker)
        names = [o["name"] for o in said["organisations"]["rows"]]
        assert names == [f"Alpha {world.marker}"]  # the demonstration left out
        assert {u["email"] for u in said["users"]["rows"]} == {
            f"owner-{world.marker}@acme.test",
            f"member-{world.marker}@acme.test",
            f"new-{world.marker}@acme.test",
        }
        # A customer's own ids: Stripe's customer, the intention's.
        by_customer = await found(f"cus_{world.marker}")
        assert [o["id"] for o in by_customer["organisations"]["rows"]] == [str(world.alpha)]
        by_id = await found(str(world.intention))
        assert [i["id"] for i in by_id["intentions"]["rows"]] == [str(world.intention)]
        # Never what the customer wrote, and a search is no reading of it.
        assert by_id["intentions"]["rows"][0]["description"] is None
        assert not await _trail("admin.viewed_content", _email(world, SUPER))

        invoice = (await found(f"LEKA-{world.marker}"))["transactions"]["rows"]
        assert [(t["kind"], t["reference"], t["amount"]) for t in invoice] == [
            ("invoice", f"LEKA-{world.marker}-0001", 214.8)
        ]
        charged = (await found(f"ch_{world.marker}"))["transactions"]["rows"]
        assert [t["kind"] for t in charged] == ["refund", "payment"]  # the latest first
        for q in (f"INC-{number}", str(number), f"run-{world.marker}", f"agent-{world.marker}"):
            assert [i["number"] for i in (await found(q))["incidents"]["rows"]] == [number], q

        # Each part only for a role that reads its list.
        finance = await found(world.marker, FINANCE)
        assert finance["intentions"] == {"granted": False, "rows": [], "more": False}
        assert finance["transactions"]["granted"] and finance["incidents"]["granted"]
        support = await found(f"ch_{world.marker}", SUPPORT)
        assert support["transactions"] == {"granted": False, "rows": [], "more": False}
        assert support["intentions"]["granted"]

        # More than shown: said, and the list with the same q has them all.
        with system_scope():
            async with session_factory() as session:
                few = await search(session, world.marker, {admin_api.P.USERS_READ}, limit=2)
        assert few.users.more and len(few.users.rows) == 2
        assert not few.organisations.granted
        listed = await client.get(
            f"{API}/users", params={"q": world.marker}, headers=as_(world, SUPER)
        )
        assert {u["email"] for u in listed.json()["data"]} == {
            u["email"] for u in said["users"]["rows"]
        }

        short = await client.get(f"{API}/search", params={"q": "a"}, headers=as_(world, SUPER))
        assert short.status_code == 422
    finally:
        await _forget_incidents(world)


# ── The exports ──────────────────────────────────────────────────────────────

# Each export and its list: the path, the filters, and how a row says its id
# in the list's JSON and in the file.
CASES: list[tuple[str, str, dict[str, Any], str, str]] = [
    ("organisations", "/organisations", {"q": "{marker}", "include_demo": "true"}, "id", "id"),
    ("users", "/users", {"q": "{marker}", "status": "new"}, "id", "id"),
    ("intentions", "/intentions", {"organisation": "Alpha {marker}"}, "id", "id"),
    ("credit-movements", "/credits/movements", {"organisation_id": "{alpha}"}, "id", "id"),
    ("subscriptions", "/subscriptions", {"organisation": "Alpha {marker}"}, "organisation", ""),
    ("invoices", "/billing/invoices", {"q": "LEKA-{marker}"}, "id", "id"),
    ("payments", "/billing/payments", {"organisation_id": "{alpha}"}, "id", "id"),
    ("refunds", "/billing/refunds", {"q": "ch_{marker}"}, "id", "id"),
    ("incidents", "/incidents", {"organisation_id": "{alpha}", "status": "open"}, "number", ""),
]


def _filled(params: dict[str, Any], world: World) -> dict[str, Any]:
    return {
        key: value.replace("{marker}", world.marker).replace("{alpha}", str(world.alpha))
        for key, value in params.items()
    }


async def test_an_export_is_its_list_as_filtered(client: AsyncClient, world: World) -> None:
    await _money(world)
    try:
        for dataset, path, params, key, column in CASES:
            asked = _filled(params, world)
            listed = await client.get(f"{API}{path}", params=asked, headers=as_(world, SUPER))
            assert listed.status_code == 200, (dataset, listed.text)
            rows = listed.json()["data"]
            assert rows, f"{dataset}: the world has rows for this filter"
            exported = _rows(
                await client.get(
                    f"{API}/exports/{dataset}", params=asked, headers=as_(world, SUPER)
                )
            )
            if key == "organisation":
                want = [r["organisation"]["id"] for r in rows]
                got = [r["organisation_id"] for r in exported]
            elif key == "number":
                want = [f"INC-{r['number']}" for r in rows]
                got = [r["number"] for r in exported]
            else:
                want = [str(r[key]) for r in rows]
                got = [r[column] for r in exported]
            assert got == want, dataset
            # Its columns, the module's own: nothing more, in that order.
            names = [name for name, _ in DATASETS[dataset][1]]
            assert list(exported[0]) == names, dataset

        # The list's order, asked.
        asked = {"q": world.marker, "sort": "email", "order": "asc"}
        listed = await client.get(f"{API}/users", params=asked, headers=as_(world, SUPER))
        exported = _rows(
            await client.get(f"{API}/exports/users", params=asked, headers=as_(world, SUPER))
        )
        assert [r["email"] for r in exported] == [u["email"] for u in listed.json()["data"]]
        assert [r["email"] for r in exported] == sorted(r["email"] for r in exported)
        bad = await client.get(
            f"{API}/exports/users", params={"sort": "password"}, headers=as_(world, SUPER)
        )
        assert bad.status_code == 400
    finally:
        await _forget_incidents(world)


def test_each_export_takes_the_very_filters_of_its_list() -> None:
    """Declared once (leka/api/admin_filters.py): the OpenAPI holds it."""
    paths = app.openapi()["paths"]

    def params(path: str) -> set[str]:
        said = paths[f"{API}{path}"]["get"].get("parameters", [])
        return {p["name"] for p in said if p["in"] == "query"}

    for dataset, path, *_ in CASES:
        listed = params(path) - {"cursor", "limit"}
        assert params(f"/exports/{dataset}") == listed, dataset
    assert set(DATASETS) == {case[0] for case in CASES}


async def test_an_export_wants_two_permissions_and_is_kept(
    client: AsyncClient, world: World
) -> None:
    await _money(world)
    try:
        # Support reads people, but exports nothing: refused, and kept.
        refused = await client.get(
            f"{API}/exports/users", params={"q": world.marker}, headers=as_(world, SUPPORT)
        )
        assert refused.status_code == 403
        [kept] = await _trail("admin.refused", _email(world, SUPPORT))
        assert kept.detail["permission"] == "exports:create"
        # Operations exports, but reads no invoice.
        no_billing = await client.get(f"{API}/exports/invoices", headers=as_(world, OPS))
        assert no_billing.status_code == 403
        [kept] = await _trail("admin.refused", _email(world, OPS))
        assert kept.detail["permission"] == "billing:read"
        assert not await _trail("admin.exported", _email(world, OPS))

        # Finance reads the money and exports it: kept, with its filters.
        asked = {"organisation_id": str(world.alpha), "outcome": "succeeded"}
        done = _rows(
            await client.get(f"{API}/exports/payments", params=asked, headers=as_(world, FINANCE))
        )
        [kept] = await _trail("admin.exported", _email(world, FINANCE))
        assert kept.target_type == "export"
        assert kept.target_id == "payments"
        assert kept.detail == {"dataset": "payments", "filters": asked, "rows": len(done)}
        assert len(done) == 1
    finally:
        await _forget_incidents(world)


async def test_an_export_carries_no_secret_nor_connection(
    client: AsyncClient, world: World
) -> None:
    await _money(world)
    try:
        forbidden = {"hosted_url", "description", "last_login_at", "password", "token", "ip"}
        for dataset, (_, columns) in DATASETS.items():
            assert not {name for name, _ in columns} & forbidden, dataset

        files: dict[str, str] = {}
        for dataset in ("users", "intentions", "invoices"):
            response = await client.get(
                f"{API}/exports/{dataset}",
                params={"organisation": f"Alpha {world.marker}"},
                headers=as_(world, SUPER),
            )
            assert response.status_code == 200, response.text
            files[dataset] = response.content.decode("utf-8")
        # The world's owner has a session: never its token, nor a sign-in.
        assert f"session-{world.marker}" not in files["users"]
        assert "last_login" not in files["users"]
        # The link that pays an invoice, never.
        assert f"pay-{world.marker}" not in files["invoices"]
        # What the customer wrote, never; its title, as the list shows it.
        assert f"Why is payment-api slow? {world.marker}" not in files["intentions"]
        assert "Why is payment-api slow?" in files["intentions"]
        assert files["users"].startswith("\ufeffid,email,") and "\r\n" in files["users"]
    finally:
        await _forget_incidents(world)


def test_a_cell_is_shown_never_run() -> None:
    assert cell('=HYPERLINK("http://x","y")') == '\'=HYPERLINK("http://x","y")'
    assert cell("+33 6 00") == "'+33 6 00"
    assert cell("-fix the build") == "'-fix the build"
    assert cell("@SUM(A1)") == "'@SUM(A1)"
    assert cell(-12.5) == "-12.5"
    assert cell(214.8) == "214.8"
    assert cell(12530.0) == "12530"
    assert cell(-0.0) == "0"
    assert cell(3) == "3"
    assert cell(True) == "true"
    assert cell(None) == ""
    assert cell(datetime(2026, 11, 7, 9, 30, tzinfo=UTC)) == "2026-11-07T09:30:00Z"


async def test_past_the_ceiling_an_export_is_refused_before_any_row(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin_api, "EXPORT_MAX_ROWS", 2)
    refused = await client.get(
        f"{API}/exports/users", params={"q": world.marker}, headers=as_(world, SUPER)
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "export_too_large"
    assert "3 rows" in refused.json()["error"]["message"]
    assert not await _trail("admin.exported", _email(world, SUPER))
    narrowed = await client.get(
        f"{API}/exports/users",
        params={"q": world.marker, "status": "new"},
        headers=as_(world, SUPER),
    )
    assert len(_rows(narrowed)) == 1


# ── The filters ──────────────────────────────────────────────────────────────


async def test_the_journal_filters_combine_by_name(client: AsyncClient, world: World) -> None:
    owner = f"owner-{world.marker}@acme.test"
    response = await client.get(
        f"{API}/activity",
        params={"organisation": f"Alpha {world.marker}", "user": owner},
        headers=as_(world, SUPER),
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows
    assert {(r["organisation"]["name"], r["person"]["email"]) for r in rows} == {
        (f"Alpha {world.marker}", owner)
    }
    # One filter more narrows what the others left.
    kinds = {r["kind"] for r in rows}
    one = sorted(kinds)[0]
    narrowed = await client.get(
        f"{API}/activity",
        params={"organisation": f"Alpha {world.marker}", "user": owner, "kind": one},
        headers=as_(world, SUPER),
    )
    assert {r["kind"] for r in narrowed.json()["data"]} == {one}
    nobody = await client.get(
        f"{API}/activity",
        params={"organisation": f"Alpha {world.marker}", "user": f"nobody-{world.marker}"},
        headers=as_(world, SUPER),
    )
    assert nobody.json()["data"] == []


async def test_a_title_only_is_searched_in_an_intention(client: AsyncClient, world: World) -> None:
    """Words of what the customer wrote find nothing: only its title is
    LEKA ADMIN's to search."""
    with system_scope():
        async with session_factory() as session:
            text = await session.scalar(
                select(Intention.text).where(Intention.id == world.intention)
            )
    assert text and world.marker in text
    said = await client.get(
        f"{API}/search", params={"q": f"slow? {world.marker}"}, headers=as_(world, SUPER)
    )
    assert said.json()["intentions"]["rows"] == []
