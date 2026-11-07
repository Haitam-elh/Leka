"""The QA and security sweep of LEKA ADMIN's API (LEKA-558): every route, as
every role, rather than one route at a time.

What these protect:
- RBAC: every admin route asks a permission, but the admin's own (signing in
  and out, their sessions, who they are, the roles, the search, whose parts
  each ask theirs); each role is refused (403) exactly what it does not grant,
  never more, never less, and each refusal is kept in the admin trail.
- Documented: every route is in docs/admin/api.md.
- Sensitive data: across every GET route and every export, as each role, no
  password, token, session nor a source's settings; a secret in a source's
  error is masked; what a customer wrote only for intentions:content.
- Isolation: what is read about an organisation says nothing of another.
- Performance: a list's page is read in the same number of queries whatever
  its size (no query per row), within a budget.
"""

# ruff: noqa: F811 — the admin world's fixtures are imported to be requested by name.
from __future__ import annotations

import inspect
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import delete, event, func, select, update

from leka.admin import (
    AdminAccount,
    AdminAuditEvent,
    AdminNotification,
    AdminPermission,
    AdminRole,
    AdminSession,
    Incident,
    credits_of,
    credits_of_many,
)
from leka.admin.incidents import Signal, apply
from leka.api import admin as admin_api
from leka.billing import (
    BillingInvoice,
    BillingPayment,
    BillingRefund,
    StripeEvent,
    SubscriptionChange,
)
from leka.capabilities import AgentRun, ModelCall
from leka.connectors import Source
from leka.core.security import hash_token
from leka.db import engine, session_factory, system_scope, workspace_scope
from leka.governance import CreditPack, month_of
from leka.identity import User
from leka.ingestion import SyncRun
from leka.metering import credits_now, post_ledger
from leka.monitoring import MonitoringAlert
from leka.platform import Invitation, InvitationStatus, Role, Workspace
from tests.test_admin_api import API, NOW, SUPER, World, _build, as_, world  # noqa: F401

pytestmark = pytest.mark.integration

ROOT = API.removesuffix("/admin")
ROOT_DIR = Path(__file__).resolve().parents[2]
ROLES = (AdminRole.OPERATIONS, AdminRole.SUPPORT, AdminRole.FINANCE)
# The admin's own: no permission asked, any admin signed in (or none, to sign
# in). The search asks each part's permission itself (leka/admin/search.py).
OWN = frozenset(
    {
        ("POST", "/admin/auth/sign-in"),
        ("POST", "/admin/auth/forgot-password"),
        ("POST", "/admin/auth/reset-password"),
        ("POST", "/admin/auth/sign-out"),
        ("POST", "/admin/auth/renew"),
        ("POST", "/admin/auth/change-password"),
        ("GET", "/admin/auth/sessions"),
        ("DELETE", "/admin/auth/sessions/{session_id}"),
        ("GET", "/admin/me"),
        ("GET", "/admin/roles"),
        ("GET", "/admin/search"),
    }
)


def _asked(dependant: Dependant) -> frozenset[AdminPermission]:
    """The permissions a route asks, read from its own dependencies."""
    found: set[AdminPermission] = set()
    for dependency in dependant.dependencies:
        call = dependency.call
        if call is not None and getattr(call, "__qualname__", "").startswith(
            "require_admin.<locals>"
        ):
            said = inspect.getclosurevars(call).nonlocals
            found |= {said["permission"], *said.get("also", ())}
        found |= _asked(dependency)
    return frozenset(found)


def _routes() -> Iterator[tuple[str, str, frozenset[AdminPermission], APIRoute]]:
    for route in admin_api.router.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods or ()):
                yield method, route.path, _asked(route.dependant), route


def _concrete(path: str, ids: dict[str, str]) -> str:
    concrete = path
    for name, value in ids.items():
        concrete = concrete.replace("{" + name + "}", value)
    assert "{" not in concrete, f"a path parameter this sweep does not fill: {path}"
    return f"{ROOT}{concrete}"


async def _incident(world: World, key: str) -> str:
    with system_scope():
        async with session_factory() as session:
            await apply(
                session,
                Signal(
                    category="agent_failed",
                    fingerprint=f"agent:{world.alpha}:qa-{key}",
                    workspace_id=world.alpha,
                    severity="critical",
                    at=NOW - timedelta(minutes=5),
                    technical_id=f"run-{key}",
                    detail={"agent": f"qa-{key}"},
                    dedupe_key=f"qa:{key}",
                ),
            )
            await session.commit()
            found = await session.scalar(
                select(Incident.id).where(Incident.technical_id == f"run-{key}")
            )
    assert found is not None
    return str(found)


