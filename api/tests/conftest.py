"""Shared fixtures.

THE TESTS RUN AGAINST THEIR OWN DATABASE, and the redirection happens at the
top of this file — before anything imports leka, because leka.core.config
reads the environment once, at import. That is why the leka imports below
sit after a statement instead of with the others, and why this file carries
an E402 exemption.

This is not tidiness. These tests delete every row in `users` and
`workspaces` between cases, and they used to do it in whatever database
LEKA_DATABASE_URL pointed at — which, on a developer's machine, is the one
holding their demo data. Running the suite silently destroyed it, and the
symptom was "I cannot sign in any more" with no obvious cause.

The test database is created and migrated automatically on first run.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest
from alembic.config import Config
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command


def _from_dotenv(name: str) -> str | None:
    """Read one variable out of .env, by hand.

    This runs before leka.core.config is imported, so pydantic-settings has
    not loaded anything yet — and it cannot, because the redirection below
    has to happen first. Six lines of parsing rather than a dependency, or
    than every developer remembering to export a variable the project
    already stores in a file.
    """
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name}=") and not stripped.startswith("#"):
            return stripped.split("=", 1)[1].strip() or None
    return None


def _redirect_to_a_test_database() -> str:
    """Point this process at <database>_test, creating the name if needed.

    Runs at import, before leka.core.config is loaded. CI already sets a
    dedicated database, so a name that already ends in _test is left alone.

    The environment wins over .env, because CI sets it and a developer
    overriding it for one run means it. Falling back to .env is what makes
    `pytest` work from a plain shell — docs/setup.md says to run exactly
    that, and it used to fail with a message about a variable nobody had
    been told to export.
    """
    url = os.environ.get("LEKA_DATABASE_URL") or _from_dotenv("LEKA_DATABASE_URL")
    if url is None:
        msg = (
            "LEKA_DATABASE_URL is neither in the environment nor in .env. "
            "Copy .env.example to .env and fill it in — see docs/setup.md."
        )
        raise RuntimeError(msg)

    parsed = urlparse(url)
    name = parsed.path.lstrip("/")
    if not name.endswith("_test"):
        url = urlunparse(parsed._replace(path=f"/{name}_test"))

    # Set in both cases, including when the value came from .env: everything
    # imported after this point reads the environment, and a value that only
    # lived in this function would let the suite run against the developer's
    # own database.
    os.environ["LEKA_DATABASE_URL"] = url
    return url


TEST_DATABASE_URL = _redirect_to_a_test_database()

from leka.core.config import settings
from leka.main import app
from leka.platform import UserId, WorkspaceId, get_current_user_id, get_session_store


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    """Create and migrate the test database, once per run.

    Created here rather than by a setup step a developer has to remember:
    `pytest` should work on a machine where only `docker compose up` has been
    run, and a test suite with a manual prerequisite is a test suite someone
    eventually skips.
    """

    parsed = urlparse(TEST_DATABASE_URL)
    name = parsed.path.lstrip("/")
    admin = urlunparse(parsed._replace(path="/postgres")).replace(
        "postgresql+asyncpg://", "postgresql://"
    )

    async def ensure() -> None:
        connection = await asyncpg.connect(admin)
        try:
            exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
            if not exists:
                await connection.execute(f'CREATE DATABASE "{name}"')
        finally:
            await connection.close()

    asyncio.run(ensure())

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(config, "head")


# ── LEKA-330's seam, implemented for tests ───────────────────────────────────
#
# LEKA-331's routes need to know who is calling and which workspace is
# active. Both come from LEKA-330, which does not exist yet. Rather than wait
# — or, worse, build a second authentication — the tests satisfy the seam's
# contract with the simplest thing that can.
#
# This is what the seam is for. When LEKA-330 lands, its real implementations
# replace these overrides and not one line of LEKA-331 changes. If that turns
# out not to be true, the contract was wrong, and better to find out here.


@dataclass
class FakeIdentity:
    """Who the next request comes from, and where it is.

    A test mutates these between calls the way a real session would change
    between sign-ins and switches.
    """

    user_id: uuid.UUID | None = None
    active_workspace: uuid.UUID | None = None
    # What set_active_workspace was asked to do, in order. Lets a test assert
    # that a refused switch left the session untouched.
    switches: list[uuid.UUID] = field(default_factory=list)

    async def current_user_id(self, request: Request) -> UserId:
        if self.user_id is None:
            msg = "no signed-in user in this test"
            raise RuntimeError(msg)
        return UserId(self.user_id)

    async def get_active_workspace(self, request: Request) -> WorkspaceId | None:
        if self.active_workspace is None:
            return None
        return WorkspaceId(self.active_workspace)

    async def set_active_workspace(self, request: Request, workspace_id: WorkspaceId) -> None:
        self.switches.append(workspace_id)
        self.active_workspace = workspace_id

    def sign_in(self, user_id: uuid.UUID, workspace_id: uuid.UUID | None = None) -> None:
        self.user_id = user_id
        self.active_workspace = workspace_id


@pytest.fixture
def identity() -> Iterator[FakeIdentity]:
    """LEKA-330's seam, implemented for tests.

    Overrides the two dependencies LEKA-331 consumes. Removed afterwards, so
    a test that forgets to sign in gets the real dependency and its
    NotImplementedError rather than the previous test's user.
    """
    fake = FakeIdentity()

    # Save whatever was there. Since LEKA-330, leka.main installs the REAL
    # implementations at import — popping instead of restoring would leave
    # the application unauthenticated for every test that ran afterwards,
    # and the failure would depend on test order.
    previous = {
        dependency: app.dependency_overrides.get(dependency)
        for dependency in (get_current_user_id, get_session_store)
    }

    app.dependency_overrides[get_current_user_id] = fake.current_user_id
    app.dependency_overrides[get_session_store] = lambda: fake

    yield fake

    for dependency, original in previous.items():
        if original is None:
            app.dependency_overrides.pop(dependency, None)
        else:
            app.dependency_overrides[dependency] = original


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An HTTP client wired straight to the ASGI app — no network, no port.

    base_url is https, and that matters: the session cookie is issued with
    Secure, so httpx correctly refuses to send it back over http. Testing
    against http would have meant turning Secure off for tests — that is,
    testing a cookie configuration we never ship.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as http_client:
        yield http_client


@pytest.fixture(autouse=True)
async def clear_rate_limits() -> AsyncIterator[None]:
    """Forget throttling counters between tests.

    Rate limiting is real state in Redis, shared by every test in the run:
    they all come from the same "address", so three registrations would
    exhaust the hourly allowance and every later test would fail with a 429
    that has nothing to do with what it is checking.

    Cleared before rather than after, so a run interrupted halfway does not
    leave the next one throttled.
    """
    import redis.asyncio as redis

    from leka.core.config import settings

    client = redis.from_url(str(settings.redis_url))
    try:
        keys = [key async for key in client.scan_iter("leka:ratelimit:*")]
        if keys:
            await client.delete(*keys)
    finally:
        await client.aclose()

    yield


@pytest.fixture
def api_prefix() -> str:
    return settings.api_v1_prefix


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A database session whose workspaces are deleted afterwards.

    Deleting the workspaces is enough: every business table cascades from
    them, which is itself part of what the schema promises.
    """
    from sqlalchemy import select

    from leka.db import session_factory
    from leka.platform import Workspace

    async with session_factory() as db_session:
        created_before = {
            workspace.id for workspace in (await db_session.execute(select(Workspace))).scalars()
        }
        try:
            yield db_session
        finally:
            await db_session.rollback()
            async with session_factory() as cleanup:
                for workspace in (await cleanup.execute(select(Workspace))).scalars().all():
                    if workspace.id not in created_before:
                        await cleanup.delete(workspace)
                await cleanup.commit()


