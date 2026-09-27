"""The authentication flows, end to end over HTTP.

This file is LEKA-330's Definition of Done: "end-to-end authentication flow
implemented and tested", and "security-sensitive flows covered by automated
tests".

Deliberately NOT using the `identity` fixture: these tests exercise the real
implementation, with real cookies, through the real seam. That is also the
proof that LEKA-331's seam was designed correctly — its own tests keep
passing with the fake, and these pass with the real one, and neither module
changed.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.core.config import settings
from leka.db import DatabaseSession, session_factory, system_scope
from leka.identity import ConsoleEmailSender, EmailMessage
from leka.identity.cookies import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from tests.conftest import comparable_error, error_code, page_items

pytestmark = pytest.mark.integration

API = "/api/v1/auth"
PASSWORD = "correct horse battery staple"
# Who registers: what the form requires, and nothing it leaves optional.
PROFILE = {"first_name": "Nora", "last_name": "Diallo", "company": "Acme"}


class CapturingEmailSender:
    """Keeps the messages instead of sending them.

    The verification and reset links are in those bodies, which is how these
    tests follow a flow a real user would follow through their inbox.
    """

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)

    def last_link(self, pattern: str) -> str:
        match = re.search(pattern, self.sent[-1].body)
        assert match, f"no link matching {pattern} in {self.sent[-1].body!r}"
        return match.group(1)


@pytest.fixture
async def mailbox() -> AsyncIterator[CapturingEmailSender]:
    """Replace the email sender for the duration of a test."""
    from leka.api import identity as identity_routes
    from leka.main import app

    sender = CapturingEmailSender()
    app.dependency_overrides[identity_routes.get_auth_service] = _service_with(sender)

    yield sender

    app.dependency_overrides.pop(identity_routes.get_auth_service, None)


def _service_with(sender: CapturingEmailSender) -> Any:
    from leka.identity import (
        AuthService,
        EmailTokenRepository,
        SessionRepository,
        UserRepository,
    )

    # The same dependency the routes use: a second spelling would be a
    # second session in the same request (see leka/db/session.py).
    def factory(db: DatabaseSession) -> AuthService:
        return AuthService(
            UserRepository(db), SessionRepository(db), EmailTokenRepository(db), sender
        )

    return factory


async def _delete_all_accounts() -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM users"))
            await session.commit()


@pytest.fixture(autouse=True)
async def clean_users() -> AsyncIterator[None]:
    """Every test starts with no accounts and leaves none behind.

    Cleared BEFORE as well as after, and that is not belt and braces. The
    seed script creates nora@acme.example — the same address these tests
    use — so running the browser suite, which seeds, left a verified account
    behind and the next `pytest` run failed on registration. Clearing only
    afterwards makes a suite that passes or fails depending on what ran
    before it.
    """
    await _delete_all_accounts()
    yield
    await _delete_all_accounts()


async def _register_and_verify(
    client: AsyncClient, mailbox: CapturingEmailSender, email: str
) -> None:
    registered = await client.post(
        f"{API}/register", json={"email": email, "password": PASSWORD, **PROFILE}
    )
    assert registered.status_code == 202, registered.text
    token = mailbox.last_link(r"/verify/(\S+)")
    verified = await client.post(f"{API}/verify/{token}")
    assert verified.status_code == 200, verified.text


async def _sign_in(client: AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(f"{API}/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf
    client.headers[CSRF_HEADER_NAME] = csrf
    body: dict[str, Any] = response.json()
    return body


# ── Registration and verification ────────────────────────────────────────────


async def test_a_new_account_must_verify_before_signing_in(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await client.post(
        f"{API}/register", json={"email": "nora@acme.example", "password": PASSWORD, **PROFILE}
    )

    refused = await client.post(
        f"{API}/login", json={"email": "nora@acme.example", "password": PASSWORD}
    )

    assert refused.status_code == 403
    assert error_code(refused) == "account_unverified"


async def test_a_verification_token_works_once(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await client.post(
        f"{API}/register", json={"email": "nora@acme.example", "password": PASSWORD, **PROFILE}
    )
    token = mailbox.last_link(r"/verify/(\S+)")

    first = await client.post(f"{API}/verify/{token}")
    second = await client.post(f"{API}/verify/{token}")

    assert first.status_code == 200
    assert second.status_code == 400
    assert error_code(second) == "token_invalid"


async def test_a_verification_token_survives_no_race(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """The same link, clicked twice at the same instant, is spent once.

    The sequential test above passes even when the guard is a read followed
    by a write: nothing runs between the two. This one fires both together,
    which is what a double-click or a retrying mail client actually does.
    """
    await client.post(
        f"{API}/register", json={"email": "nora@acme.example", "password": PASSWORD, **PROFILE}
    )
    token = mailbox.last_link(r"/verify/(\S+)")

    first, second = await asyncio.gather(
        client.post(f"{API}/verify/{token}"),
        client.post(f"{API}/verify/{token}"),
    )

    accepted = sorted([first.status_code, second.status_code])
    assert accepted == [200, 400], (
        f"the same token was spent twice concurrently (got {accepted}) - "
        "the consumed_at guard belongs in the UPDATE, not in Python"
    )


async def test_registering_a_taken_address_looks_exactly_like_success(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Otherwise the registration form becomes a way to ask "does this person
    have an account here?"."""
    first = await client.post(
        f"{API}/register", json={"email": "nora@acme.example", "password": PASSWORD, **PROFILE}
    )
    await client.post(f"{API}/verify/{mailbox.last_link(r'/verify/(\S+)')}")
    second = await client.post(
        f"{API}/register", json={"email": "nora@acme.example", "password": PASSWORD, **PROFILE}
    )

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    # The owner is told, which is both the safe answer and the useful one.
    # (An owner who never verified gets a new link instead: test_auth_emails.)
    assert mailbox.sent[-1].subject == "Une inscription a été tentée avec votre adresse"


