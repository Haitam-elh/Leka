"""The architecture view (LEKA-369): what the company runs, in columns.

    code        the repositories, by the platform that hosts them
    services    the applications and the services the company runs — an
                API, a web app, a worker, a proxy
    data        the stores its services keep data in: the databases its
                code names or a database source reads, its object stores
    cloud       the cloud resources, by provider: the machines, the cloud
                databases, the buckets, the networks
    external    the services outside it relies on — an e-mail provider, a
                payment provider — and the monitoring tools that watch it

Each thing is a CARD: its kind in one word (api, web, cache, instance,
bucket…), what it is written with, its state — deduced when nothing watches
it, and why — where it is reached, its team, its code, a few figures read
from the sources (a repository's commits and pull requests, a database's
tables and their size). Each relationship between two cards is a LINK
named by what it is, the words its evidence gives:

    source_code   a repository → the service it is the code of
    routes        a proxy → what it routes to
    calls         a front end → the API it is told of
    queue, cache, stores, files, email, uses, depends
                  a service → what its configuration says it relies on
    deployed_on   a service → the machine running it (enrichment's
                  public_address, deployed_together; a resource's tags; a
                  source's `deployed_to`)
    hosted_on     the code's store → the cloud's (only_instance,
                  named_for_repository, only_bucket)
    monitored_by  a service → the monitoring tool that shows it
    part_of       anything else part of a card

A repository that says what it is made of (its `modules`, read from its
tree) has a card for each — Leka/api, Leka/web, Leka/docs, Leka/deploy,
Leka/.github — linked to what the code says: the code of a service
(`source_code`), the configuration of a proxy or a store without code of
its own (`configures`), the workflow that deploys them (`deploys`).

Pure: things and relationships in, cards and links out; the service reads
(graph.py). docs/company-model.md § 16 says what each column holds.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from leka.knowledge.models import EntityType, RelationshipType

E = EntityType
R = RelationshipType

COLUMNS = ("code", "services", "data", "cloud", "external")
CLOUD_PROVIDERS = frozenset({"aws", "azure", "gcp"})
CODE_HOSTS = (("github.com/", "github"), ("gitlab.com/", "gitlab"), ("bitbucket.org/", "bitbucket"))
# What the architecture reads of the graph.
TYPES = (E.REPOSITORY, E.APPLICATION, E.SERVICE, E.DATABASE, E.INFRA_RESOURCE)
LINKS = (R.PART_OF, R.DEPENDS_ON, R.USES, R.DEPLOYED_TO)
# The roles a repository's configuration names (leka/connectors/components.py),
# as the evidence of a `depends_on` begins: "queue: deploy/….yml:12 — REDIS_URL".
CODE_ROLES = frozenset(
    {"routes", "calls", "queue", "cache", "stores", "files", "email", "uses", "depends"}
)
HOSTING_RULES = frozenset({"public_address", "deployed_together"})
SERVING_RULES = frozenset({"only_instance", "named_for_repository", "only_bucket"})
# The order links are named in when a card's to one column say several things.
ROLE_ORDER = (
    "source_code",
    "configures",
    "deploys",
    "routes",
    "calls",
    "deployed_on",
    "hosted_on",
    "stores",
    "queue",
    "cache",
    "files",
    "email",
    "uses",
    "depends",
    "monitored_by",
    "part_of",
)
# What is relied on — what "the most depended on" counts.
RELIED_ON = frozenset(
    {"calls", "queue", "cache", "stores", "files", "email", "uses", "depends", "deployed_on"}
)

# A column's cards, at most — the most connected first; a cloud provider's.
# The detailed map draws them all, up to its own bounds.
MAX_CARDS = 40
MAX_PER_PROVIDER = 8
MAX_CARDS_DETAILED = 200
MAX_PER_PROVIDER_DETAILED = 120
MAX_RANKED = 5
# A flow's steps, at most, and how far from where it starts.
MAX_STEPS = 24
MAX_HOPS = 4
# What a request or a job goes through: not what builds, hosts or holds it.
FLOWING = frozenset(
    {"routes", "calls", "queue", "cache", "stores", "files", "email", "uses", "depends"}
)

# The order a column reads in, top to bottom: what is reached first.
SERVICE_ORDER = ("proxy", "web", "api", "worker", "scheduler", "job")
STORE_ORDER = ("database", "cache", "queue", "search", "storage")
RESOURCE_ORDER = (
    "instance",
    "cluster",
    "function",
    "database",
    "bucket",
    "load_balancer",
    "network",
)

# A module's place among its repository's: the code first, then what
# serves it.
MODULE_ORDER = (
    "backend",
    "frontend",
    "code",
    "agents",
    "infrastructure",
    "ci",
    "docs",
    "scripts",
    "tests",
)
# What a card says of itself in detail, by type: the facts its sources give.
FACTS: dict[str, tuple[str, ...]] = {
    E.INFRA_RESOURCE: (
        "instance_type",
        "platform",
        "architecture",
        "zone",
        "public_ip",
        "public_dns",
        "private_ip",
        "runtime",
        "memory_mb",
        "timeout_s",
        "cidr",
        "default",
        "type",
        "scheme",
        "dns",
        "version",
        "account",
        "created_at",
    ),
    E.DATABASE: (
        "engine",
        "version",
        "instance_type",
        "storage_gb",
        "multi_az",
        "encrypted",
        "public",
        "endpoint",
        "host",
        "port",
        "database",
        "zone",
        "account",
    ),
    E.SERVICE: (
        "code_path",
        "image",
        "deployed_by",
        "deploy_method",
        "public_addresses",
        "ports",
        "vendor",
    ),
    E.REPOSITORY: ("default_branch", "visibility", "language", "code_files"),
}

WORST = {"incident": 3, "attention": 2, "operational": 1, "unmonitored": 0}
# An engine as people name it: RDS's `postgres`, the code's `postgresql`.
ENGINES = {
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "aurora-postgresql": "Aurora PostgreSQL",
    "aurora-mysql": "Aurora MySQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "sqlserver": "SQL Server",
    "oracle": "Oracle",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "valkey": "Valkey",
    "memcached": "Memcached",
    "rabbitmq": "RabbitMQ",
    "kafka": "Kafka",
    "elasticsearch": "Elasticsearch",
    "opensearch": "OpenSearch",
}


@dataclass(frozen=True)
class Thing:
    """An entity the architecture may show, with what it reads of it."""

    id: uuid.UUID
    type: str
    key: str
    name: str
    attributes: Mapping[str, object] = field(default_factory=dict)
    status: str | None = None
    deduced: bool = False
    # Why its state is deduced: its rule's evidence (enrichment's `architecture`).
    why: str | None = None
    kinds: frozenset[str] = frozenset()
    degree: int = 0


@dataclass(frozen=True)
class Edge:
    from_id: uuid.UUID
    to_id: uuid.UUID
    type: str
    origin: str
    rule: str
    confidence: float
    # The first evidence its records give, when stated.
    evidence: str | None = None


@dataclass
class Card:
    id: str
    column: str
    group: str
    kind: str
    type: str
    name: str
    entity_id: uuid.UUID | None = None
    key: str | None = None
    status: str | None = None
    deduced: bool = False
    why: str | None = None
    technology: list[str] = field(default_factory=list)
    description: str | None = None
    environment: str | None = None
    region: str | None = None
    url: str | None = None
    team_id: uuid.UUID | None = None
    repository_id: str | None = None
    # What runs it: the card its `deployed_on` or `hosted_on` reaches.
    host_id: str | None = None
    # How its last deployment went: succeeded, failed… (enrichment's).
    deployment: str | None = None
    stats: dict[str, int] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    # What its sources say of it in detail: an instance's type and zone, a
    # database's engine and storage — the facts FACTS names.
    facts: dict[str, object] = field(default_factory=dict)
    # A module's parts — Leka/api's connectors, ingestion, knowledge — and
    # a small one's files.
    parts: list[dict[str, object]] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    # Who maintains it, by their work (enrichment's `maintained_by`).
    maintainer_ids: list[uuid.UUID] = field(default_factory=list)
    order: tuple[int, int, str] = (0, 0, "")


@dataclass(frozen=True)
class Link:
    from_id: str
    to_id: str
    role: str
    origin: str
    confidence: float
    evidence: str | None
    status: str | None
    # What inferred it: enrichment's rule — public_address, only_instance…
    rule: str = "stated"


@dataclass(frozen=True)
class Bundle:
    """A card's links to one other column, together: what the map draws
    until a card is chosen — one arrow, named by what most of them are."""

    from_id: str
    column: str
    role: str
    roles: list[str]
    targets: list[str]


@dataclass
class Group:
    """A column's cards from one place: a code host, a cloud provider."""

    column: str
    id: str
    name: str
    regions: list[str] = field(default_factory=list)
    total: int = 0
    shown: int = 0


