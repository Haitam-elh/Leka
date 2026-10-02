"""Data enrichment (LEKA-359): what a workspace's resolved entities are to
one another, and what follows from it — each addition with how sure and why.

Entity resolution says what is ONE thing (LEKA-357). This adds, before the
company model reads them, what those things are together:

    1. RELATIONSHIPS, stated: what normalisation read between keys — a
       container, an author, "Fixes PAY-42" — between entities. A GitHub
       pull request resolving a Jira issue is an edge between two tools'
       things: cross-source.
    2. LINKS, inferred: a repository and the service of its name; a Jira
       component or a label naming a service; a service named in a title.
    3. OWNERSHIP: the team an item's container belongs to, inherited; the
       people who maintain a repository, a project, a service.
    4. MEMBERSHIP: the team a person works with, by their work.
    5. ACTIVITY: last activity, activity over 90 days, a lifecycle; a cycle
       time, staleness; an incident's duration; a service's incidents and
       their mean time to resolve.
    6. CATEGORY: the kind of work a title says, where parsing found none.
    7. LANDSCAPE: where a service or an application runs, and how critical
       it is, where no catalogue says — what its parts show (LEKA-362).
    8. INFRASTRUCTURE: the account a cloud resource's source reads it in,
       where its own record names none; the environment its cluster, its
       resource group or its account runs in, where its own tags say none
       (LEKA-363) — and a database's and a schema's, from the instance
       that serves it (LEKA-364). Run before ownership and the landscape,
       which read what it adds.
    9. DATA: what a schema, a database, the instance serving it hold — the
       kinds of data and how sensitive, from their tables (LEKA-364).
   10. EXPERTISE: what each person's work shows they know — the
       repositories, projects and services they work on, how much, in which
       roles, how lately, and the languages of that code — each with its
       evidence; and who is a bot (LEKA-365). The spaces they write in, and
       what their documents describe (LEKA-366).
   11. KNOWLEDGE: where a document or a space opens, how fresh a document
       is; whose a space is and what it documents, by its name; the
       documents a catalogue links as a thing's documentation; the data a
       business system names, found (LEKA-366). Run before ownership, which
       hands a space's team down to its documents.

ADDED, NEVER OVERWRITTEN. Nothing here changes a resolved entity: what is
enriched is kept beside it — each attribute and each relationship with its
rule, its confidence, its evidence and what it was made from. An attribute
a source states is never enriched; an edge a source states is never
replaced by an inferred one.

ISOLATED. Each enricher runs on its own: one that fails is recorded, and
what it made is dropped — the others go on with what exists. What an
enricher makes is checked before it is kept (entities that exist, a
confidence from 0 to 1, a value that is JSON); what fails the check is dropped
and counted.

Local rules, no model, no paid service. Pure: a snapshot in, an Enrichment
out; the job reads and writes. Rules: docs/enrichment.md.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import unquote

from leka.ingestion.resolution import signals as sig

# 2: where services and applications run, how critical they are; an
#    application's team inherited by its services (LEKA-362).
# 3: a resource's account, and its container's environment; a team
#    inherited through an account less surely than through a service
#    (LEKA-363).
# 4: a database's and a schema's environment, from what serves them; what
#    data each holds, from its tables (LEKA-364).
# 5: what each person's work shows they know; who is a bot (LEKA-365).
# 6: documentation and business knowledge — a document describes what its
#    title names; spaces are containers, named for their team or service;
#    documents' links and freshness; a catalogue's documentation found by
#    its address; a business system's data found by name (LEKA-366).
ENRICHER_VERSION = 6

Origin = Literal["stated", "inferred"]

# The records an edge keeps as the evidence of who stated it: the first few.
MAX_PROVENANCE = 5
# Below this, an inference says too little to be kept.
MIN_CONFIDENCE = 0.5
# An owner inherited through a container is a little less sure at each step.
INHERITED = 0.9
MAX_HOPS = 3
# A person's work on an item, by the relationship that says it.
WORK = {
    "authored_by": 1.0,
    "assigned_to": 1.0,
    "led_by": 1.0,
    "committed_by": 0.5,
    "reviewed_by": 0.5,
    "created_by": 0.3,
    "reported_by": 0.3,
    # Who last changed a document (LEKA-366).
    "edited_by": 0.5,
}
UP = frozenset({"part_of", "child_of"})
# What holds items; a space holds documents (LEKA-366).
CONTAINERS = frozenset({"repository", "project", "service", "application", "knowledge_space"})
# What names a service in its title.
TITLED = frozenset({"issue", "pull_request", "incident", "document"})
# What a title says the kind of work of.
WORK_ITEMS = frozenset({"issue", "pull_request", "commit"})
OPEN = frozenset({"open", "in_progress"})
CLOSED = frozenset({"closed", "merged"})

RECENT = timedelta(days=90)
MAINTAINED = timedelta(days=180)
ACTIVE = timedelta(days=30)
QUIET = timedelta(days=180)
STALE = timedelta(days=30)
# A date further ahead than this is a wrong date, not activity.
AHEAD = timedelta(days=1)

# A service's name core, to be matched: at least this long; in a title, longer.
MIN_CORE = 4
MIN_TITLE_CORE = 5
# A core named in more titles than this is a word, not a service.
TITLE_CROWD = 20
TITLE_SHARE = 0.2
# Maintainers: the three most active, each with a share of the work and a
# few items of their own.
MAINTAINERS = 3
MIN_SHARE = 0.2
MIN_ITEMS = 2
# Membership: enough items belonging to teams, most of them to one.
MIN_TEAM_ITEMS = 3
MIN_TEAM_SHARE = 0.6

ATTRIBUTE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
EDGE_TYPE = re.compile(r"^[a-z][a-z_]{0,49}$")

# The words of a title that say what kind of work it is — English and
# French. Parsing's own categories come first (a vendor type, a label, a
# Conventional Commits title); these only where it found none.
TITLE_WORDS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "security",
        frozenset(
            {"security", "vulnerability", "vulnerabilities", "cve", "xss", "csrf", "securite"}
        ),
    ),
    (
        "bug",
        frozenset(
            {
                "fix",
                "fixes",
                "fixed",
                "fixing",
                "bug",
                "bugs",
                "crash",
                "crashes",
                "error",
                "errors",
                "broken",
                "fail",
                "fails",
                "failing",
                "failure",
                "regression",
                "hotfix",
                "bogue",
                "erreur",
                "erreurs",
                "plantage",
                "panne",
                "corrige",
                "corriger",
                "correction",
            }
        ),
    ),
    (
        "feature",
        frozenset(
            {
                "add",
                "adds",
                "adding",
                "support",
                "implement",
                "implements",
                "introduce",
                "introduces",
                "feature",
                "ajout",
                "ajoute",
                "ajouter",
                "nouvelle",
                "nouveau",
            }
        ),
    ),
    ("docs", frozenset({"doc", "docs", "documentation", "readme"})),
    (
        "maintenance",
        frozenset(
            {
                "refactor",
                "refactoring",
                "bump",
                "upgrade",
                "cleanup",
                "chore",
                "deps",
                "dependency",
                "dependencies",
                "migrate",
                "rename",
                "lint",
                "deprecate",
                "refonte",
                "nettoyage",
            }
        ),
    ),
)
TITLE_CONFIDENCE = 0.6
# The landscape (LEKA-362): services first — an application reads theirs.
LANDSCAPE = ("service", "application")
# LEKA's scales, in order: the most critical first; environments as
# normalisation's canonical names.
LEVELS = ("critical", "high", "medium", "low")
ENVIRONMENT_ORDER = ("production", "staging", "development", "test")
# A part's criticality, said of its whole: at most this sure.
FROM_PARTS = 0.8
# Infrastructure (LEKA-363): what resources are in, and what is placed in it.
SCOPES = frozenset({"cloud_account", "resource_group"})
PLACED = frozenset({"infra_resource", "database", "resource_group", "schema"})
# Where an environment is inherited from, the nearest first: a schema's
# database, a database's instance (LEKA-364), a node's cluster, a
# resource's group, its account.
CONTAINER_ORDER = ("database", "cluster", "resource_group", "cloud_account")
# Data (LEKA-364): how sensitive, the most first; what holds data, and what
# a part of it can be.
DATA_LEVELS = ("restricted", "confidential", "internal", "public")
DATA_HOLDERS = frozenset({"data_object", "schema", "database"})
# Expertise (LEKA-365): what work shows someone knows — where it is done,
# how much of it is enough to say so, how many areas a person shows.
AREAS = frozenset({"repository", "project", "service", "knowledge_space"})
MIN_AREA_ITEMS = 2
MAX_AREAS = 10
MAX_LANGUAGES = 3
# The words of a role, as expertise says them.
ROLE_WORDS = {
    "authored_by": "authored",
    "assigned_to": "assigned",
    "led_by": "led",
    "committed_by": "committed",
    "reviewed_by": "reviewed",
    "created_by": "created",
    "reported_by": "reported",
    "edited_by": "edited",
}
# What a container says of what it holds — its environment — said a little
# less surely; and the account a source reads a resource in.
FROM_CONTAINER = 0.9
SOURCE_ACCOUNT = 0.9
# A team inherited through an account or a resource group: less sure than
# through a service — billing groups resources, a service says whose they are.
SCOPE_OWNERSHIP = 0.8
# Knowledge (LEKA-366): a document changed within FRESH is fresh, within
# AGING aging, else stale — the web's own three words.
FRESH = timedelta(days=90)
AGING = timedelta(days=365)
KNOWLEDGE = frozenset({"document", "knowledge_space"})
BUSINESS = frozenset({"business_capability", "business_process"})
# What a title names, by its kind's words, and in what titles: a service in
# any; an application, a capability, a process in a document's — which
# describes it.
TITLE_NAMED: tuple[tuple[str, frozenset[str], frozenset[str]], ...] = (
    ("service", sig.SERVICE_WORDS, TITLED),
    ("application", sig.APPLICATION_WORDS, frozenset({"document"})),
    ("business_capability", frozenset(), frozenset({"document"})),
    ("business_process", frozenset(), frozenset({"document"})),
)
# A space's name, its documentation words aside: "Billing API docs".
DOC_WORDS = frozenset(
    {"doc", "docs", "documentation", "wiki", "space", "knowledge", "kb", "handbook", "runbook"}
)
SPACE_NAMED = 0.7
# A catalogue's documentation link, found at a document's address.
LINKED = 0.95
# The data a business system names: `schema.table`, or a table's name alone
# when only one table has it.
NAMED_QUALIFIED = 0.9
NAMED_ALONE = 0.75


# ── what it reads ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Node:
    """A resolved entity, as enrichment reads it."""

    id: uuid.UUID
    type: str
    key: str
    name: str
    attributes: dict[str, object]
    # Every source that shows it: by its own records, or naming it.
    sources: frozenset[uuid.UUID] = frozenset()
    # Its dates — created_at, updated_at, merged_at… — as its own records
    # give them: resolution keeps none (they are provenance, not chosen
    # between). The earliest creation, the latest of every other.
    dates: dict[str, str] = field(default_factory=dict)
    # Where its records open it — resolution keeps no link either: a few,
    # the first found first — and the kinds of tools they come from
    # (LEKA-366).
    links: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class Stated:
    """A relationship as one normalised record states it — between keys."""

    type: str
    from_key: str
    to_key: str
    source_id: uuid.UUID
    record_id: uuid.UUID
    confidence: float
    evidence: str


@dataclass
class Snapshot:
    """A workspace, as its last resolution run left it."""

    nodes: dict[uuid.UUID, Node]
    # Every key an entity goes by → the entities that go by it: one, or
    # several when the key is ambiguous.
    holders: dict[str, set[uuid.UUID]]
    stated: list[Stated]
    now: datetime


# ── what it makes ────────────────────────────────────────────────────────────


@dataclass
class Edge:
    """A relationship between two resolved entities."""

    from_id: uuid.UUID
    to_id: uuid.UUID
    type: str
    origin: Origin
    rule: str
    confidence: float
    evidence: str
    # Stated: {source_id, record_id, evidence} of the first records stating
    # it. Inferred: {entity_id} of what it was inferred from beyond its ends.
    provenance: list[dict[str, str]] = field(default_factory=list)
    # The sources that state it; none for an inferred edge.
    sources: set[uuid.UUID] = field(default_factory=set)
    # Its two ends are shown by different sources: two tools' things joined.
    cross_source: bool = False


@dataclass(frozen=True)
class Fact:
    """An attribute enrichment adds to an entity."""

    entity_id: uuid.UUID
    attribute: str
    value: object
    confidence: float
    rule: str
    evidence: str
    # The keys of what it was made from.
    inputs: tuple[str, ...] = ()


@dataclass
class Made:
    """What one enricher made."""

    edges: list[Edge] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)


@dataclass
class Enrichment:
    edges: list[Edge]
    facts: list[Fact]
    counts: dict[str, int]
    # {enricher, error}: the enrichers that failed, and the error's type.
    failures: list[dict[str, str]]


class Graph:
    """The snapshot, and what the enrichers before have made — to read."""

    def __init__(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self.nodes = snapshot.nodes
        self.now = snapshot.now
        self.edges: dict[tuple[uuid.UUID, uuid.UUID, str], Edge] = {}
        self.facts: dict[tuple[uuid.UUID, str], Fact] = {}
        self._out: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, str]]] = defaultdict(list)
        self._in: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, str]]] = defaultdict(list)

    def add(self, edge: Edge) -> bool:
        """Keep an edge — unless one is already kept: a stated edge is never
        replaced, an inferred one only by a surer one."""
        key = (edge.from_id, edge.to_id, edge.type)
        held = self.edges.get(key)
        if held is not None:
            if held.origin == "stated" or edge.confidence <= held.confidence:
                return False
        else:
            self._out[edge.from_id].append(key)
            self._in[edge.to_id].append(key)
        self.edges[key] = edge
        return True

    def out(self, node_id: uuid.UUID, types: Iterable[str]) -> list[Edge]:
        wanted = set(types)
        return [self.edges[k] for k in self._out.get(node_id, ()) if k[2] in wanted]

    def into(self, node_id: uuid.UUID, types: Iterable[str]) -> list[Edge]:
        wanted = set(types)
        return [self.edges[k] for k in self._in.get(node_id, ()) if k[2] in wanted]

    def targets(self, node_id: uuid.UUID) -> set[uuid.UUID]:
        """What a node has an edge to, of any type."""
        return {k[1] for k in self._out.get(node_id, ())}

    def of_type(self, node_id: uuid.UUID) -> str:
        node = self.nodes.get(node_id)
        return node.type if node else ""


# ── 1. relationships, stated ─────────────────────────────────────────────────


def relationships(graph: Graph) -> Made:
    """What normalisation stated between keys, between the entities those
    keys are. A key no entity goes by (a ticket in a tool not connected, a
    quarantined record) or several do (an ambiguous ticket key) joins
    nothing: counted, not guessed."""
    made = Made()
    holders = graph.snapshot.holders
    grouped: dict[tuple[uuid.UUID, uuid.UUID, str], Edge] = {}
    fields: dict[tuple[uuid.UUID, uuid.UUID, str], set[str]] = defaultdict(set)
    for stated in graph.snapshot.stated:
        froms = holders.get(stated.from_key, set())
        tos = holders.get(stated.to_key, set())
        if not froms or not tos:
            made.counts["unresolved"] += 1
            continue
        if len(froms) > 1 or len(tos) > 1:
            made.counts["ambiguous"] += 1
            continue
        (from_id,), (to_id,) = froms, tos
        if from_id == to_id:
            # Two keys of one thing: resolution's merge, not a relationship.
            made.counts["within"] += 1
            continue
        key = (from_id, to_id, stated.type)
        edge = grouped.get(key)
        if edge is None:
            edge = grouped[key] = Edge(
                from_id, to_id, stated.type, "stated", "stated", stated.confidence, ""
            )
        edge.confidence = max(edge.confidence, stated.confidence)
        edge.sources.add(stated.source_id)
        fields[key].add(stated.evidence or "record")
        if len(edge.provenance) < MAX_PROVENANCE:
            edge.provenance.append(
                {
                    "source_id": str(stated.source_id),
                    "record_id": str(stated.record_id),
                    "evidence": stated.evidence,
                }
            )
    for key, edge in grouped.items():
        edge.evidence = "stated by its source, read in: " + ", ".join(sorted(fields[key]))
    made.edges = list(grouped.values())
    return made


# ── 2. links, inferred ───────────────────────────────────────────────────────


def links(graph: Graph) -> Made:
    """What names a service without saying so: a repository called as it
    is, a Jira component or a label, a title."""
    made = Made()
    services = _service_cores(graph)

    def service_named(name: str) -> tuple[uuid.UUID, str] | None:
        core, environment = sig.core(name, sig.SERVICE_WORDS)
        if environment or len(core.replace("-", "")) < MIN_CORE:
            return None
        found = services.get(core, set())
        return (next(iter(found)), core) if len(found) == 1 else None

    def has_service(node_id: uuid.UUID, types: Iterable[str]) -> set[uuid.UUID]:
        return {e.to_id for e in graph.out(node_id, types) if graph.of_type(e.to_id) == "service"}

    linked: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for node in graph.nodes.values():
        if node.type == "repository" and not has_service(node.id, {"part_of"}):
            found = service_named(node.name.rsplit("/", 1)[-1])
            if found:
                service_id, core = found
                made.edges.append(
                    _inferred(
                        node.id,
                        service_id,
                        "part_of",
                        "same_name",
                        0.8,
                        f"the repository and the service have one name: {core}",
                    )
                )
                linked.add((node.id, service_id))
                made.counts["same_name"] += 1
        elif node.type in TITLED and not has_service(node.id, {"part_of"}):
            for rule, attribute, confidence in (
                ("component", "components", 0.85),
                ("label", "labels", 0.7),
            ):
                values = node.attributes.get(attribute)
                named = {
                    found
                    for value in (values if isinstance(values, list) else [])
                    if isinstance(value, str) and (found := service_named(value))
                }
                for service_id, core in sorted(named, key=lambda f: f[1]):
                    made.edges.append(
                        _inferred(
                            node.id,
                            service_id,
                            "part_of",
                            rule,
                            confidence,
                            f"its {rule} names the service {core}",
                        )
                    )
                    linked.add((node.id, service_id))
                    made.counts[rule] += 1
                if named:
                    break

    # A service named in a title: a word of the title, or a few in a row —
    # mentioned. In a document's title, an application, a business
    # capability or process too: what the document describes (LEKA-366).
    titled = [node for node in graph.nodes.values() if node.type in TITLED]
    crowd = max(TITLE_CROWD, TITLE_SHARE * len(titled))
    for kind, kind_words, titles in TITLE_NAMED:
        cores = {
            tuple(sig.singular(w) for w in core.split("-")): next(iter(ids))
            for core, ids in _cores(graph, kind, kind_words).items()
            if len(ids) == 1 and len(core.replace("-", "")) >= MIN_TITLE_CORE
        }
        hits: dict[tuple[str, ...], list[uuid.UUID]] = defaultdict(list)
        for node in titled:
            if node.type not in titles:
                continue
            words = [sig.singular(w) for w in sig.words(node.name)]
            seen = {
                tuple(words[i : i + n])
                for n in (1, 2, 3)
                for i in range(len(words) - n + 1)
                if tuple(words[i : i + n]) in cores
            }
            for phrase in seen:
                hits[phrase].append(node.id)
        for phrase, named_in in hits.items():
            if len(named_in) > crowd:
                made.counts["too_common"] += 1
                continue
            target = cores[phrase]
            for node_id in named_in:
                if target in graph.targets(node_id) or (node_id, target) in linked:
                    continue
                documented = graph.of_type(node_id) == "document"
                made.edges.append(
                    _inferred(
                        node_id,
                        target,
                        "describes" if documented else "mentions",
                        "named_in_title",
                        0.6,
                        f"its title names the {kind.replace('_', ' ')} {'-'.join(phrase)}",
                    )
                )
                made.counts["named_in_title"] += 1
    return made


def _service_cores(graph: Graph) -> dict[str, set[uuid.UUID]]:
    """Each service's name core — of its name and of its key — and the
    services that have it."""
    return _cores(graph, "service", sig.SERVICE_WORDS)


def _cores(graph: Graph, kind: str, kind_words: frozenset[str]) -> dict[str, set[uuid.UUID]]:
    """Each name core of a kind — of a service's name and key, of anything
    else's name — and the entities that have it."""
    cores: dict[str, set[uuid.UUID]] = defaultdict(set)
    for node in graph.nodes.values():
        if node.type != kind:
            continue
        for name in (node.name, node.key) if kind == "service" else (node.name,):
            core, environment = sig.core(name, kind_words)
            if not environment and len(core.replace("-", "")) >= MIN_CORE:
                cores[core].add(node.id)
    return cores


