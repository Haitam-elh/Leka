"""Scope rules in the sync (LEKA-351): applied to every record, and a change
of them handled safely.

The fake source of test_sync.py, its commits spread over two repositories,
against the test database.
"""

# ruff: noqa: F811 — the fixtures of test_sync are imported to be requested by name.
from __future__ import annotations

import pytest
from sqlalchemy import select

from leka.background import Event
from leka.connectors import Capability, ScopeRules, Source, SourceService, SourceSettings
from leka.db import session_factory, workspace_scope
from tests import test_sync as sync_tests
from tests.test_sync import _index, _sync, fake, source  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API, LEGACY = "acme/api", "acme/legacy"


async def _save(source: Source, scope: ScopeRules) -> tuple[int, list[str]]:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            service = SourceService(session, source.workspace_id, actor_user_id=None)
            fresh = await service.get(source.id)
            version, _findings, changed = await service.save_settings(
                fresh, SourceSettings(scope=scope)
            )
            await session.commit()
            return version, changed


async def _events(source: Source) -> list[Event]:
    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(Event).where(Event.type == "source.scope_changed"))
            return [e for e in rows.scalars() if e.payload.get("source_id") == str(source.id)]


def _spread() -> None:
    """Commits 0 and 1 in acme/api, 2 and 3 in acme/legacy."""
    sync_tests.SCRIPT.records = {Capability.COMMITS: 4}
    sync_tests.SCRIPT.containers = {0: API, 1: API, 2: LEGACY, 3: LEGACY}


async def test_what_the_rules_exclude_is_neither_stored_nor_indexed(source: Source) -> None:
    _spread()
    await _save(source, ScopeRules(exclude=["*/legacy"]))

    report = await _sync(source)

    assert report.records["commits"] == 2
    assert report.excluded == {"commits": 2}
    assert set(await _index(source)) == {"commits-0", "commits-1"}


async def test_narrowing_the_scope_sweeps_what_went_out_at_the_full_pass(source: Source) -> None:
    _spread()
    await _sync(source)
    assert len(await _index(source)) == 4

    version, changed = await _save(source, ScopeRules(include=[API]))
    await _sync(source, full=True)  # the pass the change queues

    assert (version, changed) == (1, ["scope"])
    index = await _index(source)
    assert {k for k, row in index.items() if row.deleted_at is None} == {"commits-0", "commits-1"}
    assert index["commits-2"].deleted_at is not None  # gone from LEKA: purged, then forgotten


async def test_widening_it_again_brings_them_back(source: Source) -> None:
    _spread()
    await _save(source, ScopeRules(include=[API]))
    await _sync(source)
    await _save(source, ScopeRules())

    await _sync(source, full=True)

    assert {k for k, row in (await _index(source)).items() if row.deleted_at is None} == {
        f"commits-{n}" for n in range(4)
    }


async def test_a_scope_change_on_an_active_source_queues_a_full_pass_once_committed(
    source: Source,
) -> None:
    await _save(source, ScopeRules(exclude=["*/legacy"]))
    await _save(source, ScopeRules(exclude=["*/legacy"]))  # the same: no version, no pass

    (event,) = await _events(source)
    assert event.payload["version"] == 1
