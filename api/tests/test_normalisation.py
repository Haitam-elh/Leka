"""Normalisation (LEKA-356): many sources, one structure, the same keys.

Vendor payloads go through the whole pipeline — extraction, parsing, then
normalisation — so what is asserted is what the pipeline would hand the
graph. The dataset is one small company seen from GitHub, GitLab,
Bitbucket, Jira and three clouds: the same ticket, person or network named
by several of them must come out with the same key.
"""

from __future__ import annotations

from typing import Any

import pytest

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction import ExtractedRecord
from leka.ingestion.normalisation import (
    NormalisationFailure,
    NormalisedRecord,
    normalise,
    normalise_stored,
    values,
)
from leka.ingestion.normalisation import identifiers as ids
from leka.ingestion.parsing import ParsedRecord, parse
from tests.test_extraction import BITBUCKET_PR, GITHUB_PR, GITLAB_MR, JIRA_ISSUE, _extract

ARN = "arn:aws:ec2:eu-west-3:123456789012"


def _pipeline(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> tuple[ExtractedRecord, ParsedRecord]:
    extracted = _extract(kind, capability, payload, **extra)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)
    return extracted, parsed


def _normalised(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> NormalisedRecord:
    result = normalise(*_pipeline(kind, capability, payload, **extra))
    assert isinstance(result, NormalisedRecord), result
    return result


def _edges(record: NormalisedRecord) -> set[tuple[str, str]]:
    return {(r.type, r.to_key) for r in record.relationships}


def _failure(result: object) -> NormalisationFailure:
    assert isinstance(result, NormalisationFailure), result
    return result


# ── one pull request, three hosts ────────────────────────────────────────────


def test_a_pull_request_is_the_same_entity_shape_on_every_host() -> None:
    github = _normalised(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR)
    gitlab = _normalised(SourceKind.GITLAB, Capability.PULL_REQUESTS, GITLAB_MR)
    bitbucket = _normalised(SourceKind.BITBUCKET, Capability.PULL_REQUESTS, BITBUCKET_PR)

    for pr in (github, gitlab, bitbucket):
        assert pr.entity.type == "pull_request"
        assert pr.entity.attributes["state"] == "merged"
        assert str(pr.entity.attributes["updated_at"]).endswith("Z")
    assert github.entity.key == "github.com/acme/payments#42"
    assert gitlab.entity.key == "gitlab.com/acme/payments!42"
    assert bitbucket.entity.key == "bitbucket.org/acme/payments!42"
    assert ("part_of", "github.com/acme/payments") in _edges(github)
    # GitLab's +02:00 comes out in UTC.
    assert gitlab.entity.attributes["created_at"] == "2026-09-18T08:00:00Z"


def test_what_a_pull_request_closes_is_the_issue_s_own_key() -> None:
    pr = _normalised(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR)  # "Fixes #41."
    issue = _normalised(
        SourceKind.GITHUB,
        Capability.ISSUES,
        {
            "title": "Webhook lost",
            "number": 41,
            "state": "open",
            "html_url": "https://github.com/acme/payments/issues/41",
        },
    )

    assert ("resolves", issue.entity.key) in _edges(pr)
    assert issue.entity.attributes["state"] == "open"


# ── one ticket, two tools ────────────────────────────────────────────────────


def test_a_ticket_named_in_github_is_the_jira_ticket_by_its_alias() -> None:
    pr = _normalised(
        SourceKind.GITHUB,
        Capability.PULL_REQUESTS,
        {**GITHUB_PR, "head": {"ref": "feature/pay-42-retry"}},
    )
    jira = _normalised(
        SourceKind.JIRA, Capability.ISSUES, {**JIRA_ISSUE, "key": "PAY-42"}, container="PAY"
    )

    assert jira.entity.key == "acme.atlassian.net/PAY-42"
    assert "ticket:PAY-42" in jira.entity.aliases
    assert ("implements", "ticket:PAY-42") in _edges(pr)


def test_a_jira_issue_in_canonical_terms() -> None:
    issue = _normalised(SourceKind.JIRA, Capability.ISSUES, JIRA_ISSUE, container="PAY")

    attributes = issue.entity.attributes
    assert attributes["state"] == "in_progress"  # its status category, not its name
    assert attributes["state_raw"] == "in progress"
    assert (attributes["priority"], attributes["priority_raw"]) == ("high", "high")
    assert attributes["category"] == "bug"
    assert attributes["created_at"] == "2026-09-18T06:00:00Z"  # +0200 → UTC
    edges = _edges(issue)
    assert ("part_of", "acme.atlassian.net/PAY") in edges
    assert ("child_of", "acme.atlassian.net/PAY-1") in edges
    assert ("assigned_to", "person:acme.atlassian.net:u1") in edges


# ── one person, many sources ─────────────────────────────────────────────────


def test_a_person_is_their_email_across_hosts_and_their_login_is_an_alias() -> None:
    commit = {
        "sha": "9F2C",
        "commit": {
            "message": "Retry",
            "author": {"name": "Sara K.", "email": "Sara@Acme.io", "date": "2026-09-20T09:00:00Z"},
        },
        "author": {"login": "Sara"},
    }
    github = _normalised(SourceKind.GITHUB, Capability.COMMITS, commit)
    gitlab = _normalised(
        SourceKind.GITLAB,
        Capability.COMMITS,
        {"id": "7a1b", "title": "Retry", "author_name": "Sara K.", "author_email": "sara@acme.io"},
    )
    pr = _normalised(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR)

    (sara,) = github.related
    assert sara.type == "person"
    assert sara.key == "person:email:sara@acme.io"
    assert sara.aliases == ["person:github.com:sara"]
    assert gitlab.related[0].key == sara.key
    # The pull request names her by login: the alias joins them.
    assert ("authored_by", "person:github.com:sara") in _edges(pr)
    assert github.entity.key == "github.com/acme/payments@9f2c"


# ── cloud: one vocabulary for three providers ────────────────────────────────


def test_a_running_instance_is_running_on_every_cloud() -> None:
    aws = _normalised(
        SourceKind.AWS,
        Capability.INSTANCES,
        {"InstanceId": "i-1", "State": {"Name": "running"}},
        container="eu-west-3",
        external_id=f"{ARN}:instance/i-1",
    )
    gcp = _normalised(
        SourceKind.GCP,
        Capability.INSTANCES,
        {
            "name": "//compute.googleapis.com/projects/p/zones/z/instances/vm",
            "assetType": "compute.googleapis.com/Instance",
            "resource": {"data": {"name": "vm", "status": "RUNNING"}},
        },
        external_id="//compute.googleapis.com/projects/p/zones/z/instances/vm",
    )

    for resource in (aws, gcp):
        assert resource.entity.type == "infra_resource"
        assert resource.entity.attributes["resource_kind"] == "instance"
        assert resource.entity.attributes["state"] == "running"
    assert aws.entity.key == f"aws:{ARN}:instance/i-1"


def test_tags_become_a_service_a_team_and_an_environment() -> None:
    instance = _normalised(
        SourceKind.AWS,
        Capability.INSTANCES,
        {
            "InstanceId": "i-1",
            "VpcId": "vpc-1",
            "Tags": [
                {"Key": "env", "Value": "prod"},
                {"Key": "service", "Value": "Billing API"},
                {"Key": "team", "Value": "Payments"},
            ],
        },
        container="eu-west-3",
        external_id=f"{ARN}:instance/i-1",
    )
    vpc = _normalised(
        SourceKind.AWS,
        Capability.NETWORKS,
        {"VpcId": "vpc-1"},
        container="eu-west-3",
        external_id=f"{ARN}:vpc/vpc-1",
    )

    attributes = instance.entity.attributes
    assert (attributes["environment"], attributes["environment_confidence"]) == ("production", 0.95)
    assert attributes["tags"] == {"env": "prod", "service": "Billing API", "team": "Payments"}
    assert {(e.type, e.key, e.name) for e in instance.related} == {
        ("service", "service:billing-api", "Billing API"),
        ("team", "team:payments", "Payments"),
    }
    edges = _edges(instance)
    assert {("part_of", "service:billing-api"), ("owned_by", "team:payments")} <= edges
    # The instance's network is the VPC record's own key.
    assert ("in_network", vpc.entity.key) in edges


def test_an_azure_id_is_one_key_whatever_its_case() -> None:
    upper = "/subscriptions/S1/resourceGroups/Prod/providers/Microsoft.Compute/virtualMachines/VM"

    vm = _normalised(
        SourceKind.AZURE,
        Capability.INSTANCES,
        {"id": upper, "name": "vm", "type": "Microsoft.Compute/virtualMachines"},
        external_id=upper,
    )

    assert vm.entity.key == "azure:" + upper.lower()


# ── canonical values and identifiers ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "category", "canonical"),
    [
        ("opened", None, "open"),
        ("OPEN", None, "open"),
        ("declined", None, "closed"),
        ("MERGED", None, "merged"),
        ("Code Review", "indeterminate", "in_progress"),
        ("Done", "done", "closed"),
    ],
)
def test_work_states(raw: str, category: str | None, canonical: str) -> None:
    assert values.work_state(raw, category=category) == (canonical, True)


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("running", "running"),
        ("RUNNING", "running"),
        ("Succeeded", "running"),
        ("available", "running"),
        ("terminated", "stopped"),
        ("shutting-down", "stopping"),
        ("PROVISIONING", "starting"),
    ],
)
def test_resource_states(raw: str, canonical: str) -> None:
    assert values.resource_state(raw) == (canonical, True)


