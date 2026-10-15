"""The history's filters (LEKA-457): by the agent that ran for it, by a
source — asked about, or cited by its analyses — and by when it was asked."""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from leka.capabilities import AgentRun
from leka.db import session_factory, workspace_scope
from leka.intentions.models import Intention, IntentionAnalysis
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intentions_api import _ask, _get
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name


def _ids(page: Any) -> set[str]:
    return {i["id"] for i in page["data"]}


async def test_the_history_filters_by_agent_source_and_period(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    _as(identity, acme, "member")
    ran = (await _ask(client))["intention"]
    cited = (await _ask(client, "Qui est responsable de Billing API ?"))["intention"]
    scoped = (await _ask(client, "Qu'est-ce qui a changé sur Billing API ?"))["intention"]
    source = uuid.uuid4()
    now = datetime.now(UTC)
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            session.add(
                AgentRun(
                    workspace_id=acme["acme"],
                    key="architect",
                    version="1",
                    status="succeeded",
                    intention_id=uuid.UUID(ran["id"]),
                    format="markdown",
                    queued_at=now,
                )
            )
            session.add(
                IntentionAnalysis(
                    workspace_id=acme["acme"],
                    intention_id=uuid.UUID(cited["id"]),
                    number=99,
                    trigger="requested",
                    status="complete",
                    started_at=now,
                    result={"evidence": [{"sources": [{"id": str(source), "kind": "github"}]}]},
                )
            )
            await session.execute(
                update(Intention)
                .where(Intention.id == uuid.UUID(scoped["id"]))
                .values(scope={"sources": [str(source)]}, created_at=now - timedelta(days=40))
            )
            await session.commit()

    assert _ids(await _get(client, agent="architect")) == {ran["id"]}
    assert _ids(await _get(client, agent="nobody")) == set()
    assert _ids(await _get(client, source=str(source))) == {cited["id"], scoped["id"]}
    month = (now - timedelta(days=30)).isoformat()
    assert _ids(await _get(client, since=month)) == {ran["id"], cited["id"]}
    assert _ids(await _get(client, until=month)) == {scoped["id"]}

    # The history's columns (LEKA-457): its agents, the kinds of its sources.
    rows = {row["id"]: row for row in (await _get(client))["data"]}
    assert rows[ran["id"]]["agents"] == ["architect"]
    assert rows[cited["id"]]["sources"] == ["github"]
    assert rows[scoped["id"]]["agents"] == []

    # Counted by state for its tabs, and listed by several at once.
    counts = await _get(client, "/counts")
    assert sum(counts["statuses"].values()) == counts["all"] == 3
    states = list(counts["statuses"])
    assert len((await _get(client, status=states))["data"]) == 3
    assert (await _get(client, status=["cancelled"]))["data"] == []
