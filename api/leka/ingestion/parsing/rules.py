"""What a record's fields mean, beyond its text.

Work items: a Conventional Commits title says the kind of change, its scope,
whether it breaks; a branch name carries its ticket; labels and issue types
say what kind of work it is. Cloud resources: their tags — and, less surely,
their names — say which environment, service, application and team they
belong to, and how critical they are; their configuration says whether the
internet reaches them; the tags a Kubernetes service puts on its nodes say
which cluster they are a node of. What resources are in — an account, a
subscription, a resource group, a project — is read the same way: its name
says its environment more surely than a resource's (LEKA-363).

Every rule reads the extraction's unified fields (docs/extraction.md), so it
holds for GitHub, GitLab and Bitbucket alike, for AWS, Azure and Google
Cloud alike.
"""

from __future__ import annotations

import re

from leka.connectors import Capability
from leka.ingestion.extraction import ExtractedRecord
from leka.ingestion.parsing.contract import Evidence, Fact, FactType, Target
from leka.ingestion.parsing.text import ticket_in_branch

CONVENTIONAL = re.compile(
    r"^(?P<type>feat|fix|chore|docs|refactor|perf|test|tests|build|ci|style|revert)"
    r"(?:\((?P<scope>[^)\n]{1,50})\))?(?P<bang>!)?:\s+\S",
    re.IGNORECASE,
)
BREAKING_NOTE = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)
GITHUB_MERGE = re.compile(r"^Merge pull request #(?P<n>\d+) from (?P<branch>\S+)")

CHANGE_CATEGORY = {"feat": "feature", "fix": "bug", "docs": "docs"}  # else: maintenance

LABEL_CATEGORIES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(bug|defect|regression)\b", re.I), "bug"),
    (re.compile(r"\b(incident|outage|sev[ -]?[0-4]|postmortem)\b", re.I), "incident"),
    (re.compile(r"\b(security|vulnerabilit(y|ies)|cve)\b", re.I), "security"),
    (re.compile(r"\b(feature|enhancement|story)\b", re.I), "feature"),
    (re.compile(r"\b(docs?|documentation)\b", re.I), "docs"),
    (re.compile(r"\b(chore|maintenance|tech[ -]?debt|refactor(ing)?)\b", re.I), "maintenance"),
]
TYPE_CATEGORIES = {
    "bug": "bug",
    "story": "feature",
    "feature": "feature",
    "enhancement": "feature",
    "improvement": "feature",
    "proposal": "feature",
    "new feature": "feature",
    "task": "task",
    "sub-task": "task",
    "subtask": "task",
    "epic": "epic",
    "incident": "incident",
}

CLOUD = frozenset(
    {
        Capability.INSTANCES,
        Capability.DB_INSTANCES,
        Capability.BUCKETS,
        Capability.FUNCTIONS,
        Capability.CLUSTERS,
        Capability.NETWORKS,
        Capability.LOAD_BALANCERS,
        Capability.ACCOUNTS,
    }
)
ENVIRONMENT_KEYS = frozenset({"env", "environment", "stage"})
SERVICE_KEYS = frozenset({"service", "app", "component"})
# An application is what several services make together: Backstage's
# "system", a product.
APPLICATION_KEYS = frozenset({"application", "system", "product"})
OWNER_KEYS = frozenset({"team", "owner", "squad", "maintainer", "owning-team"})
CRITICALITY_KEYS = frozenset(
    {"criticality", "business-criticality", "business_criticality", "service-tier", "service_tier"}
)
# `tier` says an environment in some companies (tier=prod), how critical a
# thing is in others (tier=1): read by its value, nothing when it says neither.
TIER = "tier"
# Criticality words, by level; a tier number is read by TIERS.
CRITICALITIES = {
    "critical": ("critical", "mission-critical", "business-critical", "crit", "very-high", "vital"),
    "high": ("high", "important"),
    "medium": ("medium", "moderate", "normal", "standard"),
    "low": ("low", "minor", "non-critical", "noncritical", "best-effort"),
}
TIER_NUMBER = re.compile(r"^(?:tier-?|t)?(\d)$")
TIERS = ("critical", "critical", "high", "medium", "low")
# The tags EKS, GKE and AKS put on a cluster's nodes, naming the cluster;
# `kubernetes.io/cluster/<name>` says it in its key.
CLUSTER_KEYS = frozenset(
    {
        "eks:cluster-name",
        "aws:eks:cluster-name",
        "goog-k8s-cluster-name",
        "aks-managed-cluster-name",
    }
)
CLUSTER_PREFIX = "kubernetes.io/cluster/"
# How surely a name says an environment: an account, a subscription, a
# resource group, a project is named for its environment more often than
# not ("acme-prod", "Production"); a resource's name, less so.
NAMED_ENVIRONMENT = 0.5
NAMED_SCOPE_ENVIRONMENT = 0.7
ENVIRONMENTS = {
    "production": ("prod", "production", "prd", "live"),
    "staging": ("staging", "stage", "stg", "preprod", "pre-prod", "uat"),
    "development": ("dev", "development", "sandbox"),
    "test": ("test", "testing", "qa"),
}


