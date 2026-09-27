"""Rate limiting, CSRF, and the point where LEKA-330 meets LEKA-331.

The last one is the test that matters most across the two tickets: LEKA-331
promised that removing someone's membership cuts their access immediately.
That promise was verified against a stub. Here it runs against real
authentication, real cookies and a real session.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.core import ratelimit
from leka.core.config import settings
from leka.core.ratelimit import LOGIN_PER_IP, REGISTER_PER_IP
from leka.db import DatabaseSession, session_factory, system_scope
from leka.identity.cookies import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from leka.platform import Membership, Role, Workspace
from tests.conftest import error_code, error_message

from .test_auth_api import (
    API,
    PASSWORD,
    PROFILE,
    CapturingEmailSender,
    _register_and_verify,
    _sign_in,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def mailbox() -> AsyncIterator[CapturingEmailSender]:
    from leka.api import identity as identity_routes
    from leka.identity import (
        AuthService,
        EmailTokenRepository,
        SessionRepository,
        UserRepository,
    )
    from leka.main import app

    sender = CapturingEmailSender()

    # The routes' own dependency: a second spelling would be a second
    # session in the same request (see leka/db/session.py).
    def factory(db: DatabaseSession) -> AuthService:
        return AuthService(
            UserRepository(db), SessionRepository(db), EmailTokenRepository(db), sender
        )

    app.dependency_overrides[identity_routes.get_auth_service] = factory
    yield sender
    app.dependency_overrides.pop(identity_routes.get_auth_service, None)


async def _wipe() -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM workspaces"))
            await session.execute(text("DELETE FROM users"))
            await session.commit()


@pytest.fixture(autouse=True)
async def clean_everything() -> AsyncIterator[None]:
    """Cleared before as well as after — see the note in test_auth_api."""
    await _wipe()
    yield
    await _wipe()


# ── Rate limiting ────────────────────────────────────────────────────────────


async def test_repeated_failed_logins_are_throttled(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Throttled, NOT locked. Locking an account after N failures lets anyone
    who knows an email address deny that person access — a denial of service
    dressed as a security control."""
    await _register_and_verify(client, mailbox, "nora@acme.example")

    statuses = []
    for _ in range(LOGIN_PER_IP.attempts + 2):
        response = await client.post(
            f"{API}/login", json={"email": "nora@acme.example", "password": "wrong"}
        )
        statuses.append(response.status_code)

    assert 401 in statuses
    assert 429 in statuses
    throttled = next(code for code in statuses if code == 429)
    assert throttled == 429