# ── Who registers ────────────────────────────────────────────────────────────


async def test_the_profile_given_at_registration_is_the_account_s(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    profile = {
        **PROFILE,
        "first_name": "  Nora  Aïcha ",
        "job_title": "CTO",
        "company_size": "51-200",
    }
    registered = await client.post(
        f"{API}/register", json={"email": "nora@acme.example", "password": PASSWORD, **profile}
    )
    assert registered.status_code == 202, registered.text
    await client.post(f"{API}/verify/{mailbox.last_link(r'/verify/(\S+)')}")
    await _sign_in(client, "nora@acme.example")

    user = (await client.get(f"{API}/me")).json()["user"]

    assert (user["first_name"], user["last_name"], user["company"]) == (
        "Nora Aïcha",
        "Diallo",
        "Acme",
    )
    assert (user["job_title"], user["company_size"]) == ("CTO", "51-200")


async def test_the_role_and_the_company_size_may_be_left_out(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    user = (await client.get(f"{API}/me")).json()["user"]

    assert (user["job_title"], user["company_size"]) == (None, None)


@pytest.mark.parametrize(
    "change",
    [
        {"first_name": None},
        {"last_name": None},
        {"company": None},
        {"first_name": "   "},
        {"company": "x" * 201},
        {"company_size": "10-20"},
        {"first_name": "Nora\x1b[31m"},
        {"last_name": "Diallo\u202e"},
        {"job_title": "CTO\x07"},
    ],
)
async def test_a_profile_the_form_would_not_send_is_refused(
    client: AsyncClient, mailbox: CapturingEmailSender, change: dict[str, object]
) -> None:
    body: dict[str, object] = {"email": "nora@acme.example", "password": PASSWORD, **PROFILE}
    body.update(change)
    body = {key: value for key, value in body.items() if value is not None}

    response = await client.post(f"{API}/register", json=body)

    assert response.status_code == 422
    assert mailbox.sent == []


@pytest.mark.parametrize("verified", [True, False])
async def test_registering_again_never_rewrites_who_the_owner_said_they_were(
    client: AsyncClient, mailbox: CapturingEmailSender, verified: bool
) -> None:
    """Anyone can type someone else's address into the form."""
    await client.post(
        f"{API}/register", json={"email": "nora@acme.example", "password": PASSWORD, **PROFILE}
    )
    if verified:
        await client.post(f"{API}/verify/{mailbox.last_link(r'/verify/(\S+)')}")
    stranger = {"first_name": "Mallory", "last_name": "X", "company": "Evil Corp"}
    await client.post(
        f"{API}/register",
        json={"email": "nora@acme.example", "password": PASSWORD, **stranger},
    )

    with system_scope():
        async with session_factory() as session:
            found = await session.execute(
                text("SELECT first_name, company FROM users WHERE email = 'nora@acme.example'")
            )
    assert found.one() == ("Nora", "Acme")


async def test_someone_signed_in_changes_only_what_they_send(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    changed = await client.patch(
        f"{API}/me", json={"first_name": " Nora-Aïcha ", "job_title": "CTO"}
    )

    assert changed.status_code == 200, changed.text
    user = (await client.get(f"{API}/me")).json()["user"]
    assert (user["first_name"], user["last_name"], user["company"]) == (
        "Nora-Aïcha",
        "Diallo",
        "Acme",
    )
    assert user["job_title"] == "CTO"

    cleared = await client.patch(f"{API}/me", json={"job_title": None})
    assert cleared.json()["job_title"] is None


async def test_an_account_from_before_names_gets_one(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """The accounts made before registration asked: how they get a name."""
    await _register_and_verify(client, mailbox, "nora@acme.example")
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text("UPDATE users SET first_name = NULL, last_name = NULL, company = NULL")
            )
            await session.commit()
    await _sign_in(client, "nora@acme.example")

    await client.patch(
        f"{API}/me", json={"first_name": "Haitam", "last_name": "E.", "company": "LEKA"}
    )

    user = (await client.get(f"{API}/me")).json()["user"]
    assert (user["first_name"], user["last_name"], user["company"]) == ("Haitam", "E.", "LEKA")


@pytest.mark.parametrize(
    "body",
    [
        {"first_name": None},
        {"company": "   "},
        {"last_name": "D\x1b[2J"},
        {"company_size": "tiny"},
        {"email": "mallory@evil.example"},
        {"password": "a brand new passphrase"},
    ],
)
async def test_a_change_that_would_empty_or_widen_the_profile_is_refused(
    client: AsyncClient, mailbox: CapturingEmailSender, body: dict[str, object]
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    response = await client.patch(f"{API}/me", json=body)

    assert response.status_code == 422
    user = (await client.get(f"{API}/me")).json()["user"]
    assert (user["email"], user["first_name"], user["company"]) == (
        "nora@acme.example",
        "Nora",
        "Acme",
    )


async def test_nobody_changes_a_profile_without_a_session(client: AsyncClient) -> None:
    response = await client.patch(f"{API}/me", json={"first_name": "Mallory"})

    assert response.status_code == 401


async def test_addresses_are_case_insensitive(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Nora@ and nora@ must not become two accounts."""
    await _register_and_verify(client, mailbox, "nora@acme.example")

    response = await client.post(
        f"{API}/login", json={"email": "NORA@Acme.Example", "password": PASSWORD}
    )

    assert response.status_code == 200


# ── Signing in ───────────────────────────────────────────────────────────────


async def test_an_unknown_address_and_a_wrong_password_are_indistinguishable(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")

    unknown = await client.post(
        f"{API}/login", json={"email": "nobody@nowhere.example", "password": PASSWORD}
    )
    wrong = await client.post(
        f"{API}/login", json={"email": "nora@acme.example", "password": "not the one"}
    )

    assert unknown.status_code == wrong.status_code == 401
    assert comparable_error(unknown) == comparable_error(wrong)
    assert error_code(unknown) == "invalid_credentials"


async def test_the_session_cookie_carries_its_protections(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """httpOnly so an XSS cannot read it, SameSite so a cross-site form
    cannot carry it, Path=/ so it is sent to the whole API.

    Secure is asserted separately, below: it is the one attribute a developer
    legitimately turns off locally — the dev server is http — and a test that
    reads .env passes in CI and fails on the machine of whoever configured
    their environment correctly.
    """
    await _register_and_verify(client, mailbox, "nora@acme.example")

    response = await client.post(
        f"{API}/login", json={"email": "nora@acme.example", "password": PASSWORD}
    )

    header = response.headers["set-cookie"]
    assert settings.session_cookie_name in header
    assert "HttpOnly" in header
    assert "samesite=lax" in header.lower()
    assert "Path=/" in header


def test_the_cookie_is_secure_when_configured_to_be(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What we actually ship.

    Settings is frozen and read at import, so the module's reference is
    replaced rather than the value mutated. This asserts the production
    configuration regardless of what the local .env says.
    """
    from fastapi import Response

    from leka.identity import cookies

    production_like = settings.model_copy(
        update={"session_cookie_secure": True, "session_cookie_samesite": "lax"}
    )
    monkeypatch.setattr(cookies, "settings", production_like)

    response = Response()
    cookies.set_session_cookie(response, "a-token")

    header = "; ".join(response.headers.getlist("set-cookie"))
    assert "Secure" in header
    assert "HttpOnly" in header


def test_production_refuses_an_insecure_cookie() -> None:
    """The other half of the guarantee: the value cannot be wrong where it
    matters. Turning Secure off in production stops the process."""
    from pydantic import ValidationError

    from leka.core.config import Settings

    with pytest.raises(ValidationError, match="SECURE"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://l:l@127.0.0.1:5432/l",
            redis_url="redis://127.0.0.1:6379/0",
            secret_key="x",
            encryption_keys=["MN3nrX7VP5Mj0SRB4G-pIPOrvlCyT-CQoBZvsQFYHss="],
            environment="production",
            session_cookie_secure=False,
        )


async def test_signing_in_twice_issues_a_new_session(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Session fixation: an identifier that existed before authentication
    must never be valid after it."""
    await _register_and_verify(client, mailbox, "nora@acme.example")

    await _sign_in(client, "nora@acme.example")
    first = client.cookies.get(settings.session_cookie_name)
    await _sign_in(client, "nora@acme.example")
    second = client.cookies.get(settings.session_cookie_name)

    assert first != second


async def test_me_returns_the_person_and_where_they_may_go(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    response = await client.get(f"{API}/me")

    body = response.json()
    assert response.status_code == 200
    assert body["user"]["email"] == "nora@acme.example"
    assert body["workspaces"] == []
    assert body["active_workspace_id"] is None
    assert "password" not in response.text
    assert "hash" not in response.text


async def test_signing_out_invalidates_the_cookie_immediately(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    stolen = client.cookies.get(settings.session_cookie_name)

    await client.post(f"{API}/logout")

    # Present the old cookie as an attacker who copied it would.
    client.cookies.set(settings.session_cookie_name, stolen or "")
    after = await client.get(f"{API}/me")

    assert after.status_code == 401


async def test_an_unauthenticated_request_is_refused_not_crashed(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{API}/me")

    assert response.status_code == 401
    assert error_code(response) == "not_authenticated"


# ── Passwords ────────────────────────────────────────────────────────────────


async def test_changing_a_password_keeps_this_session_and_revokes_the_others(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """Signing someone out of the browser they are using, as a reward for
    improving their security, teaches them not to."""
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    elsewhere = client.cookies.get(settings.session_cookie_name)
    await _sign_in(client, "nora@acme.example")

    changed = await client.post(
        f"{API}/password/change",
        json={"current_password": PASSWORD, "new_password": "a completely new one"},
    )
    assert changed.status_code == 204

    still_here = await client.get(f"{API}/me")
    assert still_here.status_code == 200

    client.cookies.set(settings.session_cookie_name, elsewhere or "")
    del client.headers[CSRF_HEADER_NAME]
    other_device = await client.get(f"{API}/me")
    assert other_device.status_code == 401


async def test_the_forgotten_password_answer_never_reveals_anything(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")

    known = await client.post(f"{API}/password/forgot", json={"email": "nora@acme.example"})
    unknown = await client.post(f"{API}/password/forgot", json={"email": "nobody@nowhere.example"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


async def test_a_reset_token_works_once_and_revokes_every_session(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """If the reason for the reset was that someone else knew the old
    password, leaving their sessions alive makes the reset pointless."""
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    before = client.cookies.get(settings.session_cookie_name)

    await client.post(f"{API}/password/forgot", json={"email": "nora@acme.example"})
    token = mailbox.last_link(r"token=(\S+)")

    first = await client.post(
        f"{API}/password/reset", json={"token": token, "password": "a brand new secret"}
    )
    second = await client.post(
        f"{API}/password/reset", json={"token": token, "password": "another one here"}
    )

    assert first.status_code == 204
    assert second.status_code == 400

    client.cookies.set(settings.session_cookie_name, before or "")
    del client.headers[CSRF_HEADER_NAME]
    assert (await client.get(f"{API}/me")).status_code == 401

    signed_in = await client.post(
        f"{API}/login",
        json={"email": "nora@acme.example", "password": "a brand new secret"},
    )
    assert signed_in.status_code == 200


async def test_a_reset_token_survives_no_race(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """The same link, clicked twice at the same instant, spends once.

    The sequential test above passes even when the guard is a read followed
    by a write: nothing runs between the two. This one fires both resets
    together, which is what a double-click, a retrying client, or anyone
    holding the link actually does. Two different passwords must not both
    be accepted, with the last writer silently winning.
    """
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await client.post(f"{API}/password/forgot", json={"email": "nora@acme.example"})
    token = mailbox.last_link(r"token=(\S+)")

    first, second = await asyncio.gather(
        client.post(
            f"{API}/password/reset",
            json={"token": token, "password": "first password here"},
        ),
        client.post(
            f"{API}/password/reset",
            json={"token": token, "password": "second password here"},
        ),
    )

    accepted = sorted([first.status_code, second.status_code])
    assert accepted == [204, 400], (
        f"the same token was spent twice concurrently (got {accepted}) - "
        "the consumed_at guard belongs in the UPDATE, not in Python"
    )


# ── Sessions ─────────────────────────────────────────────────────────────────


async def test_i_can_see_and_revoke_my_own_sessions(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    listed = await client.get(f"{API}/sessions")
    sessions = page_items(listed)

    assert listed.status_code == 200
    assert len(sessions) == 2
    assert sum(1 for item in sessions if item["is_current"]) == 1
    # No token, not even hashed.
    assert all("token" not in item for item in sessions)

    other = next(item for item in sessions if not item["is_current"])
    revoked = await client.delete(f"{API}/sessions/{other['id']}")
    assert revoked.status_code == 204
    assert len(page_items(await client.get(f"{API}/sessions"))) == 1


async def test_i_cannot_revoke_someone_elses_session(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")

    response = await client.delete(f"{API}/sessions/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_signing_out_everywhere_ends_every_session(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    elsewhere = client.cookies.get(settings.session_cookie_name)
    await _sign_in(client, "nora@acme.example")

    await client.post(f"{API}/logout-all")

    client.cookies.set(settings.session_cookie_name, elsewhere or "")
    assert (await client.get(f"{API}/me")).status_code == 401


# ── Secrets never leave ──────────────────────────────────────────────────────


async def test_no_route_ever_returns_a_password_or_a_token(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    body = await _sign_in(client, "nora@acme.example")

    serialised = str(body) + (await client.get(f"{API}/me")).text
    serialised += (await client.get(f"{API}/sessions")).text

    token = client.cookies.get(settings.session_cookie_name)
    assert token is not None
    assert PASSWORD not in serialised
    assert "argon2" not in serialised
    assert token not in serialised


async def test_the_session_token_is_hashed_in_the_database(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    token = client.cookies.get(settings.session_cookie_name)

    with system_scope():
        async with session_factory() as session:
            rows = await session.execute(text("SELECT token_hash FROM sessions"))
            stored = [row[0] for row in rows]

    assert stored
    assert token not in stored


def test_the_console_sender_is_chosen_when_nothing_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What makes verification and recovery testable with no account
    anywhere — and what a new developer uses on their first afternoon.

    The settings are replaced rather than read: a developer who has
    configured a real mailbox, as they are meant to, would otherwise fail
    this test on their own machine.
    """
    from leka.identity import email as email_module

    nothing_configured = settings.model_copy(
        update={"smtp_host": None, "smtp_password": None, "resend_api_key": None}
    )
    monkeypatch.setattr(email_module, "settings", nothing_configured)

    assert isinstance(email_module.build_email_sender(), ConsoleEmailSender)


def test_smtp_is_preferred_over_an_api_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mailbox we already pay for beats a second account somewhere else."""
    from pydantic import SecretStr

    from leka.identity import SmtpEmailSender
    from leka.identity import email as email_module

    both = settings.model_copy(
        update={
            "smtp_host": "ssl0.ovh.net",
            "smtp_password": SecretStr("whatever"),
            "resend_api_key": SecretStr("also-set"),
        }
    )
    monkeypatch.setattr(email_module, "settings", both)

    assert isinstance(email_module.build_email_sender(), SmtpEmailSender)