async def _ids(world: World) -> dict[str, str]:
    async with session_factory() as session:
        admin = await session.scalar(
            select(AdminAccount.id).where(AdminAccount.email == world.admins[1])
        )
    return {
        "organisation_id": str(world.alpha),
        "user_id": str(world.owner),
        "intention_id": str(world.intention),
        "admin_id": str(admin),
        "session_id": str(uuid.uuid4()),
        "role": "support",
        "key": "code-review",
        "incident_id": await _incident(world, world.marker),
    }


async def _granted(client: AsyncClient, world: World, role: AdminRole) -> frozenset[str]:
    me = await client.get(f"{API}/me", headers=as_(world, role))
    assert me.status_code == 200
    return frozenset(me.json()["permissions"])


async def _forget(world: World) -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(delete(Incident).where(Incident.for_workspace_id == world.alpha))
            await session.commit()


# ── RBAC ─────────────────────────────────────────────────────────────────────


def test_every_route_asks_a_permission_but_the_admins_own() -> None:
    unguarded = {(method, path) for method, path, asked, _ in _routes() if not asked}
    assert unguarded == OWN
    # Each permission is asked by a route, but what a customer wrote: that one
    # is read inside the intentions' routes, which say it only to whom has it.
    asked = {p for _, _, permissions, _ in _routes() for p in permissions}
    assert asked == set(AdminPermission) - {AdminPermission.INTENTIONS_CONTENT}


def test_every_route_is_documented() -> None:
    docs = (ROOT_DIR / "docs" / "admin" / "api.md").read_text(encoding="utf-8")
    said = [
        re.compile(
            "^"
            + "/".join(
                "[^/]+" if part.startswith("{") else re.escape(part) for part in path.split("/")
            )
            + "$"
        )
        for path in re.findall(r"`(?:GET|POST|PATCH|PUT|DELETE) (/admin/[^` ?]*)", docs)
    ]
    missing = sorted({path for _, path, _, _ in _routes() if not any(p.match(path) for p in said)})
    assert not missing, f"routes missing from docs/admin/api.md: {missing}"


async def test_each_role_is_refused_exactly_what_it_does_not_grant(
    client: AsyncClient, world: World
) -> None:
    ids = await _ids(world)
    try:
        for role in ROLES:
            granted = await _granted(client, world, role)
            wrong: list[str] = []
            refusals = 0
            for method, path, asked, _ in _routes():
                if not asked:
                    continue
                # An empty body: refused for its role, else for its contents;
                # nothing is ever done.
                response = await client.request(
                    method, _concrete(path, ids), headers=as_(world, role), json={}
                )
                should = not {p.value for p in asked} <= granted
                if (response.status_code == 403) != should:
                    wrong.append(f"{method} {path}: {response.status_code}")
                refusals += should
            assert not wrong, f"{role.value}:\n" + "\n".join(wrong)
            # Every refusal is kept, with the permission it lacked.
            async with session_factory() as session:
                kept = await session.scalar(
                    select(func.count())
                    .select_from(AdminAuditEvent)
                    .where(
                        AdminAuditEvent.action == "admin.refused",
                        AdminAuditEvent.admin_email == f"{role.value}-{world.marker}@leka.test",
                    )
                )
            assert kept == refusals, role
    finally:
        await _forget(world)


# ── Sensitive data ───────────────────────────────────────────────────────────

GITHUB_TOKEN = "ghp_" + "Q7vX2kLm9PzR4tYw8NbC3dHs6JfA1eUo5GiK"


async def _secrets(world: World) -> set[str]:
    """Every secret this world keeps, as it is kept: none may ever be said."""
    owner_password = f"$argon2id$v=19$m=65536,t=3,p=4$qa-{world.marker}"
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                update(User).where(User.id == world.owner).values(password_hash=owner_password)
            )
            await session.execute(
                update(Source)
                .where(Source.workspace_id == world.alpha)
                .values(
                    config={"setting": f"cfg-{world.marker}"},
                    last_error={
                        "code": "AUTH_EXPIRED",
                        "message": f"GitHub refused {GITHUB_TOKEN}",
                        "retryable": False,
                    },
                )
            )
            await session.commit()
            admins = list(
                (
                    await session.execute(
                        select(AdminAccount.id, AdminAccount.password_hash).where(
                            AdminAccount.email.in_(world.admins)
                        )
                    )
                ).all()
            )
            tokens = list(
                (
                    await session.scalars(
                        select(AdminSession.token_hash).where(
                            AdminSession.admin_id.in_([a.id for a in admins])
                        )
                    )
                ).all()
            )
    return {
        owner_password,
        f"cfg-{world.marker}",
        GITHUB_TOKEN,
        f"session-{world.marker}",
        hash_token(f"session-{world.marker}"),
        *(a.password_hash for a in admins if a.password_hash),
        *tokens,
        *world.tokens.values(),
    }


