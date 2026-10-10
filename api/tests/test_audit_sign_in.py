"""The audit trail (LEKA-407) and real authentication: signing in, failing
to, signing out, changing a password — each kept in the person's
workspaces, never the password, never whether an unknown address exists.
"""

# ruff: noqa: F811 — the mailbox fixture is imported to be requested by name.
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.db import session_factory, system_scope

from .test_auth_api import API, PASSWORD, CapturingEmailSender, _register_and_verify, _sign_in
from .test_auth_hardening import mailbox  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration


async def _wipe() -> None:
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM workspaces"))
            await session.execute(text("DELETE FROM users"))
            await session.commit()


@pytest.fixture(autouse=True)
async def clean_everything() -> AsyncIterator[None]:
    await _wipe()
    yield
    await _wipe()


async def _trail(client: AsyncClient) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/governance/audit", params={"category": "user"})
    assert response.status_code == 200, response.text
    events: list[dict[str, Any]] = response.json()["events"]
    return events


async def test_signing_in_and_out_kept_in_the_person_s_workspaces(
    client: AsyncClient, mailbox: CapturingEmailSender
) -> None:
    await _register_and_verify(client, mailbox, "nora@acme.example")
    await _sign_in(client, "nora@acme.example")
    created = await client.post("/api/v1/workspaces", json={"name": "Acme Corp"})
    assert created.status_code == 201, created.text
    await client.post(f"/api/v1/workspaces/{created.json()['id']}/switch")

    # Out, a wrong password, an unknown address, in again.
    assert (await client.post(f"{API}/logout")).status_code == 204
    wrong = await client.post(
        f"{API}/login", json={"email": "nora@acme.example", "password": "not it at all"}
    )
    assert wrong.status_code == 401
    unknown = await client.post(
        f"{API}/login", json={"email": "nobody@acme.example", "password": PASSWORD}
    )
    assert unknown.status_code == 401
    await _sign_in(client, "nora@acme.example")
    changed = await client.post(
        f"{API}/password/change",
        json={"current_password": PASSWORD, "new_password": PASSWORD + " again"},
    )
    assert changed.status_code == 204, changed.text

    # A failed sign-in is kept after its answer: the timing tells nothing.
    for _ in range(50):
        events = await _trail(client)
        if len(events) >= 4:
            break
        await asyncio.sleep(0.05)
    assert [(e["action"], e["outcome"]) for e in events] == [
        ("user.password_changed", "success"),
        ("user.signed_in", "success"),
        ("user.sign_in_failed", "failure"),
        ("user.signed_out", "success"),
    ]
    failed = events[2]
    assert failed["detail"] == {"why": "invalid_credentials"}
    # Anyone may try an address: its owner is the target, never the author.
    assert (failed["actor_type"], failed["actor_id"], failed["actor_role"]) == (
        "system",
        None,
        None,
    )
    assert failed["target_type"] == "user" and failed["target_id"] == events[1]["actor_id"]
    # From where: a network prefix at most — never the password, never the
    # unknown address.
    assert PASSWORD not in str(events) and "nobody@" not in str(events)
    assert all(e["ip"] is None or e["ip"].endswith(("/24", "/48")) for e in events)
