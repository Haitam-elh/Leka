"""What a customer may read of the background loop: the history of their own job runs.

LEKA-334. `job_runs` is the one table the session guard does not protect — a sweep belongs
to no customer, so its owner is NULL — which makes this route the only place where a mistake
becomes a leak between customers, or a leak of the system's own operating data. So most of this
file is that: someone else's runs, and the runs that belong to nobody, must never come back, on
the list or by id, and the two must look exactly like a run that does not exist.

The conventions are LEKA-333's and are not optional: the page envelope, a declared sort
catalogue, typed filters, ApiError codes, a permission dependency in the signature.

Written before the route, and run to watch it fail.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.core.errors import ErrorCode
from leka.db import session_factory, system_scope
from leka.platform import Membership, Role, Workspace
from tests.conftest import FakeIdentity, error_code, error_message, page_items
from tests.job_run_helpers import insert_run

pytestmark = pytest.mark.integration

URL = "/api/v1/jobs"

# What a customer is told about a run, and NOTHING else. `last_error` is missing on purpose:
# an exception message names hosts, paths and queries, and the API says elsewhere (a 500) that
# it will not do that. `args`, `kwargs` and `concurrency_key` are how the system talks to itself.
PUBLIC_FIELDS = {
    "id",
    "job",
    "status",
    "queue",
    "attempts",
    "max_attempts",
    "created_at",
    "started_at",
    "finished_at",
    "next_run_at",
    "request_id",
}


@dataclass
class Team:
    workspace_a: uuid.UUID
    workspace_b: uuid.UUID
    users: dict[str, uuid.UUID]
    runs_a: list[uuid.UUID] = field(default_factory=list)
    run_b: uuid.UUID | None = None
    system_run: uuid.UUID | None = None


async def _user(label: str) -> uuid.UUID:
    async with session_factory() as session:
        result = await session.execute(
            text("INSERT INTO users (email) VALUES (:e) RETURNING id"),
            {"e": f"{label}-{uuid.uuid4().hex[:8]}@acme.example"},
        )
        user_id: uuid.UUID = result.scalar_one()
        await session.commit()
        return user_id


@pytest.fixture
async def team() -> AsyncIterator[Team]:
    """Two customers. A has an owner, an admin and a member and three runs; B has one of
    its own; and one run belongs to nobody."""
    users = {name: await _user(name) for name in ("owner_a", "admin_a", "member_a", "owner_b")}
    with system_scope():
        async with session_factory() as session:
            a = Workspace(name="A", slug=f"a-{uuid.uuid4().hex[:8]}")
            b = Workspace(name="B", slug=f"b-{uuid.uuid4().hex[:8]}")
            session.add_all([a, b])
            await session.flush()
            session.add_all(
                [
                    Membership(workspace_id=a.id, user_id=users["owner_a"], role=Role.OWNER),
                    Membership(workspace_id=a.id, user_id=users["admin_a"], role=Role.ADMIN),
                    Membership(workspace_id=a.id, user_id=users["member_a"], role=Role.MEMBER),
                    Membership(workspace_id=b.id, user_id=users["owner_b"], role=Role.OWNER),
                ]
            )
            await session.flush()
            built = Team(workspace_a=a.id, workspace_b=b.id, users=users)
            for job in ("leka.x.tasks.sync", "leka.x.tasks.index", "leka.x.tasks.notify"):
                built.runs_a.append(await insert_run(session, a.id, job=job))
            built.run_b = await insert_run(session, b.id, job="leka.x.tasks.secret_of_b")
            built.system_run = await insert_run(session, None, job="leka.ingestion.tasks.run_sweep")
            await session.commit()

    yield built

    async with session_factory() as session:
        await session.execute(text("DELETE FROM job_runs WHERE id = :r"), {"r": built.system_run})
        await session.execute(
            text("DELETE FROM workspaces WHERE id IN (:a, :b)"),
            {"a": built.workspace_a, "b": built.workspace_b},
        )
        await session.execute(
            text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": list(users.values())}
        )
        await session.commit()


def _as(identity: FakeIdentity, team: Team, who: str, workspace: uuid.UUID | None = None) -> None:
    identity.sign_in(team.users[who], workspace or team.workspace_a)


# ── Who may read it ───────────────────────────────────────────────────────


@pytest.mark.parametrize("who", ["owner_a", "admin_a"])
async def test_an_admin_or_owner_reads_the_workspaces_job_history(
    client: AsyncClient, identity: FakeIdentity, team: Team, who: str
) -> None:
    _as(identity, team, who)

    response = await client.get(URL)

    assert response.status_code == 200
    assert {row["id"] for row in page_items(response)} == {str(r) for r in team.runs_a}


async def test_a_member_may_not_read_the_job_history(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    """Job names and attempt counts are how the system talks to itself; a member has no use
    for them, and the permission table says so."""
    _as(identity, team, "member_a")

    response = await client.get(URL)

    assert response.status_code == 403
    assert error_code(response) == ErrorCode.PERMISSION_DENIED


async def test_a_member_may_not_read_one_run_either(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    _as(identity, team, "member_a")

    assert (await client.get(f"{URL}/{team.runs_a[0]}")).status_code == 403


# ── What it must never return ─────────────────────────────────────────────


async def test_another_workspaces_runs_are_never_listed(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    _as(identity, team, "owner_a")

    body = (await client.get(URL)).text

    assert str(team.run_b) not in body
    assert "secret_of_b" not in body


async def test_system_runs_never_reach_a_customer(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    """A retention sweep is operating data, not a customer's. The NULL rows are exactly the
    ones a careless `OR for_workspace_id IS NULL` would hand out, and this is the one test that
    stands between the system's own runs and every customer."""
    _as(identity, team, "owner_a")

    listing = await client.get(URL, params={"limit": 200})
    by_id = await client.get(f"{URL}/{team.system_run}")

    assert str(team.system_run) not in listing.text
    assert "run_sweep" not in listing.text
    assert by_id.status_code == 404


