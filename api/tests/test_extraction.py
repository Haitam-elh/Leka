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
from leka.ingestion.extraction import (
    MAX_TEXT,
    ExtractedRecord,
    ExtractionFailure,
    FailureCode,
    extract,
    strategy_for,
)
from leka.ingestion.sync import checksum

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


def _extract(kind: SourceKind, capability: Capability, payload: dict[str, Any]) -> ExtractedRecord:
    result = extract(_record(capability, payload), source_id=SOURCE, source_kind=kind)
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


@pytest.mark.parametrize("kind", [SourceKind.GITHUB, SourceKind.GITLAB, SourceKind.BITBUCKET])
def test_every_capability_a_code_host_reads_has_a_strategy(kind: SourceKind) -> None:
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
