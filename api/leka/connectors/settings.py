"""What a source contributes, and how it maps into the company model (LEKA-351).

A source's SETTINGS, beside its connector config, versioned:

    scope     include / exclude rules on each record's SCOPE KEY — its
              container: a repository (acme/api), a Jira project (PAY), a
              region (eu-west-3), a subscription, a Google Cloud project.
              Glob patterns, case-insensitive. Excluded: matched by an
              exclude rule, or — when there are include rules — by none of
              them. A record with no container (S3's global bucket list) is
              not subject to the rules.
    mapping   how its records are read into the model: the entity type of a
              capability, the service and the team a container belongs to,
              the tag keys this company uses, its own words for states,
              priorities and environments (applied by leka.ingestion's
              normalisation).
    retention how many days its raw payloads are kept — shorter than LEKA's
              policy for its kind, never longer (applied by the sync, when a
              payload is written; LEKA-348).

The connector config chooses what the connector reads (an organisation, a
list of projects); the scope rules filter what it read, the same way for
every connector. Rules in docs/connectors/scope-and-mapping.md.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The canonical vocabularies a mapping may map into — normalisation's
# (leka/ingestion/normalisation/values.py), stated here for validation.
ENTITY_TYPES = frozenset(
    {
        "repository",
        "pull_request",
        "issue",
        "commit",
        "branch",
        "release",
        "project",
        "service",
        "incident",
        "document",
        "deployment",
        "database",
        "infra_resource",
        "cloud_account",
    }
)
WORK_STATES = frozenset({"open", "in_progress", "closed", "merged"})
RESOURCE_STATES = frozenset(
    {"running", "starting", "stopping", "stopped", "deleting", "terminated", "failed"}
)
PRIORITIES = frozenset({"highest", "high", "medium", "low", "lowest"})
ENVIRONMENTS = frozenset({"production", "staging", "development", "test"})

Pattern = str
# The longest a source may ask for; its kind's policy is the real bound.
MAX_RETENTION_DAYS = 365


class ScopeRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[Pattern] = Field(
        default_factory=list, max_length=200, description="Only these containers. Empty: all."
    )
    exclude: list[Pattern] = Field(
        default_factory=list, max_length=200, description="Never these containers."
    )


class ServiceRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: Pattern
    service: str = Field(min_length=1, max_length=200)


class OwnerRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: Pattern
    team: str = Field(min_length=1, max_length=200)


class TagKeys(BaseModel):
    """This company's tag keys, beside the usual ones (env, service, team…)."""

    model_config = ConfigDict(extra="forbid")

    environment: list[str] = Field(default_factory=list, max_length=20)
    service: list[str] = Field(default_factory=list, max_length=20)
    # A group of services (LEKA-362): `system`, `product`, beside `application`.
    application: list[str] = Field(default_factory=list, max_length=20)
    owner: list[str] = Field(default_factory=list, max_length=20)
    # How critical: `business-impact`, beside `criticality` and `tier`.
    criticality: list[str] = Field(default_factory=list, max_length=20)


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_types: dict[str, str] = Field(
        default_factory=dict, description="capability → entity type: issues → incident."
    )
    services: list[ServiceRule] = Field(
        default_factory=list, max_length=200, description="Containers → the service they are."
    )
    owners: list[OwnerRule] = Field(
        default_factory=list, max_length=200, description="Containers → the team that owns them."
    )
    tag_keys: TagKeys = Field(default_factory=TagKeys)
    states: dict[str, str] = Field(
        default_factory=dict, description="The vendor's state → LEKA's: 'QA Review' → in_progress."
    )
    priorities: dict[str, str] = Field(default_factory=dict)
    environments: dict[str, str] = Field(default_factory=dict, description="'prd' → production.")


class Retention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int | None = Field(
        default=None,
        ge=1,
        le=MAX_RETENTION_DAYS,
        description="How long the raw payloads are kept, in days — at most LEKA's policy "
        "for this kind of source. Empty: the policy.",
    )


class SourceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: ScopeRules = Field(default_factory=ScopeRules)
    mapping: Mapping = Field(default_factory=Mapping)
    retention: Retention = Field(default_factory=Retention)


class Finding(BaseModel):
    """What is wrong with a setting (`error`: refused) or may be (`warning`)."""

    model_config = ConfigDict(frozen=True)

    level: Literal["error", "warning"]
    path: str = Field(description="Where: scope.include[2], mapping.states.QA Review, …")
    message: str


# ── applying the scope ──────────────────────────────────────────────────────


def matches(key: str, pattern: Pattern) -> bool:
    return fnmatch.fnmatchcase(key.lower(), pattern.strip().lower())


def in_scope(key: str | None, rules: ScopeRules) -> bool:
    """Whether a record whose container is `key` is LEKA's to keep."""
    if key is None:
        return True
    if any(matches(key, pattern) for pattern in rules.exclude):
        return False
    return not rules.include or any(matches(key, pattern) for pattern in rules.include)


