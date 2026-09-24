"""The emails authentication sends, and the links in them (LEKA-330).

What broke in front of a user: the verification and reset links were
relative paths — "/auth/verify/<token>" — with no domain, pointing at API
routes rather than at the pages that handle them. Unclickable in a mail
client, and a 404 when typed by hand. Nothing checked where a link led.

These tests check it against the frontend's own files: rename the page,
and the link test fails.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from leka.core.config import Settings, settings
from leka.core.settings.paths import REPO_ROOT
from leka.db import session_factory, system_scope
from leka.identity import EmailMessage, links
from leka.identity.links import reset_link, verification_link
from leka.identity.models import EmailToken
from tests.test_auth_api import (
    API,
    PASSWORD,
    CapturingEmailSender,
    _delete_all_accounts,
    _service_with,
)

WEB_APP = REPO_ROOT / "web" / "app"
BASE: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://leka:a-long-database-password@db:5432/leka",
    "redis_url": "redis://redis:6379/0",
    "secret_key": "a-signing-key-that-is-long-enough-for-this-test",
    "encryption_keys": ["MN3nrX7VP5Mj0SRB4G-pIPOrvlCyT-CQoBZvsQFYHss="],
}
ONLINE: dict[str, Any] = {
    **BASE,
    "web_url": "https://app.leka-core.com",
    "email_from": "LEKA <support@leka-core.com>",
    "smtp_host": "ssl0.ovh.net",
    "smtp_username": "support@leka-core.com",
    "smtp_password": "an-smtp-password",
}


@pytest.fixture
async def no_accounts() -> AsyncIterator[None]:
    await _delete_all_accounts()
    yield
    await _delete_all_accounts()


@pytest.fixture
async def mailbox(no_accounts: None) -> AsyncIterator[CapturingEmailSender]:
    """The emails, kept instead of sent — as in test_auth_api."""
    from leka.api import identity as routes
    from leka.main import app

    sender = CapturingEmailSender()
    app.dependency_overrides[routes.get_auth_service] = _service_with(sender)
    yield sender
    app.dependency_overrides.pop(routes.get_auth_service, None)


def _route_exists(path: str) -> bool:
    """Whether a URL path is served by a page in web/app.

    Route groups — "(auth)" — do not appear in URLs; a "[param]" folder
    matches any one segment. Reading the files, not a list, is the point:
    a renamed page makes this False.
    """
    wanted = [segment for segment in path.strip("/").split("/") if segment]
    for page in WEB_APP.rglob("page.tsx"):
        parts = [
            part
            for part in page.parent.relative_to(WEB_APP).parts
            if not (part.startswith("(") and part.endswith(")"))
        ]
        if len(parts) == len(wanted) and all(
            p == w or (p.startswith("[") and not p.startswith("[..."))
            for p, w in zip(parts, wanted, strict=True)
        ):
            return True
    return False


# ── the links ────────────────────────────────────────────────────────────────


def test_the_links_lead_to_pages_that_exist() -> None:
    verify = urlparse(verification_link("a-token"))
    reset = urlparse(reset_link("a-token"))

    assert _route_exists(verify.path), verify.path
    assert _route_exists(reset.path), reset.path
    assert parse_qs(reset.query) == {"token": ["a-token"]}
    # And the check can fail: the path the emails used to carry.
    assert not _route_exists("/auth/password/reset")


def test_the_links_are_absolute_on_the_web_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    online = settings.model_copy(update={"web_url": "https://app.leka-core.com"})
    monkeypatch.setattr(links, "settings", online)

    assert verification_link("t0k") == "https://app.leka-core.com/verify/t0k"
    assert reset_link("t0k") == "https://app.leka-core.com/reset-password?token=t0k"


def test_a_token_is_encoded_into_the_link() -> None:
    assert "/verify/a%2Fb%3Fc" in verification_link("a/b?c")


# ── the emails ───────────────────────────────────────────────────────────────


def _link(message: EmailMessage) -> str:
    match = re.search(r"https?://\S+", message.body)
    assert match, message.body
    return match.group(0)


@pytest.mark.integration
async def test_the_verification_email_works_from_the_inbox(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await client.post(f"{API}/register", json={"email": "nora@acme.example", "password": PASSWORD})

    message = mailbox.sent[-1]
    link = urlparse(_link(message))
    assert f"{link.scheme}://{link.netloc}" == settings.web_url
    assert _route_exists(link.path)
    # In French, with the link in both parts and its lifetime stated.
    assert message.subject == "Confirmez votre adresse e-mail LEKA"
    assert "24 heures" in message.body
    assert message.html is not None and _link(message) in message.html

    token = link.path.rsplit("/", 1)[1]
    assert (await client.post(f"{API}/verify/{token}")).status_code == 200


@pytest.mark.integration
async def test_the_reset_email_leads_to_the_reset_page(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await client.post(f"{API}/register", json={"email": "nora@acme.example", "password": PASSWORD})
    await client.post(f"{API}/verify/{urlparse(_link(mailbox.sent[-1])).path.rsplit('/', 1)[1]}")

    await client.post(f"{API}/password/forgot", json={"email": "nora@acme.example"})

    message = mailbox.sent[-1]
    link = urlparse(_link(message))
    assert link.path == "/reset-password"
    assert _route_exists(link.path)
    assert message.subject == "Réinitialisez votre mot de passe LEKA"
    assert "1 heure" in message.body

    token = parse_qs(link.query)["token"][0]
    reset = await client.post(
        f"{API}/password/reset", json={"token": token, "password": PASSWORD + " again"}
    )
    assert reset.status_code == 204


def test_the_console_sender_keeps_an_outbox_for_the_browser_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The browser tests click the link from this file, as a person would
    from their inbox. Without it they had no way to create an account."""
    import asyncio
    import json

    from leka.identity import email as email_module

    outbox = tmp_path / "outbox.jsonl"
    monkeypatch.setattr(
        email_module, "settings", settings.model_copy(update={"email_outbox_file": outbox})
    )
    message = EmailMessage(to="nora@acme.example", subject="s", body="b", html="<p>b</p>")

    asyncio.run(email_module.ConsoleEmailSender().send(message))

    assert json.loads(outbox.read_text()) == {
        "to": "nora@acme.example",
        "subject": "s",
        "body": "b",
        "html": "<p>b</p>",
    }


