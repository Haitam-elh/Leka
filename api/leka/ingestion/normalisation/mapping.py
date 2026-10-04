"""From an extraction and its parse to candidates in LEKA's structures.

The record becomes ONE entity — its type from its capability, its key from
identifiers.py, its attributes canonical (values.py): what the extraction
said, dates in UTC, states and priorities on LEKA's scale, the facts parsing
was surest of. The people it names become person entities; the services,
applications, teams and environments its tags and catalogues name, entities
of their own. What it points at becomes a relationship to that thing's key,
whether or not any source has shown it. A cloud resource is placed in what
it is in — an AWS account, an Azure resource group and its subscription, a
Google Cloud project — each an entity too (LEKA-363). A database's schemas
and tables are keyed by the server and database they were read on, so that
two sources reading one database meet; the database, by its endpoint, meets
the cloud instance that serves it (LEKA-364). A team's members and leads,
its parent team; a directory's person, their department and manager —
each a relationship to that person or team (LEKA-365). Where documents are
kept — a space, a Notion database, a topic, a collection, a drive — an
entity its documents are part of; a document's owner and last editor, what
it links to; a catalogue's documentation, what it describes; a business
system's capabilities and processes, what supports them, what they use
(LEKA-366). A deployment, part of its repository, deploying its commit, to
its environment; a change, and what it affects; an incident or a change a
ticket tool keeps, and what caused what (LEKA-367).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit

from leka.connectors import Capability, Mapping, first_match
from leka.ingestion.extraction import ExtractedRecord, Reference
from leka.ingestion.normalisation import identifiers as ids
from leka.ingestion.normalisation import values
from leka.ingestion.parsing import Fact, FactType, ParsedRecord, Target
from leka.ingestion.parsing.rules import ENVIRONMENTS, criticality
from leka.ingestion.parsing.text import url_target
from leka.ingestion.schemas import NormalisedEntity, NormalisedRelationship

C = Capability
CODE_HOSTS = frozenset({"github", "gitlab", "bitbucket"})
CLOUDS = frozenset({"aws", "azure", "gcp"})
# The operations tools whose incidents and services are mapped (LEKA-348);
# Kibana's cases are incidents too.
OPERATIONS = frozenset({"datadog", "pagerduty", "kibana"})
# The project and documentation tools beyond Jira (LEKA-346).
PROJECT_TOOLS = frozenset({"linear", "asana", "trello", "clickup", "monday"})
DOCUMENT_TOOLS = frozenset(
    {"confluence", "notion", "slab", "guru", "google_workspace", "microsoft_365"}
)
# What a custom source's resource may declare its records to be (LEKA-350):
# a CMDB's servers and databases too (LEKA-363).
CUSTOM_ENTITIES = frozenset(
    {"issue", "incident", "service", "application", "project", "document"}
    | {"infra_resource", "database"}
    # A data catalogue's tables (LEKA-364).
    | {"data_object"}
    # An HR system's people and teams (LEKA-365).
    | {"person", "team"}
    # A business system's capabilities and processes; a wiki's spaces (LEKA-366).
    | {"business_capability", "business_process", "knowledge_space"}
    # A change management tool's changes, a CI/CD tool's deployments (LEKA-367).
    | {"change", "deployment"}
)

ENTITY_TYPES = {
    C.REPOSITORIES: "repository",
    C.PULL_REQUESTS: "pull_request",
    C.ISSUES: "issue",
    C.COMMITS: "commit",
    C.BRANCHES: "branch",
    C.RELEASES: "release",
    C.PROJECTS: "project",
    C.INSTANCES: "infra_resource",
    C.DB_INSTANCES: "database",
    C.BUCKETS: "infra_resource",
    C.FUNCTIONS: "infra_resource",
    C.CLUSTERS: "infra_resource",
    C.NETWORKS: "infra_resource",
    C.LOAD_BALANCERS: "infra_resource",
    C.INCIDENTS: "incident",
    C.SERVICES: "service",
    C.PAGES: "document",
    C.FILES: "document",
    # Where documents are kept (LEKA-366).
    C.SPACES: "knowledge_space",
    C.DATABASES: "knowledge_space",
    C.DRIVES: "knowledge_space",
    # What was shipped where, and what changed (LEKA-367).
    C.DEPLOYMENTS: "deployment",
    C.CHANGES: "change",
    # What resources are in; an Azure resource group says so itself.
    C.ACCOUNTS: "cloud_account",
    # A database's schemas, and its tables, views and collections (LEKA-364).
    C.SCHEMAS: "schema",
    C.TABLES: "data_object",
    # Who works there, and their teams (LEKA-365).
    C.PEOPLE: "person",
    C.TEAMS: "team",
    # What a repository's code says it runs (LEKA-369): a service — or, as
    # the record says, a database, a store, a service outside.
    C.COMPONENTS: "service",
}
# A component's kind, as the company model types it.
COMPONENT_TYPES = {"database": "database", "storage": "infra_resource", "external": "service"}
# What a component's technology says of its language.
COMPONENT_LANGUAGES = frozenset({"Python", "TypeScript", "JavaScript", "Go", "Java", "Ruby"})
# How sure a link the code declares is: a route, a store, a queue are
# configured; that a front end calls its API is read from what it is told.
LINK_CONFIDENCE = {"calls": 0.8, "depends": 0.9}
RESOURCE_KINDS = {
    C.INSTANCES: "instance",
    C.DB_INSTANCES: "database",
    C.BUCKETS: "bucket",
    C.FUNCTIONS: "function",
    C.CLUSTERS: "cluster",
    C.NETWORKS: "network",
    C.LOAD_BALANCERS: "load_balancer",
}
# How the company reads its infrastructure (LEKA-363): what computes, what
# carries the traffic, what stores, what holds the data.
RESOURCE_CLASSES = {
    "instance": "compute",
    "function": "compute",
    "cluster": "compute",
    "network": "network",
    "load_balancer": "network",
    "bucket": "storage",
    "database": "database",
}
# A CMDB's words for a kind of resource.
RESOURCE_WORDS = {
    "instance": (
        "instance",
        "server",
        "vm",
        "virtual machine",
        "virtual-machine",
        "host",
        "machine",
    ),
    "function": ("function", "lambda", "serverless"),
    "cluster": ("cluster", "kubernetes", "k8s"),
    "network": ("network", "vpc", "vnet", "subnet"),
    "load_balancer": ("load balancer", "load_balancer", "load-balancer", "lb", "alb", "elb"),
    "bucket": ("bucket", "storage", "object storage", "storage account"),
    "database": ("database", "db", "rds", "sql"),
}
ACCOUNT_TYPES = {"aws": "aws_account", "azure": "azure_subscription", "gcp": "gcp_project"}
# Where a client connects to an Azure database server: its name, and the
# engine's domain and port.
AZURE_ENDPOINTS = {
    "microsoft.dbforpostgresql/flexibleservers": ("postgres.database.azure.com", 5432),
    "microsoft.dbformysql/flexibleservers": ("mysql.database.azure.com", 3306),
}
# How sensitive what a column holds is (LEKA-364): a credential, a payment
# card or an account, health — restricted; who someone is, how to reach
# them, where they are — confidential, and personal data.
RESTRICTED = frozenset({"credential", "financial", "health"})
PERSONAL = frozenset({"contact", "identity", "location", "personal"})
LEVELS = ("restricted", "confidential", "internal", "public")
MAX_COLUMNS = 200
# A Google Cloud zone: its region and a letter — europe-west1-b.
GCP_ZONE = re.compile(r"^([a-z]+-[a-z]+\d+)-[a-z]$")
# The tags AKS and GKE put on a node beside its cluster's name: where the
# cluster is.
AKS_CLUSTER_GROUP = "aks-managed-cluster-rg"
GKE_CLUSTER_LOCATION = "goog-k8s-cluster-location"
# The record's roles towards the people it names: item → person.
PERSON_ROLES = {
    "author": "authored_by",
    "committer": "committed_by",
    "assignee": "assigned_to",
    "reviewer": "reviewed_by",
    "reporter": "reported_by",
    "creator": "created_by",
    "lead": "led_by",
    "commander": "led_by",
    "owner": "led_by",
}
# A document's people, by their role (LEKA-366): its creator is its author;
# its owner owns it; who last changed it edited it.
DOCUMENT_ROLES = {
    **PERSON_ROLES,
    "creator": "authored_by",
    "owner": "owned_by",
    "editor": "edited_by",
}
# What each tool calls a document, and where it keeps them.
DOCUMENT_KINDS = {
    "confluence": "page",
    "notion": "page",
    "slab": "post",
    "guru": "card",
    "google_workspace": "file",
    "microsoft_365": "file",
}
SPACE_KINDS = {
    "confluence": "space",
    "notion": "database",
    "slab": "topic",
    "guru": "collection",
    "google_workspace": "shared_drive",
}
# Microsoft 365's drive types: a SharePoint library, a OneDrive.
DRIVE_KINDS = {
    "documentlibrary": "document_library",
    "business": "onedrive",
    "personal": "onedrive",
}
SPACE_CAPABILITIES = frozenset({C.SPACES, C.DATABASES, C.DRIVES})
# Google Drive's own drive: no shared drive, not a space.
MY_DRIVE = "user"
# Guru's word for a card its experts vouch for — or that wants them again.
VERIFIED = {"trusted": True, "verified": True, "needs_verification": False, "unverified": False}
MAX_DESCRIPTION = 1_000
# Operations (LEKA-367): a Jira Service Management ticket that is an
# incident or a change, by its type.
JIRA_INCIDENTS = frozenset({"incident", "major incident"})
JIRA_CHANGES = frozenset(
    {"change", "change request", "normal change", "standard change", "emergency change"}
)
# A change's state from a work state, where its own word is unknown.
WORK_TO_CHANGE = {"open": "requested", "in_progress": "in_progress", "closed": "completed"}
# What makes a monitoring tool's event a deployment or a change: a tag that
# says so — alone, or as the value of `event_type:`, `type:`, `category:` —
# or, for a deployment, the continuous delivery tool that sent it.
DEPLOY_TAGS = frozenset({"deployment", "deploy", "deployed", "release", "rollout"})
CHANGE_TAGS = frozenset(
    {"change", "config_change", "configuration_change", "feature_flag", "change_event"}
)
TYPE_TAG_KEYS = frozenset({"event_type", "type", "category", "kind", "event"})
CD_SOURCES = frozenset(
    {"argocd", "argo cd", "spinnaker", "octopus deploy", "harness", "codedeploy", "flux"}
)
EVENT_TOOLS = frozenset({"datadog", "grafana"})
# GitLab's environment tiers, on LEKA's environments.
TIERS = {
    "production": "production",
    "staging": "staging",
    "testing": "test",
    "development": "development",
}
# How parsing said one thing points at another.
REFERENCE_TYPES = {
    "closes": "resolves",
    "mentions": "mentions",
    "implements": "implements",
    "merges": "merges",
}


class InvalidRecordError(ValueError):
    """The record cannot be an entity. Its message names what is missing."""


class UnsupportedRecordError(ValueError):
    """No mapping for this kind of record."""


@dataclass
class Build:
    record: ExtractedRecord
    parsed: ParsedRecord
    related: dict[str, NormalisedEntity] = field(default_factory=dict)
    relationships: dict[tuple[str, str, str], NormalisedRelationship] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    # The record's own other keys: a Jira ticket is also its bare key.
    aliases: list[str] = field(default_factory=list)
    # The source's mapping (LEKA-351): its own words, applied over the rules.
    mapping: Mapping = field(default_factory=Mapping)
    # What the record is when its capability does not say: a PagerDuty
    # business service is an application (LEKA-362).
    as_type: str | None = None
    # Where its accounts and items live, when its link does not say: a
    # deployment's link is its pipeline's, its code host's is elsewhere
    # (LEKA-367).
    code_host: str | None = None

    @property
    def kind(self) -> str:
        return self.record.provenance.source_kind.value

    @property
    def source_id(self) -> uuid.UUID:
        return self.record.provenance.source_id

    @property
    def observed_at(self) -> datetime:
        return self.record.provenance.fetched_at

    @property
    def host(self) -> str:
        """Where this record's accounts and items live: a code host, a Jira site."""
        if self.code_host:
            return self.code_host
        if self.kind == "jira":
            return ids.site_of(self.record.url) or "jira"
        return ids.host_of(self.record.url, self.kind)

    def relate(
        self, kind: str, from_key: str, to_key: str, confidence: float, evidence: str | None
    ) -> None:
        if from_key == to_key:
            return
        edge = (kind, from_key, to_key)
        known = self.relationships.get(edge)
        if known is None or confidence > known.confidence:
            self.relationships[edge] = NormalisedRelationship(
                type=kind,
                from_key=from_key,
                to_key=to_key,
                source_id=self.source_id,
                confidence=confidence,
                evidence=evidence,
            )

    def add(self, entity: NormalisedEntity) -> str:
        known = self.related.get(entity.key)
        if known is None or entity.confidence > known.confidence:
            self.related[entity.key] = entity
        return entity.key

    def person(self, reference: Reference) -> str | None:
        """A person named by the record, as an entity: by email when known,
        with their account as an alias."""
        account = (
            ids.person_account(self.host, reference.external_id) if reference.external_id else None
        )
        email = ids.person_email(reference.email) if reference.email else None
        key = email or account
        if key is None:
            return None
        name = values.name(reference.name or reference.external_id or reference.email) or key
        return self.add(
            NormalisedEntity(
                type="person",
                key=key,
                external_id=key,
                source_id=self.source_id,
                name=name,
                attributes={"source_kind": self.kind},
                aliases=[a for a in (account,) if a and a != key],
                observed_at=self.observed_at,
            )
        )