def first_match(key: str | None, rules: list[ServiceRule] | list[OwnerRule]) -> str | None:
    """The first rule's target whose pattern the key matches."""
    if key is None:
        return None
    for rule in rules:
        if matches(key, rule.match):
            return rule.service if isinstance(rule, ServiceRule) else rule.team
    return None


# ── checking ─────────────────────────────────────────────────────────────────


def check(
    settings: SourceSettings,
    *,
    capabilities: frozenset[str],
    visible: list[str] | None,
    longest: int | None = None,
) -> list[Finding]:
    """Everything wrong or doubtful with these settings. `visible` is the
    containers the credentials can see (the connector's scope options), or
    None when they could not be listed: a rule that matches none of them is
    a warning — it may be a typo, or a container not created yet. `longest`
    is LEKA's retention policy for the source's kind: a retention above it is
    a warning — the policy applies."""
    findings: list[Finding] = []
    scope, mapping = settings.scope, settings.mapping
    days = settings.retention.days
    if days is not None and longest is not None and days > longest:
        findings.append(
            Finding(
                level="warning",
                path="retention.days",
                message=f"LEKA keeps this kind of source {longest} days at most: "
                f"{longest} will apply",
            )
        )

    patterns = [
        *((f"scope.include[{i}]", p) for i, p in enumerate(scope.include)),
        *((f"scope.exclude[{i}]", p) for i, p in enumerate(scope.exclude)),
        *((f"mapping.services[{i}].match", r.match) for i, r in enumerate(mapping.services)),
        *((f"mapping.owners[{i}].match", r.match) for i, r in enumerate(mapping.owners)),
    ]
    for path, pattern in patterns:
        problem = _bad_pattern(pattern)
        if problem:
            findings.append(Finding(level="error", path=path, message=problem))

    both = {p.strip().lower() for p in scope.include} & {p.strip().lower() for p in scope.exclude}
    for pattern in sorted(both):
        findings.append(
            Finding(
                level="error",
                path="scope",
                message=f"'{pattern}' is both included and excluded",
            )
        )

    for capability, entity_type in mapping.entity_types.items():
        path = f"mapping.entity_types.{capability}"
        if capability not in capabilities:
            findings.append(
                Finding(level="error", path=path, message="this source does not read it")
            )
        if entity_type not in ENTITY_TYPES:
            findings.append(
                Finding(
                    level="error",
                    path=path,
                    message=f"not an entity type: one of {', '.join(sorted(ENTITY_TYPES))}",
                )
            )

    for name, table, allowed in (
        ("states", mapping.states, WORK_STATES | RESOURCE_STATES),
        ("priorities", mapping.priorities, PRIORITIES),
        ("environments", mapping.environments, ENVIRONMENTS),
    ):
        for raw, canonical in table.items():
            if canonical not in allowed:
                findings.append(
                    Finding(
                        level="error",
                        path=f"mapping.{name}.{raw}",
                        message=f"not one of {', '.join(sorted(allowed))}",
                    )
                )

    seen: dict[str, str] = {}
    for facet in ("environment", "service", "application", "owner", "criticality"):
        for key in getattr(mapping.tag_keys, facet):
            other = seen.setdefault(key.strip().lower(), facet)
            if other != facet:
                findings.append(
                    Finding(
                        level="error",
                        path=f"mapping.tag_keys.{facet}",
                        message=f"tag key '{key}' is already the {other}",
                    )
                )

    pairs = {
        "services": [(r.match, r.service) for r in mapping.services],
        "owners": [(r.match, r.team) for r in mapping.owners],
    }
    for name, rules in pairs.items():
        targets: dict[str, str] = {}
        for i, (match, target) in enumerate(rules):
            known = targets.setdefault(match.strip().lower(), target)
            if known != target:
                findings.append(
                    Finding(
                        level="error",
                        path=f"mapping.{name}[{i}]",
                        message=f"'{match}' already maps to '{known}'",
                    )
                )

    if visible is None:
        if patterns:
            findings.append(
                Finding(
                    level="warning",
                    path="scope",
                    message="the containers the credentials can see could not be listed: "
                    "the rules were not checked against them",
                )
            )
    else:
        for path, pattern in patterns:
            if not _bad_pattern(pattern) and not any(matches(v, pattern) for v in visible):
                findings.append(
                    Finding(
                        level="warning",
                        path=path,
                        message=f"'{pattern}' matches nothing these credentials can see",
                    )
                )
        if scope.include and visible and not any(in_scope(v, scope) for v in visible):
            findings.append(
                Finding(level="warning", path="scope", message="these rules exclude everything")
            )
    return findings


def _bad_pattern(pattern: str) -> str | None:
    if not pattern.strip():
        return "an empty pattern"
    if len(pattern) > 300:
        return "longer than 300 characters"
    try:
        re.compile(fnmatch.translate(pattern))
    except re.error:
        return "not a valid pattern: check its [ ]"
    if pattern.count("[") != pattern.count("]"):
        return "not a valid pattern: check its [ ]"
    return None