def for_record(record: ExtractedRecord) -> list[Fact]:
    capability = record.provenance.capability
    if capability in CLOUD:
        return _cloud(record)
    facts = _categories(record)
    if capability in {Capability.COMMITS, Capability.PULL_REQUESTS}:
        facts += _change(record)
    if capability is Capability.COMMITS:
        facts += _merge(record)
    for reference in record.references:
        if reference.kind == "branch" and reference.role == "source_branch" and reference.name:
            facts += _branch_ticket(reference.name, "references.source_branch")
    if capability is Capability.BRANCHES and record.title:
        facts += _branch_ticket(record.title, "title")
    return facts


# ── work items ───────────────────────────────────────────────────────────────


def _change(record: ExtractedRecord) -> list[Fact]:
    """A Conventional Commits title: its type, its scope, whether it breaks."""
    title = record.title or ""
    match = CONVENTIONAL.match(title)
    facts: list[Fact] = []
    if match:
        kind = match.group("type").lower()
        kind = "test" if kind == "tests" else kind
        evidence = Evidence(field="title", excerpt=title[:120])
        facts.append(
            Fact(type=FactType.CHANGE_TYPE, value=kind, confidence=0.95, evidence=evidence)
        )
        facts.append(
            Fact(
                type=FactType.CATEGORY,
                value=CHANGE_CATEGORY.get(kind, "maintenance"),
                confidence=0.8,
                evidence=evidence,
            )
        )
        if match.group("scope"):
            scope = match.group("scope").strip().lower()
            facts.append(Fact(type=FactType.SCOPE, value=scope, confidence=0.9, evidence=evidence))
        if match.group("bang"):
            facts.append(
                Fact(type=FactType.BREAKING, value="true", confidence=0.95, evidence=evidence)
            )
    for content in record.content:
        if BREAKING_NOTE.search(content.text):
            facts.append(
                Fact(
                    type=FactType.BREAKING,
                    value="true",
                    confidence=0.95,
                    evidence=Evidence(field=f"content.{content.role}", excerpt="BREAKING CHANGE:"),
                )
            )
    return facts


def _merge(record: ExtractedRecord) -> list[Fact]:
    """GitHub's merge commit names the pull request it merged, and its branch."""
    match = GITHUB_MERGE.match(record.title or "")
    if not match or record.provenance.source_kind.value != "github":
        return []
    evidence = Evidence(field="title", excerpt=(record.title or "")[:120])
    pull = Target(kind="pull_request", key=f"#{match.group('n')}", system="github")
    facts = [
        Fact(
            type=FactType.REFERENCES,
            value="merges",
            target=pull,
            confidence=0.95,
            evidence=evidence,
        )
    ]
    branch = match.group("branch").split("/", 1)[-1]
    return facts + _branch_ticket(branch, "title")


def _branch_ticket(name: str, field: str) -> list[Fact]:
    ticket = ticket_in_branch(name)
    if ticket is None:
        return []
    return [
        Fact(
            type=FactType.REFERENCES,
            value="implements",
            target=ticket,
            confidence=0.8,
            evidence=Evidence(field=field, excerpt=name[:120]),
        )
    ]


def _categories(record: ExtractedRecord) -> list[Fact]:
    """What kind of work: the vendor's own type first, then its labels."""
    facts: list[Fact] = []
    kind = record.metadata.get("type")
    if isinstance(kind, str) and kind.lower() in TYPE_CATEGORIES:
        facts.append(
            Fact(
                type=FactType.CATEGORY,
                value=TYPE_CATEGORIES[kind.lower()],
                confidence=0.95,
                evidence=Evidence(field="metadata.type", excerpt=kind[:120]),
            )
        )
    labels = record.metadata.get("labels")
    for label in labels if isinstance(labels, list) else []:
        for pattern, category in LABEL_CATEGORIES:
            if pattern.search(label):
                facts.append(
                    Fact(
                        type=FactType.CATEGORY,
                        value=category,
                        confidence=0.85,
                        evidence=Evidence(field="metadata.labels", excerpt=label[:120]),
                    )
                )
                break
    return facts


# ── cloud resources ──────────────────────────────────────────────────────────