def entity(build: Build) -> NormalisedEntity:
    """The record itself, as an entity."""
    record, capability = build.record, build.record.provenance.capability
    declared = _declared(build) if capability is C.RECORDS else None
    happened = _event_kind(build) if capability is C.EVENTS else None
    if declared is None and happened is None and capability not in ENTITY_TYPES:
        raise UnsupportedRecordError(f"no mapping for {capability.value} yet")
    name = values.name(record.title)
    if not name:
        raise InvalidRecordError("no name: the extraction has no title")
    if declared is not None:
        key, attributes = _custom(build, declared)
    elif capability is C.ACCOUNTS:
        if build.kind not in CLOUDS:
            raise UnsupportedRecordError(f"no mapping for {build.kind} {capability.value} yet")
        key, attributes = _scope(build)
    elif capability in (C.SCHEMAS, C.TABLES):
        key, attributes = _data(build)
    elif capability is C.TEAMS:
        key, attributes = _team(build)
    elif capability is C.PEOPLE:
        key, attributes = _directory_person(build)
    elif happened is not None:
        build.as_type = happened
        key, attributes = _event(build, happened)
    elif capability is C.COMPONENTS:
        if build.kind not in CODE_HOSTS:
            raise UnsupportedRecordError(f"no mapping for {build.kind} {capability.value} yet")
        key, attributes = _component(build)
    elif capability is C.DEPLOYMENTS:
        if build.kind not in CODE_HOSTS:
            raise UnsupportedRecordError(f"no mapping for {build.kind} {capability.value} yet")
        key, attributes = _deployment(build)
    elif capability is C.CHANGES:
        if build.kind != "pagerduty":
            raise UnsupportedRecordError(f"no mapping for {build.kind} {capability.value} yet")
        key, attributes = _change_event(build)
    elif capability in SPACE_CAPABILITIES and build.kind in DOCUMENT_TOOLS:
        key, attributes = _space(build)
    elif capability in (C.PAGES, C.FILES) and build.kind in DOCUMENT_TOOLS:
        key, attributes = _documentation(build)
    elif capability in RESOURCE_KINDS:
        if build.kind not in CLOUDS:
            raise UnsupportedRecordError(f"no mapping for {build.kind} {capability.value} yet")
        key, attributes = _cloud(build)
    elif capability in (C.INCIDENTS, C.SERVICES):
        key, attributes = _operations(build)
    elif build.kind in PROJECT_TOOLS:
        key, attributes = _tool(build)
    else:
        key, attributes = _work(build)
    _mapped_containers(build, key)
    return NormalisedEntity(
        type=build.as_type
        or declared
        or build.mapping.entity_types.get(capability.value, ENTITY_TYPES[capability]),
        key=key,
        external_id=record.provenance.external_id,
        source_id=build.source_id,
        name=name,
        attributes=attributes,
        aliases=build.aliases,
        observed_at=build.observed_at,
    )


# ── work: code hosts and project tools ──────────────────────────────────────


def _work(build: Build) -> tuple[str, dict[str, object]]:
    record, capability = build.record, build.record.provenance.capability
    meta, container = record.metadata, record.provenance.container
    host = build.host

    if build.kind == "jira":
        issue_key = str(meta.get("key") or "")
        if not issue_key:
            raise InvalidRecordError("no key: the extraction has no metadata.key")
        site = ids.site_of(record.url)
        if site is None:
            build.diagnostics.append("no link: the Jira site is unknown, the key stands alone")
        key = ids.ticket(issue_key, site=site)
        if site:
            # How a ticket is written where its site is unknown: PAY-42 in a
            # GitHub pull request. Entity resolution joins the two by it.
            build.aliases.append(ids.ticket(issue_key, site=None))
        if capability is C.ISSUES and container:
            build.relate("part_of", key, ids.ticket(container, site=site), 1.0, "container")
        # A Jira Service Management incident, a change request (LEKA-367).
        issue_type = str(meta.get("type") or "").strip().lower()
        if capability is C.ISSUES and issue_type in JIRA_INCIDENTS:
            build.as_type = "incident"
        elif capability is C.ISSUES and issue_type in JIRA_CHANGES:
            build.as_type = "change"
    elif build.kind in CODE_HOSTS:
        repo = record.title if capability is C.REPOSITORIES else container
        if not repo:
            raise InvalidRecordError("no repository: the record has no container")
        key = _code_key(build, host, str(repo))
        if capability is not C.REPOSITORIES:
            build.relate("part_of", key, ids.repository(host, str(repo)), 1.0, "container")
    else:
        raise UnsupportedRecordError(f"no mapping for {build.kind} {capability.value} yet")

    attributes = _common(build)
    raw_priority = meta.get("priority")
    if isinstance(raw_priority, str):
        own = _own(build.mapping.priorities, raw_priority)
        attributes["priority"], known = (own, True) if own else values.priority(raw_priority)
        attributes["priority_raw"] = raw_priority
        if not known:
            build.diagnostics.append("unknown priority: kept as the vendor wrote it")
    for fact_type in (FactType.CHANGE_TYPE, FactType.SCOPE, FactType.CATEGORY):
        best = _best(build.parsed, fact_type)
        if best is not None:
            attributes[fact_type.value] = best.value
            attributes[f"{fact_type.value}_confidence"] = best.confidence
    if _best(build.parsed, FactType.BREAKING) is not None:
        attributes["breaking"] = True

    for reference in record.references:
        if reference.kind == "person" and reference.role in PERSON_ROLES:
            person = build.person(reference)
            if person:
                build.relate(PERSON_ROLES[reference.role], key, person, 1.0, "references")
        elif reference.kind == "issue" and reference.role == "parent" and reference.external_id:
            site = ids.site_of(record.url)
            parent = ids.ticket(reference.external_id, site=site)
            build.relate("child_of", key, parent, 1.0, "references")
        elif reference.kind == "issue" and reference.role in ("caused_by", "causes"):
            # Jira's cause links (LEKA-367): this one is caused by the other,
            # or causes it.
            other = ids.ticket(str(reference.external_id), site=ids.site_of(record.url))
            cause, effect = (other, key) if reference.role == "caused_by" else (key, other)
            build.relate("caused_by", effect, cause, 1.0, "references")
    if build.as_type == "change":
        _changed(build, attributes, kind=str(meta.get("type") or ""))
    _references(build, key)
    return key, attributes


def _code_key(build: Build, host: str, repo: str) -> str:
    record, capability, meta = (
        build.record,
        build.record.provenance.capability,
        build.record.metadata,
    )
    need = {
        C.PULL_REQUESTS: "number",
        C.ISSUES: "number",
        C.COMMITS: "sha",
        C.RELEASES: "tag",
    }.get(capability)
    if need and meta.get(need) in (None, ""):
        raise InvalidRecordError(f"no {need}: the extraction has no metadata.{need}")
    if capability is C.REPOSITORIES:
        return ids.repository(host, repo)
    if capability in (C.PULL_REQUESTS, C.ISSUES):
        return ids.numbered(host, repo, meta["number"], pull=capability is C.PULL_REQUESTS)
    if capability is C.COMMITS:
        return ids.commit(host, repo, str(meta["sha"]))
    if capability is C.RELEASES:
        return ids.release(host, repo, str(meta["tag"]))
    return ids.branch(host, repo, str(record.title))


def _references(build: Build, key: str) -> None:
    """What parsing found the record points at, and the people it names."""
    for fact in build.parsed.facts:
        if fact.target is None:
            continue
        if fact.type is FactType.REFERENCES and fact.value in REFERENCE_TYPES:
            target = _target_key(build, fact.target)
            if target:
                build.relate(
                    REFERENCE_TYPES[fact.value], key, target, fact.confidence, fact.evidence.field
                )
        elif fact.type is FactType.MENTIONS and fact.target.system in CODE_HOSTS:
            person = ids.person_account(ids.DEFAULT_HOSTS[fact.target.system], fact.target.key)
            build.relate("mentions", key, person, fact.confidence, fact.evidence.field)


def _target_key(build: Build, target: Target) -> str | None:
    """A parsed target's canonical key — written as '#41', 'acme/api!12',
    'PAY-42' or a sha — in the terms of the record it was read in."""
    container = build.record.provenance.container
    if target.system in CODE_HOSTS:
        host = build.host if target.system == build.kind else ids.DEFAULT_HOSTS[target.system]
        if target.kind == "commit":
            return f"commit:{target.key.lower()}"
        mark = "!" if "!" in target.key else "#"
        repo, _, number = target.key.rpartition(mark)
        repo = repo or (container if target.system == build.kind else None) or ""
        if not repo or not number.isdigit():
            return None
        return ids.numbered(host, repo, number, pull=target.kind == "pull_request" or mark == "!")
    if target.kind == "issue" and ids.JIRA_KEY.match(target.key):
        site = ids.site_of(build.record.url) if build.kind == "jira" else None
        return ids.ticket(target.key, site=site)
    return None


# ── project and documentation tools (LEKA-346) ──────────────────────────────


def _tool(build: Build) -> tuple[str, dict[str, object]]:
    """A project tool's project or issue — keyed by the tool and its own id,
    with its project, its people and its parent."""
    record, capability = build.record, build.record.provenance.capability
    own_id, container = record.provenance.external_id, record.provenance.container
    if capability is C.PROJECTS and build.kind in PROJECT_TOOLS:
        key = ids.item(build.kind, "project", own_id)
    elif capability is C.ISSUES and build.kind in PROJECT_TOOLS:
        key = _tool_issue(build, own_id)
        project = (
            next((r.external_id for r in record.references if r.kind == "project"), None)
            if build.kind == "linear"
            else container
        )
        if project:
            build.relate("part_of", key, ids.item(build.kind, "project", project), 1.0, "container")
    else:
        raise UnsupportedRecordError(f"no mapping for {build.kind} {capability.value} yet")

    attributes = _common(build)
    raw_priority = record.metadata.get("priority")
    if isinstance(raw_priority, str):
        own = _own(build.mapping.priorities, raw_priority)
        attributes["priority"], known = (own, True) if own else values.priority(raw_priority)
        attributes["priority_raw"] = raw_priority
        if not known:
            build.diagnostics.append("unknown priority: kept as the vendor wrote it")
    for reference in record.references:
        if reference.kind == "person" and reference.role in PERSON_ROLES:
            person = build.person(reference)
            if person:
                build.relate(PERSON_ROLES[reference.role], key, person, 1.0, "references")
        elif reference.role == "parent" and reference.external_id:
            parent = _tool_issue(build, reference.external_id)
            build.relate("child_of", key, parent, 1.0, "references")
    _references(build, key)
    return key, attributes


