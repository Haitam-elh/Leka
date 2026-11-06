"""The users module of LEKA ADMIN (LEKA-550): every person classified by
what they did, never by a sign-in alone — suspended when every organisation
of theirs is; their level of activity from the days they were seen and what
they did; found by organisation, role, status and last activity; their
access in each organisation as LEKA decides it; those invited and not yet
in; their agents; LEKA's internal notes about them.
"""

# ruff: noqa: F811 — the admin world's fixtures are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.admin import AdminAuditEvent, AdminNote, AdminRole
from leka.admin.reads import level_of
from leka.core.security import hash_token
from leka.db import session_factory, system_scope
from leka.identity import User
from leka.platform import Invitation, InvitationStatus, Role
from tests.test_admin_api import API, SUPER, World, as_, world  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


def test_the_level_of_activity_is_days_seen_and_things_done_never_a_sign_in() -> None:
    assert level_of(0, 0) == "none"
    assert (level_of(1, 0), level_of(0, 1)) == ("low", "low")
    assert (level_of(4, 0), level_of(0, 5)) == ("medium", "medium")
    assert (level_of(12, 0), level_of(0, 20)) == ("high", "high")
    assert level_of(3, 4) == "low"


def _emails(response: httpx.Response) -> set[str]:
    return {row["email"].split("-")[0] for row in response.json()["data"]}


async def test_a_person_s_status_and_level_come_from_what_they_did(
    client: AsyncClient, world: World
) -> None:
    rows = (
        await client.get(f"{API}/users", params={"q": world.marker}, headers=as_(world, SUPER))
    ).json()["data"]
    owner = next(r for r in rows if r["email"].startswith("owner-"))
    # An intention and two runs this month, seen today: active, a low level.
    assert owner["status"] == "active"
    assert (owner["actions_30d"], owner["active_days_30d"]) == (3, 1)
    assert owner["activity_level"] == "low"
    assert owner["last_active_at"] is not None
    assert owner["organisations"][0]["organisation_status"] == "active"
    member = next(r for r in rows if r["email"].startswith("member-"))
    assert (member["activity_level"], member["last_active_at"]) == ("none", None)

    # Alpha suspended: the owner has no organisation left to act in; the
    # member still has the demonstration's.
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text("UPDATE workspaces SET status = 'suspended' WHERE id = :id"),
                {"id": world.alpha},
            )
            await session.commit()
    for status, expected in (
        ("suspended", {"owner"}),
        ("new", {"member"}),
        ("unverified", {"new"}),
        ("active", set()),
        ("inactive", set()),
    ):
        found = await client.get(
            f"{API}/users",
            params={"q": world.marker, "status": status},
            headers=as_(world, SUPER),
        )
        assert _emails(found) == expected, status
    again = await client.get(f"{API}/users/{world.owner}", headers=as_(world, SUPER))
    assert again.json()["status"] == "suspended"


async def test_people_are_found_by_organisation_role_and_last_activity(
    client: AsyncClient, world: World
) -> None:
    async def found(**params: str) -> set[str]:
        response = await client.get(
            f"{API}/users", params={"q": world.marker, **params}, headers=as_(world, SUPER)
        )
        assert response.status_code == 200, response.text
        return _emails(response)

    assert await found(organisation=f"alpha {world.marker}") == {"owner", "member"}
    assert await found(organisation=f"Alpha {world.marker}", role="member") == {"member"}
    assert await found(organisation_id=str(world.alpha), role="owner") == {"owner"}
    # The member owns the demonstration: one seat says both.
    assert await found(organisation_id=str(world.demo), role="owner") == {"member"}
    since = (NOW - timedelta(days=1)).isoformat()
    assert await found(active_from=since) == {"owner"}
    assert await found(active_to=since) == set()
    assert await found(never_active="true") == {"member", "new"}
    refused = await client.get(f"{API}/users", params={"role": "boss"}, headers=as_(world, SUPER))
    assert refused.status_code == 422


