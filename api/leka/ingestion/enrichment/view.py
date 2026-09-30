"""The environment, as the "Mon environnement" screens show it (mockups 10
and 11): what resolution and enrichment made, laid out — each thing's
state, the map's layers and the links between them, what needs attention,
what moved last.

Every figure is made of what the sources said; what no source says is
absent, never guessed. The states — mockup 10's legend — and where each
comes from:

    service         incident      an open incident affects it
                    attention     an incident affecting it moved in 7 days
                    operational   a monitoring source (PagerDuty, Datadog,
                                  Grafana) shows it, and nothing above
                    unmonitored   no monitoring source shows it
    database,       operational   running          attention  starting,
    cloud resource  incident      failed                      stopping,
                                                              stopped, deleting
    incident        incident      open, in progress
                    operational   closed

Pure: rows in, the view out; the route reads (leka/api/enrichment.py).
Rules: docs/enrichment.md § 11.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta

RECENT_INCIDENT = timedelta(days=7)
CHANGE_WINDOW = timedelta(hours=24)
OPEN = frozenset({"open", "in_progress"})
RUNNING = frozenset({"running"})
PAUSED = frozenset({"starting", "stopping", "stopped", "deleting"})
FAILED = frozenset({"failed"})
# What the map draws, layer by layer, in the mockup's order. Its first
# layer, the users, no source describes yet.
LAYERS: dict[str, str] = {
    "repository": "applications",
    "service": "services",
    "database": "data",
    "infra_resource": "infrastructure",
}
MAP_TYPES = (*LAYERS, "team")
# What is a change, in "Changements récents".
CHANGES = frozenset({"pull_request", "commit", "release", "deployment"})
# A cloud resource's provider, by its key.
PROVIDERS = {"aws:": "aws", "azure:": "azure", "gcp:": "gcp"}


@dataclass(frozen=True)
class Thing:
    """A resolved entity, with what the view needs of its enrichment."""

    id: uuid.UUID
    type: str
    key: str
    name: str
    attributes: Mapping[str, object]
    facts: Mapping[str, object] = field(default_factory=dict)
    # The kinds of the sources that show it: github, pagerduty…
    kinds: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Link:
    from_id: uuid.UUID
    to_id: uuid.UUID
    type: str


def status(thing: Thing, *, monitoring: frozenset[str], recently_hit: bool) -> str | None:
    """A thing's state, in mockup 10's words — none for what has no state
    of its own (a repository, a team)."""
    state = thing.attributes.get("state")
    if thing.type == "service":
        if _int(thing.facts.get("open_incidents")) > 0:
            return "incident"
        if recently_hit:
            return "attention"
        return "operational" if thing.kinds & monitoring else "unmonitored"
    if thing.type in ("database", "infra_resource"):
        if state in RUNNING:
            return "operational"
        if state in PAUSED:
            return "attention"
        if state in FAILED:
            return "incident"
        return None
    if thing.type == "incident":
        return "incident" if state in OPEN else "operational"
    return None


def provider_of(thing: Thing) -> tuple[str, str | None] | None:
    """A cloud resource's provider and region: aws and eu-central-1 of
    aws:arn:aws:ec2:eu-central-1:…; Azure and GCP without a region the key
    says plainly."""
    for prefix, provider in PROVIDERS.items():
        if thing.key.startswith(prefix):
            region = None
            if provider == "aws":
                parts = thing.key.split(":")
                region = parts[4] if len(parts) > 4 and parts[4] else None
            region = str(thing.attributes.get("region") or "") or region
            return provider, region
    return None


@dataclass
class Node:
    """One box of the map: an entity, or a provider's resources together."""

    id: str
    type: str
    layer: str
    name: str
    status: str | None
    entity_id: uuid.UUID | None = None
    key: str | None = None
    detail: str | None = None
    count: int = 1
    environment: str | None = None
    team_id: uuid.UUID | None = None


@dataclass
class Edge:
    from_id: str
    to_id: str
    type: str
    status: str | None


WORST = {"incident": 3, "attention": 2, "operational": 1, "unmonitored": 0}


def layout(
    things: Iterable[Thing],
    links: Iterable[Link],
    statuses: Mapping[uuid.UUID, str | None],
) -> tuple[list[Node], list[Edge], dict[str, int]]:
    """The map: a node per repository, service and database; the cloud
    resources together per provider and region, in their worst state; an
    edge per link between two of them — a resource's to its provider's box
    — coloured by the worse of its ends. And how many there are per layer."""
    nodes: dict[str, Node] = {}
    box_of: dict[uuid.UUID, str] = {}
    layers: dict[str, int] = defaultdict(int)
    teams: dict[uuid.UUID, uuid.UUID] = {}
    listed, joined = list(things), list(links)
    for link in joined:
        if link.type == "owned_by":
            teams.setdefault(link.from_id, link.to_id)
    for thing in listed:
        layer = LAYERS.get(thing.type)
        if layer is None:
            continue
        layers[layer] += 1
        state = statuses.get(thing.id)
        environment = thing.attributes.get("environment")
        if thing.type == "infra_resource" and (found := provider_of(thing)):
            provider, region = found
            box = f"provider:{provider}:{region or ''}"
            held = nodes.get(box)
            if held is None:
                held = nodes[box] = Node(
                    id=box,
                    type="provider",
                    layer=layer,
                    name=provider,
                    status=state,
                    detail=region,
                    count=0,
                )
            held.count += 1
            if WORST.get(state or "", -1) > WORST.get(held.status or "", -1):
                held.status = state
            box_of[thing.id] = box
            continue
        box = str(thing.id)
        nodes[box] = Node(
            id=box,
            type=thing.type,
            layer=layer,
            name=thing.name,
            status=state,
            entity_id=thing.id,
            key=thing.key,
            environment=environment if isinstance(environment, str) else None,
            team_id=teams.get(thing.id),
        )
        box_of[thing.id] = box
    edges: dict[tuple[str, str], Edge] = {}
    for link in joined:
        a, b = box_of.get(link.from_id), box_of.get(link.to_id)
        if a is None or b is None or a == b or (b, a) in edges:
            continue
        worse = max((nodes[a].status, nodes[b].status), key=lambda s: WORST.get(s or "", -1))
        edges.setdefault((a, b), Edge(a, b, link.type, worse))
    return list(nodes.values()), list(edges.values()), dict(layers)


def event_kind(thing: Thing) -> str:
    """How an item that moved shows in a list of events: an incident open
    or resolved, work left waiting, a change, or news."""
    state = thing.attributes.get("state")
    if thing.type == "incident":
        return "incident" if state in OPEN else "resolved"
    if thing.facts.get("stale") is True:
        return "attention"
    if thing.type in CHANGES:
        return "change"
    return "information"


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
