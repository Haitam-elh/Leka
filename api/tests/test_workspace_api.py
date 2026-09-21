"""The multi-tenant behaviour LEKA-331 promises, exercised over HTTP.

This file IS the Definition of Done. Every test below corresponds to a
sentence in the ticket, and each one describes a way a customer could be
harmed if it stopped passing.

The seam from LEKA-330 is overridden by the `identity` fixture in conftest —
see the note there. Nothing here implements authentication.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.db import session_factory, system_scope
from leka.platform import Role, Workspace, WorkspaceStatus
from tests.conftest import FakeIdentity, error_message, page_items

pytestmark = pytest.mark.integration

API = "/api/v1"


async def _make_user(email_prefix: str) -> uuid.UUID:
    """Insert a person directly.

    Raw SQL because the users table belongs to LEKA-330: creating an account
    is their route, and this test must not pretend to own it.
    """
    with system_scope():
        async with session_factory() as session:
            result = await session.execute(
                text("INSERT INTO users (email) VALUES (:email) RETURNING id"),
                {"email": f"{email_prefix}-{uuid.uuid4().hex[:8]}@acme.example"},
            )
            user_id: uuid.UUID = result.scalar_one()
            await session.commit()
            return user_id


@pytest.fixture
async def people() -> AsyncIterator[dict[str, uuid.UUID]]:
    """Three people, removed afterwards along with everything they own."""
    created = {name: await _make_user(name) for name in ("owner", "admin", "outsider")}

    yield created

    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM workspaces"))
            await session.execute(text("DELETE FROM users"))
            await session.commit()


async def _create_workspace(
    client: AsyncClient, identity: FakeIdentity, user_id: uuid.UUID, name: str
) -> dict[str, Any]:
    identity.sign_in(user_id)
    response = await client.post(f"{API}/workspaces", json={"name": name})
    assert response.status_code == 201, response.text
    workspace: dict[str, Any] = response.json()
    identity.sign_in(user_id, uuid.UUID(workspace["id"]))
    return workspace


# ── Getting in, and not getting in ───────────────────────────────────────────


async def test_creating_a_workspace_seats_you_as_its_owner(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    await _create_workspace(client, identity, people["owner"], "Acme Corp")

    current = await client.get(f"{API}/workspaces/current")

    assert current.status_code == 200
    assert current.json()["role"] == Role.OWNER.value
    assert current.json()["workspace"]["slug"] == "acme-corp"


async def test_entering_a_workspace_without_a_membership_is_refused(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    """The core promise. An outsider pointing their session at someone else's
    workspace gets nothing — not an empty result, a refusal."""
    workspace = await _create_workspace(client, identity, people["owner"], "Acme Corp")

    identity.sign_in(people["outsider"], uuid.UUID(workspace["id"]))
    response = await client.get(f"{API}/workspaces/current")

    assert response.status_code == 403
    assert "not a member" in error_message(response).lower()


async def test_switching_to_a_workspace_you_do_not_belong_to_is_refused(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    """And the session must be left untouched: a refused switch that still
    wrote the id would hand the next request the wrong tenant."""
    workspace = await _create_workspace(client, identity, people["owner"], "Acme Corp")

    identity.sign_in(people["outsider"])
    response = await client.post(f"{API}/workspaces/{workspace['id']}/switch")

    assert response.status_code == 403
    assert identity.switches == []
    assert identity.active_workspace is None


async def test_switching_to_a_workspace_you_belong_to_works(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    first = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    second = await _create_workspace(client, identity, people["owner"], "Globex")

    identity.sign_in(people["owner"], uuid.UUID(first["id"]))
    response = await client.post(f"{API}/workspaces/{second['id']}/switch")

    assert response.status_code == 200
    assert identity.active_workspace == uuid.UUID(second["id"])


async def test_i_only_see_the_workspaces_i_belong_to(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    mine = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    theirs = await _create_workspace(client, identity, people["admin"], "Globex")

    identity.sign_in(people["owner"], uuid.UUID(mine["id"]))
    response = await client.get(f"{API}/workspaces")

    listed = {item["id"] for item in page_items(response)}
    assert mine["id"] in listed
    assert theirs["id"] not in listed


# ── Revocation ───────────────────────────────────────────────────────────────


async def test_removing_a_membership_revokes_access_immediately(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    """The reason the role is never cached in the session.

    No sign-out, no token refresh, no waiting: the very next request is
    refused.
    """
    workspace = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    seat = await _invite_and_accept(client, identity, people, Role.ADMIN, workspace)

    identity.sign_in(people["admin"], uuid.UUID(workspace["id"]))
    assert (await client.get(f"{API}/workspaces/current")).status_code == 200

    identity.sign_in(people["owner"], uuid.UUID(workspace["id"]))
    removed = await client.delete(f"{API}/members/{seat['id']}")
    assert removed.status_code == 204

    identity.sign_in(people["admin"], uuid.UUID(workspace["id"]))
    after = await client.get(f"{API}/workspaces/current")

    assert after.status_code == 403


# ── Roles ────────────────────────────────────────────────────────────────────


async def _invite_and_accept(
    client: AsyncClient,
    identity: FakeIdentity,
    people: dict[str, uuid.UUID],
    role: Role,
    workspace: dict[str, Any],
) -> dict[str, Any]:
    identity.sign_in(people["owner"], uuid.UUID(workspace["id"]))
    invited = await client.post(
        f"{API}/members/invite",
        json={"email": "admin@acme.example", "role": role.value},
    )
    assert invited.status_code == 201, invited.text
    token = invited.json()["token"]

    identity.sign_in(people["admin"], uuid.UUID(workspace["id"]))
    accepted = await client.post(f"{API}/invitations/{token}/accept")
    assert accepted.status_code == 200, accepted.text
    seat: dict[str, Any] = accepted.json()
    return seat


async def test_a_member_cannot_invite_but_an_admin_can(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    workspace = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    await _invite_and_accept(client, identity, people, Role.MEMBER, workspace)

    identity.sign_in(people["admin"], uuid.UUID(workspace["id"]))
    as_member = await client.post(f"{API}/members/invite", json={"email": "someone@acme.example"})
    assert as_member.status_code == 403

    identity.sign_in(people["owner"], uuid.UUID(workspace["id"]))
    as_owner = await client.post(f"{API}/members/invite", json={"email": "someone@acme.example"})
    assert as_owner.status_code == 201


async def test_an_admin_cannot_delete_the_workspace_but_an_owner_can(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    """Managing members must not include ending the company's account."""
    workspace = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    await _invite_and_accept(client, identity, people, Role.ADMIN, workspace)

    identity.sign_in(people["admin"], uuid.UUID(workspace["id"]))
    as_admin = await client.delete(f"{API}/workspaces/current")
    assert as_admin.status_code == 403

    identity.sign_in(people["owner"], uuid.UUID(workspace["id"]))
    as_owner = await client.delete(f"{API}/workspaces/current")
    assert as_owner.status_code == 200


