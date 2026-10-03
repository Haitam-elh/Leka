"""The company's landscapes, as the screens draw them (LEKA-369).

A VIEW is a few rows — layers — each holding entities of some kinds, and
the relationships drawn between them. One definition per landscape:

    company         users · applications · services · data · infrastructure
                    (mockup 10's rows)
    domains         capabilities · processes · applications · data
    applications    applications · services · code
    services        services · data · infrastructure
    data            databases · schemas · tables and views
    infrastructure  accounts · resources · databases
    organisation    teams · people
    dependencies    what the business and the software need to work: the
                    dependency relationships' ends (registry.DEPENDENCIES)

A layer shows its most connected entities first, MAX_PER_LAYER at most,
and says how many it holds. A TIED layer holds only what a relationship of
the view ties to some kinds: the databases services depend on, not every
database; the applications the business relies on, not every one. Where
no catalogue names applications, a code host's repositories fill the
company's row (its FALLBACK), as the environment screen always drew
them. Cloud resources are BOXED per
provider and region on the company and services views — forty instances
are one provider to someone reading the company — and listed one by one
on the infrastructure view.

Each thing's STATE is the environment screen's rules (leka.ingestion's
environment_status, docs/enrichment.md § 12): a service's from its
incidents and whether a monitoring source shows it, a database's or a
resource's from its own state.

COVERAGE says how well LEKA knows each kind of a view, over all of them —
not only those drawn: how many have an owner, are documented, are said by
two sources or more, are tied to anything at all. A measure that does not
apply to a kind — a person's owner — is none.

Pure: rows in, the view out; the service reads (graph.py).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from leka.ingestion import (
    EnvironmentThing,
    environment_status,
    environment_status_deduced,
    provider_of,
)
from leka.knowledge.models import EntityType, RelationshipType
from leka.knowledge.registry import DEPENDENCIES

# A layer's entities, at most, in a view: the map shows five a row until
# asked for all, the list all of these.
MAX_PER_LAYER = 60

E = EntityType
R = RelationshipType


@dataclass(frozen=True)
class Layer:
    name: str
    types: tuple[EntityType, ...]
    # What fills the row when nothing of `types` exists.
    fallback: tuple[EntityType, ...] = ()
    # Only what the view's relationships tie to one of these kinds.
    tied: tuple[EntityType, ...] = ()
    # Cloud resources together, per provider and region.
    boxed: bool = False


@dataclass(frozen=True)
class View:
    name: str
    layers: tuple[Layer, ...]
    links: tuple[RelationshipType, ...]

    @property
    def types(self) -> tuple[EntityType, ...]:
        seen: dict[EntityType, None] = {}
        for layer in self.layers:
            for kind in (*layer.types, *layer.fallback):
                seen[kind] = None
        return tuple(seen)


# The relationships the registry says are dependencies: depends_on,
# supported_by, uses, reads_from, references.
DEPENDENCY_LINKS = DEPENDENCIES
BUSINESS = (E.BUSINESS_CAPABILITY, E.BUSINESS_PROCESS)
DATA = (E.DATABASE, E.SCHEMA, E.DATA_OBJECT)
# What the dependency relationships' ends may be: a thing on the dependency
# view needs or is needed by one of these.
NEEDED = (*BUSINESS, E.APPLICATION, E.SERVICE, *DATA, E.INFRA_RESOURCE)

VIEWS: dict[str, View] = {
    view.name: view
    for view in (
        View(
            "company",
            (
                # No source describes the users yet: the row says so.
                Layer("users", ()),
                Layer("applications", (E.APPLICATION,), fallback=(E.REPOSITORY,)),
                Layer("services", (E.SERVICE,)),
                Layer("data", (E.DATABASE,)),
                Layer("infrastructure", (E.INFRA_RESOURCE,), boxed=True),
            ),
            (R.PART_OF, R.DEPENDS_ON, R.IN_NETWORK),
        ),
        View(
            "domains",
            (
                Layer("capabilities", (E.BUSINESS_CAPABILITY,)),
                Layer("processes", (E.BUSINESS_PROCESS,)),
                Layer("applications", (E.APPLICATION, E.SERVICE), tied=BUSINESS),
                Layer("data", DATA, tied=BUSINESS),
            ),
            (R.CHILD_OF, R.PART_OF, R.REALIZES, R.SUPPORTED_BY, R.USES),
        ),
        View(
            "applications",
            (
                Layer("applications", (E.APPLICATION,)),
                Layer("services", (E.SERVICE,)),
                Layer("code", (E.REPOSITORY,), tied=(E.APPLICATION, E.SERVICE)),
            ),
            (R.PART_OF, R.DEPENDS_ON),
        ),
        View(
            "services",
            (
                Layer("services", (E.SERVICE,)),
                Layer("data", (E.DATABASE,), tied=(E.SERVICE,)),
                Layer(
                    "infrastructure",
                    (E.INFRA_RESOURCE,),
                    tied=(E.SERVICE, E.DATABASE),
                    boxed=True,
                ),
            ),
            (R.DEPENDS_ON, R.PART_OF, R.IN_NETWORK),
        ),
        View(
            "data",
            (
                Layer("databases", (E.DATABASE,)),
                Layer("schemas", (E.SCHEMA,)),
                Layer("objects", (E.DATA_OBJECT,)),
            ),
            (R.PART_OF, R.REFERENCES, R.READS_FROM),
        ),
        View(
            "infrastructure",
            (
                Layer("accounts", (E.CLOUD_ACCOUNT, E.RESOURCE_GROUP)),
                Layer("resources", (E.INFRA_RESOURCE,)),
                Layer("databases", (E.DATABASE,)),
            ),
            (R.PART_OF, R.IN_NETWORK, R.DEPENDS_ON),
        ),
        View(
            "organisation",
            (
                Layer("teams", (E.TEAM,)),
                Layer("people", (E.PERSON,)),
            ),
            (R.CHILD_OF, R.MEMBER_OF, R.LED_BY, R.REPORTS_TO),
        ),
        View(
            "dependencies",
            (
                Layer("business", BUSINESS, tied=NEEDED),
                Layer("applications", (E.APPLICATION,), tied=NEEDED),
                Layer("services", (E.SERVICE,), tied=NEEDED),
                Layer("data", DATA, tied=NEEDED),
                Layer("infrastructure", (E.INFRA_RESOURCE,), tied=NEEDED),
            ),
            DEPENDENCY_LINKS,
        ),
    )
}

# Coverage's measures that do not apply to a kind.
NOT_OWNED = frozenset({E.PERSON, E.TEAM})
NOT_DOCUMENTED = frozenset({E.PERSON})
# What a box says under its name, the first of these its entity has.
DETAILS = ("engine", "resource_class", "title", "job_title", "environment")


@dataclass(frozen=True)
class Placed:
    """An entity of a layer, with what the view reads of it."""

    id: uuid.UUID
    type: str
    key: str
    name: str
    layer: str
    attributes: Mapping[str, object] = field(default_factory=dict)
    # The kinds of the sources that show it: github, pagerduty…
    kinds: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Tie:
    from_id: uuid.UUID
    to_id: uuid.UUID
    type: str


@dataclass
class Box:
    """One box of a view: an entity, or a provider's resources together."""

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
    deduced: bool = False


