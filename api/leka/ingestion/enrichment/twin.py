"""The Digital Twin's states (LEKA-442): each thing's state in the six words
every screen uses, read from the signals that really exist — never from
silence. « Inconnu » is not « sain ».

    unavailable   an open incident of high severity affects it (sev0, sev1,
                  P0, P1, critical); its provider says it failed
    degraded      an open incident of lower severity affects it; its
                  provider says it is starting, stopping or stopped; its
                  health deduced from what runs it is degraded
    operational   a monitoring source watching it, read recently, raises
                  nothing; its provider says it runs; its health deduced
                  from what runs it is good — each said how (`basis`)
    stale         what it rests on was last read more than STALE_AFTER ago,
                  or every source that states it is failing: what it was
                  then is not what it is now
    unknown       a connected source could tell, and says nothing of it
    not_covered   no connected source could tell: no monitoring tool for a
                  service — connect one to know

Where a state comes from (`basis`): measured (a monitoring tool, an
incident record), declared (a provider's word on its resource), deduced
(from what runs it — LEKA-369), none. An incident's state is `confirmed`
when its record says it is open; a deduced degradation is only suspected.

Freshness, as it really is: sources are read every SYNC_EVERY — not in
real time; a source that receives webhooks says so. What the screens show
says when it was last observed, and when a read is late.

Pure: rows in, states out; screens.py reads, the monitoring sweep alerts
(leka.monitoring). Rules: docs/enrichment.md § 12 bis.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from leka.ingestion.enrichment.view import FAILED, PAUSED, RUNNING, Thing

STATES = ("unavailable", "degraded", "stale", "unknown", "not_covered", "operational")
# The worst first: what a box holding several says.
WORST = {state: rank for rank, state in enumerate(reversed(STATES))}
# How often a source is read (leka.ingestion.sync.SYNC_INTERVAL): what the
# screens say, never « temps réel ».
SYNC_EVERY = timedelta(hours=1)
# Three reads missed: what it said then is not what it is now.
STALE_AFTER = 3 * SYNC_EVERY
# A read this late is said late.
LATE_AFTER = 2 * SYNC_EVERY
SEVERE = frozenset({"sev0", "sev1", "p0", "p1", "critical", "highest", "blocker", "urgent"})
HAS_STATE = frozenset({"service", "database", "infra_resource"})
# What each part of the twin is read from, by the category of its sources
# (leka.connectors.ConnectorCategory): connected, the part is covered.
COVERAGE: dict[str, tuple[str, ...]] = {
    "applications": ("code",),
    "services": ("code", "observability", "custom"),
    "health": ("observability",),
    "incidents": ("project", "observability"),
    "data": ("data", "cloud"),
    "infrastructure": ("cloud",),
    "teams": ("code", "project", "chat"),
}


@dataclass(frozen=True)
class SourceSeen:
    """A source, as the connectors hold it now."""

    id: uuid.UUID
    kind: str
    name: str
    category: str
    status: str  # draft, tested, active, degraded, error, disabled
    sync_status: str  # never, idle, running, failed
    health: str  # unknown, healthy, degraded, unhealthy
    last_synced_at: datetime | None
    error: str | None = None
    webhooks: bool = False

    @property
    def connected(self) -> bool:
        return self.status in ("active", "degraded", "error")

    def state(self, now: datetime) -> str:
        """read, error, degraded, stale, syncing, disabled or never."""
        if self.status == "disabled":
            return "disabled"
        if self.status == "error" or self.sync_status == "failed" or self.health == "unhealthy":
            return "error"
        if self.last_synced_at is None:
            return "syncing" if self.sync_status == "running" else "never"
        if self.status == "degraded" or self.health == "degraded":
            return "degraded"
        if now - self.last_synced_at > STALE_AFTER:
            return "stale"
        if self.sync_status == "running":
            return "syncing"
        return "read"


@dataclass(frozen=True)
class IncidentSeen:
    """An open incident on a thing: its record, how bad."""

    id: uuid.UUID
    key: str
    name: str
    severity: str | None

    @property
    def severe(self) -> bool:
        return (self.severity or "").lower().replace(" ", "") in SEVERE


@dataclass(frozen=True)
class TwinState:
    state: str
    basis: str  # measured, declared, deduced, none
    reason: str  # incident_open, resource_failed, monitored_quiet… — worded by the screens
    observed_at: datetime | None
    signal: tuple[str, ...] = ()  # the sources it rests on, by name
    # Read from sources not read for STALE_AFTER, or failing: what it was.
    fresh: bool = True
    was: str | None = None
    certainty: str = "confirmed"  # confirmed, suspected, unverified
    incident: IncidentSeen | None = None
    incidents: tuple[IncidentSeen, ...] = field(default_factory=tuple)


def _deduced(thing: Thing) -> str | None:
    health = thing.facts.get("deduced_health")
    return {"operational": "operational", "attention": "degraded", "incident": "unavailable"}.get(
        str(health)
    )


def state_of(
    thing: Thing,
    *,
    sources: Sequence[SourceSeen],
    incidents: Sequence[IncidentSeen],
    monitoring_connected: bool,
    now: datetime,
) -> TwinState | None:
    """A thing's state, from what really says it — none for what has no
    state of its own (a repository, a team)."""
    if thing.type not in HAS_STATE:
        return None
    read = [s for s in sources if s.last_synced_at is not None]
    observed = max((s.last_synced_at for s in read if s.last_synced_at), default=None)
    fresh = any(s.state(now) in ("read", "syncing") for s in sources)
    names = tuple(sorted({s.name for s in sources}))
    resource = thing.attributes.get("state")
    found: TwinState
    if incidents:
        worst = max(incidents, key=lambda i: (i.severe, i.name))
        found = TwinState(
            "unavailable" if worst.severe else "degraded",
            "measured",
            "incident_open",
            observed,
            names,
            incident=worst,
            incidents=tuple(incidents),
        )
    elif thing.type in ("database", "infra_resource") and resource in FAILED:
        found = TwinState("unavailable", "declared", "resource_failed", observed, names)
    elif thing.type in ("database", "infra_resource") and resource in PAUSED:
        found = TwinState("degraded", "declared", "resource_paused", observed, names)
    elif thing.type in ("database", "infra_resource") and resource in RUNNING:
        found = TwinState("operational", "declared", "resource_running", observed, names)
    elif thing.type == "service" and any(s.category == "observability" for s in sources):
        watching = [s for s in sources if s.category == "observability"]
        found = TwinState(
            "operational",
            "measured",
            "monitored_quiet",
            max((s.last_synced_at for s in watching if s.last_synced_at), default=observed),
            tuple(sorted({s.name for s in watching})),
        )
        fresh = any(s.state(now) in ("read", "syncing") for s in watching)
    elif (deduced := _deduced(thing)) is not None:
        found = TwinState(
            deduced,
            "deduced",
            "deduced_health",
            observed,
            names,
            certainty="suspected" if deduced != "operational" else "confirmed",
        )
    elif thing.type == "service" and not monitoring_connected:
        found = TwinState("not_covered", "none", "no_monitoring_source", observed, names)
    else:
        found = TwinState("unknown", "none", "no_signal", observed, names)
    if not fresh and sources:
        failing = all(s.state(now) in ("error", "disabled") for s in sources)
        if found.state in ("operational", "unknown"):
            # Never « opérationnel » on what was read long ago: what it was.
            return TwinState(
                "stale",
                found.basis,
                "sources_failing" if failing else "sources_stale",
                found.observed_at,
                found.signal,
                fresh=False,
                was=found.state,
                certainty="unverified",
                incident=found.incident,
                incidents=found.incidents,
            )
        return TwinState(
            found.state,
            found.basis,
            found.reason,
            found.observed_at,
            found.signal,
            fresh=False,
            certainty="unverified",
            incident=found.incident,
            incidents=found.incidents,
        )
    return found


def worst(states: Iterable[str | None]) -> str | None:
    """The worst of several states — a provider's box over its resources."""
    held = [s for s in states if s]
    return max(held, key=lambda s: WORST[s]) if held else None