@dataclass(frozen=True)
class Flow:
    """What one entry — a proxy, a job — goes through, step by step: a
    request reaching a web app, its API, its queue and its database. The
    entries whose steps are the same go together."""

    entries: list[str]
    steps: list[Link]


@dataclass(frozen=True)
class Check:
    """What to confirm, as the detailed map lists it in orange: a state
    deduced, a link inferred, a thing with no team, no monitoring, no tie."""

    kind: str
    card_id: str
    other_id: str | None = None
    role: str | None = None
    rule: str | None = None
    confidence: float | None = None


@dataclass
class Architecture:
    cards: list[Card]
    links: list[Link]
    bundles: list[Bundle]
    groups: list[Group]
    totals: dict[str, int]
    health: dict[str, int]
    services: dict[str, int]
    # The most relied on: each, and how many rely on it.
    ranked: list[tuple[Card, int]]
    environments: list[str]
    flows: list[Flow] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)


def column(type_: str, key: str, attributes: Mapping[str, object]) -> str | None:
    """Which column a thing is in — none for what the view does not show."""
    if type_ == E.REPOSITORY:
        return "code"
    if type_ == E.APPLICATION:
        return "services"
    if type_ == E.SERVICE:
        return "external" if attributes.get("hosting") == "external" else "services"
    if type_ == E.DATABASE:
        cloud = attributes.get("provider") in CLOUD_PROVIDERS and "store_role" not in attributes
        return "cloud" if cloud else "data"
    if type_ == E.INFRA_RESOURCE:
        if key.startswith("code:"):
            return "data"  # the code's object store, not a resource read
        return "cloud"
    return None