# ── 3. ownership ─────────────────────────────────────────────────────────────


def ownership(graph: Graph) -> Made:
    """The team an entity belongs to, where none is said: its container's —
    a pull request its repository's, a repository its service's — a little
    less sure at each step. And the people who maintain a repository, a
    project, a service: the most active on what it holds."""
    made = Made()
    for node in graph.nodes.values():
        if node.type in ("person", "team") or _owners(graph, node.id):
            continue
        found = _inherited_owner(graph, node.id)
        if found is None:
            continue
        if found == "tied":
            made.counts["tied"] += 1
            continue
        team_id, confidence, via = found
        made.edges.append(
            _inferred(
                node.id,
                team_id,
                "owned_by",
                "inherited",
                confidence,
                f"its {graph.nodes[via].type} {graph.nodes[via].key} is the team's",
                inputs=[via],
            )
        )
        made.counts["inherited"] += 1

    for node in graph.nodes.values():
        if node.type not in CONTAINERS:
            continue
        items = _contained(graph, node.id)
        scores: dict[uuid.UUID, float] = defaultdict(float)
        worked: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        for item_id in items:
            moment = _last(graph.nodes[item_id], graph.now)
            recency = 1.0 if moment and graph.now - moment <= MAINTAINED else 0.3
            for edge in graph.out(item_id, WORK):
                person = graph.nodes[edge.to_id]
                if person.type != "person" or sig.is_bot(person.key, person.name):
                    continue
                scores[person.id] += WORK[edge.type] * recency
                worked[person.id].add(item_id)
        total = sum(scores.values())
        if not total:
            continue
        for person_id, score in sorted(scores.items(), key=lambda s: -s[1])[:MAINTAINERS]:
            share = score / total
            if share < MIN_SHARE or len(worked[person_id]) < MIN_ITEMS:
                continue
            made.edges.append(
                _inferred(
                    node.id,
                    person_id,
                    "maintained_by",
                    "most_active",
                    round(min(0.9, 0.4 + 0.6 * share), 2),
                    f"{len(worked[person_id])} of its {len(items)} items, "
                    f"{round(share * 100)} % of the work",
                    inputs=sorted(worked[person_id])[:MAX_PROVENANCE],
                )
            )
            made.counts["maintainers"] += 1
    return made