@dataclass(frozen=True)
class Coverage:
    """What a part of the twin is read from, and whether anything is."""

    part: str
    covered: bool
    sources: tuple[SourceSeen, ...]


def coverage(sources: Sequence[SourceSeen]) -> list[Coverage]:
    """Each part of the twin, covered or not, by which connected sources."""
    return [
        Coverage(
            part,
            any(s.connected for s in sources if s.category in needs),
            tuple(s for s in sources if s.connected and s.category in needs),
        )
        for part, needs in COVERAGE.items()
    ]


@dataclass(frozen=True)
class Freshness:
    """When the twin was last observed, how often, and whether it is late."""

    last_read_at: datetime | None
    every: timedelta
    late: bool
    webhooks: bool


def freshness(sources: Sequence[SourceSeen], now: datetime) -> Freshness:
    connected = [s for s in sources if s.connected]
    last = max((s.last_synced_at for s in connected if s.last_synced_at), default=None)
    return Freshness(
        last_read_at=last,
        every=SYNC_EVERY,
        late=bool(connected) and (last is None or now - last > LATE_AFTER),
        webhooks=any(s.webhooks for s in connected),
    )


def counted(states: Mapping[uuid.UUID, TwinState | None]) -> dict[str, int]:
    """How many things are in each state — every state said, 0 included."""
    out = dict.fromkeys(STATES, 0)
    for found in states.values():
        if found is not None:
            out[found.state] += 1
    return out