async def test_no_answer_says_a_secret_nor_what_a_customer_wrote_to_whom_may_not(
    client: AsyncClient, world: World
) -> None:
    ids = await _ids(world)
    secrets = await _secrets(world)
    written = {f"Why is payment-api slow? {world.marker}", f"The deliverable {world.marker}"}
    try:
        for role in (SUPER, *ROLES):
            granted = await _granted(client, world, role)
            read = 0
            for method, path, asked, _ in _routes():
                if method != "GET" or not {p.value for p in asked} <= granted:
                    continue
                response = await client.get(
                    _concrete(path, ids),
                    params={"q": world.marker} if path.endswith("/search") else None,
                    headers=as_(world, role),
                )
                assert response.status_code == 200, (role.value, path, response.text[:300])
                body = response.text
                said = sorted(s[:12] for s in secrets if s in body)
                assert not said, f"{role.value} GET {path} says a secret: {said}"
                if "intentions:content" not in granted:
                    assert not [w for w in written if w in body], (role.value, path)
                read += 1
            assert read > 10, role
    finally:
        await _forget(world)


# ── Isolation ────────────────────────────────────────────────────────────────


async def test_what_is_read_about_an_organisation_says_nothing_of_another(
    client: AsyncClient, world: World
) -> None:
    other = uuid.uuid4().hex[:8]
    beta, demo, owner, member, unverified, _ = await _build(other)
    ids = await _ids(world)
    theirs = {f"Alpha {other}", f"owner-{other}@acme.test", f"member-{other}@acme.test", other}
    try:
        for method, path, _asked, _ in _routes():
            if method != "GET" or not (
                "{organisation_id}" in path or "{user_id}" in path or "{intention_id}" in path
            ):
                continue
            response = await client.get(_concrete(path, ids), headers=as_(world, SUPER))
            assert response.status_code == 200, (path, response.text[:300])
            leaked = sorted(m for m in theirs if m in response.text)
            assert not leaked, f"GET {path} about Alpha says of another: {leaked}"
    finally:
        await _forget(world)
        with system_scope():
            async with session_factory() as session:
                await session.execute(delete(Workspace).where(Workspace.id.in_([beta, demo])))
                await session.execute(delete(User).where(User.id.in_([owner, member, unverified])))
                await session.execute(
                    delete(StripeEvent).where(StripeEvent.event_id == f"evt_{other}")
                )
                await session.commit()


# ── Performance ──────────────────────────────────────────────────────────────

# A page answers within this, on a developer's machine as in the CI.
BUDGET_SECONDS = 2.0


@contextmanager
def _queries() -> Iterator[list[str]]:
    said: list[str] = []

    def count(*args: Any) -> None:
        said.append(str(args[2])[:80])

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        yield said
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)