@dataclass(frozen=True)
class Line:
    from_id: str
    to_id: str
    type: str
    status: str | None


@dataclass(frozen=True)
class Coverage:
    """How well LEKA knows one kind: how many, and how many of them are
    owned, documented, corroborated, tied — none where it does not apply."""

    type: str
    total: int
    owned: int | None
    documented: int | None
    corroborated: int
    connected: int


WORST = {"incident": 3, "attention": 2, "operational": 1, "unmonitored": 0}


def state(thing: Placed, *, monitoring: frozenset[str], recently_hit: bool) -> str | None:
    """A thing's state, by the environment screen's rules — none for what
    has no state of its own (a repository, a team)."""
    return environment_status(_seen(thing), monitoring=monitoring, recently_hit=recently_hit)


def deduced(thing: Placed, *, monitoring: frozenset[str], recently_hit: bool) -> bool:
    """Whether that state is deduced — what runs a thing no tool watches
    (LEKA-369) — rather than a tool's word or its own."""
    return environment_status_deduced(
        _seen(thing), monitoring=monitoring, recently_hit=recently_hit
    )


def _seen(thing: Placed) -> EnvironmentThing:
    return EnvironmentThing(
        id=thing.id,
        type=thing.type,
        key=thing.key,
        name=thing.name,
        attributes=thing.attributes,
        # The model keeps enrichment's measures in the attributes.
        facts=thing.attributes,
        kinds=thing.kinds,
    )


