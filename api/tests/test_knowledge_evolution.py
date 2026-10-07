"""How the company model changes over time (LEKA-383): pure, no database.

What these protect: a version says what it changed, from what, to what —
its first changes nothing, it is everything — and what it was: created,
changed, removed, back. The relationships at a moment are today's with each
change since undone, the latest first. A snapshot counts the kinds without
the removed, the lifecycles with them, and how well each kind is known as
the coverage does — what it cannot know, it says it does not. A restore
puts back only what the version said otherwise, and says what it cannot
take away. A build's rows count as the snapshot reads them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from leka.knowledge.evolution import (
    Moved,
    Thing,
    change_kind,
    days_between,
    diff,
    measure,
    restorable,
    rewind,
    zone,
)

A, B, C, D = (uuid.uuid4() for _ in range(4))


def content(
    name: str = "payment-api", lifecycle: str = "active", **attributes: object
) -> dict[str, object]:
    return {"name": name, "attributes": attributes, "lifecycle": lifecycle}


# ── what a version changed ───────────────────────────────────────────────────


def test_a_version_says_each_field_it_changed_from_what_to_what() -> None:
    before = content(version="2.8.3", sla="99.9")
    after = content(name="payments-api", version="2.8.4", region="eu-west-1")

    said = {(f.field, f.before, f.after) for f in diff(before, after)}

    assert said == {
        ("name", "payment-api", "payments-api"),
        ("attributes.version", "2.8.3", "2.8.4"),
        ("attributes.sla", "99.9", None),
        ("attributes.region", None, "eu-west-1"),
    }


def test_the_first_version_changes_nothing_it_is_everything() -> None:
    assert diff(None, content(version="1.0")) == []
    assert change_kind(1, None, content()) == "created"


def test_what_a_version_was() -> None:
    active, removed = content(), content(lifecycle="removed")
    assert change_kind(2, active, content(version="2")) == "changed"
    assert change_kind(3, active, removed) == "removed"
    assert change_kind(4, removed, active) == "returned"
    # Archived is a change of lifecycle, not a removal.
    assert change_kind(5, active, content(lifecycle="archived")) == "changed"


# ── the relationships at a moment ────────────────────────────────────────────


def test_the_relationships_then_are_today_s_with_each_change_since_undone() -> None:
    now = {
        (A, B, "depends_on"): {"confidence": 1.0, "origin": "stated"},
        (A, C, "depends_on"): {"confidence": 0.9, "origin": "inferred"},
    }
    since = [
        # The latest first: A→C appeared yesterday; A→D went; A→B changed.
        Moved(A, C, "depends_on", "added", None),
        Moved(A, D, "depends_on", "removed", {"confidence": 0.8, "origin": "stated"}),
        Moved(A, B, "depends_on", "changed", {"confidence": 0.6, "origin": "inferred"}),
    ]

    then = rewind(now, since)

    assert then == {
        (A, B, "depends_on"): {"confidence": 0.6, "origin": "inferred"},
        (A, D, "depends_on"): {"confidence": 0.8, "origin": "stated"},
    }
    assert rewind(now, []) == now


def test_a_relationship_that_came_and_went_since_is_not_there_then() -> None:
    since = [
        Moved(A, B, "owns", "removed", {"origin": "stated"}),
        Moved(A, B, "owns", "added", None),
    ]
    assert rewind({}, since) == {}


# ── snapshots ────────────────────────────────────────────────────────────────


def test_a_snapshot_counts_kinds_lifecycles_relationships_and_coverage() -> None:
    things = [
        Thing(A, "service", "active", sources=2),
        Thing(B, "service", "dormant", sources=1),
        Thing(C, "service", "removed", sources=1),
        Thing(D, "person", "active", sources=1),
        Thing(uuid.uuid4(), "person", "active", bot=True, sources=1),
    ]
    edges = [(A, D, "owned_by"), (D, B, "describes"), (B, A, "depends_on")]

    measured = measure(things, edges)

    assert measured.types == {"person": 2, "service": 2}
    assert measured.lifecycles == {"active": 3, "dormant": 1, "removed": 1}
    assert measured.relationships == {"depends_on": 1, "describes": 1, "owned_by": 1}
    assert measured.kinds["service"] == {
        "total": 2,
        "owned": 1,
        "documented": 1,
        "corroborated": 1,
        "connected": 2,
    }
    # A person is asked no owner and no document; a bot is no person.
    assert measured.kinds["person"] == {
        "total": 1,
        "owned": None,
        "documented": None,
        "corroborated": 0,
        "connected": 1,
    }
    assert measured.counts() == {
        "types": measured.types,
        "lifecycles": measured.lifecycles,
        "relationships": measured.relationships,
    }


def test_rebuilt_from_history_it_does_not_know_how_many_sources_said_each() -> None:
    measured = measure([Thing(A, "service", "active")], [])
    assert measured.kinds["service"]["corroborated"] is None


# ── restoring a version ──────────────────────────────────────────────────────


def test_a_restore_puts_back_only_what_the_version_said_otherwise() -> None:
    then = content(version="2.8.3", sla="99.95", team="payments")
    now = {"version": "2.8.4", "sla": "99.95", "team": "platform", "region": "eu-west-1"}

    restored, kept = restorable(then, now, None)

    assert restored == {
        "team": {"before": "platform", "after": "payments"},
        "version": {"before": "2.8.4", "after": "2.8.3"},
    }
    # What the version did not say, a restore cannot take away.
    assert kept == ["region"]
    chosen, _ = restorable(then, now, ["team"])
    assert chosen == {"team": {"before": "platform", "after": "payments"}}
    assert restorable(then, {"version": "2.8.3", "sla": "99.95", "team": "payments"}, None) == (
        {},
        [],
    )


# ── days ─────────────────────────────────────────────────────────────────────


def test_days_are_the_reader_s_and_an_unknown_zone_is_utc() -> None:
    assert str(zone("Europe/Paris")) == "Europe/Paris"
    assert str(zone("Mars/Olympus")) == "UTC"
    assert str(zone(None)) == "UTC"
    evening = datetime(2026, 10, 6, 22, 30, tzinfo=UTC)
    # 22:30 UTC is already the 7th in Paris.
    assert days_between(evening, evening + timedelta(hours=1), zone("Europe/Paris")) == [
        date(2026, 10, 7)
    ]
    assert days_between(evening, evening + timedelta(days=2), zone(None)) == [
        date(2026, 10, 6),
        date(2026, 10, 7),
        date(2026, 10, 8),
    ]