async def _more_rows(client: AsyncClient, world: World, n: int) -> list[tuple[uuid.UUID, ...]]:
    """Enough of each list for a page of three: two more organisations, each
    with its people, intention, runs, source and subscription; and for Alpha,
    invoices, payments, refunds, subscription changes, alerts, invitations,
    source reads, runs of other agents, notes, ledger lines, incidents and
    notifications. The other organisations, to delete afterwards."""
    others = [await _build(uuid.uuid4().hex[:8]) for _ in range(2)]
    with system_scope():
        async with session_factory() as session:
            source = await session.scalar(
                select(Source.id).where(Source.workspace_id == world.alpha)
            )
            assert source is not None
            for i in range(n):
                key = f"{world.marker}-{i}"
                at = NOW - timedelta(hours=i + 1)
                session.add_all(
                    [
                        BillingInvoice(
                            workspace_id=world.alpha,
                            id=uuid.uuid4(),
                            stripe_invoice_id=f"in_qa_{key}",
                            number=f"QA-{key}",
                            status="paid",
                            currency="eur",
                            total=1000,
                            amount_paid=1000,
                            amount_due=1000,
                            amount_remaining=0,
                            issued_at=at,
                            lines=[],
                            said_at=NOW,
                            said_by=f"evt_qa_{key}",
                        ),
                        BillingPayment(
                            workspace_id=world.alpha,
                            id=uuid.uuid4(),
                            reference=f"qa:{key}",
                            stripe_invoice_id=f"in_qa_{key}",
                            stripe_charge_id=f"ch_qa_{key}",
                            outcome="succeeded",
                            amount=1000,
                            currency="eur",
                            at=at,
                        ),
                        BillingRefund(
                            workspace_id=world.alpha,
                            id=uuid.uuid4(),
                            stripe_charge_id=f"ch_qa_{key}",
                            amount=100,
                            charged=1000,
                            currency="eur",
                            at=at,
                            said_at=NOW,
                        ),
                        SubscriptionChange(
                            workspace_id=world.alpha,
                            id=uuid.uuid4(),
                            event_id=f"evt_qa_change_{key}",
                            source="plan",
                            stripe_subscription_id=f"sub_qa_{world.marker}",
                            kind="renewal_off" if i else "new",
                            plan_before="free",
                            plan_after="growth",
                            status_before=None,
                            status_after="active",
                            interval_after="month",
                            mrr_before=0,
                            mrr_after=14320,
                            at=at,
                        ),
                        MonitoringAlert(
                            workspace_id=world.alpha,
                            subject_type="source",
                            subject_id=uuid.uuid4(),
                            subject_name=f"qa-{key}",
                            family="source",
                            kind="source_failing",
                            severity="medium",
                            certainty="confirmed",
                            status="open",
                            opened_at=at,
                            last_seen_at=NOW,
                        ),
                        Invitation(
                            workspace_id=world.alpha,
                            email=f"guest-{key}@acme.test",
                            role=Role.MEMBER,
                            token_hash=hash_token(f"invite-qa-{key}"),
                            status=InvitationStatus.PENDING,
                            expires_at=NOW + timedelta(days=5),
                        ),
                        SyncRun(
                            workspace_id=world.alpha,
                            id=uuid.uuid4(),
                            source_id=source,
                            trigger="schedule",
                            full_read=False,
                            status="succeeded",
                            started_at=at,
                            finished_at=at + timedelta(minutes=1),
                            records=10,
                        ),
                        AgentRun(
                            workspace_id=world.alpha,
                            key=f"qa-agent-{i}",
                            version="1.0.0",
                            status="succeeded",
                            inputs={},
                            requested_by=world.owner,
                            format="markdown",
                            detail={},
                            queued_at=at,
                            started_at=at,
                            finished_at=at + timedelta(minutes=1),
                        ),
                        AdminNotification(
                            id=uuid.uuid4(),
                            kind="payment_failed",
                            severity="high",
                            at=at,
                            for_workspace_id=world.alpha,
                            dedupe_key=f"qa:{key}",
                            detail={},
                        ),
                    ]
                )
            for workspace in (world.alpha, *(other[0] for other in others)):
                await post_ledger(session, workspace, now=NOW)
            await session.commit()
    for i in range(n):
        await _incident(world, f"{world.marker}-{i}")
        for path in (f"organisations/{world.alpha}/notes", f"users/{world.owner}/notes"):
            written = await client.post(
                f"{API}/{path}", json={"body": f"QA note {i}"}, headers=as_(world, SUPER)
            )
            assert written.status_code == 201, written.text
    return others


async def _drop(others: list[tuple[uuid.UUID, ...]]) -> None:
    with system_scope():
        async with session_factory() as session:
            for alpha, demo, owner, member, unverified, _ in others:
                await session.execute(delete(Workspace).where(Workspace.id.in_([alpha, demo])))
                await session.execute(delete(User).where(User.id.in_([owner, member, unverified])))
            await session.commit()