def layout(
    view: View,
    placed: Iterable[Placed],
    ties: Iterable[Tie],
    statuses: Mapping[uuid.UUID, str | None],
    teams: Mapping[uuid.UUID, uuid.UUID],
    deduced: Mapping[uuid.UUID, bool] | None = None,
) -> tuple[list[Box], list[Line]]:
    """A view's boxes and the lines between them: a box per entity — the
    cloud resources of a boxed layer together per provider and region, in
    their worst state — and a line per relationship of the view between two
    boxes, coloured by the worse of its ends."""
    boxed = {layer.name for layer in view.layers if layer.boxed}
    boxes: dict[str, Box] = {}
    box_of: dict[uuid.UUID, str] = {}
    for thing in placed:
        status = statuses.get(thing.id)
        found = provider_of(_thing(thing)) if thing.layer in boxed else None
        if found is not None:
            provider, region = found
            key = f"provider:{provider}:{region or ''}"
            held = boxes.get(key)
            if held is None:
                held = boxes[key] = Box(
                    id=key,
                    type="provider",
                    layer=thing.layer,
                    name=provider,
                    status=status,
                    detail=region,
                    count=0,
                )
            held.count += 1
            if WORST.get(status or "", -1) > WORST.get(held.status or "", -1):
                held.status = status
            box_of[thing.id] = key
            continue
        environment = thing.attributes.get("environment")
        boxes[str(thing.id)] = Box(
            id=str(thing.id),
            type=thing.type,
            layer=thing.layer,
            name=thing.name,
            status=status,
            entity_id=thing.id,
            key=thing.key,
            detail=_detail(thing),
            environment=environment if isinstance(environment, str) else None,
            team_id=teams.get(thing.id),
            deduced=bool((deduced or {}).get(thing.id)),
        )
        box_of[thing.id] = str(thing.id)
    wanted = {kind.value for kind in view.links}
    lines: dict[tuple[str, str], Line] = {}
    for tie in ties:
        if tie.type not in wanted:
            continue
        a, b = box_of.get(tie.from_id), box_of.get(tie.to_id)
        if a is None or b is None or a == b or (b, a) in lines:
            continue
        worse = max((boxes[a].status, boxes[b].status), key=lambda s: WORST.get(s or "", -1))
        lines.setdefault((a, b), Line(a, b, tie.type, worse))
    return list(boxes.values()), list(lines.values())


def coverage(
    rows: Iterable[tuple[str, int, int, int, int, int]],
) -> list[Coverage]:
    """Each kind's coverage, from (type, total, owned, documented,
    corroborated, connected) — the measures that do not apply, none."""
    return [
        Coverage(
            type=kind,
            total=total,
            owned=None if kind in NOT_OWNED else owned,
            documented=None if kind in NOT_DOCUMENTED else documented,
            corroborated=corroborated,
            connected=connected,
        )
        for kind, total, owned, documented, corroborated, connected in rows
    ]


def _thing(thing: Placed) -> EnvironmentThing:
    return EnvironmentThing(
        id=thing.id, type=thing.type, key=thing.key, name=thing.name, attributes=thing.attributes
    )


def _detail(thing: Placed) -> str | None:
    for name in DETAILS:
        value = thing.attributes.get(name)
        if isinstance(value, str) and value:
            return value
    return None
