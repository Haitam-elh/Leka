"""A demonstration's AI credits are its own (decided 2026-10-15): Free's, in
its own workspace — what it spends never counts against the real
workspace of whoever tries it, nor is its exhaustion theirs."""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from leka.db import session_factory, system_scope, workspace_scope
from leka.governance import set_plan
from leka.metering import credits_now
from leka.platform import Workspace
from tests.test_ai_credits import _keep, _spend
from tests.test_sources_api import acme  # noqa: F401 — a fixture

pytestmark = pytest.mark.integration


async def test_a_demonstration_spends_its_own_credits_never_the_real_workspace(
    acme: dict[str, uuid.UUID],
) -> None:
    real, demo = acme["acme"], acme["globex"]
    with system_scope():
        async with session_factory() as session:
            await session.execute(update(Workspace).where(Workspace.id == demo).values(demo=True))
            await session.commit()
    with workspace_scope(real):
        async with session_factory() as session:
            await set_plan(session, real, "growth", by="test", reason="a customer")
            await session.commit()

    # Far more than Free allows, spent in the demonstration.
    await _keep(demo, _spend(demo, 1_000.0))

    now = datetime.now(UTC)
    with workspace_scope(demo):
        async with session_factory() as session:
            shown = await credits_now(session, demo, now=now)
    assert (shown.plan, shown.state) == ("free", "exhausted")
    with workspace_scope(real):
        async with session_factory() as session:
            theirs = await credits_now(session, real, now=now)
    assert (theirs.plan, theirs.used, theirs.state) == ("growth", 0, "ok")