def group(column_: str, key: str, attributes: Mapping[str, object]) -> str:
    """The place a card is from in its column: a code host, a provider."""
    if column_ == "code":
        return next((host for prefix, host in CODE_HOSTS if key.startswith(prefix)), "other")
    if column_ == "cloud":
        provider = attributes.get("provider")
        if isinstance(provider, str) and provider:
            return provider
        prefix = key.split(":", 1)[0]
        return prefix if prefix in CLOUD_PROVIDERS else "other"
    return column_


def kind(type_: str, key: str, attributes: Mapping[str, object]) -> str:
    """What a thing is, in one word the screen translates."""
    if type_ == E.SERVICE:
        return _text(attributes.get("service_type")) or "service"
    if type_ == E.DATABASE:
        if column(type_, key, attributes) == "cloud":
            return "database"
        return _text(attributes.get("store_role")) or "database"
    if type_ == E.INFRA_RESOURCE:
        if key.startswith("code:"):
            return "storage"
        return _text(attributes.get("resource_kind")) or "resource"
    return type_


def technology(type_: str, attributes: Mapping[str, object]) -> list[str]:
    """What a thing is written with or runs: a service's languages and
    frameworks, a database's engine, a machine's type."""
    said = _texts(attributes.get("technology")) or _texts(attributes.get("languages"))
    if said:
        return said
    engine = _text(attributes.get("engine"))
    version = _text(attributes.get("version"))
    if engine:
        named = ENGINES.get(engine.lower()) or next(
            (name for word, name in ENGINES.items() if engine.lower().startswith(word)), engine
        )
        return [f"{named} {version}" if version else named]
    if type_ == E.INFRA_RESOURCE:
        found = _text(attributes.get("instance_type")) or _text(attributes.get("runtime"))
        return [found] if found else []
    return []


def role(edge: Edge, things: Mapping[uuid.UUID, Thing]) -> tuple[uuid.UUID, uuid.UUID, str]:
    """A relationship as the view links it: its ends — the one that relies
    first — and what it is."""
    one, other = things[edge.from_id], things[edge.to_id]
    if edge.type == R.PART_OF:
        if one.type == E.REPOSITORY:
            return edge.from_id, edge.to_id, "source_code"
        if edge.rule in SERVING_RULES:
            return edge.from_id, edge.to_id, "hosted_on"
        if column(one.type, one.key, one.attributes) == "cloud" and other.type in (
            E.SERVICE,
            E.APPLICATION,
        ):
            # A resource tagged for a service: the service runs on it.
            return edge.to_id, edge.from_id, "deployed_on"
        return edge.from_id, edge.to_id, "part_of"
    if edge.type == R.DEPENDS_ON:
        if edge.rule in HOSTING_RULES:
            return edge.from_id, edge.to_id, "deployed_on"
        said = (edge.evidence or "").split(":", 1)[0].strip()
        return edge.from_id, edge.to_id, said if said in CODE_ROLES else "depends"
    if edge.type == R.DEPLOYED_TO:
        return edge.from_id, edge.to_id, "deployed_on"
    return edge.from_id, edge.to_id, "uses"