def _owners(graph: Graph, node_id: uuid.UUID) -> list[Edge]:
    return [e for e in graph.out(node_id, {"owned_by"}) if graph.of_type(e.to_id) == "team"]


def _inherited_owner(
    graph: Graph, node_id: uuid.UUID
) -> tuple[uuid.UUID, float, uuid.UUID] | Literal["tied"] | None:
    """The nearest container's team, through part_of and child_of — the
    surest at that distance. Two teams equally sure: neither."""
    frontier: list[tuple[uuid.UUID, float]] = [(node_id, 1.0)]
    visited = {node_id}
    for hop in range(1, MAX_HOPS + 1):
        found: list[tuple[float, uuid.UUID, uuid.UUID]] = []
        following: list[tuple[uuid.UUID, float]] = []
        for current, sure in frontier:
            for edge in graph.out(current, UP):
                parent = edge.to_id
                if parent in visited:
                    continue
                visited.add(parent)
                reach = sure * edge.confidence
                following.append((parent, reach))
                scope = SCOPE_OWNERSHIP if graph.of_type(parent) in SCOPES else 1.0
                for owner in _owners(graph, parent):
                    surety = reach * owner.confidence * INHERITED**hop * scope
                    found.append((surety, owner.to_id, parent))
        if found:
            found.sort(key=lambda f: -f[0])
            best, team_id, via = found[0]
            if any(f[1] != team_id and math.isclose(f[0], best) for f in found[1:]):
                return "tied"
            confidence = round(best, 2)
            return (team_id, confidence, via) if confidence >= MIN_CONFIDENCE else None
        frontier = following
    return None