def _tool_issue(build: Build, own_id: str) -> str:
    """An issue's key. A Linear issue is its identifier in its workspace —
    'ENG-42' named in a pull request finds it by the alias ticket:ENG-42."""
    if build.kind != "linear":
        return ids.item(build.kind, "issue", own_id)
    identifier = own_id if ids.JIRA_KEY.match(own_id) else build.record.metadata.get("key")
    if not isinstance(identifier, str) or not identifier:
        raise InvalidRecordError("no key: the extraction has no metadata.key")
    path = [part for part in urlsplit(build.record.url or "").path.split("/") if part]
    ticket = ids.ticket(identifier, site=None)
    if ticket not in build.aliases and own_id == build.record.provenance.external_id:
        build.aliases.append(ticket)
    return f"linear.app/{path[0].lower()}/{identifier.upper()}" if path else ticket


# ── documentation and knowledge (LEKA-346, LEKA-366) ─────────────────────────


def _documentation(build: Build) -> tuple[str, dict[str, object]]:
    """A documentation tool's or an office suite's document — keyed by the
    tool and its own id — in its space, under its parent page, with its
    people: who wrote it, owns it, last changed it; what it links to; what
    its tool says of its verification."""
    record = build.record
    own_id, container = record.provenance.external_id, record.provenance.container
    key = _document(build, own_id, container)
    attributes = _common(build)
    attributes["document_kind"] = DOCUMENT_KINDS[build.kind]
    links = attributes.pop("links", None)
    if build.kind == "guru":
        verified = VERIFIED.get(record.state or "")
        if verified is not None:
            attributes["verified"] = verified
        slug = record.metadata.get("slug")
        if isinstance(slug, str) and slug:
            build.aliases.append(ids.item("guru", "card", slug))
    space = _space_of(build, container)
    if space is not None:
        build.relate("part_of", key, space, 1.0, "container")
    for reference in record.references:
        if reference.kind == "person" and reference.role in DOCUMENT_ROLES:
            person = build.person(reference)
            if person:
                build.relate(DOCUMENT_ROLES[reference.role], key, person, 1.0, "references")
        elif reference.role == "parent" and reference.external_id:
            if reference.kind == "space":
                space = ids.space(build.kind, reference.external_id)
                build.relate("part_of", key, space, 1.0, "references")
            else:
                parent = _document(build, reference.external_id, container)
                build.relate("child_of", key, parent, 1.0, "references")
    _references(build, key)
    _links(build, key, links)
    return key, attributes


def _document(build: Build, own_id: str, container: str | None) -> str:
    """A document's key: the tool and its id. Confluence's ids are its
    site's, so its key is the site's; a Microsoft 365 item's, its drive's."""
    return ids.document(build.kind, own_id, site=ids.site_of(build.record.url), drive=container)


def _space_of(build: Build, container: str | None) -> str | None:
    """The space a document's container is: a Confluence space by its key,
    a Slab topic, a Guru collection, a drive — never Google's own drive,
    nor a Notion page's parent, which its references say."""
    if not container or build.kind == "notion":
        return None
    if build.kind == "google_workspace" and container == MY_DRIVE:
        return None
    return ids.space(build.kind, container, site=ids.site_of(build.record.url))


def _space(build: Build) -> tuple[str, dict[str, object]]:
    """Where a tool keeps its documents — a Confluence space, a Notion
    database, a Slab topic, a Guru collection, a shared drive, a SharePoint
    library, a OneDrive — keyed as its documents name it; its kind, its
    owner where its tool says, the team and service the source's mapping
    gives its documents."""
    record = build.record
    own_id = record.provenance.external_id
    attributes = _common(build)
    raw = attributes.pop("type", None)
    for name in ("key", "owner"):
        attributes.pop(name, None)
    if build.kind == "confluence":
        own_id = str(record.metadata.get("key") or own_id).upper()
        attributes["space_key"] = own_id
    key = ids.space(build.kind, own_id, site=ids.site_of(record.url))
    if build.kind == "notion":
        # A link to a database reads as a link to a page: the same id.
        build.aliases.append(ids.item("notion", "document", own_id))
    kind = DRIVE_KINDS.get(str(raw)) if build.kind == "microsoft_365" else None
    attributes["space_kind"] = kind or SPACE_KINDS.get(build.kind) or "drive"
    if isinstance(raw, str) and raw:
        attributes["space_type"] = raw
    description = next((c.text for c in record.content if c.role == "description"), None)
    if description:
        attributes["description"] = description[:MAX_DESCRIPTION]
    for reference in record.references:
        if reference.role != "owner":
            continue
        if reference.kind == "team" and reference.name:
            team = _named(build, "team", ids.team(reference.name), reference.name, 1.0)
            build.relate("owned_by", key, team, 1.0, "references")
        elif reference.kind == "person":
            person = build.person(reference)
            if person:
                build.relate("owned_by", key, person, 1.0, "references")
    _mapped_containers(build, key, own_id)
    return key, attributes


def _links(build: Build, key: str, links: object) -> None:
    """What a document links to — in its markup (the extraction's) and in
    its text (parsing's): another document, a space — `references`; a
    repository, an issue, a pull request, a commit — `mentions`."""
    urls = [u for u in links if isinstance(u, str)] if isinstance(links, list) else []
    urls += [f.target.key for f in build.parsed.facts if f.type is FactType.LINKS_TO and f.target]
    for url in dict.fromkeys(urls):
        found = ids.linked(url)
        if found is not None:
            what, target = found
            kind = "mentions" if what == "repository" else "references"
            build.relate(kind, key, target, 0.9, "links")
            continue
        aimed = url_target(url)
        item = _target_key(build, aimed) if aimed is not None else None
        if item:
            build.relate("mentions", key, item, 0.9, "links")


def _documented(build: Build, key: str, urls: list[str], evidence: str) -> None:
    """The documents a catalogue or a business system links as a thing's
    documentation: each `describes` it."""
    for url in urls:
        found = ids.linked(url)
        if found is not None and found[0] != "repository":
            build.relate("describes", found[1], key, 1.0, evidence)


# ── custom sources (LEKA-350) ────────────────────────────────────────────────


def _declared(build: Build) -> str:
    """What the resource of a custom record declared it to be — or, when it
    declared nothing, not an entity: extracted, not modelled."""
    declared = build.record.signals.get("entity")
    if not isinstance(declared, str) or declared not in CUSTOM_ENTITIES:
        resource = build.record.signals.get("resource")
        raise UnsupportedRecordError(
            f"no entity declared for the resource {resource!r}: extracted, not modelled"
        )
    return declared


def _custom(build: Build, declared: str) -> tuple[str, dict[str, object]]:
    """A custom source's record, as the entity its resource declared: keyed
    by the source — nothing tells two unknown systems' ids apart — except a
    service, keyed by its name as PagerDuty's and a `service:` tag's are, so
    they meet, and a cloud resource a CMDB names by its provider's id — an
    ARN, an ARM id, a Google full resource name — keyed by it as the cloud
    connector's record is (LEKA-363); its state and priority on LEKA's
    scales; its author."""
    record = build.record
    provider_id = _provider_id(build) if declared in RESOURCES else None
    catalogued = _catalogued_object(build) if declared == "data_object" else None
    if declared == "service":
        key = ids.service(str(record.title))
    elif declared == "application":
        key = ids.application(str(record.title))
    elif provider_id is not None:
        key = ids.cloud(*provider_id)
    elif catalogued is not None:
        key = catalogued[0]
    elif declared == "team":
        key = ids.team(str(record.title))
    elif declared == "business_capability":
        key = ids.capability(str(record.title))
    elif declared == "business_process":
        # An activity under its process: the process's name — or its path,
        # `Order to cash/Invoicing` — then its own.
        above = next(iter(_said(build, "above", split=False)), None)
        key = ids.process(f"{above}/{record.title}" if above else str(record.title))
    elif declared == "person":
        # By address; else by the system's own id, as its teams name them.
        address = next(iter(_said(build, "email")), None)
        system_id = record.provenance.external_id.split(":", 1)[-1]
        key = ids.person_email(address) if address else ids.person_account(build.host, system_id)
    else:
        key = ids.item(f"custom-{build.source_id}", declared, record.provenance.external_id)
    attributes = _common(build)
    if declared in ("service", "application"):
        # A CMDB, a Backstage catalogue read as a custom source: what its
        # admin mapped, in the words below.
        _catalogued(build, key, attributes, application=declared == "application")
    elif declared in RESOURCES:
        _declared_resource(build, key, attributes, declared, provider_id)
    elif declared == "data_object":
        _declared_data(build, key, attributes, catalogued)
    elif declared == "person":
        _declared_person(build, key, attributes)
    elif declared == "team":
        _declared_team(build, key, attributes)
    elif declared in ("business_capability", "business_process"):
        _declared_business(build, key, attributes, process=declared == "business_process")
    elif declared == "document":
        _declared_document(build, key, attributes)
    elif declared in ("change", "deployment"):
        _declared_operation(build, key, attributes, deployment=declared == "deployment")
    stated = {"issue", "incident", "change", "deployment", *RESOURCES}
    if record.state is not None and declared in stated:
        own = _own(build.mapping.states, record.state)
        state, known = (
            (own, True)
            if own
            else values.incident_state(record.state)
            if declared == "incident"
            else values.change_state(record.state)
            if declared == "change"
            else values.deployment_state(record.state)
            if declared == "deployment"
            else values.resource_state(record.state)
            if declared in RESOURCES
            else values.work_state(record.state)
        )
        attributes["state"], attributes["state_raw"] = state, record.state
        if not known:
            build.diagnostics.append("unknown state: kept as the system wrote it")
    raw_priority = record.metadata.get("priority")
    if isinstance(raw_priority, str) and declared in ("issue", "incident"):
        own = _own(build.mapping.priorities, raw_priority)
        attributes["priority"], known = (own, True) if own else values.priority(raw_priority)
        attributes["priority_raw"] = raw_priority
        if not known:
            build.diagnostics.append("unknown priority: kept as the system wrote it")
    for reference in record.references:
        if reference.kind == "person" and reference.role in PERSON_ROLES:
            person = build.person(reference)
            if person:
                build.relate(PERSON_ROLES[reference.role], key, person, 1.0, "references")
    _references(build, key)
    return key, attributes


# ── operations: incidents and services (LEKA-348) ────────────────────────────


def _operations(build: Build) -> tuple[str, dict[str, object]]:
    """An incident — keyed by its tool and that tool's id, its state and
    priority on LEKA's scales, its people, the services it affects — or a
    service, keyed by its name: the same key as a `service:` tag's, so a
    PagerDuty service and a Datadog monitor's tag meet."""
    record, capability = build.record, build.record.provenance.capability
    if build.kind not in OPERATIONS:
        raise UnsupportedRecordError(f"no mapping for {build.kind} {capability.value} yet")
    attributes = _common(build)
    if capability is C.SERVICES:
        application = record.signals.get("kind") == "application"
        if application:
            key = ids.application(str(record.title))
            build.as_type = "application"
        else:
            key = ids.service(str(record.title))
        _catalogued(build, key, attributes, application=application)
        return key, attributes

    key = ids.incident(build.kind, record.provenance.external_id)
    if record.state is not None:
        own = _own(build.mapping.states, record.state)
        state, known = (own, True) if own else values.incident_state(record.state)
        attributes["state"], attributes["state_raw"] = state, record.state
        if not known:
            build.diagnostics.append("unknown state: kept as the vendor wrote it")
    raw_priority = next(
        (
            value
            for value in (record.metadata.get("priority"), record.metadata.get("severity"))
            if isinstance(value, str) and value
        ),
        None,
    )
    if raw_priority is not None:
        own = _own(build.mapping.priorities, raw_priority)
        attributes["priority"], known = (own, True) if own else values.priority(raw_priority)
        attributes["priority_raw"] = raw_priority
        if not known:
            build.diagnostics.append("unknown priority: kept as the vendor wrote it")
    for reference in record.references:
        if reference.kind == "person" and reference.role in PERSON_ROLES:
            person = build.person(reference)
            if person:
                build.relate(PERSON_ROLES[reference.role], key, person, 1.0, "references")
    services = [
        *(r.name for r in record.references if r.kind == "service" and r.name),
        *_names(record.signals.get("services")),
    ]
    for name in dict.fromkeys(services):
        service = _named(build, "service", ids.service(name), name, 1.0)
        build.relate("affects", key, service, 1.0, "references")
    _references(build, key)
    return key, attributes