def _cloud(record: ExtractedRecord) -> list[Fact]:
    tags = record.signals.get("tags")
    pairs = [tuple(t.split("=", 1)) for t in tags if "=" in t] if isinstance(tags, list) else []
    facts: list[Fact] = []
    for key, value in pairs:
        normalized_key = key.strip().lower()
        evidence = Evidence(field="signals.tags", excerpt=f"{key}={value}"[:120])
        if not value.strip():
            continue
        if normalized_key in ENVIRONMENT_KEYS:
            known = _environment(value)
            facts.append(
                Fact(
                    type=FactType.ENVIRONMENT,
                    value=known or value.strip().lower(),
                    confidence=0.95 if known else 0.8,
                    evidence=evidence,
                )
            )
        elif normalized_key == TIER:
            if known := _environment(value):
                facts.append(
                    Fact(type=FactType.ENVIRONMENT, value=known, confidence=0.9, evidence=evidence)
                )
            elif level := criticality(value):
                facts.append(
                    Fact(type=FactType.CRITICALITY, value=level, confidence=0.9, evidence=evidence)
                )
        elif normalized_key in CRITICALITY_KEYS:
            level = criticality(value)
            facts.append(
                Fact(
                    type=FactType.CRITICALITY,
                    value=level or value.strip().lower(),
                    confidence=0.95 if level else 0.8,
                    evidence=evidence,
                )
            )
        elif normalized_key in SERVICE_KEYS:
            facts.append(
                Fact(type=FactType.SERVICE, value=value.strip(), confidence=0.9, evidence=evidence)
            )
        elif normalized_key in APPLICATION_KEYS:
            facts.append(
                Fact(
                    type=FactType.APPLICATION,
                    value=value.strip(),
                    confidence=0.9,
                    evidence=evidence,
                )
            )
        elif normalized_key in OWNER_KEYS:
            facts.append(
                Fact(type=FactType.OWNER, value=value.strip(), confidence=0.9, evidence=evidence)
            )
        elif normalized_key in CLUSTER_KEYS:
            facts.append(
                Fact(type=FactType.CLUSTER, value=value.strip(), confidence=1.0, evidence=evidence)
            )
    named = {f.value for f in facts if f.type is FactType.CLUSTER}
    for key, _ in pairs:
        # `kubernetes.io/cluster/billing=owned`: the cluster is in the key.
        cluster = key.strip()
        if not cluster.lower().startswith(CLUSTER_PREFIX):
            continue
        cluster = cluster[len(CLUSTER_PREFIX) :]
        if cluster and cluster not in named:
            named.add(cluster)
            facts.append(
                Fact(
                    type=FactType.CLUSTER,
                    value=cluster,
                    confidence=1.0,
                    evidence=Evidence(field="signals.tags", excerpt=key[:120]),
                )
            )
    if not any(f.type is FactType.ENVIRONMENT for f in facts) and record.title:
        guess = _environment_in_name(record.title)
        if guess:
            scope = record.provenance.capability is Capability.ACCOUNTS
            facts.append(
                Fact(
                    type=FactType.ENVIRONMENT,
                    value=guess,
                    confidence=NAMED_SCOPE_ENVIRONMENT if scope else NAMED_ENVIRONMENT,
                    evidence=Evidence(field="title", excerpt=record.title[:120]),
                )
            )
    facts += _exposure(record)
    return facts


def _environment(value: str) -> str | None:
    word = value.strip().lower()
    return next((name for name, words in ENVIRONMENTS.items() if word in words), None)


def criticality(value: str) -> str | None:
    """How critical, on one scale — critical, high, medium, low — or None
    for a word it does not know. A tier is a number, 1 the most critical
    (0 too, where a company counts from it): `tier-1`, `T1`, `1`."""
    word = re.sub(r"[\s_]+", "-", value.strip().lower())
    tier = TIER_NUMBER.match(word)
    if tier:
        return TIERS[min(int(tier.group(1)), len(TIERS) - 1)]
    return next((level for level, words in CRITICALITIES.items() if word in words), None)


def _environment_in_name(name: str) -> str | None:
    """'api-prod-1' → production. A guess: 'products' is not production."""
    tokens = set(re.split(r"[^a-z0-9]+", name.lower()))
    found = {env for env, words in ENVIRONMENTS.items() if tokens & set(words)}
    return found.pop() if len(found) == 1 else None


def _exposure(record: ExtractedRecord) -> list[Fact]:
    public = record.signals.get("public")
    scheme = record.signals.get("scheme")
    if isinstance(public, bool):
        value, field, excerpt = ("public" if public else "internal"), "signals.public", str(public)
    elif isinstance(scheme, str) and scheme in {"internet-facing", "external", "external_managed"}:
        value, field, excerpt = "public", "signals.scheme", scheme
    elif isinstance(scheme, str) and scheme in {
        "internal",
        "internal_managed",
        "internal_self_managed",
    }:
        value, field, excerpt = "internal", "signals.scheme", scheme
    else:
        return []
    return [
        Fact(
            type=FactType.EXPOSURE,
            value=value,
            confidence=0.95,
            evidence=Evidence(field=field, excerpt=excerpt),
        )
    ]