def _contained(graph: Graph, node_id: uuid.UUID) -> set[uuid.UUID]:
    """What a container holds: what is part of it — and, for a service,
    what is part of its repositories."""
    held = {e.from_id for e in graph.into(node_id, {"part_of"})}
    if graph.of_type(node_id) == "service":
        for repository in [r for r in held if graph.of_type(r) == "repository"]:
            held |= {e.from_id for e in graph.into(repository, {"part_of"})}
    return {i for i in held if graph.of_type(i) not in CONTAINERS | {"team", "person"}}


# ── 4. membership ────────────────────────────────────────────────────────────


def membership(graph: Graph) -> Made:
    """The team a person works with: most of what they work on belongs to
    it. Not an org chart — said as an inference, with its share."""
    made = Made()
    for person in graph.nodes.values():
        if person.type != "person" or sig.is_bot(person.key, person.name):
            continue
        if graph.out(person.id, {"member_of"}):
            continue
        items = {e.from_id for e in graph.into(person.id, WORK)}
        teams: Counter[uuid.UUID] = Counter()
        for item_id in items:
            owners = _owners(graph, item_id)
            if owners:
                teams[max(owners, key=lambda e: e.confidence).to_id] += 1
        teamed = sum(teams.values())
        if teamed < MIN_TEAM_ITEMS:
            continue
        team_id, count = teams.most_common(1)[0]
        share = count / teamed
        if share < MIN_TEAM_SHARE:
            continue
        made.edges.append(
            _inferred(
                person.id,
                team_id,
                "member_of",
                "works_with",
                round(min(0.85, 0.35 + 0.5 * share), 2),
                f"{count} of the {teamed} items they work on that have a team are its",
            )
        )
        made.counts["members"] += 1
    return made


# ── 10. expertise (LEKA-365) ─────────────────────────────────────────────────


def expertise(graph: Graph) -> Made:
    """What each person's work shows they know: the repositories, projects
    and services the items they work on are part of — a pull request its
    repository, and that repository's service; an incident the services it
    affects — weighed as maintainers are (role, recency). Each area kept
    with its evidence: how many items, in which roles, the last one; the
    languages of the code. Sourced and attributed: nothing a person did not
    do, nothing said of a bot — who is one, said too."""
    made = Made()
    for person in graph.nodes.values():
        if person.type != "person":
            continue
        if sig.is_bot(person.key, person.name):
            if "bot" not in person.attributes:
                made.facts.append(_fact(person, "bot", True, 0.9, "name", "its name or handle"))
                made.counts["bots"] += 1
            continue
        scores: dict[uuid.UUID, float] = defaultdict(float)
        items: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        roles: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
        lasts: dict[uuid.UUID, datetime] = {}
        for edge in graph.into(person.id, WORK):
            item = graph.nodes[edge.from_id]
            if item.type in CONTAINERS | {"team", "person"}:
                continue
            moment = _last(item, graph.now)
            recency = 1.0 if moment and graph.now - moment <= MAINTAINED else 0.3
            for area in _areas(graph, item.id):
                scores[area] += WORK[edge.type] * recency
                items[area].add(item.id)
                roles[area][ROLE_WORDS[edge.type]] += 1
                if moment and (area not in lasts or moment > lasts[area]):
                    lasts[area] = moment
        kept = sorted(
            (a for a in scores if len(items[a]) >= MIN_AREA_ITEMS),
            key=lambda a: (-scores[a], graph.nodes[a].key),
        )[:MAX_AREAS]
        if not kept:
            continue
        total = sum(scores[a] for a in kept)
        shown: list[dict[str, object]] = []
        for area in kept:
            node = graph.nodes[area]
            done = ", ".join(f"{n} {word}" for word, n in roles[area].most_common())
            last = f" — the last on {lasts[area].date().isoformat()}" if area in lasts else ""
            made.edges.append(
                _inferred(
                    person.id,
                    area,
                    "contributes_to",
                    "work",
                    round(min(0.9, 0.4 + 0.5 * scores[area] / total), 2),
                    f"{len(items[area])} items: {done}{last}",
                    inputs=sorted(items[area], key=str)[:MAX_PROVENANCE],
                )
            )
            shown.append(
                {
                    "key": node.key,
                    "name": node.name,
                    "type": node.type,
                    "items": len(items[area]),
                    "roles": dict(roles[area].most_common()),
                    "last_at": _iso(lasts[area]) if area in lasts else None,
                }
            )
        made.counts["contributes_to"] += len(kept)
        if "expertise" not in person.attributes:
            made.facts.append(
                _fact(
                    person,
                    "expertise",
                    shown,
                    0.9,
                    "work",
                    f"what their work on {len(kept)} areas shows",
                )
            )
        languages = _languages(graph, kept, scores)
        if languages and "languages" not in person.attributes:
            made.facts.append(
                _fact(
                    person,
                    "languages",
                    languages,
                    0.8,
                    "work",
                    "the languages of the repositories they work on",
                )
            )
    return made