def _names(value: object) -> list[str]:
    return [str(v) for v in value if v] if isinstance(value, list) else []


# ── changes and deployments (LEKA-367) ───────────────────────────────────────


def _deployment(build: Build) -> tuple[str, dict[str, object]]:
    """A code host's deployment — keyed in its repository by the host's id —
    part of its repository, deploying its commit and the release its ref
    names, to the environment it names; who made it; how it went, on LEKA's
    scale, each status kept with when."""
    record, meta = build.record, build.record.metadata
    repo = record.provenance.container
    if not repo:
        raise InvalidRecordError("no repository: the record has no container")
    build.code_host = _code_host(build)
    host = build.host
    repository = ids.repository(host, repo)
    key = ids.deployment(repository, str(meta.get("id") or record.provenance.external_id))
    attributes = _common(build)
    for name in ("id", "iid", "api_url", "job_url", "tier"):
        attributes.pop(name, None)
    build.relate("part_of", key, repository, 1.0, "container")
    sha, ref = meta.get("sha"), meta.get("ref")
    if isinstance(sha, str) and sha:
        build.relate("deploys", key, ids.commit(host, repo, sha), 1.0, "metadata.sha")
    if isinstance(ref, str) and ref and ref != sha:
        # A tag is a release; a branch's name, a key no release has.
        build.relate("deploys", key, ids.release(host, repo, ref), 0.8, "metadata.ref")
    _deployment_state(build, attributes)
    _deployed_to(
        build,
        key,
        attributes,
        meta.get("environment"),
        tier=meta.get("tier"),
        production=meta.get("production") is True,
    )
    for reference in record.references:
        if reference.kind == "person" and reference.role in PERSON_ROLES:
            person = build.person(reference)
            if person:
                build.relate(PERSON_ROLES[reference.role], key, person, 1.0, "references")
    return key, attributes


def _code_host(build: Build) -> str:
    """Where a deployment's repository lives: its API's host for GitHub —
    its link is its pipeline's — its job's for GitLab."""
    meta = build.record.metadata
    if build.kind == "github":
        api = meta.get("api_url")
        host = (urlsplit(api).hostname or "").lower() if isinstance(api, str) else ""
        return "github.com" if host in ("", "api.github.com") else host
    job = meta.get("job_url")
    return ids.host_of(job if isinstance(job, str) else build.record.url, build.kind)


def _deployment_state(build: Build, attributes: dict[str, object]) -> None:
    """How a deployment went, on LEKA's scale — its statuses' too, each with
    when."""
    raw = build.record.state
    if raw is not None:
        own = _own(build.mapping.states, raw)
        state, known = (own, True) if own else values.deployment_state(raw)
        attributes["state"], attributes["state_raw"] = state, raw
        if not known:
            build.diagnostics.append("unknown state: kept as the tool wrote it")
    history = attributes.get("status_history")
    if isinstance(history, list):
        # `state@when`, as the extraction keeps them: on LEKA's scale.
        steps = [str(h).partition("@") for h in history if isinstance(h, str) and h]
        attributes["status_history"] = [
            {"state": values.deployment_state(state)[0], "at": _utc(at)}
            for state, _, at in steps
            if state
        ]


def _deployed_to(
    build: Build,
    key: str,
    attributes: dict[str, object],
    word: object,
    *,
    tier: object = None,
    production: bool = False,
) -> None:
    """Where a deployment went: one of the company's environments — the
    source's own word for it, the usual words, GitLab's tier, GitHub's
    production flag — an entity it is `deployed_to`; else its word."""
    said = word.strip() if isinstance(word, str) and word.strip() else None
    own = _own(build.mapping.environments, said)
    usual = next(
        (env for env, words in ENVIRONMENTS.items() if said and said.lower() in words), None
    )
    tiered = TIERS.get(str(tier).lower()) if isinstance(tier, str) else None
    canonical = own or usual or tiered or ("production" if production else None)
    if canonical in ENVIRONMENTS:
        attributes["environment"] = canonical
        target = _named(build, "environment", ids.environment(canonical), canonical, 1.0)
        build.relate("deployed_to", key, target, 1.0, "environment")
    elif said:
        attributes["environment"] = said.lower()


def _component(build: Build) -> tuple[str, dict[str, object]]:
    """What a repository's code says it runs (LEKA-369): a service of its
    code — its repository part of it — a store, a service outside; where it
    runs; and what it relies on, each link named by its role and the file
    and line that say so (leka/connectors/components.py)."""
    meta = build.record.metadata
    kind = str(meta.get("component_kind") or "service")
    repository = str(meta.get("repository") or build.record.provenance.container or "")
    if kind == "layout":
        return _layout(build, repository)
    key = _component_key(build, kind, repository, dict(meta))
    build.as_type = COMPONENT_TYPES.get(kind, "service")
    attributes = _common(build)
    for name in ("component", "component_kind", "links", "repository", "role"):
        attributes.pop(name, None)
    role = meta.get("role")
    if kind in ("service", "external"):
        attributes["service_type"] = role
        attributes["display_name"] = build.record.title
        attributes["hosting"] = "external" if kind == "external" else "self"
        attributes["languages"] = [
            t for t in _texts(meta.get("technology")) if t in COMPONENT_LANGUAGES
        ] or None
    elif kind == "database":
        attributes["store_role"] = role
    else:
        attributes["resource_kind"] = "bucket"
        attributes["resource_class"] = "storage"
    if kind == "service" and meta.get("code_path") and repository:
        # The repository itself: its code is this service's.
        code = ids.repository(build.host, repository)
        build.relate("part_of", code, key, 1.0, f"code: {meta['code_path']}")
    environment = meta.get("environment")
    if isinstance(environment, str) and environment in ENVIRONMENTS:
        target = _named(build, "environment", ids.environment(environment), environment, 1.0)
        build.relate("runs_in", key, target, 1.0, "compose")
    for raw in _texts(meta.get("links")):
        try:
            link = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(link, dict) or not link.get("to"):
            continue
        target = _component_key(
            build,
            str(link.get("kind") or "service"),
            repository,
            {
                "component": link.get("to"),
                "engine": link.get("engine"),
                "vendor": link.get("vendor"),
            },
            title=str(link.get("display_name") or link.get("to")),
        )
        build.relate(
            "depends_on",
            key,
            target,
            LINK_CONFIDENCE.get(str(link.get("role")), 0.9),
            f"{link.get('role')}: {link.get('evidence')}",
        )
    return key, attributes


def _texts(value: object) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def _layout(build: Build, repository: str) -> tuple[str, dict[str, object]]:
    """What a repository is made of (LEKA-369): its modules, said of the
    repository itself — one entity with the record that names it."""
    meta = build.record.metadata
    build.as_type = "repository"
    modules: list[object] = []
    for line in _texts(meta.get("modules")):
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if isinstance(found, dict):
            modules.append(found)
    attributes: dict[str, object] = {"modules": modules}
    if isinstance(meta.get("default_branch"), str) and meta["default_branch"]:
        attributes["default_branch"] = meta["default_branch"]
    if isinstance(meta.get("files"), int):
        attributes["code_files"] = meta["files"]
    if meta.get("truncated"):
        attributes["layout_truncated"] = True
    return ids.repository(build.host, repository), attributes


def _component_key(
    build: Build,
    kind: str,
    repository: str,
    meta: dict[str, object],
    *,
    title: str | None = None,
) -> str:
    """A component's key: a service by its name, as every tool that names it
    writes it — Leka API, `service:leka-api`; a service outside by its
    vendor's, so that two repositories' OVH are one; a store by where it was
    read, the repository and its name in it."""
    name = title or str(build.record.title)
    if kind in ("service", "external"):
        return ids.service(name)
    where = f"{build.host}/{repository}".lower()
    component = str(meta.get("component") or name)
    if kind == "database":
        engine = str(meta.get("engine") or "unknown")
        return ids.database(engine, where, None, component)
    return ids.item(f"code:{where}", "storage", component)


def _change_event(build: Build) -> tuple[str, dict[str, object]]:
    """A change event an incident tool keeps — a deploy, a configuration
    change a pipeline sent PagerDuty: done when it was sent; the services
    it affects."""
    record = build.record
    key = ids.event("change", build.kind, record.provenance.external_id)
    attributes = _common(build)
    for name in ("links", "services", "service"):
        attributes.pop(name, None)
    attributes["state"] = "completed"
    services = [r.name for r in record.references if r.kind == "service" and r.name]
    for name in dict.fromkeys(services):
        service = _named(build, "service", ids.service(name), name, 1.0)
        build.relate("affects", key, service, 1.0, "references")
    _references(build, key)
    return key, attributes


def _event_kind(build: Build) -> str | None:
    """Whether a monitoring tool's event is a deployment or a change — by a
    tag that says so, or the delivery tool that sent it — or neither: then
    it stays evidence, not an entity."""
    if build.kind not in EVENT_TOOLS:
        return None
    tags = _names(build.record.signals.get("tags"))
    words = {t.lower() for t in tags if ":" not in t}
    for tag in tags:
        name, _, value = tag.lower().partition(":")
        if value and name in TYPE_TAG_KEYS:
            words.add(value)
    source = str(build.record.signals.get("source") or "").lower()
    if words & DEPLOY_TAGS or source in CD_SOURCES:
        return "deployment"
    if words & CHANGE_TAGS:
        return "change"
    return None


def _event(build: Build, kind: str) -> tuple[str, dict[str, object]]:
    """A deploy or a change a monitoring tool recorded — Datadog's event,
    Grafana's annotation: keyed by the tool and its id; its service — a
    deployment part of it, a change affecting it — its environment, its
    version, by its tags."""
    record = build.record
    key = ids.event(kind, build.kind, record.provenance.external_id)
    attributes = _common(build)
    tags = _names(record.signals.get("tags"))
    said = {
        name: value
        for tag in tags
        if ":" in tag
        for name, _, value in (tag.partition(":"),)
        if value
    }
    for name in ("tags", "source", "host", "team", "service", "env", "monitor_id"):
        attributes.pop(name, None)
    for name in ("priority", "aggregation_key", "dashboard_uid", "panel_id"):
        attributes.pop(name, None)
    # A Grafana region's end: when a deployment finished.
    ends = attributes.pop("ends_at", None)
    if kind == "deployment" and isinstance(ends, str):
        attributes["finished_at"] = ends
    state = record.state
    attributes.pop("state", None)
    if kind == "deployment":
        found, known = values.deployment_state(state)
        if known and found is not None:
            attributes["state"] = found
    version = said.get("version")
    if version:
        attributes["ref"] = version
    service = record.signals.get("service") or said.get("service")
    if isinstance(service, str) and service:
        target = _named(build, "service", ids.service(service), service, 0.95)
        build.relate("part_of" if kind == "deployment" else "affects", key, target, 0.95, "tags")
    environment = record.signals.get("env") or said.get("env") or said.get("environment")
    if kind == "deployment":
        _deployed_to(build, key, attributes, environment)
    elif isinstance(environment, str) and environment:
        attributes["environment"] = environment.lower()
    return key, attributes


def _changed(build: Build, attributes: dict[str, object], *, kind: str) -> None:
    """A ticket that is a change: its type — normal, standard, emergency —
    and its state on a change's scale, else its work state's."""
    word = kind.strip().lower()
    if word.endswith(" change"):
        attributes["change_type"] = word.removesuffix(" change")
    raw = build.record.state
    found, known = values.change_state(raw)
    if raw is not None and known:
        attributes["state"] = found
    elif isinstance(attributes.get("state"), str):
        attributes["state"] = WORK_TO_CHANGE.get(str(attributes["state"]), attributes["state"])


