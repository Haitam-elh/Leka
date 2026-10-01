"""From an extraction and its parse to candidates in LEKA's structures.

The record becomes ONE entity — its type from its capability, its key from
identifiers.py, its attributes canonical (values.py): what the extraction
said, dates in UTC, states and priorities on LEKA's scale, the facts parsing
was surest of. The people it names become person entities; the services,
applications, teams and environments its tags and catalogues name, entities
of their own. What it points at becomes a relationship to that thing's key,
whether or not any source has shown it. A cloud resource is placed in what
it is in — an AWS account, an Azure resource group and its subscription, a
Google Cloud project — each an entity too (LEKA-363).
"""

from __future__ import annotations

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
    # What resources are in; an Azure resource group says so itself.
    C.ACCOUNTS: "cloud_account",
}
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
    if declared is None and capability not in ENTITY_TYPES:
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
    elif capability in RESOURCE_KINDS:
        if build.kind not in CLOUDS:
            raise UnsupportedRecordError(f"no mapping for {build.kind} {capability.value} yet")
        key, attributes = _cloud(build)
    elif capability in (C.INCIDENTS, C.SERVICES):
        key, attributes = _operations(build)
    elif build.kind in PROJECT_TOOLS or build.kind in DOCUMENT_TOOLS:
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
    """A project tool's project or issue, a documentation tool's or an office
    suite's document — keyed by the tool and its own id, with its project,
    its people and its parent."""
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
    elif capability in (C.PAGES, C.FILES) and build.kind in DOCUMENT_TOOLS:
        key = _document(build, own_id, container)
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
            parent = (
                _tool_issue(build, reference.external_id)
                if reference.kind == "issue"
                else _document(build, reference.external_id, container)
            )
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


def _document(build: Build, own_id: str, container: str | None) -> str:
    """A document's key: the tool and its id. Confluence's ids are its
    site's, so its key is the site's; a Microsoft 365 item's, its drive's."""
    if build.kind == "confluence":
        site = ids.site_of(build.record.url)
        return f"{site}/wiki/pages/{own_id}" if site else ids.item("confluence", "page", own_id)
    if build.kind == "microsoft_365" and container:
        return ids.item("microsoft_365", "document", f"{container}/{own_id}")
    return ids.item(build.kind, "document", own_id)


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
    if declared == "service":
        key = ids.service(str(record.title))
    elif declared == "application":
        key = ids.application(str(record.title))
    elif provider_id is not None:
        key = ids.cloud(*provider_id)
    else:
        key = ids.item(f"custom-{build.source_id}", declared, record.provenance.external_id)
    attributes = _common(build)
    if declared in ("service", "application"):
        # A CMDB, a Backstage catalogue read as a custom source: what its
        # admin mapped, in the words below.
        _catalogued(build, key, attributes, application=declared == "application")
    elif declared in RESOURCES:
        _declared_resource(build, key, attributes, declared, provider_id)
    if record.state is not None and declared in {"issue", "incident", *RESOURCES}:
        own = _own(build.mapping.states, record.state)
        state, known = (
            (own, True)
            if own
            else values.incident_state(record.state)
            if declared == "incident"
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
# Read here, kept as relationships or on LEKA's scales, not as attributes.
CATALOGUE_FIELDS = frozenset(
    {"kind", "application", "system", "product", "services", "depends_on", "dependencies"}
    | {"dependsOn", "criticality", "tier", "lifecycle", "stage", "environments", "environment"}
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
    for name in CATALOGUE_FIELDS:
        attributes.pop(name, None)
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
    for word in _said(build, "environments"):
        own = _own(build.mapping.environments, word)
        usual = next((env for env, words in ENVIRONMENTS.items() if word.lower() in words), None)
        _runs_in(build, key, own or usual or word.lower(), 1.0)


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
        for name in {**SAID, **RESOURCE_SAID}[what]:
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


def _gke(project: str, location: str, name: str) -> str:
    return f"gcp:cluster:{project}/{location.lower()}/{name}"


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


def _mapped_containers(build: Build, key: str) -> None:
    """The service and the team the source's mapping gives the record's
    container — surer than any tag: an administrator said so."""
    container = build.record.provenance.container
    service = first_match(container, build.mapping.services)
    if service:
        target = _named(build, "service", ids.service(service), service, 1.0)
        build.relate("part_of", key, target, 1.0, "mapping.services")
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