def _areas(graph: Graph, item_id: uuid.UUID) -> set[uuid.UUID]:
    """Where an item's work is done: the repositories, projects, services
    and spaces it is part of — and their services — or, for an incident,
    the services it affects; for a document, what it describes."""
    found: set[uuid.UUID] = set()
    for edge in graph.out(item_id, {"part_of", "affects"}):
        if graph.of_type(edge.to_id) in AREAS:
            found.add(edge.to_id)
    # What a document describes is where its work is too (LEKA-366).
    for edge in graph.out(item_id, {"describes"}):
        if graph.of_type(edge.to_id) in AREAS:
            found.add(edge.to_id)
    for area in list(found):
        if graph.of_type(area) == "repository":
            found |= {
                e.to_id for e in graph.out(area, {"part_of"}) if graph.of_type(e.to_id) == "service"
            }
    return found


def _languages(graph: Graph, areas: list[uuid.UUID], scores: dict[uuid.UUID, float]) -> list[str]:
    """The languages of the repositories among them, the most worked first."""
    weights: dict[str, float] = defaultdict(float)
    for area in areas:
        language = graph.nodes[area].attributes.get("language")
        if graph.of_type(area) == "repository" and isinstance(language, str) and language:
            weights[language.lower()] += scores[area]
    return [name for name, _ in sorted(weights.items(), key=lambda w: (-w[1], w[0]))][
        :MAX_LANGUAGES
    ]


# ── 5. activity ──────────────────────────────────────────────────────────────


def activity(graph: Graph) -> Made:
    """How alive things are, measured when the run is made: what was last
    done in a container, by a person, for a team — or to an item itself;
    how long work took; how long an incident lasted; a service's
    incidents."""
    made = Made()
    now = graph.now
    for node in graph.nodes.values():
        related = _related(graph, node)
        if related is not None:
            moments = [m for i in related if (m := _last(graph.nodes[i], now))]
            # A container's own date counts: a repository's last push.
            own = _last(node, now) if node.type in CONTAINERS else None
            latest = max([m for m in (own, *moments) if m], default=None)
            if latest is not None:
                made.facts.append(
                    _fact(
                        node,
                        "last_activity_at",
                        _iso(latest),
                        1.0,
                        "activity",
                        f"the latest date of it and its {len(related)} related items",
                    )
                )
            if related:
                made.facts.append(
                    _fact(
                        node,
                        "activity_90d",
                        sum(1 for m in moments if now - m <= RECENT),
                        1.0,
                        "activity",
                        "related items changed in the last 90 days",
                    )
                )
            if (
                latest is not None
                and node.type in CONTAINERS
                and node.attributes.get("state") != "archived"
            ):
                idle = now - latest
                stage = "active" if idle <= ACTIVE else "quiet" if idle <= QUIET else "dormant"
                made.facts.append(
                    _fact(
                        node,
                        "lifecycle",
                        stage,
                        0.9,
                        "activity",
                        f"last activity {idle.days} days ago",
                    )
                )
        elif (own := _last(node, now)) is not None:
            # An item — a ticket, a pull request, an incident, a resource:
            # its own latest date, where the company model finds what moved.
            made.facts.append(
                _fact(node, "last_activity_at", _iso(own), 1.0, "activity", "its latest date")
            )
        if node.type in ("issue", "pull_request"):
            made.facts.extend(_work_times(node, now))
        elif node.type == "incident":
            minutes = _minutes(node, "resolved_at")
            if minutes is not None:
                made.facts.append(
                    _fact(
                        node,
                        "duration_minutes",
                        minutes,
                        1.0,
                        "dates",
                        "from its creation to its resolution",
                    )
                )
        elif node.type == "service":
            made.facts.extend(_incidents(graph, node))
    made.counts["facts"] = len(made.facts)
    return made


def _related(graph: Graph, node: Node) -> set[uuid.UUID] | None:
    """What a node's activity is measured on — None for what has none of
    its own to measure."""
    if node.type in CONTAINERS:
        return _contained(graph, node.id)
    if node.type == "person":
        return {e.from_id for e in graph.into(node.id, WORK)}
    if node.type == "team":
        owned = {e.from_id for e in graph.into(node.id, {"owned_by"})}
        for container in [o for o in owned if graph.of_type(o) in CONTAINERS]:
            owned |= _contained(graph, container)
        return {o for o in owned if graph.of_type(o) not in CONTAINERS | {"team", "person"}}
    return None


def _work_times(node: Node, now: datetime) -> list[Fact]:
    facts: list[Fact] = []
    state = node.attributes.get("state")
    if state in CLOSED:
        for end in ("merged_at", "closed_at", "resolved_at"):
            minutes = _minutes(node, end)
            if minutes is not None:
                facts.append(
                    _fact(
                        node,
                        "cycle_time_hours",
                        round(minutes / 60, 1),
                        1.0,
                        "dates",
                        f"from its creation to {end.removesuffix('_at')}",
                    )
                )
                break
    elif state in OPEN:
        updated = _moment(node.dates.get("updated_at"), now)
        if updated is not None and now - updated > STALE:
            facts.append(
                _fact(
                    node,
                    "stale",
                    True,
                    0.8,
                    "inactivity",
                    f"open, unchanged for {(now - updated).days} days",
                )
            )
    return facts


def _incidents(graph: Graph, service: Node) -> list[Fact]:
    """A service's incidents — what says they affect it."""
    now = graph.now
    incidents = [
        graph.nodes[e.from_id]
        for e in graph.into(service.id, {"affects"})
        if graph.of_type(e.from_id) == "incident"
    ]
    if not incidents:
        return []
    recent = [
        i
        for i in incidents
        if (created := _moment(i.dates.get("created_at"), now)) and now - created <= RECENT
    ]
    facts = [
        _fact(service, "incidents_90d", len(recent), 1.0, "incidents", "incidents affecting it"),
        _fact(
            service,
            "open_incidents",
            sum(1 for i in incidents if i.attributes.get("state") in OPEN),
            1.0,
            "incidents",
            "incidents affecting it, not resolved",
        ),
    ]
    durations = [m for i in recent if (m := _minutes(i, "resolved_at")) is not None]
    if durations:
        facts.append(
            _fact(
                service,
                "mttr_minutes",
                round(statistics.median(durations)),
                1.0,
                "incidents",
                f"the median time to resolve {len(durations)} incidents of the last 90 days",
            )
        )
    return facts


# ── 6. category ──────────────────────────────────────────────────────────────


def category(graph: Graph) -> Made:
    """The kind of work a title says — bug, security, feature, docs,
    maintenance — where parsing said none (a vendor's type, a label, a
    Conventional Commits title come first). One kind clearly ahead, or
    nothing."""
    made = Made()
    for node in graph.nodes.values():
        if node.type not in WORK_ITEMS or "category" in node.attributes:
            continue
        words = set(sig.words(node.name))
        votes = {kind: len(words & vocabulary) for kind, vocabulary in TITLE_WORDS}
        best = max(votes.values())
        winners = [kind for kind, n in votes.items() if n == best]
        if not best or len(winners) > 1:
            continue
        made.facts.append(
            _fact(
                node,
                "category",
                winners[0],
                TITLE_CONFIDENCE,
                "title_words",
                f"{best} word{'s' if best > 1 else ''} of its title say {winners[0]}",
            )
        )
        made.counts[winners[0]] += 1
    return made


# ── the run ──────────────────────────────────────────────────────────────────

Enricher = Callable[[Graph], Made]

# In order: each reads what those before it made.
# ── 7. landscape (LEKA-362) ─────────────────────────────────────────────────


