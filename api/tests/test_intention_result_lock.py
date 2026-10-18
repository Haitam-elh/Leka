"""« Bloquer l'aperçu du résultat » (LEKA-499) — its analysis scripted
(Gemini proposes the Architect), as test_intention_offer.

What these protect: while what its analysis asks is not had — a plan, an
agent to buy — no result reaches the browser: not its analysis (latest or
any), its summary on its page or in a list; only how it went and what it
proposes, with what is missing. Had — granted, included —, everything. A
demonstration: never locked.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient

from leka.db import session_factory, system_scope
from leka.platform.models import Workspace
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import _ready
from tests.test_context_engine import model
from tests.test_intention_agents import Gemini, _proposed, gemini, started
from tests.test_intention_analysis_api import API, queued  # noqa: F401
from tests.test_intention_offer import _on
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

pytestmark = pytest.mark.integration

_ = (model, gemini, started)  # fixtures, requested by name


async def _read(client: AsyncClient, intention: str) -> tuple[dict, dict, dict, dict]:
    analysis = (await client.get(f"{API}/{intention}/analysis")).json()
    [first] = (await client.get(f"{API}/{intention}/analyses")).json()
    detail = (await client.get(f"{API}/{intention}")).json()
    listed = next(i for i in (await client.get(API)).json()["data"] if i["id"] == intention)
    return analysis, first, detail, listed


async def test_had_everything_is_read(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = (await _proposed(client, acme))["id"]
    analysis, first, detail, listed = await _read(client, intention)
    assert analysis["locked"] is None and first["locked"] is None
    assert detail["locked"] is None and listed["locked"] is None
    assert analysis["result"]["proposal"] is not None


async def test_on_free_nothing_found_reaches_the_browser_only_what_it_proposes(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = (await _proposed(client, acme))["id"]
    await _on(acme["acme"], "free")

    analysis, first, detail, listed = await _read(client, intention)
    for read in (analysis, first):
        assert read["locked"] == "plan_required"
        result = read["result"]
        assert result["proposal"]["agents"], "what it proposes is still said"
        for kept_out in ("summary", "findings", "causes", "impact", "evidence", "support"):
            assert result[kept_out] == [], kept_out
        assert result["answer"] is None and result["risk"] == "unknown"
        assert read["detail"] == {}
    assert (detail["locked"], detail["summary"]) == ("plan_required", None)
    assert (listed["locked"], listed["summary"]) == ("plan_required", None)

    # On Starter, the Architect not bought: the agent is what is missing.
    await _on(acme["acme"], "starter")
    analysis, *_ = await _read(client, intention)
    assert analysis["locked"] == "agents_required"


async def test_a_demonstration_is_never_locked(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    gemini: Callable[..., Gemini],
    started: list[uuid.UUID],
) -> None:
    await _ready(acme)
    gemini()
    _as(identity, acme, "member")
    intention = (await _proposed(client, acme))["id"]
    await _on(acme["acme"], "free")
    with system_scope():
        async with session_factory() as session:
            workspace = await session.get(Workspace, acme["acme"])
            assert workspace is not None
            workspace.demo = True
            await session.commit()
    analysis, _first, detail, _listed = await _read(client, intention)
    assert analysis["locked"] is None and detail["locked"] is None