async def test_the_last_owner_cannot_be_removed(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    """A workspace with no owner can never be deleted, transferred or
    rescued — a support ticket created by one careless click."""
    await _create_workspace(client, identity, people["owner"], "Acme Corp")
    members = await client.get(f"{API}/members")
    seat = page_items(members)[0]

    response = await client.delete(f"{API}/members/{seat['id']}")

    assert response.status_code == 409
    assert "last owner" in error_message(response).lower()


# ── Lifecycle ────────────────────────────────────────────────────────────────


async def _set_status(workspace_id: str, status: WorkspaceStatus) -> None:
    with system_scope():
        async with session_factory() as session:
            workspace = await session.get(Workspace, uuid.UUID(workspace_id))
            assert workspace is not None
            workspace.status = status
            await session.commit()


async def test_a_suspended_workspace_reads_but_does_not_write(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    """An unpaid invoice must not look like data loss."""
    workspace = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    await _set_status(workspace["id"], WorkspaceStatus.SUSPENDED)

    readable = await client.get(f"{API}/workspaces/current")
    writable = await client.patch(f"{API}/workspaces/current", json={"name": "Renamed"})

    assert readable.status_code == 200
    assert writable.status_code == 403
    assert "suspended" in error_message(writable).lower()


async def test_a_workspace_awaiting_deletion_refuses_everything(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    workspace = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    await _set_status(workspace["id"], WorkspaceStatus.PENDING_DELETION)

    readable = await client.get(f"{API}/workspaces/current")
    listed = await client.get(f"{API}/members")

    assert readable.status_code == 200  # reading the workspace itself still answers
    assert listed.status_code == 200
    denied = await client.patch(f"{API}/workspaces/current", json={"name": "Renamed"})
    assert denied.status_code == 403
    assert "deletion" in error_message(denied).lower()


# ── Invitations ──────────────────────────────────────────────────────────────


async def test_an_invitation_token_works_once(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    workspace = await _create_workspace(client, identity, people["owner"], "Acme Corp")

    identity.sign_in(people["owner"], uuid.UUID(workspace["id"]))
    invited = await client.post(f"{API}/members/invite", json={"email": "admin@acme.example"})
    token = invited.json()["token"]

    identity.sign_in(people["admin"], uuid.UUID(workspace["id"]))
    first = await client.post(f"{API}/invitations/{token}/accept")
    second = await client.post(f"{API}/invitations/{token}/accept")

    assert first.status_code == 200
    assert second.status_code == 403


async def test_an_expired_invitation_is_refused(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    from datetime import UTC, datetime, timedelta

    from leka.platform import Invitation

    workspace = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    invited = await client.post(f"{API}/members/invite", json={"email": "admin@acme.example"})
    token = invited.json()["token"]

    with system_scope():
        async with session_factory() as session:
            invitation = await session.get(
                Invitation, uuid.UUID(invited.json()["invitation"]["id"])
            )
            assert invitation is not None
            invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    identity.sign_in(people["admin"], uuid.UUID(workspace["id"]))
    response = await client.post(f"{API}/invitations/{token}/accept")

    assert response.status_code == 403


async def test_the_clear_token_is_never_stored(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    """A leaked backup must not be a set of usable invitations."""
    await _create_workspace(client, identity, people["owner"], "Acme Corp")
    invited = await client.post(f"{API}/members/invite", json={"email": "admin@acme.example"})
    token = invited.json()["token"]

    with system_scope():
        async with session_factory() as session:
            found = await session.execute(
                text("SELECT count(*) FROM invitations WHERE token_hash = :token"),
                {"token": token},
            )

    assert found.scalar_one() == 0


# ── Erasure ──────────────────────────────────────────────────────────────────


async def test_deleting_a_workspace_erases_its_data_and_only_its_data(
    client: AsyncClient, identity: FakeIdentity, people: dict[str, uuid.UUID]
) -> None:
    """The GDPR obligation, met by the schema rather than by a script that
    has to remember every table."""
    doomed = await _create_workspace(client, identity, people["owner"], "Acme Corp")
    kept = await _create_workspace(client, identity, people["admin"], "Globex")

    with system_scope():
        async with session_factory() as session:
            workspace = await session.get(Workspace, uuid.UUID(doomed["id"]))
            assert workspace is not None
            await session.delete(workspace)
            await session.commit()

            remaining = await session.execute(text("SELECT workspace_id FROM memberships"))
            owners = {str(row[0]) for row in remaining}

    assert doomed["id"] not in owners
    assert kept["id"] in owners