def test_an_unknown_state_is_kept_and_said() -> None:
    issue = _normalised(
        SourceKind.GITHUB, Capability.ISSUES, {"title": "x", "number": 1, "state": "Frozen"}
    )

    assert issue.entity.attributes["state"] == "frozen"
    assert issue.diagnostics == ["unknown state: kept as the vendor wrote it"]


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("Highest", "highest"),
        ("blocker", "highest"),
        ("major", "high"),
        ("Normal", "medium"),
        ("trivial", "lowest"),
    ],
)
def test_priorities(raw: str, canonical: str) -> None:
    assert values.priority(raw) == (canonical, True)


def test_identifiers_are_spelled_one_way() -> None:
    assert ids.repository("github.com", "Acme/Payments.git/") == "github.com/acme/payments"
    assert ids.numbered("github.com", "acme/api", 3, pull=True) == "github.com/acme/api#3"
    assert ids.numbered("gitlab.com", "acme/api", 3, pull=True) == "gitlab.com/acme/api!3"
    assert ids.ticket("pay-42", site=None) == "ticket:PAY-42"
    assert ids.person_email(" Sara@Acme.IO ") == "person:email:sara@acme.io"
    assert ids.service("Billing  API") == ids.service("billing-api") == "service:billing-api"
    assert ids.host_of("https://www.github.com/acme", "github") == "github.com"
    assert ids.host_of(None, "gitlab") == "gitlab.com"
    assert values.utc("2026-09-20T10:00:00.123456+02:00") == "2026-09-20T08:00:00Z"


