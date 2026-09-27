"""From an extraction and its parse to candidates in LEKA's structures.

The record becomes ONE entity — its type from its capability, its key from
identifiers.py, its attributes canonical (values.py): what the extraction
said, dates in UTC, states and priorities on LEKA's scale, the facts parsing
was surest of. The people it names become person entities; the services and
teams its tags name, service and team entities. What it points at becomes a
relationship to that thing's key, whether or not any source has shown it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from leka.connectors import Capability
from leka.ingestion.extraction import ExtractedRecord, Reference
from leka.ingestion.normalisation import identifiers as ids
from leka.ingestion.normalisation import values
from leka.ingestion.parsing import Fact, FactType, ParsedRecord, Target
from leka.ingestion.schemas import NormalisedEntity, NormalisedRelationship

C = Capability
CODE_HOSTS = frozenset({"github", "gitlab", "bitbucket"})
CLOUDS = frozenset({"aws", "azure", "gcp"})

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
# The record's roles towards the people it names: item → person.
PERSON_ROLES = {
    "author": "authored_by",
    "committer": "committed_by",
    "assignee": "assigned_to",
    "reviewer": "reviewed_by",
    "reporter": "reported_by",
    "creator": "created_by",
    "lead": "led_by",
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
    if capability not in ENTITY_TYPES:
        raise UnsupportedRecordError(f"no mapping for {capability.value} yet")
    name = values.name(record.title)
    if not name:
        raise InvalidRecordError("no name: the extraction has no title")
    if capability in RESOURCE_KINDS:
        if build.kind not in CLOUDS:
            raise UnsupportedRecordError(f"no mapping for {build.kind} {capability.value} yet")
        key, attributes = _cloud(build)
    else:
        key, attributes = _work(build)
    return NormalisedEntity(
        type=ENTITY_TYPES[capability],
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
        attributes["priority"], known = values.priority(raw_priority)
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


# ── cloud resources ──────────────────────────────────────────────────────────


def _cloud(build: Build) -> tuple[str, dict[str, object]]:
    record, capability = build.record, build.record.provenance.capability
    key = ids.cloud(build.kind, record.provenance.external_id)
    attributes = _common(build, resource=True)
    attributes["resource_kind"] = RESOURCE_KINDS[capability]
    tags = record.signals.get("tags")
    attributes["tags"] = (
        dict(t.split("=", 1) for t in tags if "=" in t) if isinstance(tags, list) else {}
    )

    for fact_type in (FactType.ENVIRONMENT, FactType.EXPOSURE):
        best = _best(build.parsed, fact_type)
        if best is not None:
            attributes[fact_type.value] = best.value
            attributes[f"{fact_type.value}_confidence"] = best.confidence
    for fact in build.parsed.facts:
        if fact.type is FactType.SERVICE and fact.value:
            service = _named(build, "service", ids.service(fact.value), fact.value, fact.confidence)
            build.relate("part_of", key, service, fact.confidence, fact.evidence.field)
        elif fact.type is FactType.OWNER and fact.value:
            team = _named(build, "team", ids.team(fact.value), fact.value, fact.confidence)
            build.relate("owned_by", key, team, fact.confidence, fact.evidence.field)

    network = next((r.external_id for r in record.references if r.kind == "network"), None)
    if network:
        network_key = _network_key(build, network)
        if network_key:
            build.relate("in_network", key, network_key, 1.0, "references")
    return key, attributes


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
        state, known = (
            values.resource_state(record.state)
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


def _best(parsed: ParsedRecord, kind: FactType) -> Fact | None:
    """The surest fact of this type; the first found on a tie."""
    found = [f for f in parsed.facts if f.type is kind]
    return max(found, key=lambda f: f.confidence) if found else None
