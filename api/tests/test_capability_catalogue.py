"""The catalogue's history (LEKA-393), in the database.

What these protect: each version of a capability is registered once, as
what it is — a second sync changes nothing; a new version supersedes the
last; a move its lifecycle allows is kept, one it forbids refused and the
registered lifecycle stands; a change without a new version, an older
version — refused, once, said why, and what was registered stands; every
event is kept, and the database refuses to change one; one sync at a time.

Its tables are LEKA's, shared by the run: each test registers keys of its
own.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from leka.capabilities import (
    CapabilityEvent,
    CapabilityRegistration,
    Definition,
    Kind,
    Lifecycle,
    standings,
    sync,
)
from leka.db import session_factory, system_scope

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _definition() -> Definition:
    return Definition(
        key=f"test-{uuid.uuid4().hex[:12]}",
        title="A test capability",
        summary="Use when a test needs a capability of its own to register.",
        category="knowledge",
        kind=Kind.RULES,
        version="1.0.0",
        lifecycle=Lifecycle.DRAFT,
    )


async def _sync(*found: Definition, at: datetime = NOW) -> dict[str, int]:
    with system_scope():
        async with session_factory() as session:
            counts = await sync(session, found, now=at)
            await session.commit()
            return counts


async def _history(key: str) -> tuple[list[CapabilityRegistration], list[CapabilityEvent]]:
    with system_scope():
        async with session_factory() as session:
            rows = (
                await session.scalars(
                    select(CapabilityRegistration)
                    .where(CapabilityRegistration.key == key)
                    .order_by(CapabilityRegistration.registered_at)
                )
            ).all()
            events = (
                await session.scalars(
                    select(CapabilityEvent)
                    .where(CapabilityEvent.key == key)
                    .order_by(CapabilityEvent.at, CapabilityEvent.version)
                )
            ).all()
            return list(rows), list(events)


async def test_a_version_is_registered_once_and_a_new_one_supersedes_it() -> None:
    first = _definition()
    assert await _sync(first) == {"registered": 1}
    assert await _sync(first, at=NOW + timedelta(hours=1)) == {}

    second = replace(first, version="1.1.0", summary=first.summary + " Better.")
    assert await _sync(second, at=NOW + timedelta(days=1)) == {"registered": 1}
    rows, events = await _history(first.key)
    assert [(r.version, r.superseded_at is not None) for r in rows] == [
        ("1.0.0", True),
        ("1.1.0", False),
    ]
    assert [(e.version, e.kind) for e in events] == [
        ("1.0.0", "registered"),
        ("1.0.0", "superseded"),
        ("1.1.0", "registered"),
    ]
    # What it was is kept — its instructions never.
    assert rows[1].definition["summary"] == second.summary
    assert rows[1].fingerprint == second.fingerprint()


async def test_its_lifecycle_moves_where_it_may_and_retired_is_final() -> None:
    d = _definition()
    hour = timedelta(hours=1)
    await _sync(d)
    assert await _sync(replace(d, lifecycle=Lifecycle.ACTIVE), at=NOW + hour) == {"moved": 1}
    assert await _sync(replace(d, lifecycle=Lifecycle.RETIRED), at=NOW + 2 * hour) == {"moved": 1}
    # Back from retired: refused, once — the registered lifecycle stands.
    back = replace(d, lifecycle=Lifecycle.ACTIVE)
    assert await _sync(back, at=NOW + 3 * hour) == {"refused": 1}
    assert await _sync(back, at=NOW + 4 * hour) == {}
    rows, events = await _history(d.key)
    assert rows[0].lifecycle == "retired"
    assert [(e.kind, e.from_lifecycle, e.to_lifecycle) for e in events] == [
        ("registered", None, "draft"),
        ("lifecycle_changed", "draft", "active"),
        ("lifecycle_changed", "active", "retired"),
        ("refused", None, "active"),
    ]
    assert events[-1].detail["why"] == "lifecycle_refused"
    [standing] = standings([back], rows)
    assert (standing.definition.lifecycle, standing.refused) == (
        Lifecycle.RETIRED,
        "lifecycle_refused",
    )


async def test_a_change_without_a_new_version_or_an_older_one_is_refused() -> None:
    d = _definition()
    await _sync(replace(d, version="2.0.0"))
    changed = replace(d, version="2.0.0", summary=d.summary + " Quietly changed.")
    hour = timedelta(hours=1)
    assert await _sync(changed, at=NOW + hour) == {"refused": 1}
    assert await _sync(changed, at=NOW + 2 * hour) == {}
    older = replace(d, version="1.9.0")
    assert await _sync(older, at=NOW + 3 * hour) == {"refused": 1}
    rows, events = await _history(d.key)
    assert [r.version for r in rows] == ["2.0.0"]
    assert [e.detail.get("why") for e in events if e.kind == "refused"] == [
        "changed_without_version",
        "version_regressed",
    ]
    by_key = {s.definition.version: s.refused for s in standings([changed, older], rows)}
    assert by_key == {"2.0.0": "changed_without_version", "1.9.0": "version_regressed"}


async def test_the_history_is_append_only() -> None:
    d = _definition()
    await _sync(d)
    _, [event] = await _history(d.key)
    with system_scope():
        async with session_factory() as session:
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    text("UPDATE capability_events SET kind = 'x' WHERE id = :e"),
                    {"e": event.id},
                )
