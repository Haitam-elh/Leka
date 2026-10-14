"""A new account's plan, and what each plan holds (2026-10-14, the product
call).

What these protect:
- A new workspace starts on Free, with Free's 200 AI credits a month.
- A plan holds so many sources (to validate): once they are all there, one
  more is refused — `sources_quota`, the next plan said — and what is there
  is kept. LEKA's grant (its team's workspaces) holds no quota.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid

from httpx import AsyncClient

from leka.db import session_factory, workspace_scope
from leka.governance import set_plan
from tests.conftest import FakeIdentity
from tests.test_sources_api import API, _as, _create, acme, fake_connector  # noqa: F401


async def test_a_new_workspace_starts_on_free_with_its_200_credits(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "other_admin")
    said = (await client.get(f"{API}/billing/credits")).json()
    assert (said["plan"], said["allowance"]) == ("free", 200)


async def test_a_plan_holds_so_many_sources_then_offers_the_next(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "other_admin")
    for n in range(3):
        await _create(client, display_name=f"Free source {n}")
    refused = await client.post(
        f"{API}/sources",
        json={"type": "slack", "display_name": "One too many", "credentials": {"api_key": "k"}},
    )
    assert refused.status_code == 422
    error = refused.json()["error"]
    assert error["code"] == "sources_quota"
    assert error["details"] == [{"field": "plan", "message": "starter"}]
    # What is there is kept.
    listed = (await client.get(f"{API}/sources")).json()["data"]
    assert len(listed) == 3

    # On Starter: two more.
    globex = acme["globex"]
    with workspace_scope(globex):
        async with session_factory() as session:
            await set_plan(session, globex, "starter", by="tests", reason="upgraded")
            await session.commit()
    await _create(client, display_name="Starter source")


async def test_leka_s_team_s_workspaces_hold_no_quota(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    for n in range(5):
        await _create(client, display_name=f"Team source {n}")