def landscape(graph: Graph) -> Made:
    """Where a service or an application runs, and how critical it is, where
    no catalogue says — what its parts show. A service runs in the
    environments its resources run in, an application in its services';
    one holding a critical part is critical. Each environment is also an
    inferred `runs_in`, to the environment's own entity."""
    made = Made()
    # What this enricher found, for the applications that read their
    # services': node → environment → (confidence, the part that says it).
    runs: dict[uuid.UUID, dict[str, tuple[float, uuid.UUID]]] = {}
    levels: dict[uuid.UUID, tuple[str, float]] = {}
    for kind in LANDSCAPE:
        for node in [n for n in graph.nodes.values() if n.type == kind]:
            found: dict[str, tuple[float, uuid.UUID]] = {}
            highest: tuple[int, float, uuid.UUID] | None = None
            for edge in graph.into(node.id, {"part_of"}):
                part = graph.nodes[edge.from_id]
                for name, sure in _runs_in(graph, part, runs).items():
                    surety = round(min(edge.confidence, sure), 2)
                    if surety > found.get(name, (0.0, part.id))[0]:
                        found[name] = (surety, part.id)
                level = levels.get(part.id) or _criticality(part)
                if level is not None:
                    rank = LEVELS.index(level[0])
                    surety = round(min(FROM_PARTS, edge.confidence, level[1]), 2)
                    if highest is None or (rank, -surety) < (highest[0], -highest[1]):
                        highest = (rank, surety, part.id)
            own = _runs_in(graph, node, {})
            runs[node.id] = {**found, **{n: (s, node.id) for n, s in own.items()}}
            for name, (surety, via) in sorted(found.items()):
                if name in own:
                    continue
                target = _one_holder(graph, f"environment:{name}")
                if target is None:
                    continue
                made.edges.append(
                    _inferred(
                        node.id,
                        target,
                        "runs_in",
                        "parts",
                        surety,
                        f"its {graph.nodes[via].type} {graph.nodes[via].key} runs in {name}",
                        inputs=[via],
                    )
                )
                made.counts["runs_in"] += 1
            everywhere = runs[node.id]
            if everywhere and "environments" not in node.attributes:
                names = sorted(everywhere, key=_environment_rank)
                made.facts.append(
                    _fact(
                        node,
                        "environments",
                        names,
                        max(s for s, _ in everywhere.values()),
                        "parts",
                        f"runs in {', '.join(names)}",
                    )
                )
                made.counts["environments"] += 1
            stated = _criticality(node)
            if stated is not None:
                levels[node.id] = stated
            elif highest is not None:
                rank, surety, via = highest
                levels[node.id] = (LEVELS[rank], surety)
                part = graph.nodes[via]
                made.facts.append(
                    _fact(
                        node,
                        "criticality",
                        LEVELS[rank],
                        surety,
                        "parts",
                        f"its {part.type} {part.key} is {LEVELS[rank]}",
                    )
                )
                made.counts["criticality"] += 1
    return made


def _runs_in(
    graph: Graph, node: Node, found: dict[uuid.UUID, dict[str, tuple[float, uuid.UUID]]]
) -> dict[str, float]:
    """Where a thing runs, and how surely: its sources' `runs_in`, its own
    `environment`, what this enricher found for it."""
    where: dict[str, float] = {}
    for edge in graph.out(node.id, {"runs_in"}):
        name = graph.nodes[edge.to_id].key.removeprefix("environment:")
        where[name] = max(where.get(name, 0.0), edge.confidence)
    environment = node.attributes.get("environment")
    if isinstance(environment, str) and environment in ENVIRONMENT_ORDER:
        sure = node.attributes.get("environment_confidence", 1.0)
        surety = float(sure) if isinstance(sure, int | float) else 1.0
        where[environment] = max(where.get(environment, 0.0), surety)
    for name, (surety, _) in found.get(node.id, {}).items():
        where[name] = max(where.get(name, 0.0), surety)
    return where


def _criticality(node: Node) -> tuple[str, float] | None:
    """What a thing's sources say of how critical it is, on LEKA's scale."""
    level = node.attributes.get("criticality")
    if level not in LEVELS:
        return None
    sure = node.attributes.get("criticality_confidence", 1.0)
    return str(level), float(sure) if isinstance(sure, int | float) else 1.0


def _environment_rank(name: str) -> int:
    return ENVIRONMENT_ORDER.index(name) if name in ENVIRONMENT_ORDER else len(ENVIRONMENT_ORDER)


def _one_holder(graph: Graph, key: str) -> uuid.UUID | None:
    holders = graph.snapshot.holders.get(key, set())
    return next(iter(holders)) if len(holders) == 1 else None


# ── 8. infrastructure (LEKA-363) ────────────────────────────────────────────


def infrastructure(graph: Graph) -> Made:
    """What a cloud resource's place says, where its own sources say
    nothing. Its account: an S3 bucket's ARN names none, but the source
    that reads it reads one account of its provider. Its environment: its
    cluster's, else its resource group's, else its account's — a company
    that keeps production in an account of its own says so once, there."""
    made = Made()
    accounts: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for node in graph.nodes.values():
        if node.type == "cloud_account":
            for source in node.sources:
                accounts[source].add(node.id)
    for node in graph.nodes.values():
        if node.type not in PLACED or _containers(graph, node.id):
            continue
        provider = node.attributes.get("provider")
        held = {
            account
            for source in node.sources
            for account in accounts.get(source, ())
            if graph.nodes[account].attributes.get("provider") == provider
        }
        if len(held) != 1:
            continue
        account = graph.nodes[next(iter(held))]
        evidence = f"its source reads it in {account.key}"
        made.edges.append(
            _inferred(node.id, account.id, "part_of", "source_account", SOURCE_ACCOUNT, evidence)
        )
        identifier = account.attributes.get("account_id")
        if isinstance(identifier, str) and "account" not in node.attributes:
            made.facts.append(
                _fact(node, "account", identifier, SOURCE_ACCOUNT, "source_account", evidence)
            )
        made.counts["account"] += 1

    # Containers before what they hold — groups, clusters, the instances
    # serving databases, databases, schemas: a group's environment,
    # inherited from its account, is what its resources inherit.
    inherited: dict[uuid.UUID, tuple[str, float]] = {}
    placed = sorted(
        (n for n in graph.nodes.values() if n.type in PLACED),
        key=lambda n: (_depth(n), n.key),
    )
    for node in placed:
        if "environment" in node.attributes or graph.out(node.id, {"runs_in"}):
            continue
        for edge, container in _containers(graph, node.id, made.edges):
            found = _placed_environment(graph, container, inherited)
            if found is None:
                continue
            name, sure = found
            surety = round(sure * edge.confidence * FROM_CONTAINER, 2)
            if surety < MIN_CONFIDENCE:
                break
            inherited[node.id] = (name, surety)
            evidence = f"its {_container_word(container)} {container.key} runs in {name}"
            made.facts.append(_fact(node, "environment", name, surety, "container", evidence))
            target = _one_holder(graph, f"environment:{name}")
            if target is not None:
                made.edges.append(
                    _inferred(
                        node.id,
                        target,
                        "runs_in",
                        "container",
                        surety,
                        evidence,
                        inputs=[container.id],
                    )
                )
            made.counts["environment"] += 1
            break
    return made


def _containers(
    graph: Graph, node_id: uuid.UUID, made: Iterable[Edge] = ()
) -> list[tuple[Edge, Node]]:
    """What a resource is in — its cluster, its resource group, its account —
    the nearest first: stated, or found by this enricher."""
    edges = [*graph.out(node_id, {"part_of"}), *(e for e in made if e.from_id == node_id)]
    found = []
    for edge in edges:
        container = graph.nodes.get(edge.to_id)
        if container is None:
            continue
        word = _container_word(container)
        if word in CONTAINER_ORDER:
            found.append((CONTAINER_ORDER.index(word), edge, container))
    return [(edge, container) for _, edge, container in sorted(found, key=lambda f: f[0])]