def _utc(value: object) -> str | None:
    """A date as normalisation writes them — or none for what is not one."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return values.utc(value)
    except ValueError:
        return None


# ── services and applications (LEKA-362) ─────────────────────────────────────

# What a catalogue says, in the fields its tool — or a custom source's admin —
# names it: the first of each list found.
SAID = {
    "teams": ("teams", "team", "owner", "owners"),
    "application": ("application", "system", "product"),
    "services": ("services",),
    "depends_on": ("depends_on", "dependencies", "dependsOn"),
    "criticality": ("criticality", "tier"),
    "stage": ("lifecycle", "stage"),
    "environments": ("environments", "environment"),
}
# What a CMDB says of a resource, beyond a catalogue's words (LEKA-363):
# the provider's id it goes by, what kind of resource it is, its service.
RESOURCE_SAID = {
    "resource_id": ("resource_id", "arn", "cloud_id", "provider_id"),
    "resource_kind": ("resource_kind", "kind", "type"),
    "service": ("service", "services"),
}
RESOURCES = frozenset({"infra_resource", "database"})
# What a data catalogue says of a table (LEKA-364): where it is — the same
# engine, server, database and schema a database source reads it on — its
# classification, what kinds of data it holds, what it reads from.
DATA_SAID = {
    "engine": ("engine", "database_engine", "platform"),
    "host": ("host", "server", "hostname"),
    "port": ("port",),
    "database": ("database", "database_name", "db"),
    "schema": ("schema", "schema_name", "namespace"),
    "table": ("table", "table_name"),
    "classification": ("classification", "sensitivity", "confidentiality"),
    "data_categories": ("data_categories", "categories"),
    "reads_from": ("reads_from", "upstream", "sources"),
}
# What an HR system says of a person, of a team (LEKA-365).
PEOPLE_SAID = {
    "email": ("email", "mail", "work_email"),
    "manager": ("manager", "manager_email", "reports_to"),
    "job_title": ("job_title", "position", "role"),
    "department": ("department", "division"),
    "parent": ("parent", "parent_team"),
    "members": ("members", "people"),
    "leads": ("leads", "lead", "managers", "team_lead"),
}
ENGINES = {
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "supabase": "postgresql",
    "mysql": "mysql",
    "mariadb": "mariadb",
    "sqlserver": "sqlserver",
    "sql server": "sqlserver",
    "mssql": "sqlserver",
    "oracle": "oracle",
    "mongodb": "mongodb",
    "mongo": "mongodb",
}
# A catalogue's words for how sensitive, in English and French.
CLASSIFICATION_WORDS = {
    "restricted": ("restricted", "secret", "highly confidential", "strictement confidentiel"),
    "confidential": ("confidential", "confidentiel", "sensitive", "sensible", "pii", "personal"),
    "internal": ("internal", "interne", "internal use"),
    "public": ("public",),
}
# What a business system says of a capability, of a process (LEKA-366):
# what it is under, its level, a process's type and step, what realizes or
# supports it, the data it uses, its business owner, its documentation.
BUSINESS_SAID = {
    "above": ("parent", "parent_capability", "parent_process"),
    "level": ("level",),
    "process_type": ("process_type", "type", "kind"),
    "step": ("step", "order", "sequence"),
    "capabilities": ("capabilities", "capability", "business_capabilities"),
    "processes": ("processes", "process", "business_processes"),
    "supporting_applications": ("applications", "application", "systems", "system"),
    "supporting_services": ("services", "service"),
    "data_used": ("data", "data_objects", "tables", "datasets"),
    "business_owner": ("business_owner", "owner", "owners"),
}
# What a change management tool says of a change, a CI/CD tool of a
# deployment (LEKA-367): its type and risk, what it touched, who made it and
# asked for it, when it was planned and made, what it shipped.
OPERATIONS_SAID = {
    "change_type": ("change_type", "type", "category"),
    "risk": ("risk", "risk_level"),
    "touched_services": ("services", "service", "affected_services", "cmdb_ci"),
    "touched_applications": ("applications", "application", "affected_applications"),
    "touched_resources": ("resources", "resource_id", "affected_resources"),
    "implementer": ("implementer", "assigned_to", "assignee", "deployer", "deployed_by"),
    "requester": ("requested_by", "requester", "opened_by"),
    "planned_start": ("planned_start", "planned_start_date", "start_date"),
    "planned_end": ("planned_end", "planned_end_date", "end_date"),
    "work_start": ("work_start", "actual_start", "started"),
    "work_end": ("work_end", "actual_end", "finished"),
    "version": ("version", "release", "tag"),
    "commit": ("commit", "sha", "revision"),
    "repository": ("repository", "repo"),
}
# Where a catalogue, a business system, a wiki says a thing's documentation is.
DOCUMENTATION = ("docs_url", "runbook_url", "documentation", "docs", "runbook")
# Read here, kept as relationships or on LEKA's scales, not as attributes.
CATALOGUE_FIELDS = frozenset(
    {"kind", "application", "system", "product", "services", "depends_on", "dependencies"}
    | {"dependsOn", "criticality", "tier", "lifecycle", "stage", "environments", "environment"}
    | {"capabilities", "capability", "business_capabilities"}
    | {"processes", "process", "business_processes"}
)


def _catalogued(
    build: Build, key: str, attributes: dict[str, object], *, application: bool
) -> None:
    """What a tool's catalogue says of a service or an application: who owns
    it, the application it is part of — or, for an application, its
    services — what it depends on, how critical it is, where it is in its
    life, where it runs. In its words, then on LEKA's scales."""
    for team in _said(build, "teams"):
        owner = _named(build, "team", ids.team(team), team, 1.0)
        build.relate("owned_by", key, owner, 1.0, "signals")
    if not application:
        for group in _said(build, "application")[:1]:
            target = _named(build, "application", ids.application(group), group, 1.0)
            build.relate("part_of", key, target, 1.0, "catalogue.application")
    for name in _said(build, "services"):
        service = _named(build, "service", ids.service(name), name, 1.0)
        build.relate("part_of", service, key, 1.0, "catalogue.services")
    kind, key_of = ("application", ids.application) if application else ("service", ids.service)
    for name in _said(build, "depends_on"):
        other = _named(build, kind, key_of(name), name, 1.0)
        build.relate("depends_on", key, other, 1.0, "catalogue.depends_on")
    # The business capabilities and processes it supports (LEKA-366).
    for name in _said(build, "capabilities"):
        capability = _named(build, "business_capability", ids.capability(name), name, 1.0)
        build.relate("supported_by", capability, key, 1.0, "catalogue.capabilities")
    for name in _said(build, "processes"):
        last = name.rsplit("/", 1)[-1]
        process = _named(build, "business_process", ids.process(name), last, 1.0)
        build.relate("supported_by", process, key, 1.0, "catalogue.processes")
    _documented(build, key, _documentation_urls(build), "catalogue.links")
    for name in CATALOGUE_FIELDS:
        attributes.pop(name, None)
    _rated(build, attributes)
    for word in _said(build, "environments"):
        own = _own(build.mapping.environments, word)
        usual = next((env for env, words in ENVIRONMENTS.items() if word.lower() in words), None)
        _runs_in(build, key, own or usual or word.lower(), 1.0)


def _rated(build: Build, attributes: dict[str, object]) -> None:
    """How critical a catalogue says a thing is, where in its life — in its
    words, then on LEKA's scales."""
    raw = next(iter(_said(build, "criticality", split=False)), None)
    if raw:
        level = criticality(raw)
        attributes["criticality"], attributes["criticality_raw"] = level or raw.lower(), raw
        if level is None:
            build.diagnostics.append("unknown criticality: kept as the catalogue wrote it")
    raw = next(iter(_said(build, "stage", split=False)), None)
    if raw:
        stage, known = values.stage(raw)
        attributes["stage"], attributes["stage_raw"] = stage, raw
        if not known:
            build.diagnostics.append("unknown lifecycle: kept as the catalogue wrote it")


def _documentation_urls(build: Build) -> list[str]:
    """Every link a record gives as documentation — its docs, its runbook."""
    found: list[str] = []
    for bag in (build.record.signals, build.record.metadata):
        for name in DOCUMENTATION:
            value = bag.get(name)
            items = value if isinstance(value, list) else [value]
            found += [v.strip() for v in items if isinstance(v, str) and v.strip()]
    return list(dict.fromkeys(found))


def _declared_business(
    build: Build, key: str, attributes: dict[str, object], *, process: bool
) -> None:
    """What a business system — an architecture repository, a process
    catalogue — says of a capability or a process: what it is under, its
    level, a process's type and step; the capabilities a process realizes,
    the processes realizing a capability; the applications and services
    supporting it; the data it uses — kept by name, found by enrichment —
    its business owner, a person or a team; how critical; its
    documentation."""
    said = {n for names in BUSINESS_SAID.values() for n in names}
    for name in said | set(SAID["teams"]) | set(SAID["criticality"]) | set(SAID["stage"]):
        attributes.pop(name, None)
    for name in DOCUMENTATION:
        attributes.pop(name, None)
    for above in _said(build, "above", split=False)[:1]:
        if process:
            name = above.rsplit("/", 1)[-1]
            target = _named(build, "business_process", ids.process(above), name, 1.0)
            build.relate("part_of", key, target, 1.0, "signals")
        else:
            target = _named(build, "business_capability", ids.capability(above), above, 1.0)
            build.relate("child_of", key, target, 1.0, "signals")
    for name, wanted in (("level", "level"), ("step", "step")):
        raw = next(iter(_said(build, name, split=False)), None)
        if raw is not None and raw.lstrip("Ll").isdigit():
            attributes[wanted] = int(raw.lstrip("Ll"))
    kind = next(iter(_said(build, "process_type", split=False)), None)
    if process and kind:
        attributes["process_type"] = kind.strip().lower()
    if process:
        for name in _said(build, "capabilities"):
            target = _named(build, "business_capability", ids.capability(name), name, 1.0)
            build.relate("realizes", key, target, 1.0, "signals")
    else:
        for name in _said(build, "processes"):
            own = name.rsplit("/", 1)[-1]
            target = _named(build, "business_process", ids.process(name), own, 1.0)
            build.relate("realizes", target, key, 1.0, "signals")
    for what, kind_of, key_of in (
        ("supporting_applications", "application", ids.application),
        ("supporting_services", "service", ids.service),
    ):
        for name in _said(build, what):
            target = _named(build, kind_of, key_of(name), name, 1.0)
            build.relate("supported_by", key, target, 1.0, "signals")
    data = _said(build, "data_used")
    if data:
        attributes["data_names"] = data
    owners = list(dict.fromkeys([*_said(build, "business_owner"), *_said(build, "teams")]))
    for owner in owners:
        if "@" in owner:
            person = build.person(_someone(build, owner))
            if person is not None:
                build.relate("owned_by", key, person, 1.0, "signals")
        else:
            team = _named(build, "team", ids.team(owner), owner, 1.0)
            build.relate("owned_by", key, team, 1.0, "signals")
    _rated(build, attributes)
    _documented(build, key, _documentation_urls(build), "signals")