# ── provenance, contract, failures ───────────────────────────────────────────


def test_the_provenance_is_kept() -> None:
    extracted, parsed = _pipeline(
        SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR, external_id="PR_kw"
    )

    result = normalise(extracted, parsed)

    assert isinstance(result, NormalisedRecord)
    assert result.provenance == extracted.provenance
    assert result.entity.external_id == "PR_kw"
    assert result.entity.source_id == extracted.provenance.source_id
    assert {r.source_id for r in result.relationships} == {extracted.provenance.source_id}
    assert NormalisedRecord.model_validate_json(result.model_dump_json()) == result


def test_a_pull_request_without_its_number_is_invalid() -> None:
    extracted, parsed = _pipeline(
        SourceKind.GITHUB, Capability.PULL_REQUESTS, {**GITHUB_PR, "number": None}
    )

    failure = _failure(normalise(extracted, parsed))

    assert (failure.code.value, failure.message) == (
        "invalid",
        "no number: the extraction has no metadata.number",
    )


def test_a_kind_no_rule_maps_is_unsupported() -> None:
    extracted, parsed = _pipeline(SourceKind.GITHUB, Capability.ISSUES, {"title": "x", "number": 1})
    elsewhere = extracted.model_copy(
        update={
            "provenance": extracted.provenance.model_copy(update={"source_kind": SourceKind.SLACK})
        }
    )
    parsed = parsed.model_copy(update={"provenance": elsewhere.provenance})

    assert _failure(normalise(elsewhere, parsed)).code.value == "unsupported"


def test_a_parse_of_another_record_is_refused() -> None:
    one, _ = _pipeline(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR, external_id="a")
    _, other = _pipeline(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR, external_id="b")

    assert _failure(normalise(one, other)).code.value == "malformed"


def test_stored_inputs_that_no_longer_read_are_named_not_quoted() -> None:
    failure = _failure(normalise_stored({"title": "the-customer-text"}, {}))

    assert failure.code.value == "malformed"
    assert "the-customer-text" not in failure.message


def test_one_invalid_record_does_not_stop_its_neighbours() -> None:
    good = _pipeline(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR)
    bad = _pipeline(SourceKind.GITHUB, Capability.PULL_REQUESTS, {**GITHUB_PR, "number": None})

    assert [normalise(*p).status for p in (good, bad, good)] == [
        "normalised",
        "failed",
        "normalised",
    ]
