"""The Digital Twin's states (LEKA-442), pure — the ticket's scenarios.

What these protect:
- a normal state: a monitoring source read recently, raising nothing —
  operational, measured, said from which source and when;
- a confirmed incident: unavailable when severe, degraded otherwise —
  confirmed by its record;
- a suspected anomaly: a degradation deduced from what runs it — suspected,
  never confirmed;
- an unknown thing: a source could tell, says nothing — unknown, never
  operational; no source could tell — not covered;
- a stale source: what it rests on not read for three hours — stale, what
  it was said; an incident read from it stays an incident, unverified;
- an unavailable source: every source of it failing — stale, said failing;
- the twin's freshness: read every hour, never « temps réel »; late when no
  read in two; webhooks said; each part covered or not, by which sources.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from leka.ingestion.enrichment.twin import (
    IncidentSeen,
    SourceSeen,
    counted,
    coverage,
    freshness,
    state_of,
    worst,
)
from leka.ingestion.enrichment.view import Thing

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def source(
    name: str = "datadog",
    category: str = "observability",
    *,
    ago: timedelta = timedelta(minutes=20),
    status: str = "active",
    sync: str = "idle",
    health: str = "healthy",
    webhooks: bool = False,
) -> SourceSeen:
    return SourceSeen(
        id=uuid.uuid5(uuid.NAMESPACE_URL, name),
        kind=name,
        name=name,
        category=category,
        status=status,
        sync_status=sync,
        health=health,
        last_synced_at=NOW - ago,
        webhooks=webhooks,
    )


def thing(kind: str = "service", **attributes: object) -> Thing:
    facts = attributes.pop("facts", {})
    return Thing(
        id=uuid.uuid4(),
        type=kind,
        key=kind,
        name="payment-api",
        attributes=attributes,
        facts=facts,  # type: ignore[arg-type]
    )


GITHUB = source("github", "code")
DATADOG = source()


def test_a_monitored_service_raising_nothing_is_operational_and_says_from_what() -> None:
    found = state_of(
        thing(), sources=[GITHUB, DATADOG], incidents=[], monitoring_connected=True, now=NOW
    )
    assert found is not None
    assert (found.state, found.basis, found.reason) == (
        "operational",
        "measured",
        "monitored_quiet",
    )
    assert found.signal == ("datadog",)
    assert found.observed_at == NOW - timedelta(minutes=20)
    assert found.fresh and found.certainty == "confirmed"


def test_a_confirmed_incident_is_unavailable_when_severe_degraded_otherwise() -> None:
    severe = IncidentSeen(uuid.uuid4(), "OPS-1", "payment-api down", "sev1")
    mild = IncidentSeen(uuid.uuid4(), "OPS-2", "payment-api slow", "sev3")
    down = state_of(
        thing(),
        sources=[GITHUB, DATADOG],
        incidents=[mild, severe],
        monitoring_connected=True,
        now=NOW,
    )
    slow = state_of(thing(), sources=[GITHUB], incidents=[mild], monitoring_connected=True, now=NOW)
    assert down is not None and slow is not None
    assert (down.state, down.reason, down.certainty) == (
        "unavailable",
        "incident_open",
        "confirmed",
    )
    assert down.incident == severe and len(down.incidents) == 2
    assert slow.state == "degraded"


def test_a_degradation_deduced_from_what_runs_it_is_only_suspected() -> None:
    found = state_of(
        thing(facts={"deduced_health": "attention"}),
        sources=[GITHUB],
        incidents=[],
        monitoring_connected=False,
        now=NOW,
    )
    assert found is not None
    assert (found.state, found.basis, found.certainty) == ("degraded", "deduced", "suspected")


def test_silence_is_never_health_unknown_or_not_covered() -> None:
    watched_elsewhere = state_of(
        thing(), sources=[GITHUB], incidents=[], monitoring_connected=True, now=NOW
    )
    nothing_could_tell = state_of(
        thing(), sources=[GITHUB], incidents=[], monitoring_connected=False, now=NOW
    )
    assert watched_elsewhere is not None and nothing_could_tell is not None
    assert (watched_elsewhere.state, watched_elsewhere.reason) == ("unknown", "no_signal")
    assert (nothing_could_tell.state, nothing_could_tell.reason) == (
        "not_covered",
        "no_monitoring_source",
    )
    # A repository, a team: no state of their own.
    assert (
        state_of(thing("repository"), sources=[], incidents=[], monitoring_connected=True, now=NOW)
        is None
    )


def test_what_was_read_long_ago_is_stale_never_operational() -> None:
    old = source(ago=timedelta(hours=5))
    found = state_of(thing(), sources=[old], incidents=[], monitoring_connected=True, now=NOW)
    assert found is not None
    assert (found.state, found.was, found.reason, found.fresh) == (
        "stale",
        "operational",
        "sources_stale",
        False,
    )
    assert found.certainty == "unverified"
    # An incident read from it stays what it was — unverified now.
    incident = IncidentSeen(uuid.uuid4(), "OPS-1", "down", "sev1")
    kept = state_of(
        thing(), sources=[old], incidents=[incident], monitoring_connected=True, now=NOW
    )
    assert kept is not None
    assert (kept.state, kept.fresh, kept.certainty) == ("unavailable", False, "unverified")


def test_a_thing_whose_every_source_fails_is_said_failing() -> None:
    failing = source(status="error", sync="failed", health="unhealthy", ago=timedelta(minutes=30))
    found = state_of(thing(), sources=[failing], incidents=[], monitoring_connected=True, now=NOW)
    assert found is not None
    assert (found.state, found.reason) == ("stale", "sources_failing")
    assert failing.state(NOW) == "error"


def test_a_cloud_resource_is_what_its_provider_says() -> None:
    def resource(state: str) -> str | None:
        found = state_of(
            thing("infra_resource", state=state),
            sources=[source("aws", "cloud")],
            incidents=[],
            monitoring_connected=True,
            now=NOW,
        )
        return found.state if found else None

    assert [resource(s) for s in ("running", "stopped", "failed")] == [
        "operational",
        "degraded",
        "unavailable",
    ]


def test_the_twin_says_how_fresh_it_is_and_what_covers_it() -> None:
    hooks = source("custom_webhook", "custom", webhooks=True)
    fresh = freshness([GITHUB, DATADOG, hooks], NOW)
    assert fresh.every == timedelta(hours=1)
    assert fresh.last_read_at == NOW - timedelta(minutes=20)
    assert not fresh.late and fresh.webhooks
    late = freshness([source(ago=timedelta(hours=3))], NOW)
    assert late.late
    # Nothing connected: nothing late, nothing to say late.
    assert not freshness([], NOW).late
    parts = {c.part: c for c in coverage([GITHUB, source("aws", "cloud")])}
    assert parts["applications"].covered and parts["infrastructure"].covered
    assert not parts["health"].covered and not parts["incidents"].covered
    assert [s.name for s in parts["infrastructure"].sources] == ["aws"]


def test_states_are_counted_every_one_said_and_a_box_takes_its_worst() -> None:
    a = state_of(thing(), sources=[DATADOG], incidents=[], monitoring_connected=True, now=NOW)
    b = state_of(thing(), sources=[GITHUB], incidents=[], monitoring_connected=False, now=NOW)
    counts = counted({uuid.uuid4(): a, uuid.uuid4(): b, uuid.uuid4(): None})
    assert counts == {
        "unavailable": 0,
        "degraded": 0,
        "stale": 0,
        "unknown": 0,
        "not_covered": 1,
        "operational": 1,
    }
    assert worst(["operational", "stale", None, "degraded"]) == "degraded"
    assert worst([]) is None