async def test_a_person_s_access_is_what_leka_lets_them_do_in_each_organisation(
    client: AsyncClient, world: World
) -> None:
    member = (await client.get(f"{API}/users/{world.member}", headers=as_(world, SUPER))).json()
    access = {a["organisation"]["id"]: a for a in member["access"]}
    in_alpha, in_demo = access[str(world.alpha)], access[str(world.demo)]
    assert (in_alpha["role"], in_alpha["custom_role"]) == ("member", None)
    assert "intention:create" in in_alpha["permissions"]
    assert "member:invite" not in in_alpha["permissions"]
    # The same person owns the demonstration: everything there.
    assert in_demo["role"] == "owner"
    assert {"workspace:delete", "member:invite"} <= set(in_demo["permissions"])

    owner = (await client.get(f"{API}/users/{world.owner}", headers=as_(world, SUPER))).json()
    assert owner["agents_used"] == ["code-review"]
    assert owner["analyses_completed"] == 0


async def test_those_invited_are_listed_until_they_accept(
    client: AsyncClient, world: World
) -> None:
    m = world.marker
    with system_scope():
        async with session_factory() as session:
            session.add_all(
                [
                    Invitation(
                        workspace_id=world.alpha,
                        email=email,
                        role=Role.MEMBER,
                        token_hash=hash_token(f"invite-{email}"),
                        status=InvitationStatus.PENDING,
                        expires_at=expires,
                    )
                    for email, expires in (
                        (f"guest-{m}@acme.test", NOW + timedelta(days=5)),
                        (f"late-{m}@acme.test", NOW - timedelta(days=1)),
                        # Already a person of LEKA's, invited to one more.
                        (f"member-{m}@acme.test", NOW + timedelta(days=5)),
                    )
                ]
            )
            await session.commit()
    listed = await client.get(
        f"{API}/invitations", params={"q": m}, headers=as_(world, AdminRole.SUPPORT)
    )
    assert listed.status_code == 200
    rows = {r["email"].split("-")[0]: r for r in listed.json()["data"]}
    assert set(rows) == {"guest", "member"}
    assert (rows["guest"]["has_account"], rows["member"]["has_account"]) == (False, True)
    assert rows["guest"]["organisation"]["id"] == str(world.alpha)
    assert rows["guest"]["role"] == "member"
    expired = await client.get(
        f"{API}/invitations",
        params={"q": m, "include_expired": "true"},
        headers=as_(world, SUPER),
    )
    assert {r["email"].split("-")[0]: r["expired"] for r in expired.json()["data"]} == {
        "guest": False,
        "late": True,
        "member": False,
    }


async def test_a_person_s_agents_are_the_runs_they_asked(client: AsyncClient, world: World) -> None:
    owner = await client.get(
        f"{API}/agents", params={"user_id": str(world.owner)}, headers=as_(world, SUPER)
    )
    [stat] = owner.json()["data"]
    assert (stat["key"], stat["runs"], stat["succeeded"], stat["failed"]) == (
        "code-review",
        2,
        1,
        1,
    )
    member = await client.get(
        f"{API}/agents", params={"user_id": str(world.member)}, headers=as_(world, SUPER)
    )
    assert member.json()["data"] == []


async def test_a_note_about_a_person_is_for_leka_s_team_and_goes_with_them(
    client: AsyncClient, world: World
) -> None:
    path = f"{API}/users/{world.member}/notes"
    written = await client.post(
        path, json={"body": "Prefers the English interface."}, headers=as_(world, AdminRole.SUPPORT)
    )
    assert written.status_code == 201
    listed = await client.get(path, headers=as_(world, AdminRole.FINANCE))
    assert [n["body"] for n in listed.json()["data"]] == ["Prefers the English interface."]
    assert (
        await client.post(
            f"{API}/users/{uuid.uuid4()}/notes", json={"body": "nobody"}, headers=as_(world, SUPER)
        )
    ).status_code == 404

    with system_scope():
        async with session_factory() as session:
            [trail] = (
                await session.scalars(
                    select(AdminAuditEvent).where(
                        AdminAuditEvent.action == "admin.note_added",
                        AdminAuditEvent.target_id == str(world.member),
                    )
                )
            ).all()
            assert (trail.target_type, trail.for_workspace_id, trail.detail) == (
                "user",
                None,
                {"characters": 30},
            )
            # Gone with them.
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": world.member})
            await session.commit()
            left = (
                await session.scalars(
                    select(AdminNote).where(AdminNote.for_user_id == world.member)
                )
            ).all()
    assert left == []
    async with session_factory() as session:
        assert await session.get(User, world.member) is None