def _declared_operation(
    build: Build, key: str, attributes: dict[str, object], *, deployment: bool
) -> None:
    """What a change management tool — ServiceNow, read as a custom source —
    says of a change, a CI/CD tool of a deployment: its type and risk; the
    services, applications and resources it affects — a deployment, the
    service it is part of, where it went; its environment; who made it and
    asked for it; when it was planned, started and finished; what it
    shipped."""
    for name in {n for names in OPERATIONS_SAID.values() for n in names}:
        attributes.pop(name, None)
    for name in SAID["environments"]:
        attributes.pop(name, None)
    if not deployment:
        for what in ("change_type", "risk"):
            word = next(iter(_said(build, what, split=False)), None)
            if word:
                attributes[what] = word.strip().lower()
    for what, name in (
        ("planned_start", "planned_start_at"),
        ("planned_end", "planned_end_at"),
        ("work_start", "started_at"),
        ("work_end", "finished_at"),
    ):
        when = _utc(next(iter(_said(build, what, split=False)), None))
        if when:
            attributes[name] = when
    touch = "part_of" if deployment else "affects"
    for name in _said(build, "touched_services"):
        service = _named(build, "service", ids.service(name), name, 1.0)
        build.relate(touch, key, service, 1.0, "signals")
    for name in _said(build, "touched_applications"):
        application = _named(build, "application", ids.application(name), name, 1.0)
        build.relate(touch, key, application, 1.0, "signals")
    for value in _said(build, "touched_resources"):
        found = _provider_of(value)
        if found is not None:
            build.relate(
                "deployed_to" if deployment else "affects", key, ids.cloud(*found), 1.0, "signals"
            )
    environment = next(iter(_said(build, "environments")), None)
    if deployment:
        _deployed_to(build, key, attributes, environment)
    elif environment:
        own = _own(build.mapping.environments, environment)
        usual = next(
            (env for env, words in ENVIRONMENTS.items() if environment.lower() in words), None
        )
        attributes["environment"] = own or usual or environment.lower()
    for what, role in (
        ("implementer", "created_by" if deployment else "assigned_to"),
        ("requester", "reported_by"),
    ):
        for someone in _said(build, what)[:1]:
            person = build.person(_someone(build, someone))
            if person is not None:
                build.relate(role, key, person, 1.0, "signals")
    if deployment:
        version = next(iter(_said(build, "version", split=False)), None)
        sha = next(iter(_said(build, "commit", split=False)), None)
        if version:
            attributes["ref"] = version
        if sha:
            attributes["sha"] = sha
        repository = next(iter(_said(build, "repository", split=False)), "")
        place = urlsplit(repository if "://" in repository else f"https://{repository}")
        host, path = (place.hostname or "").lower(), place.path.strip("/")
        # A repository its host names — github.com/acme/api — only.
        if sha and "." in host and path.count("/") >= 1:
            build.relate("deploys", key, ids.commit(host, path, sha), 1.0, "signals")


def _declared_document(build: Build, key: str, attributes: dict[str, object]) -> None:
    """What a wiki, an intranet, read as a custom source, says of a
    document: the services, applications, capabilities it is about; its
    team."""
    attributes.setdefault("document_kind", "document")
    for what, kind_of, key_of, fields in (
        ("services", "service", ids.service, ("services", "service")),
        ("application", "application", ids.application, ("application", "applications")),
        ("capabilities", "business_capability", ids.capability, ("capabilities", "capability")),
    ):
        for field_name in fields:
            attributes.pop(field_name, None)
        for name in _said(build, what):
            target = _named(build, kind_of, key_of(name), name, 1.0)
            build.relate("describes", key, target, 1.0, "signals")
    for team in _said(build, "teams"):
        owner = _named(build, "team", ids.team(team), team, 1.0)
        build.relate("owned_by", key, owner, 1.0, "signals")
    for name in SAID["teams"]:
        attributes.pop(name, None)


def _declared_resource(
    build: Build,
    key: str,
    attributes: dict[str, object],
    declared: str,
    provider_id: tuple[str, str] | None,
) -> None:
    """What a CMDB says of a server, a database: its kind and class; whose
    it is, its service and application, how critical, where it runs; what
    it depends on — a resource by its provider's id, or another record of
    the same resource by its id. In its words, then on LEKA's scales."""
    # Read from the record below; kept as relationships or on LEKA's scales.
    for name in CATALOGUE_FIELDS | {n for names in RESOURCE_SAID.values() for n in names}:
        attributes.pop(name, None)
    for name in SAID["teams"]:
        attributes.pop(name, None)
    if provider_id is not None:
        attributes["provider"] = provider_id[0]
    word = next(iter(_said(build, "resource_kind", split=False)), None)
    kind = "database" if declared == "database" else _resource_kind(word)
    if kind:
        attributes["resource_kind"] = kind
        attributes["resource_class"] = RESOURCE_CLASSES[kind]
    for team in _said(build, "teams"):
        owner = _named(build, "team", ids.team(team), team, 1.0)
        build.relate("owned_by", key, owner, 1.0, "signals")
    for name in _said(build, "service"):
        service = _named(build, "service", ids.service(name), name, 1.0)
        build.relate("part_of", key, service, 1.0, "catalogue.service")
    for group in _said(build, "application")[:1]:
        target = _named(build, "application", ids.application(group), group, 1.0)
        build.relate("part_of", key, target, 1.0, "catalogue.application")
    resource = str(build.record.signals.get("resource") or "")
    for other in _said(build, "depends_on"):
        found = _provider_of(other)
        if found is not None:
            target = ids.cloud(*found)
        elif resource:
            target = ids.item(f"custom-{build.source_id}", declared, f"{resource}:{other}")
        else:
            continue
        build.relate("depends_on", key, target, 1.0, "catalogue.depends_on")
    raw = next(iter(_said(build, "criticality", split=False)), None)
    if raw:
        level = criticality(raw)
        attributes["criticality"], attributes["criticality_raw"] = level or raw.lower(), raw
        if level is None:
            build.diagnostics.append("unknown criticality: kept as the system wrote it")
    places: list[str] = []
    for word in _said(build, "environments"):
        own = _own(build.mapping.environments, word)
        usual = next((env for env, words in ENVIRONMENTS.items() if word.lower() in words), None)
        places.append(own or usual or word.lower())
        _runs_in(build, key, places[-1], 1.0)
    if len(places) == 1:
        attributes["environment"] = places[0]


def _catalogued_object(build: Build) -> tuple[str, str, str] | None:
    """A catalogue's table, by the server, database and schema a database
    source reads it on: (its key, its database's, its schema's) — or None
    when the catalogue does not say where it is."""
    said = {name: next(iter(_said(build, name, split=False)), None) for name in DATA_SAID}
    engine = ENGINES.get(str(said["engine"] or "").strip().lower())
    host, schema = said["host"], said["schema"]
    if engine is None or not host or not schema:
        return None
    port = int(said["port"]) if said["port"] and str(said["port"]).isdigit() else None
    database = ids.database(engine, host, port, said["database"])
    name = said["table"] or str(build.record.title)
    schema_key = ids.data_schema(database, schema)
    return ids.data_object(database, schema, name), database, schema_key


def _declared_data(
    build: Build,
    key: str,
    attributes: dict[str, object],
    catalogued: tuple[str, str, str] | None,
) -> None:
    """What a data catalogue says of a table: whose it is, its service and
    application, how it is classified and what kinds of data it holds, what
    it reads from — in its words, then on LEKA's scales."""
    for name in {n for names in DATA_SAID.values() for n in names} | set(SAID["teams"]):
        attributes.pop(name, None)
    for name in ("service", "services"):
        attributes.pop(name, None)
    for team in _said(build, "teams"):
        owner = _named(build, "team", ids.team(team), team, 1.0)
        build.relate("owned_by", key, owner, 1.0, "signals")
    for name in _said(build, "service"):
        service = _named(build, "service", ids.service(name), name, 1.0)
        build.relate("part_of", key, service, 1.0, "catalogue.service")
    for group in _said(build, "application")[:1]:
        target = _named(build, "application", ids.application(group), group, 1.0)
        build.relate("part_of", key, target, 1.0, "catalogue.application")
    raw = next(iter(_said(build, "classification", split=False)), None)
    if raw:
        word = raw.strip().lower()
        level = next((lv for lv, words in CLASSIFICATION_WORDS.items() if word in words), None)
        attributes["classification"] = level or word
        attributes["classification_raw"] = raw
        if level is None:
            build.diagnostics.append("unknown classification: kept as the catalogue wrote it")
    categories = sorted({c.strip().lower() for c in _said(build, "data_categories")})
    if categories:
        attributes["data_categories"] = categories
        attributes["personal_data"] = any(c in PERSONAL for c in categories)
    if catalogued is None:
        return
    _, database, schema_key = catalogued
    build.relate("part_of", key, schema_key, 1.0, "catalogue.schema")
    build.relate("part_of", schema_key, database, 1.0, "catalogue.database")
    for table in _said(build, "reads_from"):
        other_schema, _, other = table.partition(".")
        target = ids.data_object(database, other_schema, other or other_schema)
        build.relate("reads_from", key, target, 1.0, "catalogue.reads_from")


def _declared_person(build: Build, key: str, attributes: dict[str, object]) -> None:
    """What an HR system says of a person: their address, title and
    department — their department a team — their teams, their manager."""
    for name in {n for names in PEOPLE_SAID.values() for n in names} | set(SAID["teams"]):
        attributes.pop(name, None)
    address = next(iter(_said(build, "email")), None)
    if address:
        attributes["email"] = address.strip().lower()
    title = next(iter(_said(build, "job_title", split=False)), None)
    if title:
        attributes["job_title"] = title
    department = next(iter(_said(build, "department", split=False)), None)
    if department:
        attributes["department"] = department
        _department(build, key, department)
    for team in _said(build, "teams"):
        target = _named(build, "team", ids.team(team), team, 1.0)
        build.relate("member_of", key, target, 1.0, "signals")
    for manager in _said(build, "manager")[:1]:
        above = build.person(_someone(build, manager))
        if above is not None and above != key:
            build.relate("reports_to", key, above, 1.0, "signals")


def _declared_team(build: Build, key: str, attributes: dict[str, object]) -> None:
    """What an HR system says of a team: its parent, its members, who leads
    it — people by address, or by the system's own id."""
    for name in {n for names in PEOPLE_SAID.values() for n in names}:
        attributes.pop(name, None)
    attributes["team_type"] = "team"
    for parent in _said(build, "parent")[:1]:
        above = _named(build, "team", ids.team(parent), parent, 1.0)
        build.relate("child_of", key, above, 1.0, "signals")
    for role in ("members", "leads"):
        for someone in _said(build, role):
            person = build.person(_someone(build, someone))
            if person is None:
                continue
            build.relate("member_of", person, key, 1.0, "signals")
            if role == "leads":
                build.relate("led_by", key, person, 1.0, "signals")


def _someone(build: Build, said: str) -> Reference:
    """A person an HR system names: by address, else by its own id."""
    value = said.strip()
    if "@" in value:
        return Reference(role="person", kind="person", email=value)
    return Reference(role="person", kind="person", external_id=value, name=value)


def _provider_id(build: Build) -> tuple[str, str] | None:
    """The provider's own id a CMDB gives a resource — a field of its own,
    else the record's id — when it reads as one."""
    for value in _said(build, "resource_id", split=False):
        found = _provider_of(value)
        if found is not None:
            return found
    own = build.record.provenance.external_id.split(":", 1)[-1]
    return _provider_of(own)


def _provider_of(value: str) -> tuple[str, str] | None:
    """('aws', an ARN), ('azure', an ARM id), ('gcp', a full resource name)
    — or None for an id that is none of them."""
    value = value.strip()
    if value.startswith("arn:aws"):
        return "aws", value
    if value.lower().startswith("/subscriptions/"):
        return "azure", value
    if value.startswith("//") and ".googleapis.com/" in value:
        return "gcp", value
    return None


def _resource_kind(word: str | None) -> str | None:
    if not word:
        return None
    folded = word.strip().lower()
    return next((kind for kind, words in RESOURCE_WORDS.items() if folded in words), None)


def _said(build: Build, what: str, *, split: bool = True) -> list[str]:
    """The first of `what`'s fields the record has — its signals, then its
    metadata — as text: a list, or words between commas."""
    for bag in (build.record.signals, build.record.metadata):
        said = {**SAID, **RESOURCE_SAID, **DATA_SAID, **PEOPLE_SAID, **BUSINESS_SAID}
        for name in {**said, **OPERATIONS_SAID}[what]:
            value = bag.get(name)
            if isinstance(value, list):
                found = [str(v).strip() for v in value if str(v).strip()]
            elif isinstance(value, str | int | float) and not isinstance(value, bool):
                text = str(value).strip()
                found = [p.strip() for p in text.split(",")] if split else [text]
            else:
                continue
            found = [f for f in found if f]
            if found:
                return list(dict.fromkeys(found))
    return []


