"""A source's settings (LEKA-351): what the rules mean, and what is refused.

Pure functions: the scope rules applied to a record's container, and the
check of a whole settings document — errors refuse it, warnings do not.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from leka.connectors import (
    Mapping,
    Retention,
    ScopeRules,
    SourceSettings,
    first_match,
    in_scope,
)
from leka.connectors import settings as settings_module
from leka.connectors.settings import OwnerRule, ServiceRule, TagKeys, check
from leka.ingestion.normalisation import mapping as normalisation_mapping
from leka.ingestion.normalisation import values
from leka.ingestion.parsing import rules as parsing_rules

READS = frozenset({"repositories", "issues", "pull_requests"})
VISIBLE = ["acme/api", "acme/payments", "acme/legacy-billing"]


def _check(settings: SourceSettings, visible: list[str] | None = VISIBLE) -> list[tuple[str, str]]:
    return [(f.level, f.path) for f in check(settings, capabilities=READS, visible=visible)]


# ── the scope ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "rules", "kept"),
    [
        ("acme/api", ScopeRules(), True),
        ("acme/legacy-billing", ScopeRules(exclude=["acme/legacy-*"]), False),
        ("acme/api", ScopeRules(include=["acme/payments"]), False),
        ("acme/payments", ScopeRules(include=["acme/*"], exclude=["*/payments"]), False),
        ("ACME/API", ScopeRules(include=["acme/api"]), True),  # case does not matter
        ("PAY", ScopeRules(include=["PAY", "OPS"]), True),
        ("eu-west-3", ScopeRules(include=["eu-*"]), True),
        (None, ScopeRules(include=["acme/*"]), True),  # no container: not subject to rules
    ],
)
def test_the_scope_rules(key: str | None, rules: ScopeRules, kept: bool) -> None:
    assert in_scope(key, rules) is kept


def test_the_first_matching_rule_names_the_service() -> None:
    rules = [
        ServiceRule(match="acme/pay*", service="billing"),
        ServiceRule(match="*", service="core"),
    ]

    assert first_match("acme/payments", rules) == "billing"
    assert first_match("acme/api", rules) == "core"
    assert first_match(None, rules) is None


# ── the check: errors ────────────────────────────────────────────────────────


def test_default_settings_are_fine() -> None:
    assert _check(SourceSettings()) == []


def test_a_container_both_included_and_excluded_is_a_conflict() -> None:
    found = _check(SourceSettings(scope=ScopeRules(include=["acme/*"], exclude=["ACME/*"])))

    assert ("error", "scope") in found


def test_a_broken_or_empty_pattern_is_refused() -> None:
    found = _check(SourceSettings(scope=ScopeRules(include=["acme/[api", " "])))

    assert ("error", "scope.include[0]") in found
    assert ("error", "scope.include[1]") in found


def test_an_entity_type_must_exist_for_a_capability_the_source_reads() -> None:
    found = _check(
        SourceSettings(mapping=Mapping(entity_types={"issues": "incident", "commits": "thing"}))
    )

    assert ("error", "mapping.entity_types.commits") in found  # not read, and not a type
    assert not [p for level, p in found if p == "mapping.entity_types.issues"]


def test_canonical_values_must_be_leka_s() -> None:
    found = _check(
        SourceSettings(
            mapping=Mapping(
                states={"QA Review": "in_progress", "Parked": "sleeping"},
                priorities={"P0": "highest", "P9": "whenever"},
                environments={"prd": "production", "lab": "laboratory"},
            )
        )
    )

    assert [p for level, p in found if level == "error"] == [
        "mapping.states.Parked",
        "mapping.priorities.P9",
        "mapping.environments.lab",
    ]


def test_one_tag_key_cannot_mean_two_things() -> None:
    found = _check(
        SourceSettings(mapping=Mapping(tag_keys=TagKeys(environment=["stage"], service=["Stage"])))
    )

    assert ("error", "mapping.tag_keys.service") in found


def test_one_pattern_cannot_map_to_two_services_or_teams() -> None:
    found = _check(
        SourceSettings(
            mapping=Mapping(
                services=[
                    ServiceRule(match="acme/pay*", service="billing"),
                    ServiceRule(match="acme/pay*", service="payments"),
                ],
                owners=[
                    OwnerRule(match="acme/*", team="core"),
                    OwnerRule(match="acme/*", team="core"),
                ],
            )
        )
    )

    assert ("error", "mapping.services[1]") in found
    assert not [p for _, p in found if p.startswith("mapping.owners")]  # the same twice is fine


def test_unknown_fields_are_refused_when_read() -> None:
    with pytest.raises(ValidationError):
        SourceSettings.model_validate({"scope": {"includes": ["acme/*"]}})


# ── the check: warnings, against what the credentials can see ────────────────


def test_a_rule_that_matches_nothing_visible_is_a_warning() -> None:
    found = _check(SourceSettings(scope=ScopeRules(include=["acme/api", "acme/apii"])))

    assert found == [("warning", "scope.include[1]")]


def test_rules_that_exclude_everything_are_said() -> None:
    found = _check(
        SourceSettings(scope=ScopeRules(include=["acme/*"], exclude=["acme/*-*", "*i", "*s"]))
    )

    assert ("warning", "scope") in found


def test_when_the_credentials_cannot_list_the_rules_are_not_checked_against_them() -> None:
    found = _check(SourceSettings(scope=ScopeRules(include=["acme/apii"])), visible=None)

    assert found == [("warning", "scope")]


# ── one vocabulary with normalisation ────────────────────────────────────────


def test_the_vocabularies_are_normalisation_s() -> None:
    assert set(values.WORK_STATES.values()) == settings_module.WORK_STATES
    assert set(values.RESOURCE_STATES.values()) == settings_module.RESOURCE_STATES
    assert set(values.PRIORITIES.values()) == settings_module.PRIORITIES
    assert set(parsing_rules.ENVIRONMENTS) == settings_module.ENVIRONMENTS
    assert set(normalisation_mapping.ENTITY_TYPES.values()) <= settings_module.ENTITY_TYPES


# ── retention (LEKA-348) ─────────────────────────────────────────────────────


def test_a_retention_within_the_policy_is_fine_a_longer_one_a_warning() -> None:
    within = SourceSettings(retention=Retention(days=14))
    longer = SourceSettings(retention=Retention(days=60))

    assert check(within, capabilities=frozenset(), visible=None, longest=30) == []
    findings = check(longer, capabilities=frozenset(), visible=None, longest=30)
    assert [(f.level, f.path) for f in findings] == [("warning", "retention.days")]
    assert "30" in findings[0].message


@pytest.mark.parametrize("days", [0, -3, 366])
def test_a_retention_out_of_bounds_is_refused(days: int) -> None:
    with pytest.raises(ValidationError):
        Retention(days=days)