def build(
    things: Sequence[Thing],
    edges: Iterable[Edge],
    *,
    stats: Mapping[uuid.UUID, dict[str, int]],
    teams: Mapping[uuid.UUID, uuid.UUID],
    totals: Mapping[str, int],
    providers: Mapping[str, int],
    monitoring: frozenset[str],
    environment: str | None = None,
    maintainers: Mapping[uuid.UUID, list[uuid.UUID]] | None = None,
    detailed: bool = False,
) -> Architecture:
    """The cards, the links between them, the figures: from the things —
    the most connected first — what relates them, and how many of each
    there are in all."""
    environments = sorted(
        {e for thing in things for e in _environments(thing.attributes)},
        key=lambda e: (e != "production", e),
    )
    shown = [
        thing
        for thing in things
        if column(thing.type, thing.key, thing.attributes) is not None
        and (environment is None or _in(thing.attributes, environment))
    ]
    by_id = {thing.id: thing for thing in shown}
    cards: dict[str, Card] = {}
    for thing in shown:
        card = _card(thing, stats.get(thing.id, {}), teams.get(thing.id))
        card.maintainer_ids = list((maintainers or {}).get(thing.id, []))
        cards[card.id] = card

    links: dict[tuple[str, str, str], Link] = {}
    for edge in edges:
        if edge.from_id not in by_id or edge.to_id not in by_id:
            continue
        a, b, named = role(edge, by_id)
        key = (str(a), str(b), named)
        if a == b or key in links:
            continue
        worse = max(
            (cards[str(a)].status, cards[str(b)].status), key=lambda s: WORST.get(s or "", -1)
        )
        links[key] = Link(
            str(a), str(b), named, edge.origin, edge.confidence, edge.evidence, worse, edge.rule
        )
    for link in links.values():
        if link.role == "source_code":
            cards[link.to_id].repository_id = cards[link.to_id].repository_id or link.from_id
        elif link.role in ("deployed_on", "hosted_on"):
            cards[link.from_id].host_id = cards[link.from_id].host_id or link.to_id

    # What each repository is made of: a card a module, linked as its code says.
    laid_out: set[str] = set()
    for thing in shown:
        if thing.type != E.REPOSITORY or not isinstance(thing.attributes.get("modules"), list):
            continue
        for module in _modules(thing, cards[str(thing.id)]):
            cards[module.id] = module
            laid_out.add(str(thing.id))
            for link in _module_links(module, thing, by_id, cards):
                links.setdefault((link.from_id, link.to_id, link.role), link)

    # The monitoring tools that show a service: a card each, outside.
    for thing in shown:
        if thing.type != E.SERVICE or column(thing.type, thing.key, thing.attributes) != "services":
            continue
        for tool in sorted(thing.kinds & monitoring):
            tool_id = f"tool:{tool}"
            cards.setdefault(
                tool_id,
                Card(
                    id=tool_id,
                    column="external",
                    group="external",
                    kind="monitoring",
                    type="tool",
                    name=tool,
                    sources=[tool],
                ),
            )
            link_key = (str(thing.id), tool_id, "monitored_by")
            links.setdefault(
                link_key, Link(str(thing.id), tool_id, "monitored_by", "stated", 1.0, None, None)
            )

    kept, groups = _kept(
        cards.values(),
        links.values(),
        providers,
        most=MAX_CARDS_DETAILED if detailed else MAX_CARDS,
        per_provider=MAX_PER_PROVIDER_DETAILED if detailed else MAX_PER_PROVIDER,
    )
    drawn = [link for link in links.values() if link.from_id in kept and link.to_id in kept]
    # A repository laid out speaks through its modules: no arrow of its own.
    bundles = _bundles([link for link in drawn if link.from_id not in laid_out], kept)
    services = Counter(
        card.status or "unmonitored"
        for card in cards.values()
        if card.type == E.SERVICE and card.column == "services"
    )
    health = Counter(
        card.status
        for card in cards.values()
        if card.column in ("services", "data", "cloud") and card.status
    )
    relied = Counter(link.to_id for link in links.values() if link.role in RELIED_ON)
    ranked = [(cards[card_id], count) for card_id, count in relied.most_common(MAX_RANKED)]
    return Architecture(
        # Column by column, each in the order it was chosen in.
        cards=list(kept.values()),
        links=drawn,
        bundles=bundles,
        groups=groups,
        totals=dict(totals),
        health={s: health.get(s, 0) for s in ("operational", "attention", "incident")}
        | {"unmonitored": health.get("unmonitored", 0)},
        services={s: services.get(s, 0) for s in WORST},
        ranked=ranked,
        environments=environments,
        flows=flows(kept, drawn) if detailed else [],
        checks=checks(kept, drawn) if detailed else [],
    )