def test_an_outbox_is_refused_online(tmp_path: Path) -> None:
    """It writes working sign-in links to disk."""
    with pytest.raises(ValidationError, match="LEKA_EMAIL_OUTBOX_FILE"):
        _settings("staging", **{**ONLINE, "email_outbox_file": tmp_path / "outbox.jsonl"})


# ── registering twice ────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_registering_again_before_verifying_sends_a_new_link(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """The first email was lost; the person registers again. They used to be
    told "you already have an account" — and then refused at sign-in for not
    having verified it. Now they get what they need: a new link."""
    body = {"email": "nora@acme.example", "password": PASSWORD}
    first = await client.post(f"{API}/register", json=body)
    again = await client.post(f"{API}/register", json=body)

    assert again.status_code == first.status_code == 202
    assert again.json() == first.json()
    assert mailbox.sent[-1].subject == "Confirmez votre adresse e-mail LEKA"
    token = urlparse(_link(mailbox.sent[-1])).path.rsplit("/", 1)[1]
    assert (await client.post(f"{API}/verify/{token}")).status_code == 200


@pytest.mark.integration
async def test_registering_a_verified_address_warns_its_owner(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    body = {"email": "nora@acme.example", "password": PASSWORD}
    await client.post(f"{API}/register", json=body)
    await client.post(f"{API}/verify/{urlparse(_link(mailbox.sent[-1])).path.rsplit('/', 1)[1]}")

    again = await client.post(f"{API}/register", json=body)

    assert again.status_code == 202
    assert mailbox.sent[-1].subject == "Une inscription a été tentée avec votre adresse"


# ── after the commit ─────────────────────────────────────────────────────────


@pytest.fixture
async def probe(monkeypatch: pytest.MonkeyPatch, no_accounts: None) -> AsyncIterator[list[bool]]:
    """A sender that asks, at the moment it sends: is the token committed?"""
    from leka.api import identity as routes

    seen: list[bool] = []

    class Probe:
        async def send(self, message: EmailMessage) -> None:
            token = urlparse(_link(message)).path.rsplit("/", 1)[1]
            from leka.core.security import hash_token

            with system_scope():
                async with session_factory() as session:
                    found = await session.scalar(
                        select(EmailToken.id).where(EmailToken.token_hash == hash_token(token))
                    )
            seen.append(found is not None)

    monkeypatch.setattr(routes, "build_email_sender", lambda: Probe())
    yield seen


@pytest.mark.integration
async def test_the_email_leaves_only_once_its_token_is_committed(
    client: AsyncClient, probe: list[bool]
) -> None:
    """Sent before the commit, a link can name a token the database then
    never keeps: the person clicks, and is told the link is invalid."""
    email = f"n-{uuid.uuid4().hex[:6]}@acme.example"
    response = await client.post(f"{API}/register", json={"email": email, "password": PASSWORD})

    assert response.status_code == 202
    assert probe == [True]


# ── what an online deployment refuses ───────────────────────────────────────


def _settings(environment: str, **values: Any) -> Settings:
    return Settings(_env_file=None, environment=environment, **values)


def test_online_refuses_to_start_without_a_real_sender() -> None:
    """A server that accepts sign-ups and sends nothing, silently: what the
    demo met. It now refuses to start, and says what is missing."""
    values = {key: value for key, value in ONLINE.items() if not key.startswith("smtp")}
    with pytest.raises(ValidationError, match="LEKA_SMTP_HOST"):
        _settings("staging", **values)


def test_online_needs_an_https_web_address() -> None:
    with pytest.raises(ValidationError, match="LEKA_WEB_URL"):
        _settings("staging", **{**ONLINE, "web_url": "http://localhost:3000"})


def test_the_sender_must_be_the_mailbox_that_signs_in() -> None:
    """OVH drops, without a word, mail whose From is not the authenticated box."""
    with pytest.raises(ValidationError, match="LEKA_EMAIL_FROM"):
        _settings("local", **{**ONLINE, "email_from": "LEKA <no-reply@leka-core.com>"})


def test_a_configured_online_deployment_starts() -> None:
    assert _settings("staging", **ONLINE).sends_real_email is True


def test_locally_the_console_is_fine() -> None:
    assert _settings("local", **BASE).sends_real_email is False


# ── dates ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_dates_leave_the_api_with_their_offset(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    """The "two hours late" in psql is psql showing UTC. The API must say
    which instant it means, so the browser can show it in local time."""
    await client.post(f"{API}/register", json={"email": "nora@acme.example", "password": PASSWORD})
    token = urlparse(_link(mailbox.sent[-1])).path.rsplit("/", 1)[1]

    verified = (await client.post(f"{API}/verify/{token}")).json()["email_verified_at"]

    assert re.search(r"(Z|[+-]\d\d:\d\d)$", verified), verified


def test_the_link_checker_reads_real_files() -> None:
    """The page checker is only worth something if it reads the real tree."""
    assert Path(WEB_APP / "(auth)" / "reset-password" / "page.tsx").is_file()
    assert Path(WEB_APP / "(auth)" / "verify" / "[token]" / "page.tsx").is_file()
