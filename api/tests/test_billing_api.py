"""Facturation's figures (GET /billing/usage), on Acme's company model.

What these protect: what the workspace holds — members, sources, the
model's things — and what it did this month — intentions asked, analyses
run, capabilities run — counted, not estimated; read by members; another
workspace's never counted.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from leka.connectors.models import Source, SourceKind, SourceStatus
from leka.db import session_factory, workspace_scope
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intention_decisions_api import _asked, queued  # noqa: F401 — a fixture
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/billing/usage"


async def test_what_the_workspace_holds_and_did_this_month(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    before = (await client.get(API)).json()
    assert before["members"] >= 2
    assert before["entities"] >= len(model) - 1
    assert before["sources"] >= 1
    assert (before["intentions"], before["analyses"], before["capability_runs"]) == (0, 0, 0)

    await _asked(client, acme)  # asked, and analysed as the job would
    after = (await client.get(API)).json()
    assert (after["intentions"], after["analyses"]) == (1, 1)
    assert after["capability_runs"] > 0
    assert set(after["previous"]) == {"intentions", "analyses", "capability_runs"}

    _as(identity, acme, "other_admin")
    elsewhere = (await client.get(API)).json()
    assert (elsewhere["intentions"], elsewhere["entities"]) == (0, 0)


async def test_a_source_in_error_is_counted_connected_as_on_the_home(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
) -> None:
    # LEKA-469: Facturation said « 0 sources connectées » while the home said 1.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            for n, status in enumerate(
                (SourceStatus.ACTIVE, SourceStatus.ERROR, SourceStatus.DRAFT)
            ):
                session.add(
                    Source(
                        workspace_id=acme["acme"],
                        kind=SourceKind.DATADOG,
                        name=f"source-{n}",
                        status=status,
                        config={},
                    )
                )
            await session.commit()
    _as(identity, acme, "admin")
    usage = (await client.get(API)).json()
    assert (usage["sources"], usage["sources_connected"]) == (3, 2)