def _runs_in(build: Build, key: str, environment: str | None, confidence: float) -> None:
    """Where a thing runs: one of the company's environments, an entity of
    its own — only a canonical one: `prd-eu-2` is a name, not an environment."""
    if environment not in ENVIRONMENTS:
        return
    target = _named(build, "environment", ids.environment(environment), environment, confidence)
    build.relate("runs_in", key, target, confidence, "environment")


# ── cloud resources ──────────────────────────────────────────────────────────


def _cloud(build: Build) -> tuple[str, dict[str, object]]:
    """A cloud resource: keyed by the provider's own id; its kind and class;
    where it is — its region and zone, the account, resource group or
    project it is in; what its tags say — environment, service,
    application, team, how critical, the cluster it is a node of; the
    network it is in."""
    record, capability = build.record, build.record.provenance.capability
    key = ids.cloud(build.kind, record.provenance.external_id)
    attributes = _common(build, resource=True)
    kind = RESOURCE_KINDS[capability]
    attributes["resource_kind"] = kind
    attributes["resource_class"] = RESOURCE_CLASSES[kind]
    attributes["tags"] = _tag_dict(record.signals.get("tags"))
    _placed(build, key, attributes)
    _described(build, key, attributes)
    if kind == "database":
        build.aliases += _endpoints(build, attributes)
    if kind == "cluster":
        build.aliases += _cluster_aliases(build, attributes)
    for fact in build.parsed.facts:
        if fact.type is FactType.CLUSTER and fact.value and kind != "cluster":
            cluster = _cluster_key(build, fact.value, attributes)
            if cluster:
                _resource(build, cluster, fact.value, "cluster", attributes)
                build.relate("part_of", key, cluster, fact.confidence, fact.evidence.field)

    network = next((r.external_id for r in record.references if r.kind == "network"), None)
    if network:
        network_key = _network_key(build, network)
        if network_key:
            build.relate("in_network", key, network_key, 1.0, "references")
    return key, attributes


def _described(build: Build, key: str, attributes: dict[str, object]) -> None:
    """What a cloud thing's tags say — and, less surely, its name: its
    environment, exposure and criticality as attributes; its service, its
    application and its team as relationships; where it runs."""
    for fact_type in (FactType.ENVIRONMENT, FactType.EXPOSURE, FactType.CRITICALITY):
        best = _best(build.parsed, fact_type)
        if best is not None:
            attributes[fact_type.value] = best.value
            attributes[f"{fact_type.value}_confidence"] = best.confidence
    services: list[tuple[str, float, str]] = []
    applications: list[tuple[str, float, str]] = []
    _mapped_tags(build, key, attributes, services, applications)
    if isinstance(attributes.get("environment"), str):
        # 'prd' read in a tag: the company says it is production.
        own = _own(build.mapping.environments, str(attributes["environment"]))
        attributes["environment"] = own or attributes["environment"]
    for fact in build.parsed.facts:
        if fact.type is FactType.SERVICE and fact.value:
            service = _named(build, "service", ids.service(fact.value), fact.value, fact.confidence)
            services.append((service, fact.confidence, fact.evidence.field))
        elif fact.type is FactType.APPLICATION and fact.value:
            group = ids.application(fact.value)
            _named(build, "application", group, fact.value, fact.confidence)
            applications.append((group, fact.confidence, fact.evidence.field))
        elif fact.type is FactType.OWNER and fact.value:
            team = _named(build, "team", ids.team(fact.value), fact.value, fact.confidence)
            build.relate("owned_by", key, team, fact.confidence, fact.evidence.field)
    for service, confidence, evidence in services:
        build.relate("part_of", key, service, confidence, evidence)
    # An application tag beside a service tag says the service's
    # application; alone, the resource's.
    for group, confidence, evidence in applications:
        for service, surety, _ in services or [(key, 1.0, "")]:
            build.relate("part_of", service, group, min(confidence, surety), evidence)
    environment = attributes.get("environment")
    _runs_in(
        build,
        key,
        environment if isinstance(environment, str) else None,
        float(str(attributes.get("environment_confidence", 1.0))),
    )


def _placed(build: Build, key: str, attributes: dict[str, object]) -> None:
    """Where a resource is: its region and zone, and what it is in — an AWS
    account or a Google Cloud project; an Azure resource group, in its
    subscription — each an entity of its own, the resource part of it. An
    S3 bucket's ARN names no account: enrichment finds it (enrichment.md)."""
    record, provenance = build.record, build.record.provenance
    account: str | None = None
    if build.kind == "aws":
        arn = provenance.external_id.split(":")
        account = arn[4] if len(arn) > 5 and arn[4].isdigit() else None
    elif build.kind == "azure":
        found = provenance.container or _after(provenance.external_id, "subscriptions")
        account = found.lower() if found else None
    elif build.kind == "gcp":
        # The project as the scope names it: some APIs say its number.
        account = provenance.container or _text(record.metadata.get("project"))
        location = _text(attributes.get("region"))
        zone = GCP_ZONE.match(location or "")
        if zone:
            attributes["zone"], attributes["region"] = location, zone.group(1)
    if not account:
        return
    attributes["account"] = account
    parent = _account(build, account)
    group = _text(record.metadata.get("resource_group"))
    if build.kind != "azure" or not group:
        build.relate("part_of", key, parent, 1.0, "hierarchy")
        return
    group_key = ids.cloud("azure", f"/subscriptions/{account}/resourceGroups/{group}")
    build.add(
        NormalisedEntity(
            type="resource_group",
            key=group_key,
            external_id=group_key,
            source_id=build.source_id,
            name=values.name(group) or group_key,
            attributes={"provider": "azure", "account": account, "resource_group": group},
            observed_at=build.observed_at,
        )
    )
    # The resource is in its group, the group in its subscription.
    build.relate("part_of", key, group_key, 1.0, "hierarchy")
    build.relate("part_of", group_key, parent, 1.0, "hierarchy")


def _account(build: Build, account: str) -> str:
    """The account, subscription or project a thing is in, as an entity —
    named by its id until its own record names it."""
    key = ids.cloud_account(build.kind, account)
    if key not in build.related:
        build.add(
            NormalisedEntity(
                type="cloud_account",
                key=key,
                external_id=key,
                source_id=build.source_id,
                name=account,
                attributes={
                    "provider": build.kind,
                    "account_type": ACCOUNT_TYPES[build.kind],
                    "account_id": account,
                },
                observed_at=build.observed_at,
            )
        )
    return key


def _resource(build: Build, key: str, name: str, kind: str, near: dict[str, object]) -> None:
    """A resource a record names — a node's cluster — as an entity, with
    what is known of it until its own record says more."""
    build.add(
        NormalisedEntity(
            type="infra_resource",
            key=key,
            external_id=key,
            source_id=build.source_id,
            name=values.name(name) or key,
            attributes={
                "provider": build.kind,
                "resource_kind": kind,
                "resource_class": RESOURCE_CLASSES[kind],
                **{k: near[k] for k in ("account", "region") if near.get(k)},
            },
            observed_at=build.observed_at,
        )
    )


def _cluster_key(build: Build, name: str, attributes: dict[str, object]) -> str | None:
    """A node's cluster, by the key the cluster's own record has: its ARN, its
    ARM id — from the region, the account and the group the node's tags
    name — or, at Google, the project, location and name its record is
    also known by. None when the node does not say enough."""
    tags = attributes.get("tags")
    tagged = {str(k).lower(): str(v) for k, v in tags.items()} if isinstance(tags, dict) else {}
    account, region = _text(attributes.get("account")), _text(attributes.get("region"))
    if build.kind == "aws" and account and region:
        return ids.cloud("aws", f"arn:aws:eks:{region}:{account}:cluster/{name}")
    if build.kind == "azure" and account and tagged.get(AKS_CLUSTER_GROUP):
        group = tagged[AKS_CLUSTER_GROUP]
        return ids.cloud(
            "azure",
            f"/subscriptions/{account}/resourceGroups/{group}"
            f"/providers/Microsoft.ContainerService/managedClusters/{name}",
        )
    if build.kind == "gcp" and account and tagged.get(GKE_CLUSTER_LOCATION):
        return _gke(account, tagged[GKE_CLUSTER_LOCATION], name)
    return None


def _cluster_aliases(build: Build, attributes: dict[str, object]) -> list[str]:
    """A GKE cluster's other key: its project, location and name — what its
    nodes' labels say of it."""
    account = _text(attributes.get("account"))
    # A zonal cluster's location is its zone; a regional one's, its region.
    location = _text(attributes.get("zone")) or _text(attributes.get("region"))
    name = values.name(build.record.title)
    if build.kind == "gcp" and account and location and name:
        return [_gke(account, location, name)]
    return []


def _endpoints(build: Build, attributes: dict[str, object]) -> list[str]:
    """Where a client connects to a cloud database instance — RDS's endpoint,
    an Azure flexible server's name in its engine's domain: the key a
    database source names it by (LEKA-364)."""
    host, port = _text(attributes.get("endpoint")), attributes.get("port")
    if build.kind == "aws" and host:
        return [ids.endpoint(host, port if isinstance(port, int) else None)]
    domain = AZURE_ENDPOINTS.get(str(attributes.get("resource_type") or ""))
    name = values.name(build.record.title)
    if build.kind == "azure" and domain and name:
        return [ids.endpoint(f"{name.lower()}.{domain[0]}", domain[1])]
    return []


def _gke(project: str, location: str, name: str) -> str:
    return f"gcp:cluster:{project}/{location.lower()}/{name}"


# ── people and teams (LEKA-365) ──────────────────────────────────────────────


def _team(build: Build) -> tuple[str, dict[str, object]]:
    """A team — GitHub's, PagerDuty's — keyed by its name as a tag's and a
    catalogue's team are, so they meet: its parent team, its members, who
    leads it."""
    record = build.record
    key = ids.team(str(record.title))
    slug = _text(record.metadata.get("slug"))
    if slug and ids.team(slug) != key:
        build.aliases.append(ids.team(slug))
    attributes = _common(build)
    attributes.pop("kind", None)
    attributes["team_type"] = "team"
    described = next((c.text for c in record.content if c.role == "description"), None)
    if described:
        attributes["description"] = described[:2000]
    for reference in record.references:
        if reference.kind == "team" and reference.role == "parent":
            parent = reference.name or reference.external_id
            if parent:
                above = _named(build, "team", ids.team(parent), parent, 1.0)
                build.relate("child_of", key, above, 1.0, "parent")
        elif reference.kind == "person" and reference.role in ("lead", "member"):
            person = build.person(reference)
            if person is None:
                continue
            build.relate("member_of", person, key, 1.0, "members")
            if reference.role == "lead":
                build.relate("led_by", key, person, 1.0, "members")
    return key, attributes


def _directory_person(build: Build) -> tuple[str, dict[str, object]]:
    """A person a directory describes — Microsoft 365's, Google Workspace's
    — keyed by their address, their account at the directory an alias: their
    title and department, their department a team they are a member of,
    and who they report to."""
    record = build.record
    own = next((r for r in record.references if r.role == "self"), None)
    email = ids.person_email(own.email) if own and own.email else None
    account = ids.person_account(build.host, own.external_id) if own and own.external_id else None
    key = email or account
    if key is None:
        raise InvalidRecordError("no address and no id: the person cannot be told apart")
    if email and account:
        build.aliases.append(account)
    attributes = _common(build)
    attributes.pop("kind", None)
    attributes["directory"] = build.kind
    department = _text(attributes.get("department"))
    if department:
        _department(build, key, department)
    manager = next((r for r in record.references if r.role == "manager"), None)
    if manager is not None:
        above = build.person(manager)
        if above is not None and above != key:
            build.relate("reports_to", key, above, 1.0, "manager")
    return key, attributes


def _department(build: Build, person: str, department: str) -> None:
    """A department a directory names: a team of its own kind, the person a
    member of it."""
    key = ids.team(department)
    build.add(
        NormalisedEntity(
            type="team",
            key=key,
            external_id=key,
            source_id=build.source_id,
            name=values.name(department) or key,
            attributes={"team_type": "department"},
            observed_at=build.observed_at,
        )
    )
    build.relate("member_of", person, key, 1.0, "department")