def flows(cards: Mapping[str, Card], links: Iterable[Link]) -> list[Flow]:
    """What each entry goes through: from a service nothing routes to or
    calls — a proxy, a worker, a job — every step a request or a job takes,
    MAX_HOPS away at most, in the order they are reached."""
    out: dict[str, list[Link]] = {}
    reached: set[str] = set()
    for link in links:
        if link.role in FLOWING:
            out.setdefault(link.from_id, []).append(link)
            if link.role in ("routes", "calls"):
                reached.add(link.to_id)
    entries = [
        card
        for card in cards.values()
        if card.column == "services" and card.id in out and card.id not in reached
    ]
    found: list[Flow] = []
    alike: dict[tuple[tuple[str, str], ...], int] = {}
    for entry in sorted(entries, key=lambda c: c.order):
        steps: list[Link] = []
        seen = {entry.id}
        frontier = [entry.id]
        for _ in range(MAX_HOPS):
            following: list[str] = []
            for at in frontier:
                for link in sorted(out.get(at, []), key=lambda li: _step_order(li, cards)):
                    if len(steps) >= MAX_STEPS:
                        break
                    steps.append(link)
                    if link.to_id not in seen:
                        seen.add(link.to_id)
                        following.append(link.to_id)
            frontier = following
        signature = tuple(sorted((li.role, li.to_id) for li in steps if li.from_id == entry.id))
        if len(steps) == len([li for li in steps if li.from_id == entry.id]) and signature in alike:
            # A worker and a scheduler doing the same: one flow, both entries.
            index = alike[signature]
            found[index] = Flow([*found[index].entries, entry.id], found[index].steps)
            continue
        alike[signature] = len(found)
        found.append(Flow([entry.id], steps))
    return found


def _step_order(link: Link, cards: Mapping[str, Card]) -> tuple[int, tuple[int, int, str]]:
    """Steps in the order things are reached: by what the step is, then
    where its target reads in its column."""
    target = cards.get(link.to_id)
    return _rank(link.role), target.order if target else (0, 0, link.to_id)


# How much each check weighs: what is wrong first, what is unsure next.
CHECK_ORDER = ("incident", "attention", "deduced", "inferred", "unmonitored", "no_team", "unlinked")


def checks(cards: Mapping[str, Card], links: Iterable[Link]) -> list[Check]:
    """What to confirm: what is wrong, what LEKA deduced or inferred rather
    than read, what has no team, no monitoring, no tie to anything."""
    found: list[Check] = []
    tied: set[str] = set()
    for link in links:
        tied |= {link.from_id, link.to_id}
        if link.origin == "inferred":
            found.append(
                Check("inferred", link.from_id, link.to_id, link.role, link.rule, link.confidence)
            )
    for card in cards.values():
        if card.type in ("module", "tool"):
            continue
        if card.status in ("incident", "attention"):
            found.append(Check(card.status, card.id))
        if card.deduced:
            found.append(Check("deduced", card.id, card.host_id))
        elif card.status == "unmonitored" and card.column == "services":
            found.append(Check("unmonitored", card.id))
        if card.column in ("services", "data") and card.team_id is None:
            found.append(Check("no_team", card.id))
        if card.id not in tied:
            found.append(Check("unlinked", card.id))
    return sorted(
        found,
        key=lambda c: (
            CHECK_ORDER.index(c.kind),
            cards[c.card_id].order if c.card_id in cards else (0, 0, ""),
        ),
    )