def _depth(node: Node) -> int:
    """How deep a thing sits among what holds things: the shallowest first."""
    if node.type == "resource_group":
        return 0
    if _container_word(node) == "cluster":
        return 1
    if node.type == "database":
        return 2 if node.attributes.get("provider") else 3  # an instance, then its databases
    return 4 if node.type == "schema" else 5


def _container_word(node: Node) -> str:
    if node.type == "infra_resource" and node.attributes.get("resource_kind") == "cluster":
        return "cluster"
    return node.type


def _placed_environment(
    graph: Graph, node: Node, inherited: dict[uuid.UUID, tuple[str, float]]
) -> tuple[str, float] | None:
    """The one environment a container runs in, and how surely: its own, or
    what this enricher found for it — none where it runs in several."""
    environment = node.attributes.get("environment")
    if isinstance(environment, str) and environment in ENVIRONMENT_ORDER:
        sure = node.attributes.get("environment_confidence", 1.0)
        return environment, float(sure) if isinstance(sure, int | float) else 1.0
    if node.id in inherited:
        return inherited[node.id]
    places = {
        graph.nodes[e.to_id].key.removeprefix("environment:"): e.confidence
        for e in graph.out(node.id, {"runs_in"})
    }
    if len(places) == 1:
        [(name, sure)] = places.items()
        return name, sure
    return None


# ── 9. data (LEKA-364) ───────────────────────────────────────────────────────


def data(graph: Graph) -> Made:
    """What a schema holds, from its tables; a database, from its schemas;
    the instance serving databases, from them: the kinds of data, the most
    sensitive classification, whether personal data — where its sources say
    none. At most FROM_PARTS sure: a part's word, said of its whole."""
    made = Made()
    held: dict[uuid.UUID, tuple[set[str], str | None, bool, uuid.UUID | None]] = {}
    holders = sorted(
        (n for n in graph.nodes.values() if n.type in ("schema", "database")),
        key=lambda n: (n.type != "schema", bool(n.attributes.get("provider")), n.key),
    )
    for node in holders:
        categories: set[str] = set()
        levels: list[tuple[int, uuid.UUID]] = []
        personal = False
        for edge in graph.into(node.id, {"part_of"}):
            part = graph.nodes[edge.from_id]
            if part.type not in DATA_HOLDERS:
                continue
            kinds, level, personal_part, _ = held.get(part.id) or _holds(part)
            categories |= kinds
            personal = personal or personal_part
            if level is not None:
                levels.append((DATA_LEVELS.index(level), part.id))
        level = DATA_LEVELS[min(levels)[0]] if levels else None
        via = min(levels)[1] if levels else None
        own = _holds(node)
        # What goes up is the most sensitive: a schema said internal that
        # holds a restricted table holds restricted data.
        known = [lv for lv in (own[1], level) if lv is not None]
        most = min(known, key=DATA_LEVELS.index) if known else None
        held[node.id] = (categories | own[0], most, personal or own[2], via)
        if categories and "data_categories" not in node.attributes:
            made.facts.append(
                _fact(
                    node,
                    "data_categories",
                    sorted(categories),
                    FROM_PARTS,
                    "objects",
                    f"its tables hold {', '.join(sorted(categories))} data",
                )
            )
            made.counts["data_categories"] += 1
        if personal and "personal_data" not in node.attributes:
            made.facts.append(
                _fact(node, "personal_data", True, FROM_PARTS, "objects", "its tables hold some")
            )
        if level is not None and via is not None and "classification" not in node.attributes:
            part = graph.nodes[via]
            made.facts.append(
                _fact(
                    node,
                    "classification",
                    level,
                    FROM_PARTS,
                    "objects",
                    f"its {part.type} {part.key} is {level}",
                )
            )
            made.counts["classification"] += 1
    return made


def _holds(node: Node) -> tuple[set[str], str | None, bool, None]:
    """What a thing's sources say of the data it holds."""
    found = node.attributes.get("data_categories")
    categories = {str(c) for c in found} if isinstance(found, list) else set()
    level = node.attributes.get("classification")
    return (
        categories,
        str(level) if level in DATA_LEVELS else None,
        node.attributes.get("personal_data") is True,
        None,
    )


# ── 11. knowledge (LEKA-366) ─────────────────────────────────────────────────


def knowledge(graph: Graph) -> Made:
    """Documentation and business knowledge: where a document or a space
    opens, the tools it is read from, how fresh a document is — and when its tool wants it verified
    again; the team a space is named for, owning it, and the service or
    application, which it documents; the documents a catalogue links as a
    thing's documentation, found at their address; the data a business
    system names, found by name. Each said as enrichment's, with its rule."""
    made = Made()
    now = graph.now
    for node in graph.nodes.values():
        if node.type in KNOWLEDGE and node.links:
            made.facts.append(_fact(node, "url", node.links[0], 1.0, "record", "its record's link"))
        if node.type in KNOWLEDGE and node.tools:
            made.facts.append(
                _fact(node, "tools", list(node.tools), 1.0, "record", "the tools it is read from")
            )
        if node.type != "document":
            continue
        moment = _last(node, now)
        if moment is not None:
            age = now - moment
            word = "fresh" if age <= FRESH else "aging" if age <= AGING else "stale"
            made.facts.append(
                _fact(node, "freshness", word, 1.0, "freshness", f"changed {age.days} days ago")
            )
            made.counts[word] += 1
        due = _date(node.dates.get("next_verification_at"))
        if due is not None:
            made.facts.append(
                _fact(
                    node,
                    "verification_due_at",
                    _iso(due),
                    1.0,
                    "dates",
                    "when its tool wants it verified again",
                )
            )
    made.edges += _named_spaces(graph, made)
    made.edges += _linked_documentation(graph, made)
    made.edges += _named_data(graph, made)
    return made


def _named_spaces(graph: Graph, made: Made) -> list[Edge]:
    """A space named for a team — `Payments`, `Payments team wiki` — is
    the team's, where nothing says whose it is; one named for a service or
    an application documents it. Only a name one team, one service, one
    application has."""
    found: list[Edge] = []
    named = [
        ("owned_by", _cores(graph, "team", sig.TEAM_WORDS | DOC_WORDS), sig.TEAM_WORDS),
        ("describes", _cores(graph, "service", sig.SERVICE_WORDS), sig.SERVICE_WORDS),
        ("describes", _cores(graph, "application", sig.APPLICATION_WORDS), sig.APPLICATION_WORDS),
    ]
    for node in graph.nodes.values():
        if node.type != "knowledge_space":
            continue
        for relation, cores, kind_words in named:
            if relation == "owned_by" and _owners(graph, node.id):
                continue
            core, environment = sig.core(node.name, kind_words | DOC_WORDS)
            holders = cores.get(core, set())
            if environment or len(core.replace("-", "")) < MIN_CORE or len(holders) != 1:
                continue
            target = next(iter(holders))
            if target in graph.targets(node.id):
                continue
            kind = graph.of_type(target).replace("_", " ")
            found.append(
                _inferred(
                    node.id,
                    target,
                    relation,
                    "same_name",
                    SPACE_NAMED,
                    f"the space is named for the {kind} {core}",
                )
            )
            made.counts[f"space_{relation}"] += 1
    return found


