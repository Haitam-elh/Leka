"""A plan's users and sources (LEKA-463): one more than it allows is refused,
the plan that allows it named; nothing is changed for them."""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from itertools import pairwise

from httpx import AsyncClient

from leka.billing import catalogue
from leka.db import session_factory, workspace_scope
from leka.governance import set_plan
from tests.conftest import FakeIdentity, error_code
from tests.test_sources_api import API, _as, _create, acme, fake_connector  # noqa: F401 — fixtures


async def _on(workspace: uuid.UUID, plan: str) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await set_plan(session, workspace, plan, by="test", reason="LEKA-463")
            await session.commit()


def test_each_plan_allows_at_least_the_one_below() -> None:
    sold = [p for p in catalogue().plans if p.self_service]
    for lower, higher in pairwise(sold):
        assert (lower.quotas.users or 0) <= (higher.quotas.users or 0)
        assert (lower.quotas.sources or 0) < (higher.quotas.sources or 0)
    assert catalogue().plan("enterprise").quotas.users is None


async def test_a_seat_more_than_the_plan_allows_is_refused_the_plan_above_named(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    # Acme has two seats; Free and Starter allow one.
    refused = await client.post(f"{API}/members/invite", json={"email": "new@acme.example"})
    assert refused.status_code == 403
    assert error_code(refused) == "plan_limit"
    assert "Growth" in refused.json()["error"]["message"]

    await _on(acme["acme"], "growth")
    for n in range(3):
        made = await client.post(f"{API}/members/invite", json={"email": f"n{n}@acme.example"})
        assert made.status_code == 201, made.text
    # 2 seats and 3 invitations: Growth's 5.
    full = await client.post(f"{API}/members/invite", json={"email": "n3@acme.example"})
    assert error_code(full) == "plan_limit"
    assert "Business" in full.json()["error"]["message"]


async def test_a_source_more_than_the_plan_allows_is_refused(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "admin")
    await _on(acme["acme"], "starter")
    for n in range(5):
        await _create(client, display_name=f"Source {n}")
    refused = await client.post(
        f"{API}/sources",
        json={"type": "slack", "display_name": "Sixth", "credentials": {"api_key": "k"}},
    )
    assert refused.status_code == 403
    assert error_code(refused) == "plan_limit"
    assert refused.json()["error"]["message"] == (
        "The Starter plan allows 5 sources. Growth allows more."
    )