# ── Reading an error response ────────────────────────────────────────────────


def error_code(response: Any) -> str:
    """The machine code out of an error body.

    One helper rather than `response.json()["error"]["code"]` spelled out
    forty times: the shape is a contract with clients, and the day it moves
    again this is the one place that has to follow.

    LEKA-333 replaced three error shapes with one. Tests that used to read
    `["detail"]["code"]` read this instead — the assertion they make is
    unchanged, only where they look for the value.
    """
    body: dict[str, Any] = response.json()
    return str(body["error"]["code"])


def error_message(response: Any) -> str:
    """The human sentence out of an error body."""
    body: dict[str, Any] = response.json()
    return str(body["error"]["message"])


def error_fields(response: Any) -> dict[str, str]:
    """Per-field problems, as {field: message}. Empty when there are none."""
    body: dict[str, Any] = response.json()
    details = body["error"].get("details") or []
    return {item["field"]: item["message"] for item in details}


def comparable_error(response: Any) -> dict[str, Any]:
    """An error body with the request id removed, for comparing two of them.

    Several tests assert that two refusals are indistinguishable — an
    unknown address and a wrong password, a token that never existed and one
    already spent. That property is what stops the API answering "does this
    person have an account here?".

    Since LEKA-333 every error carries its own request id, so two bodies are
    never byte-identical. The id is a ULID: a timestamp and ten random
    bytes, generated the same way on both paths, so it distinguishes the
    REQUESTS and never the ACCOUNTS. Removing it keeps the assertion exactly
    as strong — anything else that differed would still fail, including a
    field added later.
    """
    body: dict[str, Any] = response.json()
    error = {key: value for key, value in body["error"].items() if key != "request_id"}
    return {**body, "error": error}


def page_items(response: Any) -> list[Any]:
    """The rows out of a list response.

    Every list route returns {"data": [...], "next_cursor": ...} since
    LEKA-333 — a bare array has nowhere to put the cursor. This is the one
    place tests read that shape, so the day it changes again only this
    function follows.
    """
    body: dict[str, Any] = response.json()
    items: list[Any] = body["data"]
    return items


def next_cursor(response: Any) -> str | None:
    """The cursor for the following page, or None at the end of a list."""
    body: dict[str, Any] = response.json()
    cursor: str | None = body["next_cursor"]
    return cursor
