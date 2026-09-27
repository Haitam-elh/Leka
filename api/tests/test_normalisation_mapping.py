"""A source's mapping, applied by normalisation (LEKA-351).

Vendor payloads through extraction and parsing, then normalised with the
mapping an administrator saved: the company's own words win over LEKA's
defaults, and what they add — services, teams — joins the model with the
certainty of someone having said so.
"""

from __future__ import annotations

from typing import Any

from leka.connectors import Capability, Mapping, SourceKind
from leka.connectors.settings import OwnerRule, ServiceRule, TagKeys
from leka.ingestion.normalisation import NormalisedRecord, normalise
from leka.ingestion.parsing import ParsedRecord, parse
from tests.test_extraction import GITHUB_PR, JIRA_ISSUE, _extract

ARN = "arn:aws:ec2:eu-west-3:123456789012"


def _normalised(
    kind: SourceKind,
    capability: Capability,
    payload: dict[str, Any],
    mapping: Mapping,
    **extra: Any,
) -> NormalisedRecord:
    extracted = _extract(kind, capability, payload, **extra)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)
    result = normalise(extracted, parsed, mapping)
    assert isinstance(result, NormalisedRecord), result
    return result


def _edges(record: NormalisedRecord) -> set[tuple[str, str, float]]:
    return {(r.type, r.to_key, r.confidence) for r in record.relationships}


def test_a_capability_s_records_become_the_entity_type_it_is_mapped_to() -> None:
    issue = _normalised(
        SourceKind.GITHUB,
        Capability.ISSUES,
        {"title": "Checkout down", "number": 7, "state": "open"},
        Mapping(entity_types={"issues": "incident"}),
    )

    assert issue.entity.type == "incident"
    assert issue.entity.key == "github.com/acme/payments#7"  # the key does not change


def test_containers_are_mapped_to_their_service_and_team() -> None:
    mapping = Mapping(
        services=[ServiceRule(match="acme/pay*", service="Billing")],
        owners=[OwnerRule(match="acme/*", team="Payments")],
    )

    pr = _normalised(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR, mapping)

    assert {(e.type, e.key, e.confidence) for e in pr.related if e.type != "person"} == {
        ("service", "service:billing", 1.0),
        ("team", "team:payments", 1.0),
    }
    assert {("part_of", "service:billing", 1.0), ("owned_by", "team:payments", 1.0)} <= _edges(pr)


def test_the_company_s_state_and_priority_words_win() -> None:
    payload = {
        **JIRA_ISSUE,
        "fields": {
            **JIRA_ISSUE["fields"],
            "status": {"name": "QA Review", "statusCategory": {"key": "new"}},
            "priority": {"name": "P0"},
        },
    }

    issue = _normalised(
        SourceKind.JIRA,
        Capability.ISSUES,
        payload,
        Mapping(states={"qa review": "in_progress"}, priorities={"P0": "highest"}),
        container="PAY",
    )

    attributes = issue.entity.attributes
    assert (attributes["state"], attributes["state_raw"]) == ("in_progress", "qa review")
    assert (attributes["priority"], attributes["priority_raw"]) == ("highest", "p0")
    assert issue.diagnostics == []  # known now: nothing kept as the vendor wrote it


def test_the_company_s_tag_keys_say_the_environment_the_service_and_the_team() -> None:
    instance = _normalised(
        SourceKind.AWS,
        Capability.INSTANCES,
        {
            "InstanceId": "i-1",
            "Tags": [
                {"Key": "stage", "Value": "prd"},
                {"Key": "app", "Value": "billing"},
                {"Key": "squad", "Value": "payments"},
            ],
        },
        Mapping(
            tag_keys=TagKeys(environment=["stage"], service=["app"], owner=["squad"]),
            environments={"prd": "production"},
        ),
        container="eu-west-3",
        external_id=f"{ARN}:instance/i-1",
    )

    attributes = instance.entity.attributes
    assert (attributes["environment"], attributes["environment_confidence"]) == ("production", 0.95)
    assert {("part_of", "service:billing", 0.95), ("owned_by", "team:payments", 0.95)} <= _edges(
        instance
    )


def test_an_environment_word_read_in_a_usual_tag_is_mapped_too() -> None:
    instance = _normalised(
        SourceKind.AWS,
        Capability.INSTANCES,
        {"InstanceId": "i-1", "Tags": [{"Key": "env", "Value": "prd"}]},
        Mapping(environments={"PRD": "production"}),
        container="eu-west-3",
        external_id=f"{ARN}:instance/i-1",
    )

    assert instance.entity.attributes["environment"] == "production"


def test_no_mapping_changes_nothing() -> None:
    plain = _normalised(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR, Mapping())

    assert plain.entity.type == "pull_request"
    assert [e for e in plain.related if e.type in {"service", "team"}] == []