def _linked_documentation(graph: Graph, made: Made) -> list[Edge]:
    """A service's — an application's, a capability's — documentation or
    runbook link, at the address of a document or a space LEKA reads: it
    describes the thing. Where normalisation could not read the address —
    a SharePoint file's — this finds it."""
    at: dict[str, uuid.UUID] = {}
    for node in graph.nodes.values():
        if node.type in KNOWLEDGE:
            for link in node.links:
                at.setdefault(_address(link), node.id)
    found: list[Edge] = []
    for node in graph.nodes.values():
        for name in ("docs_url", "runbook_url"):
            said = node.attributes.get(name)
            target = at.get(_address(said)) if isinstance(said, str) and said else None
            if target is None or target == node.id or node.id in graph.targets(target):
                continue
            found.append(
                _inferred(
                    target,
                    node.id,
                    "describes",
                    "linked",
                    LINKED,
                    f"its {name.removesuffix('_url')} link is this document",
                )
            )
            made.counts["linked"] += 1
    return found


def _address(link: str) -> str:
    """A link, compared: no scheme, no query, no fragment, no trailing
    slash, its host in lower case, its path decoded — `Shared%20Documents`
    is `Shared Documents`."""
    rest = link.strip().split("#", 1)[0].split("?", 1)[0].split("://", 1)[-1].rstrip("/")
    host, _, path = rest.partition("/")
    return f"{host.lower()}/{unquote(path)}"


def _named_data(graph: Graph, made: Made) -> list[Edge]:
    """The tables a business system says a capability or a process uses —
    `billing.invoices`, or `invoices` when only one table has the name —
    and the databases it names: each `uses` it. A name two tables share
    says nothing."""
    qualified: dict[str, set[uuid.UUID]] = defaultdict(set)
    alone: dict[str, set[uuid.UUID]] = defaultdict(set)
    for node in graph.nodes.values():
        if node.type == "data_object":
            table = node.key.rsplit("/", 1)[-1].lower()
            schema = node.attributes.get("schema_name")
            if isinstance(schema, str) and schema:
                qualified[f"{schema.lower()}.{table}"].add(node.id)
            alone[table].add(node.id)
        elif node.type in ("database", "schema"):
            alone[node.name.lower()].add(node.id)
    found: list[Edge] = []
    for node in graph.nodes.values():
        names = node.attributes.get("data_names")
        if node.type not in BUSINESS or not isinstance(names, list):
            continue
        for raw in names:
            name = str(raw).strip().lower()
            holders = qualified.get(name) or alone.get(name.rsplit(".", 1)[-1], set())
            confidence = NAMED_QUALIFIED if name in qualified else NAMED_ALONE
            if len(holders) != 1:
                made.counts["data_unfound" if not holders else "data_ambiguous"] += 1
                continue
            target = next(iter(holders))
            if target in graph.targets(node.id):
                continue
            found.append(
                _inferred(
                    node.id,
                    target,
                    "uses",
                    "named",
                    confidence,
                    f"its source names the data {raw}",
                )
            )
            made.counts["uses"] += 1
    return found


ENRICHERS: tuple[tuple[str, Enricher], ...] = (
    ("relationships", relationships),
    ("links", links),
    ("infrastructure", infrastructure),
    ("data", data),
    ("knowledge", knowledge),
    ("ownership", ownership),
    ("membership", membership),
    ("expertise", expertise),
    ("activity", activity),
    ("category", category),
    ("landscape", landscape),
)


def enrich(snapshot: Snapshot, enrichers: Iterable[tuple[str, Enricher]] = ENRICHERS) -> Enrichment:
    """Every enricher, in order, each on its own: one that raises is
    recorded and its output dropped; what one makes is checked before it
    is kept."""
    graph = Graph(snapshot)
    counts: Counter[str] = Counter()
    failures: list[dict[str, str]] = []
    for name, enricher in enrichers:
        try:
            made = enricher(graph)
        except Exception as error:  # an enricher's bug costs its own output, not the run
            failures.append({"enricher": name, "error": type(error).__name__[:200]})
            continue
        for edge in made.edges:
            if not _admissible_edge(graph, edge):
                counts["rejected"] += 1
            elif not graph.add(edge):
                counts["superseded"] += 1
        for fact in made.facts:
            if _admissible_fact(graph, fact):
                graph.facts[(fact.entity_id, fact.attribute)] = fact
            else:
                counts["rejected"] += 1
        counts.update({f"{name}.{k}": v for k, v in made.counts.items() if v})
    edges = list(graph.edges.values())
    for edge in edges:
        ends = graph.nodes[edge.from_id].sources, graph.nodes[edge.to_id].sources
        edge.cross_source = bool(ends[0] and ends[1] and not ends[0] & ends[1])
    counts.update(
        {
            "relationships": len(edges),
            "stated": sum(1 for e in edges if e.origin == "stated"),
            "inferred": sum(1 for e in edges if e.origin == "inferred"),
            "cross_source": sum(1 for e in edges if e.cross_source),
            "attributes": len(graph.facts),
            "failed": len(failures),
        }
    )
    return Enrichment(
        edges=edges, facts=list(graph.facts.values()), counts=dict(counts), failures=failures
    )


def _admissible_edge(graph: Graph, edge: Edge) -> bool:
    return (
        edge.from_id in graph.nodes
        and edge.to_id in graph.nodes
        and edge.from_id != edge.to_id
        and bool(EDGE_TYPE.match(edge.type))
        and _confidence(edge.confidence)
        and 0 < len(edge.rule) <= 100
    )


def _admissible_fact(graph: Graph, fact: Fact) -> bool:
    """An entity that exists; an attribute its sources do not state, not
    enriched yet; a value that is JSON; a confidence from 0 to 1."""
    node = graph.nodes.get(fact.entity_id)
    if node is None or not ATTRIBUTE.match(fact.attribute):
        return False
    stated = fact.attribute in node.attributes or fact.attribute in node.dates
    if stated or (fact.entity_id, fact.attribute) in graph.facts:
        return False
    if fact.value is None or not _confidence(fact.confidence) or not 0 < len(fact.rule) <= 100:
        return False
    try:
        json.dumps(fact.value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def _confidence(value: object) -> bool:
    return isinstance(value, int | float) and math.isfinite(value) and 0 <= value <= 1


# ── helpers ──────────────────────────────────────────────────────────────────


def _inferred(
    from_id: uuid.UUID,
    to_id: uuid.UUID,
    type: str,  # noqa: A002 — the relationship's word
    rule: str,
    confidence: float,
    evidence: str,
    *,
    inputs: Iterable[uuid.UUID] = (),
) -> Edge:
    return Edge(
        from_id,
        to_id,
        type,
        "inferred",
        rule,
        confidence,
        evidence,
        provenance=[{"entity_id": str(i)} for i in inputs],
    )


def _fact(
    node: Node, attribute: str, value: object, confidence: float, rule: str, evidence: str
) -> Fact:
    return Fact(node.id, attribute, value, confidence, rule, evidence, (node.key,))


def _date(value: object) -> datetime | None:
    """A date an attribute holds — none for what does not read as one."""
    if not isinstance(value, str) or not value:
        return None
    try:
        found = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def _moment(value: object, now: datetime) -> datetime | None:
    """A date, when it is not in the future: a wrong date is not activity."""
    found = _date(value)
    return found if found is not None and found <= now + AHEAD else None


def _last(node: Node, now: datetime) -> datetime | None:
    """When a thing last changed: updated, else created."""
    return _moment(node.dates.get("updated_at"), now) or _moment(node.dates.get("created_at"), now)


def _minutes(node: Node, end: str) -> int | None:
    """From its creation to an end — minutes, when both are dates in order."""
    start = _date(node.dates.get("created_at"))
    stop = _date(node.dates.get(end))
    if start is None or stop is None or stop < start:
        return None
    return round((stop - start).total_seconds() / 60)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
