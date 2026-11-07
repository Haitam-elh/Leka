"""Who may open LEKA ADMIN, and what is kept of it (LEKA-544).

Signing in, its one answer for every failure, the lock after wrong
passwords, sessions that end, the four roles refused by default on the
server, a trail nobody can rewrite — and above all: no customer session,
whatever its role, opens a single admin route.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from leka.admin import (
    ROLE_PERMISSIONS,
    AdminAccount,
    AdminAuditEvent,
    AdminPermission,
    AdminRole,
    AdminSession,
    allows,
    create_account,
)
from leka.core import ratelimit
from leka.db import session_factory
from leka.main import app
from tests.conftest import FakeIdentity, error_code

pytestmark = pytest.mark.integration

API = "/api/v1/admin"
PASSWORD = "a long admin passphrase"


async def make_admin(role: AdminRole = AdminRole.SUPER_ADMIN, *, email: str | None = None) -> str:
    address = email or f"admin-{uuid.uuid4().hex[:8]}@leka.test"
    async with session_factory() as session:
        await create_account(
            session, email=address, name="Test Admin", role=role.value, password=PASSWORD, by="test"
        )
        await session.commit()
    return address


async def sign_in(client: AsyncClient, email: str, password: str = PASSWORD) -> str:
    response = await client.post(f"{API}/auth/sign-in", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def trail(email: str) -> list[AdminAuditEvent]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(AdminAuditEvent)
                    .where(AdminAuditEvent.admin_email == email)
                    .order_by(AdminAuditEvent.at)
                )
            ).all()
        )


@pytest.fixture
async def admin_email() -> AsyncIterator[str]:
    yield await make_admin()


# ── Signing in ───────────────────────────────────────────────────────────────


async def test_an_admin_signs_in_and_is_who_the_token_says(
    client: AsyncClient, admin_email: str
) -> None:
    response = await client.post(
        f"{API}/auth/sign-in", json={"email": admin_email.upper(), "password": PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["admin"]["email"] == admin_email
    assert body["admin"]["role"] == "super_admin"
    assert set(body["admin"]["permissions"]) == {p.value for p in AdminPermission}
    assert body["idle_minutes"] == 120

    me = await client.get(f"{API}/me", headers=bearer(body["token"]))
    assert me.status_code == 200
    assert me.json()["email"] == admin_email
    assert [e.action for e in await trail(admin_email)] == ["admin.signed_in"]


async def test_every_failure_has_the_same_answer_and_its_own_reason_in_the_trail(
    client: AsyncClient, admin_email: str
) -> None:
    wrong = await client.post(
        f"{API}/auth/sign-in", json={"email": admin_email, "password": "wrong"}
    )
    unknown_email = f"nobody-{uuid.uuid4().hex[:6]}@leka.test"
    unknown = await client.post(
        f"{API}/auth/sign-in", json={"email": unknown_email, "password": "x"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert error_code(wrong) == error_code(unknown) == "invalid_credentials"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]

    assert [(e.action, e.detail["reason"]) for e in await trail(admin_email)] == [
        ("admin.sign_in_failed", "wrong_password")
    ]
    assert [e.detail["reason"] for e in await trail(unknown_email)] == ["no_account"]


async def test_five_wrong_passwords_lock_the_account(
    client: AsyncClient, admin_email: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import leka.api.admin as routes

    monkeypatch.setattr(
        routes, "SIGN_IN_PER_ACCOUNT", ratelimit.Limit(attempts=100, window_seconds=60)
    )
    for _ in range(5):
        await client.post(f"{API}/auth/sign-in", json={"email": admin_email, "password": "wrong"})

    locked = await client.post(
        f"{API}/auth/sign-in", json={"email": admin_email, "password": PASSWORD}
    )
    assert locked.status_code == 401
    reasons = [e.detail["reason"] for e in await trail(admin_email)]
    assert reasons[-2:] == ["locked_now", "locked"]

    async with session_factory() as session:
        await session.execute(
            update(AdminAccount)
            .where(AdminAccount.email == admin_email)
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert (
        await client.post(f"{API}/auth/sign-in", json={"email": admin_email, "password": PASSWORD})
    ).status_code == 200


async def test_sign_in_is_rate_limited_per_address(client: AsyncClient, admin_email: str) -> None:
    for _ in range(5):
        await client.post(f"{API}/auth/sign-in", json={"email": admin_email, "password": "wrong"})
    sixth = await client.post(
        f"{API}/auth/sign-in", json={"email": admin_email, "password": PASSWORD}
    )
    assert sixth.status_code == 429
    assert error_code(sixth) == "rate_limited"


async def test_a_disabled_admin_cannot_sign_in_and_their_sessions_stop(
    client: AsyncClient, admin_email: str
) -> None:
    token = await sign_in(client, admin_email)
    async with session_factory() as session:
        await session.execute(
            update(AdminAccount).where(AdminAccount.email == admin_email).values(status="disabled")
        )
        await session.commit()
    assert (await client.get(f"{API}/me", headers=bearer(token))).status_code == 401
    refused = await client.post(
        f"{API}/auth/sign-in", json={"email": admin_email, "password": PASSWORD}
    )
    assert refused.status_code == 401
    assert (await trail(admin_email))[-1].detail["reason"] == "disabled"


# ── Sessions ─────────────────────────────────────────────────────────────────


async def test_signing_out_ends_the_session(client: AsyncClient, admin_email: str) -> None:
    token = await sign_in(client, admin_email)
    assert (await client.post(f"{API}/auth/sign-out", headers=bearer(token))).status_code == 204
    assert (await client.get(f"{API}/me", headers=bearer(token))).status_code == 401


@pytest.mark.parametrize(
    "aged",
    [
        {"expires_at": datetime.now(UTC) - timedelta(minutes=1)},
        {"last_seen_at": datetime.now(UTC) - timedelta(minutes=121)},
        {"revoked_at": datetime.now(UTC)},
    ],
    ids=["expired", "idle", "revoked"],
)
async def test_a_session_ends_when_it_should(
    client: AsyncClient, admin_email: str, aged: dict[str, datetime]
) -> None:
    token = await sign_in(client, admin_email)
    async with session_factory() as session:
        account = await session.scalar(
            select(AdminAccount).where(AdminAccount.email == admin_email)
        )
        assert account is not None
        await session.execute(
            update(AdminSession).where(AdminSession.admin_id == account.id).values(**aged)
        )
        await session.commit()
    response = await client.get(f"{API}/me", headers=bearer(token))
    assert response.status_code == 401
    assert error_code(response) == "not_authenticated"


async def test_the_token_is_kept_hashed(client: AsyncClient, admin_email: str) -> None:
    token = await sign_in(client, admin_email)
    async with session_factory() as session:
        stored = (await session.scalars(select(AdminSession.token_hash))).all()
    assert token not in stored


# ── No customer opens LEKA ADMIN ─────────────────────────────────────────────


# The only admin routes open without an admin's token, each a credential in
# itself: a password, or a code sent by email (LEKA-545). Nothing else.
PUBLIC = frozenset(
    {f"{API}/auth/sign-in", f"{API}/auth/forgot-password", f"{API}/auth/reset-password"}
)


def _admin_routes() -> list[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return [
        (method, path)
        for path, operations in paths.items()
        if path.startswith(API)
        for method in operations
        if method in {"get", "post", "patch", "put", "delete"}
    ]


async def test_every_admin_route_but_the_public_three_wants_an_admin_token(
    client: AsyncClient,
) -> None:
    routes = _admin_routes()
    assert {("post", path) for path in PUBLIC} <= set(routes)
    let_through = []
    for method, path in routes:
        if path in PUBLIC:
            continue
        concrete = (
            path.replace("{organisation_id}", str(uuid.uuid4()))
            .replace("{user_id}", str(uuid.uuid4()))
            .replace("{intention_id}", str(uuid.uuid4()))
            .replace("{admin_id}", str(uuid.uuid4()))
            .replace("{session_id}", str(uuid.uuid4()))
            .replace("{role}", "support")
            .replace("{key}", "code-review")
            .replace("{incident_id}", str(uuid.uuid4()))
        )
        assert "{" not in concrete, f"a path parameter this test does not fill: {path}"
        for headers in ({}, bearer("not-a-token"), {"Authorization": "Basic YWRtaW46YWRtaW4="}):
            response = await client.request(method.upper(), concrete, headers=headers, json={})
            if response.status_code != 401:
                let_through.append(
                    f"{method.upper()} {path} with {headers or 'nothing'}: {response.status_code}"
                )
    assert not let_through, "\n".join(let_through)


async def test_a_customer_owner_session_opens_no_admin_route(
    client: AsyncClient, identity: FakeIdentity
) -> None:
    """The customer's seam signed in — as if a workspace owner called — and
    still every admin route refuses: their identity is not LEKA's team's."""
    identity.sign_in(uuid.uuid4(), uuid.uuid4())
    opened = []
    for method, path in _admin_routes():
        if path in PUBLIC or "{" in path:
            continue
        response = await client.request(method.upper(), path, json={})
        if response.status_code != 401:
            opened.append(f"{method.upper()} {path}: {response.status_code}")
    assert not opened, "\n".join(opened)


def test_no_route_outside_the_admin_api_names_an_organisation() -> None:
    """An organisation id in a path is LEKA ADMIN's alone: a customer's routes
    take their workspace from the session (tests/test_tenant_isolation.py)."""
    paths = app.openapi()["paths"]
    named = [p for p in paths if "{organisation_id}" in p and not p.startswith(API)]
    assert not named


# ── Roles ────────────────────────────────────────────────────────────────────


def test_the_four_roles_and_what_they_grant() -> None:
    assert set(ROLE_PERMISSIONS) == set(AdminRole)
    assert ROLE_PERMISSIONS[AdminRole.SUPER_ADMIN] == frozenset(AdminPermission)
    # Only a Super Admin manages admins or reads the admin trail.
    for role in (AdminRole.OPERATIONS, AdminRole.SUPPORT, AdminRole.FINANCE):
        assert not allows(role, AdminPermission.ADMINS_MANAGE)
        assert not allows(role, AdminPermission.AUDIT_READ)
    # What a customer wrote: Support's, not Operations' nor Finance's.
    assert allows(AdminRole.SUPPORT, AdminPermission.INTENTIONS_CONTENT)
    assert not allows(AdminRole.OPERATIONS, AdminPermission.INTENTIONS_CONTENT)
    assert not allows(AdminRole.FINANCE, AdminPermission.INTENTIONS_CONTENT)
    # The money: Finance's.
    assert allows(AdminRole.FINANCE, AdminPermission.BILLING_READ)
    assert allows(AdminRole.FINANCE, AdminPermission.CREDITS_WRITE)
    assert not allows(AdminRole.SUPPORT, AdminPermission.BILLING_READ)
    assert not allows(AdminRole.OPERATIONS, AdminPermission.CREDITS_WRITE)
    # A role nobody knows grants nothing.
    assert not allows("viewer", AdminPermission.DASHBOARD_READ)


# ── The trail ────────────────────────────────────────────────────────────────


async def test_the_admin_trail_cannot_be_rewritten(client: AsyncClient, admin_email: str) -> None:
    await sign_in(client, admin_email)
    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(
                update(AdminAuditEvent)
                .where(AdminAuditEvent.admin_email == admin_email)
                .values(action="admin.nothing")
            )
            await session.flush()
        await session.rollback()


async def test_deleting_an_admin_forgets_who_and_keeps_what(
    client: AsyncClient, admin_email: str
) -> None:
    await sign_in(client, admin_email)
    async with session_factory() as session:
        await session.execute(delete(AdminAccount).where(AdminAccount.email == admin_email))
        await session.commit()
    kept = await trail(admin_email)
    assert [e.action for e in kept] == ["admin.signed_in"]
    assert kept[0].admin_id is None


async def test_an_admin_account_wants_a_long_password_and_a_known_role() -> None:
    from leka.admin import AdminAccountError

    async with session_factory() as session:
        with pytest.raises(AdminAccountError, match="14 characters"):
            await create_account(
                session, email="short@leka.test", name="", role="support", password="short", by="t"
            )
        with pytest.raises(AdminAccountError, match="Unknown role"):
            await create_account(
                session, email="role@leka.test", name="", role="viewer", password=PASSWORD, by="t"
            )
        await session.rollback()


async def test_the_tables_are_leka_s_own() -> None:
    async with session_factory() as session:
        columns = (
            await session.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE column_name = 'workspace_id' "
                    "AND table_name LIKE ANY (ARRAY['admin_%', 'activity_%'])"
                )
            )
        ).all()
    assert columns == []


def test_no_two_contracts_share_a_name() -> None:
    """Two schemas with one name are published as `leka__module__schemas__X`
    by FastAPI, and web/lib/api-types.ts loses the name the screens use
    (an admin `RoleRead` once renamed governance's). Each contract is named
    once (LEKA-545)."""
    names = app.openapi()["components"]["schemas"]
    assert [name for name in names if "__" in name] == []