# ── data: databases, schemas, tables (LEKA-364) ──────────────────────────────


def _data(build: Build) -> tuple[str, dict[str, object]]:
    """A schema, or a table, a view, a collection — keyed by the server and
    database it was read on, part of its schema, the schema of its
    database; the tables its foreign keys reference and a view reads from;
    what kind of data its columns hold, and how sensitive. The database
    itself is named, part of the cloud instance at its endpoint."""
    record, capability = build.record, build.record.provenance.capability
    engine, host = _text(record.signals.get("engine")), _text(record.signals.get("host"))
    if engine is None or host is None:
        raise InvalidRecordError("no server: the record was read before it said its own")
    port = record.signals.get("port")
    database = _database(
        build,
        engine,
        host,
        port if isinstance(port, int) else None,
        _text(record.metadata.get("database")),
    )
    attributes = _common(build)
    for raw in ("host", "port", "database"):
        attributes.pop(raw, None)
    owner = attributes.pop("owner", None)
    if isinstance(owner, str) and owner:
        attributes["owner_role"] = owner  # a role of the database, not a team
    described = next((c.text for c in record.content if c.role == "description"), None)
    if described:
        attributes["description"] = described[:2000]
    if capability is C.SCHEMAS:
        key = ids.data_schema(database, str(record.title))
        build.relate("part_of", key, database, 1.0, "server")
        return key, attributes

    schema = str(record.metadata.get("schema") or "")
    title = str(record.title)
    name = title[len(schema) + 1 :] if schema and title.startswith(f"{schema}.") else title
    key = ids.data_object(database, schema, name)
    attributes["object_kind"] = str(attributes.pop("kind", None) or "table")
    attributes["schema_name"] = attributes.pop("schema", schema)
    build.relate("part_of", key, ids.data_schema(database, schema), 1.0, "container")
    for reference in record.references:
        if reference.kind != "table" or not reference.external_id:
            continue
        other_schema, _, other = reference.external_id.partition(".")
        target = ids.data_object(database, other_schema, other or other_schema)
        relation = "reads_from" if reference.role == "reads" else "references"
        build.relate(relation, key, target, 1.0, "references")
    _classified(build, attributes)
    return key, attributes


def _database(build: Build, engine: str, host: str, port: int | None, name: str | None) -> str:
    """The database a record was read on, as an entity — and part of the
    cloud instance a client reaches at its address, if one is known."""
    key = ids.database(engine, host, port, name)
    build.add(
        NormalisedEntity(
            type="database",
            key=key,
            external_id=key,
            source_id=build.source_id,
            name=name or host,
            attributes={
                "engine": engine,
                "host": host,
                **({"port": port} if port else {}),
                **({"database_name": name} if name else {}),
                "resource_kind": "database",
                "resource_class": "database",
            },
            observed_at=build.observed_at,
        )
    )
    build.relate("part_of", key, ids.endpoint(host, port), 1.0, "endpoint")
    return key


def _classified(build: Build, attributes: dict[str, object]) -> None:
    """What kind of data a table's columns hold, and how sensitive it is:
    restricted — a credential, a card, an account, health — confidential —
    who someone is, how to reach them, where — or what its documentation
    says, the most sensitive of them."""
    columns: dict[str, str] = {}
    surety: dict[str, float] = {}
    for fact in build.parsed.facts:
        if fact.type is FactType.DATA_CATEGORY and fact.value and fact.target:
            columns[fact.target.key] = fact.value
            surety[fact.value] = max(surety.get(fact.value, 0.0), fact.confidence)
    levels: dict[str, float] = {}
    for category, sure in surety.items():
        level = "restricted" if category in RESTRICTED else "confidential"
        levels[level] = max(levels.get(level, 0.0), sure)
    for fact in build.parsed.facts:
        if fact.type is FactType.CLASSIFICATION and fact.value in LEVELS:
            levels[fact.value] = max(levels.get(fact.value, 0.0), fact.confidence)
    if columns:
        attributes["data_categories"] = sorted(set(columns.values()))
        attributes["column_categories"] = dict(sorted(columns.items())[:MAX_COLUMNS])
        attributes["personal_data"] = any(c in PERSONAL for c in columns.values())
    if levels:
        level = min(levels, key=LEVELS.index)
        attributes["classification"] = level
        attributes["classification_confidence"] = levels[level]


# ── what resources are in (LEKA-363) ─────────────────────────────────────────


def _scope(build: Build) -> tuple[str, dict[str, object]]:
    """What resources are in, as its provider describes it: an AWS account
    — its alias, its organisation — an Azure subscription or resource
    group, a Google Cloud project — its labels, its folder or organisation.
    Its state on one scale; what its tags and name say, as a resource's."""
    record = build.record
    meta = record.metadata
    attributes = _common(build)
    attributes.pop("state", None)
    if record.state is not None:
        state, known = values.account_state(record.state)
        attributes["state"], attributes["state_raw"] = state, record.state
        if not known:
            build.diagnostics.append("unknown state: kept as the provider wrote it")
    attributes["tags"] = _tag_dict(record.signals.get("tags"))
    identifier = str(meta.get("id") or record.provenance.external_id)
    if record.signals.get("resource_type") == "resource_group":
        build.as_type = "resource_group"
        key = ids.cloud("azure", identifier)
        subscription = _text(meta.get("subscription")) or _after(identifier, "subscriptions")
        if subscription:
            attributes["account"] = subscription.lower()
            build.relate("part_of", key, _account(build, subscription.lower()), 1.0, "hierarchy")
    else:
        account = identifier.removeprefix("/subscriptions/")
        key = ids.cloud_account(build.kind, account)
        attributes["account_type"] = ACCOUNT_TYPES[build.kind]
        attributes["account_id"] = account
        number = _text(meta.get("number"))
        if build.kind == "gcp" and number and number != account:
            # What an API that names the project by its number calls it.
            build.aliases.append(ids.cloud_account("gcp", number))
    _described(build, key, attributes)
    return key, attributes


def _tag_dict(tags: object) -> dict[str, object]:
    return dict(t.split("=", 1) for t in tags if "=" in t) if isinstance(tags, list) else {}


def _after(path: str, marker: str) -> str | None:
    """'/subscriptions/s/resourceGroups/Prod/…' → 's' for 'subscriptions'."""
    parts = path.split("/")
    for index, part in enumerate(parts[:-1]):
        if part.lower() == marker.lower():
            return parts[index + 1] or None
    return None


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _named(build: Build, kind: str, key: str, name: str, confidence: float) -> str:
    return build.add(
        NormalisedEntity(
            type=kind,
            key=key,
            external_id=key,
            source_id=build.source_id,
            name=values.name(name) or key,
            confidence=confidence,
            observed_at=build.observed_at,
        )
    )


def _network_key(build: Build, network: str) -> str | None:
    """The network a resource is in, by the key the network's own record has."""
    provenance = build.record.provenance
    if build.kind == "aws":
        arn = provenance.external_id.split(":")
        if len(arn) < 5 or not provenance.container:
            return None
        return ids.cloud("aws", f"arn:aws:ec2:{provenance.container}:{arn[4]}:vpc/{network}")
    if build.kind == "gcp":
        project = build.record.metadata.get("project")
        if not project:
            return None
        return ids.cloud(
            "gcp", f"//compute.googleapis.com/projects/{project}/global/networks/{network}"
        )
    return None


# ── shared ───────────────────────────────────────────────────────────────────


def _common(build: Build, *, resource: bool = False) -> dict[str, object]:
    """What every entity carries: the extraction's metadata and signals,
    dates in UTC, a canonical state beside the vendor's, its quality."""
    record = build.record
    attributes: dict[str, object] = {"source_kind": build.kind}
    for bag in (record.metadata, record.signals):
        for name, value in bag.items():
            if name == "tags":
                continue
            if name.endswith("_at") and isinstance(value, str):
                attributes[name] = values.utc(value)
            else:
                attributes[name] = value
    attributes["url"] = record.url
    attributes["created_at"] = values.utc(record.created_at)
    attributes["updated_at"] = values.utc(record.updated_at)
    capability = record.provenance.capability
    if record.state is not None and (resource or capability in (C.ISSUES, C.PULL_REQUESTS)):
        category = record.metadata.get("status_category")
        own = _own(build.mapping.states, record.state)
        state, known = (
            (own, True)
            if own  # the company's own word for it wins, even over Jira's category
            else values.resource_state(record.state)
            if resource
            else values.work_state(
                record.state, category=category if isinstance(category, str) else None
            )
        )
        attributes["state"], attributes["state_raw"] = state, record.state
        if not known:
            build.diagnostics.append("unknown state: kept as the vendor wrote it")
    elif record.state is not None:
        attributes["state"] = record.state  # archived, published, draft: already one word
    attributes["quality"] = build.parsed.quality.score
    return {k: v for k, v in attributes.items() if v is not None}


def _own(table: dict[str, str], raw: str | None) -> str | None:
    """The source's own mapping of a vendor word, case-insensitive."""
    if not raw or not table:
        return None
    word = raw.strip().lower()
    return next((v for k, v in table.items() if k.strip().lower() == word), None)


def _mapped_containers(build: Build, key: str, container: str | None = None) -> None:
    """The service and the team the source's mapping gives the record's
    container — surer than any tag: an administrator said so. A document,
    or the space it is kept in, is not part of its service: it describes
    it (LEKA-366)."""
    container = container or build.record.provenance.container
    service = first_match(container, build.mapping.services)
    if service:
        target = _named(build, "service", ids.service(service), service, 1.0)
        documentation = build.kind in DOCUMENT_TOOLS and build.record.provenance.capability in (
            SPACE_CAPABILITIES | {C.PAGES, C.FILES}
        )
        kind = "describes" if documentation else "part_of"
        build.relate(kind, key, target, 1.0, "mapping.services")
    team = first_match(container, build.mapping.owners)
    if team:
        target = _named(build, "team", ids.team(team), team, 1.0)
        build.relate("owned_by", key, target, 1.0, "mapping.owners")


def _mapped_tags(
    build: Build,
    key: str,
    attributes: dict[str, object],
    services: list[tuple[str, float, str]],
    applications: list[tuple[str, float, str]],
) -> None:
    """The company's own tag keys: `stage` for the environment, `app` for
    the service, `product` for the application, `squad` for the team,
    `impact` for how critical it is. The services and applications found
    are added to the lists, related by the caller."""
    tags = attributes.get("tags")
    if not isinstance(tags, dict):
        return
    by_key = {str(k).strip().lower(): str(v) for k, v in tags.items() if str(v).strip()}
    keys = build.mapping.tag_keys
    for tag in keys.environment:
        value = by_key.get(tag.strip().lower())
        if value:
            word = value.strip().lower()
            known = next((env for env, words in ENVIRONMENTS.items() if word in words), None)
            attributes["environment"] = _own(build.mapping.environments, value) or known or word
            attributes["environment_confidence"] = 0.95
            break
    for tag in keys.service:
        value = by_key.get(tag.strip().lower())
        if value:
            target = _named(build, "service", ids.service(value), value, 0.95)
            services.append((target, 0.95, "mapping.tag_keys.service"))
    for tag in keys.application:
        value = by_key.get(tag.strip().lower())
        if value:
            group = _named(build, "application", ids.application(value), value, 0.95)
            applications.append((group, 0.95, "mapping.tag_keys.application"))
    for tag in keys.criticality:
        value = by_key.get(tag.strip().lower())
        if value:
            attributes["criticality"] = criticality(value) or value.strip().lower()
            attributes["criticality_confidence"] = 0.95
            break
    for tag in keys.owner:
        value = by_key.get(tag.strip().lower())
        if value:
            target = _named(build, "team", ids.team(value), value, 0.95)
            build.relate("owned_by", key, target, 0.95, "mapping.tag_keys.owner")


def _best(parsed: ParsedRecord, kind: FactType) -> Fact | None:
    """The surest fact of this type; the first found on a tie."""
    found = [f for f in parsed.facts if f.type is kind]
    return max(found, key=lambda f: f.confidence) if found else None
