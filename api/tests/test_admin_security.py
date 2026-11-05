"""LEKA ADMIN's sessions and its trail, kept safe (LEKA-546).

A session renewed into a new token with the same end, the old one let
through for the calls in flight and, shown later, ending its device's
sessions; an admin's own devices listed and closed; the trail refusing to be
rewritten, deleted or emptied, but by the nightly sweep past its retention;
every action the code records named in its catalogue and in the docs; who
read the trail, in the trail.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

import leka.admin.retention as retention
from leka.admin import (
    AdminAccount,
    AdminAuditEvent,
    AdminRole,
    AdminSession,
    audit_record,
    create_account,
    permissions_of,
    sweep_retention,
)
from leka.admin.audit import ACTIONS
from leka.admin.models import AdminCode
from leka.core.security import hash_token
from leka.db import session_factory

pytestmark = pytest.mark.integration

API = "/api/v1/admin"
PASSWORD = "a long admin passphrase"
ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Crew:
    marker: str
    super_email: str
    token: str

    def address(self, who: str) -> str:
        return f"{who}-{self.marker}@leka.test"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make(email: str, role: AdminRole) -> uuid.UUID:
    async with session_factory() as session:
        account = await create_account(
            session,
            email=email,
            name=email.split("@")[0],
            role=role.value,
            password=PASSWORD,
            by="test",
        )
        await session.commit()
        return account.id


async def sign_in(client: AsyncClient, email: str) -> str:
    response = await client.post(f"{API}/auth/sign-in", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


@pytest.fixture
async def crew(client: AsyncClient) -> AsyncIterator[Crew]:
    marker = uuid.uuid4().hex[:8]
    super_email = f"super-{marker}@leka.test"
    await make(super_email, AdminRole.SUPER_ADMIN)
    yield Crew(marker, super_email, await sign_in(client, super_email))
    async with session_factory() as session:
        await session.execute(
            delete(AdminAccount).where(AdminAccount.email.like(f"%-{marker}@leka.test"))
        )
        await session.commit()


async def _session_of(token: str) -> AdminSession:
    async with session_factory() as session:
        found = await session.scalar(
            select(AdminSession).where(AdminSession.token_hash == hash_token(token))
        )
        assert found is not None
        return found


async def _trail(action: str, session_id: uuid.UUID | None = None) -> list[AdminAuditEvent]:
    query = select(AdminAuditEvent).where(AdminAuditEvent.action == action)
    if session_id is not None:
        query = query.where(AdminAuditEvent.session_id == session_id)
    async with session_factory() as session:
        return list((await session.scalars(query)).all())


# ── Renewing a session ───────────────────────────────────────────────────────


async def test_a_renewed_session_has_a_new_token_and_keeps_its_end(
    client: AsyncClient, crew: Crew
) -> None:
    before = await _session_of(crew.token)
    renewed = await client.post(f"{API}/auth/renew", headers=bearer(crew.token))
    assert renewed.status_code == 200, renewed.text
    body = renewed.json()
    assert body["token"] != crew.token
    assert body["admin"]["email"] == crew.super_email

    after = await _session_of(body["token"])
    assert after.id != before.id
    assert (after.family_id, after.signed_in_at, after.expires_at) == (
        before.family_id,
        before.signed_in_at,
        before.expires_at,
    )
    old = await _session_of(crew.token)
    assert (old.ended_reason, old.revoked_at is not None) == ("renewed", True)

    me = await client.get(f"{API}/me", headers=bearer(body["token"]))
    assert me.status_code == 200
    [row] = await _trail("admin.session_renewed", session_id=before.id)
    assert row.target_id == str(after.id)


async def test_the_old_token_still_works_a_moment_but_is_never_renewed_twice(
    client: AsyncClient, crew: Crew
) -> None:
    renewed = await client.post(f"{API}/auth/renew", headers=bearer(crew.token))
    assert renewed.status_code == 200
    # A call that left with the old token comes back: let through.
    assert (await client.get(f"{API}/me", headers=bearer(crew.token))).status_code == 200
    again = await client.post(f"{API}/auth/renew", headers=bearer(crew.token))
    assert again.status_code == 409
    assert (
        await client.get(f"{API}/me", headers=bearer(renewed.json()["token"]))
    ).status_code == 200


async def test_a_renewed_token_shown_after_its_grace_ends_every_session_of_its_device(
    client: AsyncClient, crew: Crew
) -> None:
    other_device = await sign_in(client, crew.super_email)
    renewed = await client.post(f"{API}/auth/renew", headers=bearer(crew.token))
    new_token = renewed.json()["token"]
    old = await _session_of(crew.token)
    async with session_factory() as session:
        await session.execute(
            update(AdminSession)
            .where(AdminSession.id == old.id)
            .values(revoked_at=datetime.now(UTC) - timedelta(minutes=2))
        )
        await session.commit()

    assert (await client.get(f"{API}/me", headers=bearer(crew.token))).status_code == 401
    # The copy and the device it was copied from are both out…
    assert (await client.get(f"{API}/me", headers=bearer(new_token))).status_code == 401
    assert (await _session_of(new_token)).ended_reason == "reused"
    # …the admin's other device is not.
    assert (await client.get(f"{API}/me", headers=bearer(other_device))).status_code == 200
    [row] = await _trail("admin.session_reused", session_id=old.id)
    assert row.detail == {"family": str(old.family_id), "sessions_ended": 1}


async def test_a_token_signed_out_is_simply_refused(client: AsyncClient, crew: Crew) -> None:
    assert (
        await client.post(f"{API}/auth/sign-out", headers=bearer(crew.token))
    ).status_code == 204
    assert (await client.get(f"{API}/me", headers=bearer(crew.token))).status_code == 401
    assert (await client.post(f"{API}/auth/renew", headers=bearer(crew.token))).status_code == 401
    assert (await _session_of(crew.token)).ended_reason == "signed_out"


# ── One's own devices ────────────────────────────────────────────────────────


async def test_an_admin_sees_their_devices_and_closes_one_from_another(
    client: AsyncClient, crew: Crew
) -> None:
    tablet = await sign_in(client, crew.super_email)
    listed = await client.get(f"{API}/auth/sessions", headers=bearer(crew.token))
    assert listed.status_code == 200
    sessions = listed.json()["sessions"]
    phone_id = str((await _session_of(crew.token)).id)
    tablet_id = str((await _session_of(tablet)).id)
    assert {s["id"]: s["current"] for s in sessions} == {phone_id: True, tablet_id: False}

    closed = await client.delete(f"{API}/auth/sessions/{tablet_id}", headers=bearer(crew.token))
    assert closed.status_code == 204
    assert (await client.get(f"{API}/me", headers=bearer(tablet))).status_code == 401
    assert (await _session_of(tablet)).ended_reason == "ended_by_self"
    [row] = await _trail("admin.session_ended", session_id=uuid.UUID(phone_id))
    assert row.target_id == tablet_id

    again = await client.delete(f"{API}/auth/sessions/{tablet_id}", headers=bearer(crew.token))
    assert again.status_code == 404


async def test_nobody_closes_another_admins_session(client: AsyncClient, crew: Crew) -> None:
    support = crew.address("sami")
    await make(support, AdminRole.SUPPORT)
    theirs = await sign_in(client, support)
    their_id = (await _session_of(theirs)).id
    refused = await client.delete(f"{API}/auth/sessions/{their_id}", headers=bearer(crew.token))
    assert refused.status_code == 404
    assert (await client.get(f"{API}/me", headers=bearer(theirs))).status_code == 200


async def test_signing_in_says_what_the_role_grants_now_not_its_defaults(
    client: AsyncClient, crew: Crew
) -> None:
    support = crew.address("lina")
    await make(support, AdminRole.SUPPORT)
    narrower = ["dashboard:read", "organisations:read"]
    defaults = sorted(permissions_of(AdminRole.SUPPORT.value))
    set_to = await client.put(
        f"{API}/roles/support/permissions",
        json={"permissions": narrower},
        headers=bearer(crew.token),
    )
    assert set_to.status_code == 200, set_to.text
    try:
        signed = await client.post(
            f"{API}/auth/sign-in", json={"email": support, "password": PASSWORD}
        )
        assert signed.json()["admin"]["permissions"] == narrower
        me = await client.get(f"{API}/me", headers=bearer(signed.json()["token"]))
        assert me.json()["permissions"] == narrower
    finally:
        await client.put(
            f"{API}/roles/support/permissions",
            json={"permissions": defaults},
            headers=bearer(crew.token),
        )


# ── The trail: who read it, which session did what ───────────────────────────


async def test_reading_the_trail_is_in_the_trail_with_its_session(
    client: AsyncClient, crew: Crew
) -> None:
    read = await client.get(
        f"{API}/audit", params={"action": "admin.signed_in"}, headers=bearer(crew.token)
    )
    assert read.status_code == 200
    mine = (await _session_of(crew.token)).id
    [row] = await _trail("admin.viewed_trail", session_id=mine)
    assert (row.route, row.detail["filters"]) == (f"GET {API}/audit", {"action": "admin.signed_in"})
    signed = [r for r in read.json()["data"] if r["session_id"] == str(mine)]
    assert [r["action"] for r in signed] == ["admin.signed_in"]

    # The reading itself kept the admin's id only; read back, it says who by address.
    again = await client.get(
        f"{API}/audit", params={"action": "admin.viewed_trail"}, headers=bearer(crew.token)
    )
    [viewed] = [r for r in again.json()["data"] if r["session_id"] == str(mine)]
    assert viewed["admin_email"] == crew.super_email


# ── The trail refuses to be rewritten, deleted or emptied ────────────────────


async def _kept_row(at: datetime) -> uuid.UUID:
    """A row as it would have been written then: an insert, which the trail
    takes."""
    async with session_factory() as session:
        moved = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO admin_audit_events (id, at, action, outcome, target_type, detail)"
                " VALUES (:id, :at, 'admin.viewed', 'succeeded', 'test', '{}')"
            ),
            {"id": moved, "at": at},
        )
        await session.commit()
        return moved


async def _refused(statement: str, *, sweep: bool = False, **values: object) -> bool:
    async with session_factory() as session:
        try:
            if sweep:
                await session.execute(text("SET LOCAL leka.admin_audit_sweep = 'on'"))
            await session.execute(text(statement), values)
        except DBAPIError:
            return True
        finally:
            await session.rollback()
    return False


async def test_no_row_of_the_trail_is_rewritten_deleted_or_emptied() -> None:
    recent = await _kept_row(datetime.now(UTC))
    assert await _refused(
        "UPDATE admin_audit_events SET action = 'admin.signed_in' WHERE id = :id", id=recent
    )
    assert await _refused("DELETE FROM admin_audit_events WHERE id = :id", id=recent)
    # Not even the sweep deletes a row under six months old.
    assert await _refused("DELETE FROM admin_audit_events WHERE id = :id", sweep=True, id=recent)
    assert await _refused("TRUNCATE admin_audit_events")


async def test_only_the_sweep_deletes_a_row_and_only_past_six_months() -> None:
    old = await _kept_row(datetime.now(UTC) - timedelta(days=200))
    assert await _refused("DELETE FROM admin_audit_events WHERE id = :id", id=old)
    assert not await _refused("DELETE FROM admin_audit_events WHERE id = :id", sweep=True, id=old)


# ── Retention: the nightly sweep ─────────────────────────────────────────────


async def test_the_sweep_deletes_what_is_past_its_keeping_and_says_so() -> None:
    now = datetime.now(UTC)
    expired = await _kept_row(now - timedelta(days=400))
    within = await _kept_row(now - timedelta(days=200))
    admin_id = await make(f"swept-{uuid.uuid4().hex[:8]}@leka.test", AdminRole.SUPPORT)

    def a_session(**values: object) -> AdminSession:
        first = uuid.uuid4()
        defaults: dict[str, object] = {
            "id": first,
            "admin_id": admin_id,
            "token_hash": uuid.uuid4().hex,
            "family_id": first,
            "signed_in_at": now - timedelta(days=50),
            "last_seen_at": now - timedelta(days=50),
            "expires_at": now + timedelta(hours=1),
        }
        return AdminSession(**{**defaults, **values})

    closed_long_ago = a_session(revoked_at=now - timedelta(days=40), ended_reason="signed_out")
    over_long_ago = a_session(expires_at=now - timedelta(days=40))
    closed_lately = a_session(revoked_at=now - timedelta(days=10), ended_reason="signed_out")
    open_now = a_session(last_seen_at=now)
    spent = AdminCode(
        id=uuid.uuid4(),
        admin_id=admin_id,
        purpose="reset",
        code_hash="x" * 64,
        expires_at=now - timedelta(days=8),
        attempts=0,
    )
    live = AdminCode(
        id=uuid.uuid4(),
        admin_id=admin_id,
        purpose="invite",
        code_hash="y" * 64,
        expires_at=now + timedelta(days=1),
        attempts=0,
    )
    async with session_factory() as session:
        session.add_all([closed_long_ago, over_long_ago, closed_lately, open_now, spent, live])
        await session.commit()
    try:
        swept = await sweep_retention(now=now)
        assert swept["trail"] >= 1 and swept["sessions"] >= 2 and swept["codes"] >= 1
        async with session_factory() as session:
            trail = set((await session.scalars(select(AdminAuditEvent.id))).all())
            sessions = set(
                (
                    await session.scalars(
                        select(AdminSession.id).where(AdminSession.admin_id == admin_id)
                    )
                ).all()
            )
            codes = set(
                (
                    await session.scalars(
                        select(AdminCode.id).where(AdminCode.admin_id == admin_id)
                    )
                ).all()
            )
        assert expired not in trail and within in trail
        assert sessions == {closed_lately.id, open_now.id}
        assert codes == {live.id}
        counts = [r.detail["count"] for r in await _trail("admin.trail_expired")]
        assert any(isinstance(count, int) and count >= 1 for count in counts)
    finally:
        async with session_factory() as session:
            await session.execute(delete(AdminAccount).where(AdminAccount.id == admin_id))
            await session.commit()


async def test_the_trail_is_protected_and_the_sweep_says_so_when_it_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        assert await retention.unprotected(session) == []

    expired = await _kept_row(datetime.now(UTC) - timedelta(days=400))

    async def a_trigger_gone(session: object) -> list[str]:
        return ["admin_audit_events_never_emptied"]

    monkeypatch.setattr(retention, "unprotected", a_trigger_gone)
    swept = await sweep_retention()
    assert swept["trail"] == 0
    async with session_factory() as session:
        assert await session.get(AdminAuditEvent, expired) is not None
    [*_, said] = await _trail("admin.trail_unprotected")
    assert (said.outcome, said.detail) == (
        "failed",
        {"missing": ["admin_audit_events_never_emptied"]},
    )


# ── Every action said, and said in the docs ──────────────────────────────────


def _recorded_actions() -> set[str]:
    sources = [*(ROOT / "leka" / "admin").glob("*.py"), ROOT / "leka" / "api" / "admin.py"]
    found: set[str] = set()
    for source in sources:
        code = source.read_text(encoding="utf-8")
        found |= set(re.findall(r'"(admin\.[a-z_]+)"', code))
        # f"admin.organisation_{action}" (leka/admin/actions.py).
        if 'f"admin.organisation_{action}"' in code:
            found |= {"admin.organisation_suspended", "admin.organisation_reactivated"}
    return found


def test_every_action_the_code_records_is_in_the_catalogue_and_none_is_unused() -> None:
    assert _recorded_actions() == set(ACTIONS)


def test_the_docs_name_every_action_of_the_trail() -> None:
    docs = (ROOT.parent / "docs" / "admin" / "api.md").read_text(encoding="utf-8")
    missing = sorted(action for action in ACTIONS if f"`{action}`" not in docs)
    assert not missing, missing


async def test_an_action_nobody_catalogued_is_refused() -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match=r"admin\.made_up"):
            audit_record(session, "admin.made_up", admin_id=None)