async def test_a_throttled_response_says_how_long_to_wait(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """A message a user can act on, which is an acceptance criterion."""
    for _ in range(REGISTER_PER_IP.attempts + 1):
        response = await client.post(
            f"{API}/register",
            json={"email": f"{uuid.uuid4().hex}@acme.example", "password": PASSWORD, **PROFILE},
        )

    assert response.status_code == 429
    assert error_code(response) == "rate_limited"
    assert "Retry-After" in response.headers


async def test_a_successful_login_forgives_earlier_typos(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Someone who got in should not be throttled by the mistakes they made
    on the way."""
    await _register_and_verify(client, mailbox, "nora@acme.example")
    for _ in range(LOGIN_PER_IP.attempts - 1):
        await client.post(f"{API}/login", json={"email": "nora@acme.example", "password": "wrong"})

    good = await client.post(
        f"{API}/login", json={"email": "nora@acme.example", "password": PASSWORD}
    )
    again = await client.post(
        f"{API}/login", json={"email": "nora@acme.example", "password": PASSWORD}
    )

    assert good.status_code == 200
    assert again.status_code == 200


async def test_counting_an_attempt_always_leaves_an_expiry() -> None:
    """A counter with no expiry never decays, and locks someone out for good.

    INCR and EXPIRE used to be two calls. A Redis restart or a dropped
    connection between them left a key with no TTL at all: every later
    attempt incremented a counter that would never reset, the person could
    not sign in again, and nothing in the logs said why. The fix puts both
    in one transactional pipeline; this is what proves the expiry is
    actually there afterwards.
    """
    import redis.asyncio as redis

    from leka.core.config import settings

    limit = ratelimit.Limit(attempts=5, window_seconds=60)
    identifier = f"ttl-{uuid.uuid4().hex}"

    verdict = await ratelimit.consume("test", identifier, limit)

    client = redis.from_url(str(settings.redis_url))
    try:
        ttl = await client.ttl(limit.key("test", identifier))
    finally:
        await client.delete(limit.key("test", identifier))
        await client.aclose()

    assert verdict.allowed
    assert 0 < ttl <= limit.window_seconds, (
        f"the counter has no usable expiry (TTL {ttl}) - a key without one "
        "never decays and throttles that person for ever"
    )
    assert verdict.retry_after_seconds > 0


async def test_a_counter_that_lost_its_expiry_gets_one_back() -> None:
    """Self-repair, not just prevention.

    EXPIRE ... NX sets the window whenever the key has none, so a counter
    left over from the old two-call version — or from any future mishap —
    starts decaying again at the next attempt instead of staying stuck.
    """
    import redis.asyncio as redis

    from leka.core.config import settings

    limit = ratelimit.Limit(attempts=5, window_seconds=60)
    identifier = f"stuck-{uuid.uuid4().hex}"
    key = limit.key("test", identifier)

    client = redis.from_url(str(settings.redis_url))
    try:
        # Exactly the state the old code could leave behind: a counter, no TTL.
        await client.set(key, 1)
        assert await client.ttl(key) == -1

        await ratelimit.consume("test", identifier, limit)

        repaired = await client.ttl(key)
    finally:
        await client.delete(key)
        await client.aclose()

    assert 0 < repaired <= limit.window_seconds, (
        f"a counter with no expiry stayed stuck (TTL {repaired})"
    )


# ── CSRF ─────────────────────────────────────────────────────────────────────


async def test_a_mutation_without_its_csrf_token_is_refused(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Defence in depth behind SameSite=Lax, and the only protection left if
    the cookie ever has to become SameSite=None."""
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    del client.headers[CSRF_HEADER_NAME]
    response = await client.post(f"{API}/logout")

    assert response.status_code == 403
    assert error_code(response) == "csrf_failed"


async def test_a_wrong_csrf_token_is_refused(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    client.headers[CSRF_HEADER_NAME] = "not the token in the cookie"
    response = await client.post(f"{API}/logout")

    assert response.status_code == 403


async def test_reading_never_needs_a_csrf_token(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    del client.headers[CSRF_HEADER_NAME]
    response = await client.get(f"{API}/me")

    assert response.status_code == 200


async def test_signing_in_needs_no_csrf_token() -> None:
    """Requiring one from someone who has never been issued one would break
    the very flow that issues it."""
    from leka.identity.csrf import EXEMPT_PATHS

    assert f"{API}/login" in EXEMPT_PATHS
    assert f"{API}/register" in EXEMPT_PATHS


async def test_the_csrf_cookie_is_readable_and_the_session_one_is_not(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """The double-submit pattern needs the page to copy the CSRF value into a
    header, so that one is not httpOnly. The session cookie is, so an XSS
    cannot exfiltrate it."""
    await _register_and_verify(client, mailbox, "nora@acme.example")
    response = await client.post(
        f"{API}/login", json={"email": "nora@acme.example", "password": PASSWORD}
    )

    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if settings.session_cookie_name in c)
    csrf_cookie = next(c for c in cookies if CSRF_COOKIE_NAME in c)

    assert "HttpOnly" in session_cookie
    assert "HttpOnly" not in csrf_cookie


# ── Where LEKA-330 meets LEKA-331 ────────────────────────────────────────────


async def test_removing_a_membership_cuts_access_on_the_next_request(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """LEKA-331's central promise, now verified against real authentication.

    It was previously tested with a stubbed identity. If the role had been
    cached in the session — the obvious optimisation — this is the test that
    would fail, and the guarantee it protects is the difference between a
    revocation and a delay.
    """
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    created = await client.post("/api/v1/workspaces", json={"name": "Acme Corp"})
    assert created.status_code == 201, created.text
    workspace_id = created.json()["id"]

    switched = await client.post(f"/api/v1/workspaces/{workspace_id}/switch")
    assert switched.status_code == 200

    inside = await client.get("/api/v1/workspaces/current")
    assert inside.status_code == 200
    assert inside.json()["role"] == Role.OWNER.value

    # Remove the seat out from under the live session.
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM memberships"))
            await session.commit()

    after = await client.get("/api/v1/workspaces/current")

    assert after.status_code == 403
    assert "not a member" in error_message(after).lower()


async def test_a_session_survives_its_workspace_being_deleted(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """ON DELETE SET NULL on sessions.active_workspace_id.

    Deleting a workspace must not destroy the sessions of people who were
    looking at it, and the request that follows must be a clean 403 rather
    than a 500.
    """
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    created = await client.post("/api/v1/workspaces", json={"name": "Doomed"})
    await client.post(f"/api/v1/workspaces/{created.json()['id']}/switch")

    with system_scope():
        async with session_factory() as session:
            workspace = await session.get(Workspace, uuid.UUID(created.json()["id"]))
            assert workspace is not None
            await session.delete(workspace)
            await session.commit()

    response = await client.get("/api/v1/workspaces/current")
    me = await client.get(f"{API}/me")

    assert response.status_code == 403
    assert me.status_code == 200
    assert me.json()["active_workspace_id"] is None


async def test_the_workspace_never_comes_from_the_client(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Architecture rule 3, end to end. A header naming a workspace changes
    nothing: the server reads its own session."""
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    mine = await client.post("/api/v1/workspaces", json={"name": "Mine"})
    await client.post(f"/api/v1/workspaces/{mine.json()['id']}/switch")

    # Fabricate someone else's workspace, with a membership for nobody.
    with system_scope():
        async with session_factory() as session:
            other = Workspace(name="Theirs", slug=f"theirs-{uuid.uuid4().hex[:8]}")
            session.add(other)
            await session.flush()
            # A real person: the foreign key on memberships.user_id is not
            # decorative, and an invented id is rejected by the database.
            stranger = await session.execute(
                text("INSERT INTO users (email) VALUES (:email) RETURNING id"),
                {"email": f"stranger-{uuid.uuid4().hex[:8]}@example.test"},
            )
            session.add(
                Membership(
                    workspace_id=other.id,
                    user_id=stranger.scalar_one(),
                    role=Role.OWNER,
                )
            )
            await session.commit()
            other_id = str(other.id)

    response = await client.get("/api/v1/workspaces/current", headers={"X-Workspace-Id": other_id})

    assert response.status_code == 200
    assert response.json()["workspace"]["id"] == mine.json()["id"]


# ── Housekeeping ─────────────────────────────────────────────────────────────


async def test_expired_sessions_and_tokens_are_deleted_not_ignored(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """A row nobody will ever use again still appears in a backup."""
    from datetime import UTC, datetime, timedelta

    from leka.identity.tasks import purge_expired

    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    with system_scope():
        async with session_factory() as session:
            past = datetime.now(UTC) - timedelta(days=1)
            await session.execute(text("UPDATE sessions SET expires_at = :t"), {"t": past})
            await session.execute(text("UPDATE email_tokens SET expires_at = :t"), {"t": past})
            await session.commit()

    removed = await purge_expired()

    assert removed["sessions"] >= 1
    with system_scope():
        async with session_factory() as session:
            remaining = await session.execute(text("SELECT count(*) FROM sessions"))
            assert remaining.scalar_one() == 0


async def test_an_unauthenticated_request_to_a_workspace_route_is_401_not_500(
    client: AsyncClient,
) -> None:
    """The seam's placeholder raised NotImplementedError, which is right for
    "nobody implemented this" and wrong for "you are not signed in".

    Keeping it in the real implementation made every LEKA-331 route answer an
    anonymous visitor with a 500 — found by running the flow end to end, not
    by any unit test, which is why this one exists now.
    """
    for path in ("/api/v1/workspaces/current", "/api/v1/members"):
        response = await client.get(path)

        assert response.status_code == 401, path
        assert error_code(response) == "not_authenticated"


async def test_signing_in_lands_you_in_your_only_workspace(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Asking someone to choose between one option is friction with nothing
    on the other side of it — and until the switcher exists there is no way
    to choose at all."""
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    created = await client.post("/api/v1/workspaces", json={"name": "Only One"})
    assert created.status_code == 201

    # Sign in again, fresh session.
    signed_in = await client.post(
        f"{API}/login", json={"email": "nora@acme.example", "password": PASSWORD}
    )

    assert signed_in.json()["active_workspace_id"] == created.json()["id"]
    assert (await client.get("/api/v1/workspaces/current")).status_code == 200


async def test_signing_in_with_several_workspaces_picks_none(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Choosing for them would be guessing. The interface asks."""
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    await client.post("/api/v1/workspaces", json={"name": "First"})
    await client.post("/api/v1/workspaces", json={"name": "Second"})

    signed_in = await client.post(
        f"{API}/login", json={"email": "nora@acme.example", "password": PASSWORD}
    )

    assert signed_in.json()["active_workspace_id"] is None
    assert len(signed_in.json()["workspaces"]) == 2