def _card(thing: Thing, stats: dict[str, int], team: uuid.UUID | None) -> Card:
    attributes = thing.attributes
    where = column(thing.type, thing.key, attributes) or "services"
    what = kind(thing.type, thing.key, attributes)
    order = (
        SERVICE_ORDER
        if where in ("services", "external")
        else STORE_ORDER
        if where == "data"
        else RESOURCE_ORDER
        if where == "cloud"
        else ()
    )
    rank = order.index(what) if what in order else len(order)
    return Card(
        id=str(thing.id),
        column=where,
        group=group(where, thing.key, attributes),
        kind=what,
        type=thing.type,
        name=thing.name,
        entity_id=thing.id,
        key=thing.key,
        status=thing.status,
        deduced=thing.deduced,
        why=thing.why if thing.deduced else None,
        technology=technology(thing.type, attributes),
        description=_text(attributes.get("description")),
        environment=next(iter(_environments(attributes)), None),
        region=_text(attributes.get("region")),
        url=_text(attributes.get("public_url")) or _text(attributes.get("url")) or _site(thing),
        team_id=team,
        stats=stats,
        deployment=_text(attributes.get("last_deployment")),
        facts=_facts(thing.type, attributes),
        # Each file and line once, though several records say it.
        evidence=list(dict.fromkeys(_texts(attributes.get("evidence")))),
        sources=sorted(thing.kinds),
        # A service first in what reaches it — the proxy, the front end —
        # then the most connected; the code's first among the services.
        order=(rank, -thing.degree, thing.name.lower()),
    )


def _modules(repository: Thing, card: Card) -> list[Card]:
    """A repository's modules, as cards of its column, under it."""
    short = repository.name.rsplit("/", 1)[-1]
    branch = _text(repository.attributes.get("default_branch"))
    found: list[Card] = []
    for module in _dicts(repository.attributes.get("modules")):
        if not isinstance(module, dict) or not _text(module.get("path")):
            continue
        path = str(module["path"])
        what = _module_kind(module)
        rank = MODULE_ORDER.index(what) if what in MODULE_ORDER else len(MODULE_ORDER)
        parts = _dicts(module.get("parts"))
        files = module.get("files")
        found.append(
            Card(
                id=f"module:{repository.id}:{path}",
                column="code",
                group=card.group,
                kind=what,
                type="module",
                name=f"{short}/{path}",
                key=f"{repository.key}/{path}",
                technology=_texts(module.get("languages")),
                url=f"{card.url}/tree/{branch}/{path}" if card.url and branch else card.url,
                repository_id=card.id,
                stats={"files": files} if isinstance(files, int) else {},
                sources=card.sources,
                parts=parts,
                files=_texts(module.get("names")),
                order=(card.order[0], card.order[1], f"{card.order[2]}\x01{rank:02d}{path}"),
            )
        )
    return found


def _module_kind(module: Mapping[str, object]) -> str:
    """What a module is: the code of a back end or of a front end, else
    what its folder is — docs, infrastructure, CI, agents, scripts."""
    role = _text(module.get("role")) or "code"
    if role != "service":
        return role
    serves = {_text(s.get("role")) for s in _dicts(module.get("services"))}
    return "frontend" if serves and serves <= {"web"} else "backend"


def _module_links(
    module: Card, repository: Thing, things: Mapping[uuid.UUID, Thing], cards: Mapping[str, Card]
) -> list[Link]:
    """What a module is to the rest, as the code says: the code of the
    services built from it, the configuration of what has no code of its
    own, the workflow that deploys them."""
    path = module.name.split("/", 1)[1]
    inside = f"{path}/"
    found: list[Link] = []
    for thing in things.values():
        card = cards.get(str(thing.id))
        if card is None or card.column not in ("services", "data"):
            continue
        attributes = thing.attributes
        if _text(attributes.get("repository_url")) and not _same_repository(attributes, repository):
            continue
        code = _text(attributes.get("code_path"))
        role = None
        evidence = None
        if (
            module.kind in ("backend", "frontend")
            and code
            and (code == path or code.startswith(inside))
        ):
            role, evidence = "source_code", f"code: {code}"
        elif module.kind == "infrastructure" and not code:
            said = next(
                (e for e in _texts(attributes.get("evidence")) if e.startswith(inside)), None
            )
            if said:
                role, evidence = "configures", said
        elif module.kind == "ci":
            deployed = _text(attributes.get("deployed_by"))
            if deployed and deployed.startswith(inside):
                role, evidence = "deploys", deployed
        if role:
            found.append(Link(module.id, card.id, role, "stated", 1.0, evidence, card.status))
    return found