async def test_another_workspaces_run_is_not_found_and_not_forbidden(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    """403 would confirm the run exists. A run of someone else's, a run that belongs to
    nobody and a run that never existed must be indistinguishable."""
    _as(identity, team, "owner_a")

    theirs = await client.get(f"{URL}/{team.run_b}")
    nobodys = await client.get(f"{URL}/{team.system_run}")
    absent = await client.get(f"{URL}/{uuid.uuid4()}")

    assert (theirs.status_code, nobodys.status_code, absent.status_code) == (404, 404, 404)
    assert error_code(theirs) == error_code(nobodys) == error_code(absent) == ErrorCode.NOT_FOUND
    assert error_message(theirs) == error_message(nobodys) == error_message(absent)


async def test_a_workspace_offered_by_the_client_is_ignored(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    """The workspace comes from the session, never from a parameter (rule 3)."""
    _as(identity, team, "owner_a")

    response = await client.get(URL, params={"workspace_id": str(team.workspace_b)})

    ids = {row["id"] for row in page_items(response)}
    assert ids == {str(r) for r in team.runs_a}
    assert str(team.run_b) not in ids


async def test_a_run_shows_what_the_documentation_says_and_nothing_more(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    _as(identity, team, "owner_a")

    listed = page_items(await client.get(URL))[0]
    single = (await client.get(f"{URL}/{team.runs_a[0]}")).json()

    assert set(listed) == PUBLIC_FIELDS
    assert set(single) == PUBLIC_FIELDS


async def test_a_single_run_is_returned_unwrapped(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    _as(identity, team, "owner_a")

    body = (await client.get(f"{URL}/{team.runs_a[0]}")).json()

    assert body["id"] == str(team.runs_a[0])
    assert (body["status"], body["attempts"], body["queue"]) == ("queued", 0, "leka")


# ── Lists behave like every other list ────────────────────────────────────


async def test_the_history_pages_through_completely_without_repeats(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    _as(identity, team, "owner_a")

    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = (await client.get(URL, params=params)).json()
        seen.extend(row["id"] for row in body["data"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert sorted(seen) == sorted(str(r) for r in team.runs_a)
    assert len(seen) == len(set(seen))


async def test_the_history_is_newest_first_by_default(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    _as(identity, team, "owner_a")

    rows = page_items(await client.get(URL))

    created = [row["created_at"] for row in rows]
    assert created == sorted(created, reverse=True)


async def test_the_history_can_be_filtered_by_status(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    async with session_factory() as session:
        await session.execute(
            text("UPDATE job_runs SET status = 'failed', finished_at = now() WHERE id = :r"),
            {"r": team.runs_a[0]},
        )
        await session.commit()
    _as(identity, team, "owner_a")

    failed = page_items(await client.get(URL, params={"status": "failed"}))
    queued = page_items(await client.get(URL, params={"status": "queued"}))

    assert [row["id"] for row in failed] == [str(team.runs_a[0])]
    assert str(team.runs_a[0]) not in {row["id"] for row in queued}
    assert len(queued) == 2


async def test_an_unknown_status_is_refused_before_it_reaches_a_query(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    _as(identity, team, "owner_a")

    response = await client.get(URL, params={"status": "exploded"})

    assert response.status_code == 422
    assert error_code(response) == ErrorCode.VALIDATION_FAILED


async def test_only_declared_fields_may_be_sorted_by(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    """`last_error` is a real column and is not in the catalogue — and sorting by it would
    let a client probe what it may not read."""
    _as(identity, team, "owner_a")

    response = await client.get(URL, params={"sort": "last_error"})

    assert response.status_code == 400
    assert error_code(response) == ErrorCode.INVALID_SORT
    assert "created_at" in error_message(response)


async def test_a_forged_cursor_is_refused_not_misread(
    client: AsyncClient, identity: FakeIdentity, team: Team
) -> None:
    _as(identity, team, "owner_a")

    response = await client.get(URL, params={"cursor": "not-a-cursor"})

    assert response.status_code == 400
    assert error_code(response) == ErrorCode.INVALID_CURSOR
