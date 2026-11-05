"""LEKA's team, managed by its Super Admins (LEKA-545).

Inviting an admin and their first password, a forgotten password, a changed
one; the Super Admin changing a role, disabling an account, ending its
sessions; what each role may do, set by the Super Admin and applied on the
server at the next request — and the limits nobody can lift.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update

import leka.api.admin as admin_routes
from leka.admin import (
    AdminAccount,
    AdminAuditEvent,
    AdminPrincipal,
    AdminRole,
    create_account,
    permissions_of,
    team,
)
from leka.admin.models import AdminCode
from leka.db import session_factory
from leka.identity import EmailMessage
from leka.main import app
from tests.conftest import error_code

pytestmark = pytest.mark.integration

API = "/api/v1/admin"
PASSWORD = "a long admin passphrase"
NEW_PASSWORD = "another long passphrase"


class Outbox:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)

    def code_for(self, address: str) -> str:
        body = next(m.body for m in reversed(self.sent) if m.to == address)
        found = re.search(r"\b([A-Z2-9]{4}-[A-Z2-9]{4})\b", body)
        assert found, body
        return found.group(1)


@pytest.fixture
def outbox() -> Iterator[Outbox]:
    box = Outbox()
    app.dependency_overrides[admin_routes.get_admin_mailer] = lambda: box
    yield box
    app.dependency_overrides.pop(admin_routes.get_admin_mailer, None)


@dataclass
class Team:
    marker: str
    super_email: str
    token: str

    def headers(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.token}"}

    def address(self, who: str) -> str:
        return f"{who}-{self.marker}@leka.test"


async def make(email: str, role: AdminRole) -> None:
    async with session_factory() as session:
        await create_account(
            session,
            email=email,
            name=email.split("@")[0],
            role=role.value,
            password=PASSWORD,
            by="test",
        )
        await session.commit()


async def sign_in(client: AsyncClient, email: str, password: str = PASSWORD) -> str:
    response = await client.post(f"{API}/auth/sign-in", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


@pytest.fixture
async def crew(client: AsyncClient, outbox: Outbox) -> AsyncIterator[Team]:
    marker = uuid.uuid4().hex[:8]
    super_email = f"super-{marker}@leka.test"
    await make(super_email, AdminRole.SUPER_ADMIN)
    yield Team(marker, super_email, await sign_in(client, super_email))
    async with session_factory() as session:
        await session.execute(
            delete(AdminAccount).where(AdminAccount.email.like(f"%-{marker}@leka.test"))
        )
        await session.commit()


async def _trail(action: str) -> list[AdminAuditEvent]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(AdminAuditEvent).where(AdminAuditEvent.action == action)
                )
            ).all()
        )


# ── Inviting, and the first password ─────────────────────────────────────────


async def test_an_invited_admin_chooses_a_password_with_the_code_then_signs_in(
    client: AsyncClient, crew: Team, outbox: Outbox
) -> None:
    email = crew.address("nadia")
    invited = await client.post(
        f"{API}/admins",
        json={"email": email.upper(), "name": "Nadia", "role": "support"},
        headers=crew.headers(),
    )
    assert invited.status_code == 201, invited.text
    assert (invited.json()["email"], invited.json()["status"], invited.json()["role"]) == (
        email,
        "invited",
        "support",
    )
    message = outbox.sent[-1]
    assert message.to == email
    assert "Support" in message.body and "72 heures" in message.body
    assert "—" not in message.body

    refused = await client.post(f"{API}/auth/sign-in", json={"email": email, "password": PASSWORD})
    assert refused.status_code == 401

    chosen = await client.post(
        f"{API}/auth/reset-password",
        json={"email": email, "code": outbox.code_for(email).lower(), "password": NEW_PASSWORD},
    )
    assert chosen.status_code == 204, chosen.text
    token = await sign_in(client, email, NEW_PASSWORD)
    me = await client.get(f"{API}/me", headers=crew.headers(token))
    assert me.json()["role"] == "support"
    # A code is used once.
    again = await client.post(
        f"{API}/auth/reset-password",
        json={"email": email, "code": outbox.code_for(email), "password": NEW_PASSWORD + "!"},
    )
    assert error_code(again) == "token_invalid"


async def test_inviting_twice_the_same_address_is_refused(client: AsyncClient, crew: Team) -> None:
    payload = {"email": crew.address("twice"), "name": "Twice", "role": "finance"}
    assert (
        await client.post(f"{API}/admins", json=payload, headers=crew.headers())
    ).status_code == 201
    second = await client.post(f"{API}/admins", json=payload, headers=crew.headers())
    assert second.status_code == 409


async def test_a_new_invitation_replaces_the_old_code(
    client: AsyncClient, crew: Team, outbox: Outbox
) -> None:
    email = crew.address("late")
    invited = await client.post(
        f"{API}/admins",
        json={"email": email, "name": "Late", "role": "finance"},
        headers=crew.headers(),
    )
    first = outbox.code_for(email)
    resent = await client.post(
        f"{API}/admins/{invited.json()['id']}/invitation", headers=crew.headers()
    )
    assert resent.status_code == 200
    second = outbox.code_for(email)
    assert first != second
    old = await client.post(
        f"{API}/auth/reset-password", json={"email": email, "code": first, "password": NEW_PASSWORD}
    )
    assert old.status_code == 400
    new = await client.post(
        f"{API}/auth/reset-password",
        json={"email": email, "code": second, "password": NEW_PASSWORD},
    )
    assert new.status_code == 204


async def test_five_wrong_codes_burn_the_code(
    client: AsyncClient, crew: Team, outbox: Outbox
) -> None:
    email = crew.address("guess")
    await client.post(
        f"{API}/admins",
        json={"email": email, "name": "Guess", "role": "support"},
        headers=crew.headers(),
    )
    good = outbox.code_for(email)
    for _ in range(5):
        wrong = await client.post(
            f"{API}/auth/reset-password",
            json={"email": email, "code": "AAAA-AAAA", "password": NEW_PASSWORD},
        )
        assert wrong.status_code == 400
    burnt = await client.post(
        f"{API}/auth/reset-password", json={"email": email, "code": good, "password": NEW_PASSWORD}
    )
    assert burnt.status_code == 400
    assert len(await _trail("admin.code_refused")) >= 6


async def test_an_expired_code_is_refused(client: AsyncClient, crew: Team, outbox: Outbox) -> None:
    email = crew.address("slow")
    await client.post(
        f"{API}/admins",
        json={"email": email, "name": "Slow", "role": "support"},
        headers=crew.headers(),
    )
    async with session_factory() as session:
        await session.execute(
            update(AdminCode)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            .where(
                AdminCode.admin_id
                == select(AdminAccount.id).where(AdminAccount.email == email).scalar_subquery()
            )
        )
        await session.commit()
    late = await client.post(
        f"{API}/auth/reset-password",
        json={"email": email, "code": outbox.code_for(email), "password": NEW_PASSWORD},
    )
    assert late.status_code == 400


async def test_a_short_password_is_refused_and_the_code_kept(
    client: AsyncClient, crew: Team, outbox: Outbox
) -> None:
    email = crew.address("short")
    await client.post(
        f"{API}/admins",
        json={"email": email, "name": "Short", "role": "support"},
        headers=crew.headers(),
    )
    code = outbox.code_for(email)
    short = await client.post(
        f"{API}/auth/reset-password", json={"email": email, "code": code, "password": "short"}
    )
    assert short.status_code == 422
    kept = await client.post(
        f"{API}/auth/reset-password", json={"email": email, "code": code, "password": NEW_PASSWORD}
    )
    assert kept.status_code == 204


# ── Forgotten and changed passwords ──────────────────────────────────────────


async def test_a_forgotten_password_is_replaced_and_every_session_ends(
    client: AsyncClient, crew: Team, outbox: Outbox
) -> None:
    email = crew.address("forgot")
    await make(email, AdminRole.OPERATIONS)
    before = await sign_in(client, email)

    unknown = await client.post(
        f"{API}/auth/forgot-password", json={"email": crew.address("nobody")}
    )
    known = await client.post(f"{API}/auth/forgot-password", json={"email": email})
    assert unknown.status_code == known.status_code == 202
    assert unknown.content == known.content
    assert [m.to for m in outbox.sent] == [email]
    assert "15 minutes" in outbox.sent[-1].body

    reset = await client.post(
        f"{API}/auth/reset-password",
        json={"email": email, "code": outbox.code_for(email), "password": NEW_PASSWORD},
    )
    assert reset.status_code == 204
    assert (await client.get(f"{API}/me", headers=crew.headers(before))).status_code == 401
    await sign_in(client, email, NEW_PASSWORD)


async def test_a_disabled_admin_is_sent_no_code(
    client: AsyncClient, crew: Team, outbox: Outbox
) -> None:
    email = crew.address("gone")
    await make(email, AdminRole.FINANCE)
    async with session_factory() as session:
        await session.execute(
            update(AdminAccount).where(AdminAccount.email == email).values(status="disabled")
        )
        await session.commit()
    assert (
        await client.post(f"{API}/auth/forgot-password", json={"email": email})
    ).status_code == 202
    assert outbox.sent == []


async def test_changing_one_s_password_ends_the_other_sessions(
    client: AsyncClient, crew: Team
) -> None:
    email = crew.address("change")
    await make(email, AdminRole.SUPPORT)
    here, elsewhere = await sign_in(client, email), await sign_in(client, email)
    wrong = await client.post(
        f"{API}/auth/change-password",
        json={"current_password": "not it", "password": NEW_PASSWORD},
        headers=crew.headers(here),
    )
    assert wrong.status_code == 403
    changed = await client.post(
        f"{API}/auth/change-password",
        json={"current_password": PASSWORD, "password": NEW_PASSWORD},
        headers=crew.headers(here),
    )
    assert changed.json() == {"sessions_ended": 1}
    assert (await client.get(f"{API}/me", headers=crew.headers(here))).status_code == 200
    assert (await client.get(f"{API}/me", headers=crew.headers(elsewhere))).status_code == 401


# ── The Super Admin manages the team ─────────────────────────────────────────


async def test_only_a_super_admin_manages_the_team(client: AsyncClient, crew: Team) -> None:
    for role in (AdminRole.OPERATIONS, AdminRole.SUPPORT, AdminRole.FINANCE):
        email = crew.address(role.value)
        await make(email, role)
        token = await sign_in(client, email)
        for method, path in (
            ("GET", f"{API}/admins"),
            ("POST", f"{API}/admins"),
            ("PUT", f"{API}/roles/support/permissions"),
        ):
            response = await client.request(
                method,
                path,
                json={"email": "x@leka.test", "name": "x", "role": "support", "permissions": []},
                headers=crew.headers(token),
            )
            assert response.status_code == 403, (role, method, path)


async def test_a_role_changed_and_an_account_disabled(client: AsyncClient, crew: Team) -> None:
    email = crew.address("moved")
    await make(email, AdminRole.SUPPORT)
    token = await sign_in(client, email)
    listed = await client.get(f"{API}/admins", headers=crew.headers())
    row = next(a for a in listed.json()["data"] if a["email"] == email)
    assert row["sessions"] == 1

    moved = await client.patch(
        f"{API}/admins/{row['id']}", json={"role": "finance"}, headers=crew.headers()
    )
    assert moved.json()["role"] == "finance"
    # Applied at the next request, without signing in again.
    assert (
        await client.get(f"{API}/subscriptions", headers=crew.headers(token))
    ).status_code == 200

    disabled = await client.patch(
        f"{API}/admins/{row['id']}", json={"status": "disabled"}, headers=crew.headers()
    )
    assert disabled.json()["status"] == "disabled"
    assert (await client.get(f"{API}/me", headers=crew.headers(token))).status_code == 401
    kept = await _trail("admin.account_changed")
    afters = [e.detail["after"] for e in kept if e.target_id == row["id"]]
    assert any(isinstance(after, dict) and after["status"] == "disabled" for after in afters)


async def test_a_super_admin_ends_an_admin_s_sessions(client: AsyncClient, crew: Team) -> None:
    email = crew.address("away")
    await make(email, AdminRole.OPERATIONS)
    one, two = await sign_in(client, email), await sign_in(client, email)
    row = next(
        a
        for a in (await client.get(f"{API}/admins", headers=crew.headers())).json()["data"]
        if a["email"] == email
    )
    ended = await client.post(f"{API}/admins/{row['id']}/sign-out", headers=crew.headers())
    assert ended.json() == {"sessions_ended": 2}
    for token in (one, two):
        assert (await client.get(f"{API}/me", headers=crew.headers(token))).status_code == 401


async def test_nobody_changes_their_own_access(client: AsyncClient, crew: Team) -> None:
    me = (await client.get(f"{API}/me", headers=crew.headers())).json()
    for change in ({"role": "support"}, {"status": "disabled"}):
        refused = await client.patch(
            f"{API}/admins/{me['id']}", json=change, headers=crew.headers()
        )
        assert refused.status_code == 409
    renamed = await client.patch(
        f"{API}/admins/{me['id']}", json={"name": "Haïtam"}, headers=crew.headers()
    )
    assert renamed.json()["name"] == "Haïtam"


async def test_the_team_keeps_an_active_super_admin() -> None:
    """Not reachable through the API (a Super Admin cannot change themselves),
    kept for whatever else calls it."""
    marker = uuid.uuid4().hex[:8]
    email = f"last-{marker}@leka.test"
    await make(email, AdminRole.SUPER_ADMIN)
    try:
        async with session_factory() as session:
            await session.execute(
                update(AdminAccount)
                .where(AdminAccount.role == "super_admin", AdminAccount.email != email)
                .values(status="disabled")
            )
            account = await session.scalar(select(AdminAccount).where(AdminAccount.email == email))
            assert account is not None
            somebody = AdminPrincipal(
                admin_id=uuid.uuid4(),
                email="cli",
                name="cli",
                role=AdminRole.SUPER_ADMIN,
                permissions=permissions_of("super_admin"),
                session_id=uuid.uuid4(),
            )
            with pytest.raises(team.TeamError, match="at least one active Super Admin"):
                await team.change(
                    session,
                    somebody,
                    account.id,
                    name=None,
                    role=AdminRole.SUPPORT,
                    status=None,
                    route="t",
                )
            await session.rollback()
    finally:
        async with session_factory() as session:
            await session.execute(delete(AdminAccount).where(AdminAccount.email == email))
            await session.commit()


async def test_an_invited_admin_is_not_made_active_by_hand(client: AsyncClient, crew: Team) -> None:
    invited = await client.post(
        f"{API}/admins",
        json={"email": crew.address("wait"), "name": "Wait", "role": "support"},
        headers=crew.headers(),
    )
    refused = await client.patch(
        f"{API}/admins/{invited.json()['id']}", json={"status": "active"}, headers=crew.headers()
    )
    assert refused.status_code == 409


# ── What each role may do ────────────────────────────────────────────────────


async def test_the_roles_say_what_they_grant(client: AsyncClient, crew: Team) -> None:
    body = (await client.get(f"{API}/roles", headers=crew.headers())).json()
    roles = {r["role"]: r for r in body["roles"]}
    assert set(roles) == {"super_admin", "operations", "support", "finance"}
    assert roles["super_admin"]["editable"] is False
    assert len(roles["super_admin"]["permissions"]) == len(body["permissions"])
    levels = {
        p["permission"]: (p["module"], p["level"], p["grantable"]) for p in body["permissions"]
    }
    assert levels["intentions:content"] == ("intentions", "sensitive", True)
    assert levels["admins:manage"] == ("admins", "sensitive", False)
    assert levels["dashboard:read"] == ("dashboard", "read", True)


async def test_a_role_set_by_the_super_admin_applies_at_the_next_request(
    client: AsyncClient, crew: Team
) -> None:
    email = crew.address("support")
    await make(email, AdminRole.SUPPORT)
    token = await sign_in(client, email)
    assert (await client.get(f"{API}/intentions", headers=crew.headers(token))).status_code == 200
    before = next(
        r
        for r in (await client.get(f"{API}/roles", headers=crew.headers())).json()["roles"]
        if r["role"] == "support"
    )
    try:
        narrowed = await client.put(
            f"{API}/roles/support/permissions",
            json={"permissions": ["dashboard:read"]},
            headers=crew.headers(),
        )
        assert narrowed.json()["permissions"] == ["dashboard:read"]
        assert (
            await client.get(f"{API}/intentions", headers=crew.headers(token))
        ).status_code == 403
        assert len(await _trail("admin.role_changed")) >= 1
    finally:
        await client.put(
            f"{API}/roles/support/permissions",
            json={"permissions": before["permissions"]},
            headers=crew.headers(),
        )


async def test_what_only_a_super_admin_may_do_is_never_given(
    client: AsyncClient, crew: Team
) -> None:
    for permissions in (["admins:manage"], ["audit:read", "dashboard:read"]):
        refused = await client.put(
            f"{API}/roles/operations/permissions",
            json={"permissions": permissions},
            headers=crew.headers(),
        )
        assert refused.status_code == 409
    untouchable = await client.put(
        f"{API}/roles/super_admin/permissions", json={"permissions": []}, headers=crew.headers()
    )
    assert untouchable.status_code == 409
    unknown = await client.put(
        f"{API}/roles/operations/permissions",
        json={"permissions": ["everything"]},
        headers=crew.headers(),
    )
    assert unknown.status_code == 422