def _dicts(value: object) -> list[dict[str, object]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _same_repository(attributes: Mapping[str, object], repository: Thing) -> bool:
    url = str(attributes.get("repository_url") or "").lower().rstrip("/")
    return url.endswith("/" + repository.key.split("/", 1)[-1])


def _facts(type_: str, attributes: Mapping[str, object]) -> dict[str, object]:
    """What a card's sources say of it in detail, by FACTS."""
    found: dict[str, object] = {}
    for name in FACTS.get(type_, ()):
        value = attributes.get(name)
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v) or None
        if isinstance(value, (str, int, float, bool)) and value != "":
            found[name] = value
    return found


def _site(thing: Thing) -> str | None:
    """Where a repository is kept: its key is its address."""
    if thing.type == E.REPOSITORY and any(thing.key.startswith(p) for p, _ in CODE_HOSTS):
        return f"https://{thing.key}"
    return None


def _kept(
    cards: Iterable[Card],
    links: Iterable[Link],
    providers: Mapping[str, int],
    *,
    most: int = MAX_CARDS,
    per_provider: int = MAX_PER_PROVIDER,
) -> tuple[dict[str, Card], list[Group]]:
    """The cards each column shows, and its groups: MAX_CARDS a column, a
    cloud provider's MAX_PER_PROVIDER — what a link ties to the rest first."""
    tied = Counter[str]()
    for link in links:
        tied[link.from_id] += 1
        tied[link.to_id] += 1
    by_group: dict[tuple[str, str], list[Card]] = {}
    for card in cards:
        by_group.setdefault((card.column, card.group), []).append(card)
    kept: dict[str, Card] = {}
    groups: list[Group] = []
    per_column = Counter[str]()
    for (where, name), members in sorted(
        by_group.items(), key=lambda item: (COLUMNS.index(item[0][0]), item[0][1])
    ):
        if where == "cloud":
            members.sort(key=lambda c: (not tied[c.id], c.order))
            room = per_provider
        else:
            members.sort(key=lambda c: c.order)
            room = most
        room = min(room, most - per_column[where])
        chosen = members[: max(room, 0)]
        per_column[where] += len(chosen)
        kept |= {card.id: card for card in chosen}
        regions = sorted({c.region for c in members if c.region})
        # A code host counts its repositories: their modules are theirs.
        own = [c for c in members if c.type != "module"]
        groups.append(
            Group(
                column=where,
                id=f"{where}:{name}",
                name=name,
                regions=regions,
                total=providers.get(name, len(members)) if where == "cloud" else len(own),
                shown=len([c for c in chosen if c.type != "module"]),
            )
        )
    return kept, groups


def _bundles(links: Iterable[Link], cards: Mapping[str, Card]) -> list[Bundle]:
    """Each card's links to every other column, together."""
    together: dict[tuple[str, str], list[Link]] = {}
    for link in links:
        target = cards[link.to_id].column
        if cards[link.from_id].column != target:
            together.setdefault((link.from_id, target), []).append(link)
    found: list[Bundle] = []
    for (from_id, target), members in together.items():
        said = Counter(link.role for link in members)
        roles = sorted(said, key=lambda r: (-said[r], _rank(r)))
        found.append(
            Bundle(
                from_id=from_id,
                column=target,
                role=roles[0],
                roles=sorted(said, key=_rank),
                targets=sorted({link.to_id for link in members}, key=lambda c: cards[c].order),
            )
        )
    return sorted(found, key=lambda b: (cards[b.from_id].order, COLUMNS.index(b.column)))


def _rank(role_: str) -> int:
    return ROLE_ORDER.index(role_) if role_ in ROLE_ORDER else len(ROLE_ORDER)


def _environments(attributes: Mapping[str, object]) -> list[str]:
    own = _text(attributes.get("environment"))
    return [own] if own else _texts(attributes.get("environments"))


def _in(attributes: Mapping[str, object], environment: str) -> bool:
    """Whether a thing is in an environment — or says none: shared."""
    said = _environments(attributes)
    return not said or environment in said or environment in _texts(attributes.get("environments"))


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _texts(value: object) -> list[str]:
    return [str(v) for v in value if v] if isinstance(value, list) else []