async def test_a_page_is_read_in_the_same_queries_whatever_its_size(
    client: AsyncClient, world: World
) -> None:
    """A query per row shows as one more query for each row more: a page of
    three asks two more than a page of one. A lookup made once, only when a
    row needs it (a person to name), may add one, never two."""
    others = await _more_rows(client, world, 3)
    ids = await _ids(world)
    per_row: list[str] = []
    slow: list[str] = []
    measured = paged = 0
    try:
        for method, path, _, route in _routes():
            name = getattr(route.response_model, "__name__", "")
            if method != "GET" or not name.startswith("PageEnvelope"):
                continue
            paged += 1
            url = _concrete(path, ids)
            await client.get(url, params={"limit": 3}, headers=as_(world, SUPER))  # warm
            counted: dict[int, int] = {}
            for limit in (1, 3):
                with _queries() as said:
                    started = time.perf_counter()
                    response = await client.get(
                        url, params={"limit": limit}, headers=as_(world, SUPER)
                    )
                    took = time.perf_counter() - started
                assert response.status_code == 200, (path, response.text[:300])
                if len(response.json()["data"]) < limit:
                    break
                counted[limit] = len(said)
                if took > BUDGET_SECONDS:
                    slow.append(f"{path}: {took:.2f}s")
            if len(counted) == 2:
                measured += 1
                if counted[3] - counted[1] >= 2:
                    per_row.append(f"{path}: {counted[1]} queries for 1 row, {counted[3]} for 3")
        assert not per_row, "a query per row:\n" + "\n".join(per_row)
        assert not slow, "past the budget:\n" + "\n".join(slow)
        # Every list had a page of three to measure.
        assert measured == paged, (measured, paged)
    finally:
        await _forget(world)
        await _drop(others)


# ── Consistency ──────────────────────────────────────────────────────────────


async def test_what_a_list_says_its_record_says_and_the_customer_sees(
    client: AsyncClient, world: World
) -> None:
    """The same organisation, read in a list, in its record and by the
    customer's own page: the same plan, people, intentions and credits. The
    credits of a list are read for the whole page at once (LEKA-558): they
    are those of each organisation read alone."""
    other = await _build(uuid.uuid4().hex[:8])
    with system_scope():
        async with session_factory() as session:
            session.add_all(
                [
                    CreditPack(
                        workspace_id=world.alpha,
                        credits=250,
                        period=month_of(NOW),
                        reason="QA",
                        granted_by="test",
                        at=NOW,
                    ),
                    *(
                        ModelCall(
                            workspace_id=workspace,
                            purpose="agent:code-review",
                            tier="deep",
                            provider="google",
                            model="gemini-2.5-pro",
                            route="default",
                            owner=owner,
                            status=status,
                            cost_usd=cost,
                            at=NOW - timedelta(minutes=5),
                        )
                        for workspace, owner, status, cost in (
                            (world.alpha, "leka", "ok", 1.2),
                            (world.alpha, "leka", "failed", 9.0),
                            (world.alpha, "workspace", "ok", 4.0),
                            (other[0], "leka", "ok", 0.3),
                        )
                    ),
                ]
            )
            await session.commit()
    try:
        names = {world.alpha: f"Alpha {world.marker}"}
        listed = await client.get(
            f"{API}/credits", params={"q": names[world.alpha]}, headers=as_(world, SUPER)
        )
        [row] = listed.json()["data"]
        record = (
            await client.get(f"{API}/organisations/{world.alpha}", headers=as_(world, SUPER))
        ).json()
        assert row["credits"] == record["credits"]
        assert row["credits"]["packs"] == 250 and row["credits"]["used"] > 0
        with workspace_scope(world.alpha):
            async with session_factory() as session:
                seen = await credits_now(session, world.alpha, now=datetime.now(UTC))
        assert (row["credits"]["used"], row["credits"]["allowance"]) == (seen.used, seen.allowance)
        # A page of organisations: each as read alone.
        with system_scope():
            async with session_factory() as session:
                many = await credits_of_many(session, [world.alpha, other[0]])
                alone = {w: await credits_of(session, w) for w in (world.alpha, other[0])}
        assert many == alone

        [organisation] = (
            await client.get(
                f"{API}/organisations", params={"q": names[world.alpha]}, headers=as_(world, SUPER)
            )
        ).json()["data"]
        assert (organisation["plan"], organisation["members"], organisation["intentions"]) == (
            record["plan"],
            record["counts"]["members"],
            record["counts"]["intentions"],
        )
        [person] = (
            await client.get(
                f"{API}/users",
                params={"q": f"owner-{world.marker}@acme.test"},
                headers=as_(world, SUPER),
            )
        ).json()["data"]
        detail = (await client.get(f"{API}/users/{world.owner}", headers=as_(world, SUPER))).json()
        for field in ("intentions", "status", "activity_level", "actions_30d"):
            assert person[field] == detail[field], field
    finally:
        await _drop([other])
