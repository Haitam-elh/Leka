"""Extraction (LEKA-354): stored vendor records in, one shape out.

Pure functions: no database, no network. The payloads are trimmed copies of
what each vendor's API returns — the fields a strategy reads, and a few it
must ignore.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from leka.connectors import Capability, RawRecord, SourceKind, get_connector
from leka.ingestion.checksum import checksum
from leka.ingestion.extraction import (
    MAX_TEXT,
    ExtractedRecord,
    ExtractionFailure,
    FailureCode,
    extract,
    strategy_for,
)

SOURCE = uuid.UUID("00000000-0000-0000-0000-00000000c0de")
FETCHED = datetime(2026, 9, 27, 12, tzinfo=UTC)
SECRET = "the-customer-text-that-must-not-leak"

GITHUB_PR: dict[str, Any] = {
    "node_id": "PR_kwDOA",
    "number": 42,
    "title": "Retry the payment webhook",
    "body": "Fixes #41.\n\n- backoff\n- idempotency key",
    "state": "closed",
    "draft": False,
    "merged_at": "2026-09-20T10:00:00Z",
    "closed_at": "2026-09-20T10:00:00Z",
    "created_at": "2026-09-18T08:00:00Z",
    "updated_at": "2026-09-20T10:00:01Z",
    "html_url": "https://github.com/acme/payments/pull/42",
    "user": {"login": "sara", "id": 1},
    "assignees": [{"login": "sara"}],
    "requested_reviewers": [{"login": "omar"}],
    "labels": [{"name": "bug"}, {"name": "payments"}],
    "head": {"ref": "fix/webhook-retry"},
    "base": {"ref": "main"},
}
GITLAB_MR: dict[str, Any] = {
    "id": 9001,
    "iid": 42,
    "title": "Retry the payment webhook",
    "description": "Closes #41",
    "state": "merged",
    "draft": False,
    "merged_at": "2026-09-20T12:00:00.000+02:00",
    "created_at": "2026-09-18T10:00:00.000+02:00",
    "updated_at": "2026-09-20T12:00:01.000+02:00",
    "web_url": "https://gitlab.com/acme/payments/-/merge_requests/42",
    "author": {"username": "sara", "name": "Sara K."},
    "assignees": [],
    "reviewers": [{"username": "omar", "name": "Omar B."}],
    "labels": ["bug", "payments"],
    "source_branch": "fix/webhook-retry",
    "target_branch": "main",
}
BITBUCKET_PR: dict[str, Any] = {
    "id": 42,
    "title": "Retry the payment webhook",
    "description": "Closes #41",
    "state": "MERGED",
    "created_on": "2026-09-18T08:00:00.123456+00:00",
    "updated_on": "2026-09-20T10:00:01.654321+00:00",
    "links": {"html": {"href": "https://bitbucket.org/acme/payments/pull-requests/42"}},
    "author": {"uuid": "{a1}", "display_name": "Sara K."},
    "source": {"branch": {"name": "fix/webhook-retry"}},
    "destination": {"branch": {"name": "main"}},
}


def _record(capability: Capability, payload: dict[str, Any], **extra: Any) -> RawRecord:
    return RawRecord(
        kind=capability,
        external_id=extra.pop("external_id", "x-1"),
        container=extra.pop("container", "acme/payments"),
        payload=payload,
        fetched_at=FETCHED,
    )


def _extract(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> ExtractedRecord:
    result = extract(_record(capability, payload, **extra), source_id=SOURCE, source_kind=kind)
    assert isinstance(result, ExtractedRecord), result
    return result


def _failure(
    kind: SourceKind, capability: Capability, payload: dict[str, Any]
) -> ExtractionFailure:
    result = extract(_record(capability, payload), source_id=SOURCE, source_kind=kind)
    assert isinstance(result, ExtractionFailure), result
    assert SECRET not in result.model_dump_json()
    return result


# ── coverage ─────────────────────────────────────────────────────────────────


EXTRACTED_KINDS = [
    SourceKind.GITHUB,
    SourceKind.GITLAB,
    SourceKind.BITBUCKET,
    SourceKind.JIRA,
    SourceKind.AWS,
    SourceKind.AZURE,
    SourceKind.GCP,
    SourceKind.DATADOG,
]


@pytest.mark.parametrize("kind", EXTRACTED_KINDS)
def test_every_capability_these_connectors_read_has_a_strategy(kind: SourceKind) -> None:
    """A capability added to one of these connectors needs its strategy. A
    new connector's records are `unsupported` until it has them — observable,
    not blocking."""
    for capability in get_connector(kind).manifest.capabilities:
        assert strategy_for(kind, capability) is not None, (kind, capability)


# ── one shape, three hosts ───────────────────────────────────────────────────


def test_a_pull_request_is_the_same_shape_on_every_host() -> None:
    github = _extract(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR)
    gitlab = _extract(SourceKind.GITLAB, Capability.PULL_REQUESTS, GITLAB_MR)
    bitbucket = _extract(SourceKind.BITBUCKET, Capability.PULL_REQUESTS, BITBUCKET_PR)

    for pr in (github, gitlab, bitbucket):
        assert pr.title == "Retry the payment webhook"
        assert pr.state == "merged"
        assert pr.metadata["number"] == 42
        branches = {r.role: r.name for r in pr.references if r.kind == "branch"}
        assert branches == {"source_branch": "fix/webhook-retry", "target_branch": "main"}
        assert pr.content[0].role == "body" and pr.content[0].format == "markdown"
        assert pr.updated_at is not None and pr.updated_at.tzinfo is not None
    assert github.extractor == "github.pull_requests"
    assert gitlab.metadata["labels"] == github.metadata["labels"] == ["bug", "payments"]


def test_a_github_pull_request_keeps_its_people() -> None:
    pr = _extract(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR)

    people = {(r.role, r.external_id) for r in pr.references if r.kind == "person"}
    assert people == {("author", "sara"), ("assignee", "sara"), ("reviewer", "omar")}
    assert pr.url == "https://github.com/acme/payments/pull/42"


def test_a_commit_is_its_first_line_its_message_and_its_author() -> None:
    commit = _extract(
        SourceKind.GITHUB,
        Capability.COMMITS,
        {
            "sha": "9f2c",
            "node_id": "C_kw",
            "html_url": "https://github.com/acme/payments/commit/9f2c",
            "commit": {
                "message": "Retry the webhook\n\nWith an idempotency key.",
                "author": {
                    "name": "Sara K.",
                    "email": "sara@acme.io",
                    "date": "2026-09-20T09:00:00Z",
                },
                "committer": {
                    "name": "GitHub",
                    "email": "noreply@github.com",
                    "date": "2026-09-20T10:00:00Z",
                },
            },
            "author": {"login": "sara"},
            "committer": {"login": "web-flow"},
            "parents": [{"sha": "a"}, {"sha": "b"}],
        },
    )

    assert commit.title == "Retry the webhook"
    assert commit.content[0].text.endswith("idempotency key.")
    author = next(r for r in commit.references if r.role == "author")
    assert (author.external_id, author.name, author.email) == ("sara", "Sara K.", "sara@acme.io")
    assert commit.signals["merge"] is True
    assert commit.metadata["sha"] == "9f2c"


def test_a_gitlab_commit_names_its_author_by_email() -> None:
    commit = _extract(
        SourceKind.GITLAB,
        Capability.COMMITS,
        {
            "id": "9f2c",
            "title": "Retry the webhook",
            "message": "Retry the webhook\n",
            "author_name": "Sara K.",
            "author_email": "sara@acme.io",
            "authored_date": "2026-09-20T11:00:00.000+02:00",
            "committed_date": "2026-09-20T11:00:00.000+02:00",
            "parent_ids": ["a"],
        },
    )

    author = next(r for r in commit.references if r.role == "author")
    assert (author.external_id, author.email) == (None, "sara@acme.io")
    assert commit.signals["merge"] is False


def test_a_bitbucket_commit_without_an_account_reads_git_s_author_line() -> None:
    commit = _extract(
        SourceKind.BITBUCKET,
        Capability.COMMITS,
        {
            "hash": "9f2c",
            "message": "Retry",
            "date": "2026-09-20T09:00:00+00:00",
            "author": {"raw": "Sara K. <sara@acme.io>"},
        },
    )

    author = commit.references[0]
    assert (author.name, author.email) == ("Sara K.", "sara@acme.io")


def test_a_repository_carries_its_technical_signals() -> None:
    repository = _extract(
        SourceKind.GITHUB,
        Capability.REPOSITORIES,
        {
            "full_name": "acme/payments",
            "description": "Payment service",
            "language": "Python",
            "topics": ["payments", "pci"],
            "archived": False,
            "private": True,
            "default_branch": "main",
            "owner": {"login": "acme"},
            "pushed_at": "2026-09-26T18:00:00Z",
        },
    )

    assert repository.title == "acme/payments"
    assert repository.signals == {"language": "Python", "topics": ["payments", "pci"]}
    assert repository.metadata["visibility"] == "private"
    assert repository.state == "active"


# ── what is kept, what is not ────────────────────────────────────────────────


def test_what_a_vendor_does_not_say_is_left_out() -> None:
    issue = _extract(
        SourceKind.GITHUB, Capability.ISSUES, {"title": "Webhook lost", "state": "open"}
    )

    assert issue.metadata == {}
    assert issue.content == []
    assert issue.references == []


def test_a_long_text_is_cut_and_says_so() -> None:
    issue = _extract(
        SourceKind.GITHUB, Capability.ISSUES, {"title": "Logs", "body": "x" * (MAX_TEXT + 10)}
    )

    assert len(issue.content[0].text) == MAX_TEXT
    assert issue.content[0].truncated is True


def test_the_provenance_leads_back_to_the_stored_record() -> None:
    record = _record(Capability.PULL_REQUESTS, GITHUB_PR, external_id="PR_kwDOA")

    result = extract(
        record, source_id=SOURCE, source_kind=SourceKind.GITHUB, payload_key="w/s/b.jsonl"
    )

    assert result.provenance.source_id == SOURCE
    assert result.provenance.external_id == "PR_kwDOA"
    assert result.provenance.container == "acme/payments"
    assert result.provenance.checksum == checksum(record)  # source_records.checksum
    assert result.provenance.payload_key == "w/s/b.jsonl"
    assert result.provenance.fetched_at == FETCHED


def test_an_extracted_record_travels_as_json_to_the_next_stage() -> None:
    pr = _extract(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR)

    assert ExtractedRecord.model_validate_json(pr.model_dump_json()) == pr


# ── failures, one record at a time ───────────────────────────────────────────


def test_a_record_missing_what_it_means_nothing_without_is_malformed() -> None:
    failure = _failure(SourceKind.GITHUB, Capability.PULL_REQUESTS, {"body": SECRET})

    assert failure.code is FailureCode.MALFORMED
    assert failure.message == "missing field 'title'"
    assert failure.extractor == "github.pull_requests"


def test_a_date_that_is_not_one_is_named_not_quoted() -> None:
    failure = _failure(SourceKind.GITLAB, Capability.ISSUES, {"title": "x", "created_at": SECRET})

    assert failure.code is FailureCode.MALFORMED
    assert "created_at" in failure.message


def test_a_payload_of_the_wrong_shape_is_a_failure_not_an_exception() -> None:
    failure = _failure(SourceKind.BITBUCKET, Capability.PULL_REQUESTS, {"title": ["not", SECRET]})

    assert failure.code is FailureCode.MALFORMED


def test_a_kind_with_no_strategy_yet_is_unsupported() -> None:
    failure = _failure(SourceKind.SLACK, Capability.ISSUES, {"title": SECRET})

    assert failure.code is FailureCode.UNSUPPORTED
    assert failure.extractor is None


def test_one_malformed_record_does_not_stop_its_neighbours() -> None:
    payloads = [GITHUB_PR, {"body": SECRET}, {**GITHUB_PR, "number": 43}]

    results = [
        extract(
            _record(Capability.PULL_REQUESTS, p), source_id=SOURCE, source_kind=SourceKind.GITHUB
        )
        for p in payloads
    ]

    assert [r.status for r in results] == ["extracted", "failed", "extracted"]


# ── Jira ─────────────────────────────────────────────────────────────────────


def _adf(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "version": 1, "content": list(blocks)}


def _paragraph(*inline: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(inline)}


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


JIRA_ISSUE: dict[str, Any] = {
    "id": "10042",
    "key": "PAY-42",
    "self": "https://acme.atlassian.net/rest/api/3/issue/10042",
    "fields": {
        "summary": "Payment webhook lost under load",
        "description": _adf(
            _paragraph(
                _text("Seen by "), {"type": "mention", "attrs": {"id": "u1", "text": "@Omar"}}
            ),
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [_paragraph(_text("retry"))]},
                    {"type": "listItem", "content": [_paragraph(_text("alert"))]},
                ],
            },
        ),
        "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
        "issuetype": {"name": "Bug"},
        "priority": {"name": "High"},
        "assignee": {"accountId": "u1", "displayName": "Omar B."},
        "reporter": {"accountId": "u2", "displayName": "Sara K."},
        "labels": ["payments"],
        "components": [{"name": "webhooks"}],
        "project": {"key": "PAY", "name": "Payments"},
        "parent": {"key": "PAY-1"},
        "created": "2026-09-18T08:00:00.000+0200",
        "updated": "2026-09-20T10:00:00.000+0200",
        "comment": {"comments": [{"body": _adf(_paragraph(_text("Reproduced on staging.")))}]},
    },
}


def test_a_jira_issue_comes_out_with_its_text_people_and_links() -> None:
    issue = _extract(SourceKind.JIRA, Capability.ISSUES, JIRA_ISSUE, container="PAY")

    assert issue.title == "Payment webhook lost under load"
    assert issue.url == "https://acme.atlassian.net/browse/PAY-42"
    assert issue.state == "in progress"
    assert issue.content[0].text == "Seen by @Omar\nretry\nalert"
    assert issue.content[1].role == "comment"
    roles = {(r.role, r.external_id) for r in issue.references}
    assert {
        ("assignee", "u1"),
        ("reporter", "u2"),
        ("project", "PAY"),
        ("parent", "PAY-1"),
    } <= roles
    assert issue.metadata["status_category"] == "indeterminate"
    assert issue.metadata["components"] == ["webhooks"]
    assert issue.updated_at is not None and issue.updated_at.utcoffset() is not None


def test_a_jira_project() -> None:
    project = _extract(
        SourceKind.JIRA,
        Capability.PROJECTS,
        {
            "id": "1",
            "key": "PAY",
            "name": "Payments",
            "description": "All things money",
            "projectTypeKey": "software",
            "self": "https://acme.atlassian.net/rest/api/3/project/1",
        },
    )

    assert (project.title, project.url) == ("Payments", "https://acme.atlassian.net/browse/PAY")
    assert project.content[0].text == "All things money"


def test_deeply_nested_rich_text_is_read() -> None:
    deep: dict[str, Any] = _text("bottom")
    for _ in range(300):
        deep = {"type": "blockquote", "content": [deep]}
    payload = {**JIRA_ISSUE, "fields": {**JIRA_ISSUE["fields"], "description": _adf(deep)}}

    issue = _extract(SourceKind.JIRA, Capability.ISSUES, payload)

    assert issue.content[0].text == "bottom"


# ── Cloud ────────────────────────────────────────────────────────────────────


def test_an_aws_instance_is_named_by_its_tag_and_placed_in_its_region() -> None:
    instance = _extract(
        SourceKind.AWS,
        Capability.INSTANCES,
        {
            "InstanceId": "i-0abc",
            "InstanceType": "t3.small",
            "State": {"Name": "running"},
            "LaunchTime": "2026-09-01 08:00:00+00:00",
            "VpcId": "vpc-1",
            "Placement": {"AvailabilityZone": "eu-west-3a"},
            "Tags": [{"Key": "Name", "Value": "api-1"}, {"Key": "team", "Value": "payments"}],
        },
        container="eu-west-3",
    )

    assert (instance.title, instance.state) == ("api-1", "running")
    assert instance.signals["region"] == "eu-west-3"
    assert instance.signals["instance_type"] == "t3.small"
    assert instance.signals["tags"] == ["Name=api-1", "team=payments"]
    assert instance.references[0].external_id == "vpc-1"
    assert instance.created_at is not None


def test_an_aws_database_says_its_engine() -> None:
    database = _extract(
        SourceKind.AWS,
        Capability.DB_INSTANCES,
        {
            "DBInstanceIdentifier": "payments-db",
            "Engine": "postgres",
            "EngineVersion": "16.3",
            "DBInstanceClass": "db.t4g.medium",
            "DBInstanceStatus": "available",
            "MultiAZ": True,
            "TagList": [{"Key": "env", "Value": "prod"}],
        },
        container="eu-west-3",
    )

    assert database.signals["engine"] == "postgres"
    assert database.signals["multi_az"] is True
    assert database.signals["tags"] == ["env=prod"]


def test_an_s3_bucket_has_no_region_in_a_global_list() -> None:
    bucket = _extract(
        SourceKind.AWS,
        Capability.BUCKETS,
        {"Name": "acme-invoices", "CreationDate": "2025-01-01 00:00:00+00:00"},
        container=None,
    )

    assert bucket.title == "acme-invoices"
    assert "region" not in bucket.signals


def test_an_azure_resource() -> None:
    vm = _extract(
        SourceKind.AZURE,
        Capability.INSTANCES,
        {
            "id": "/subscriptions/s1/resourceGroups/Prod/providers/"
            "Microsoft.Compute/virtualMachines/api-1",
            "name": "api-1",
            "type": "Microsoft.Compute/virtualMachines",
            "location": "westeurope",
            "tags": {"team": "payments"},
        },
        container="s1",
    )

    assert vm.title == "api-1"
    assert vm.metadata["resource_group"] == "Prod"
    assert vm.signals["resource_type"] == "microsoft.compute/virtualmachines"
    assert vm.signals["tags"] == ["team=payments"]


def test_a_google_cloud_asset() -> None:
    vm = _extract(
        SourceKind.GCP,
        Capability.INSTANCES,
        {
            "name": "//compute.googleapis.com/projects/acme-prod"
            "/zones/europe-west1-b/instances/api-1",
            "assetType": "compute.googleapis.com/Instance",
            "updateTime": "2026-09-20T10:00:00.123456Z",
            "resource": {
                "location": "europe-west1-b",
                "data": {
                    "name": "api-1",
                    "status": "RUNNING",
                    "machineType": "https://www.googleapis.com/compute/v1/projects/acme-prod/zones/europe-west1-b/machineTypes/e2-small",
                    "creationTimestamp": "2026-01-01T00:00:00.000-08:00",
                    "labels": {"team": "payments"},
                },
            },
        },
        container="acme-prod",
    )

    assert (vm.title, vm.state) == ("api-1", "running")
    assert vm.signals["instance_type"] == "e2-small"
    assert vm.metadata["project"] == "acme-prod"


def test_an_instance_has_the_same_signals_on_every_cloud() -> None:
    aws = _extract(
        SourceKind.AWS,
        Capability.INSTANCES,
        {"InstanceId": "i-1", "InstanceType": "t3.small", "Tags": [{"Key": "team", "Value": "x"}]},
        container="eu-west-3",
    )
    azure = _extract(
        SourceKind.AZURE,
        Capability.INSTANCES,
        {
            "id": "/subscriptions/s/resourceGroups/g/providers/p/t/vm",
            "name": "vm",
            "type": "t",
            "location": "westeurope",
            "tags": {"team": "x"},
        },
    )
    gcp = _extract(
        SourceKind.GCP,
        Capability.INSTANCES,
        {
            "name": "//compute.googleapis.com/projects/p/zones/z/instances/vm",
            "assetType": "compute.googleapis.com/Instance",
            "resource": {"location": "z", "data": {"labels": {"team": "x"}}},
        },
    )

    for resource in (aws, azure, gcp):
        assert {"provider", "resource_type", "region", "tags"} <= set(resource.signals)
        assert resource.signals["tags"] == ["team=x"]
    assert [r.signals["provider"] for r in (aws, azure, gcp)] == ["aws", "azure", "gcp"]


def test_a_cloud_resource_without_its_id_is_malformed() -> None:
    failure = _failure(SourceKind.AWS, Capability.INSTANCES, {"InstanceType": SECRET})

    assert failure.message == "missing field 'InstanceId'"
