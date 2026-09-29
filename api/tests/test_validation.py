"""Validation, the rules (LEKA-358): what a processed record is worth.

Representative records as normalisation makes them — a GitHub pull request,
a Jira issue, a PagerDuty incident, an AWS instance, a person — pass; then
each way a record goes wrong, and what it becomes: quarantined for an error
(kept out of the company model), a warning for a doubt, an info for what is
merely missing — each with what to do about it, never a value of the record.

The job, the quarantine downstream and the API: test_validation_job.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from leka.ingestion.validation import Severity, validate

SOURCE = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
NOW = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


def record(
    kind: str,
    key: str,
    *,
    capability: str = "issues",
    source_kind: str = "github",
    related: list[dict[str, Any]] | None = None,
    relationships: list[tuple[str, str, str]] = (),  # type: ignore[assignment]
    diagnostics: list[str] | None = None,
    aliases: list[str] | None = None,
    confidence: float = 1.0,
    **attributes: Any,
) -> dict[str, Any]:
    """A NormalisedRecord, as the job reads it from normalised_records.result."""
    return {
        "status": "normalised",
        "provenance": {
            "source_id": str(SOURCE),
            "source_kind": source_kind,
            "capability": capability,
            "external_id": key,
            "container": None,
            "fetched_at": (NOW - timedelta(hours=1)).isoformat(),
            "checksum": "0" * 64,
        },
        "extractor_version": 1,
        "parser_version": 1,
        "normaliser_version": 1,
        "entity": {
            "type": kind,
            "key": key,
            "external_id": key,
            "source_id": str(SOURCE),
            "name": attributes.pop("name", "A name"),
            "attributes": attributes,
            "aliases": aliases or [],
            "confidence": confidence,
            "observed_at": (NOW - timedelta(hours=1)).isoformat(),
        },
        "related": related or [],
        "relationships": [
            {"type": t, "from_key": a, "to_key": b, "source_id": str(SOURCE)}
            for t, a, b in relationships
        ],
        "diagnostics": diagnostics or [],
    }


def person(key: str, name: str = "Sara Martin") -> dict[str, Any]:
    return {
        "type": "person",
        "key": key,
        "external_id": key,
        "source_id": str(SOURCE),
        "name": name,
        "observed_at": NOW.isoformat(),
    }


def codes(result: object) -> dict[str, str]:
    return {i.code: i.severity.value for i in result.issues}  # type: ignore[attr-defined]


SEEN = NOW - timedelta(days=1)
PR = "github.com/acme/api#42"
SARA = "person:email:sara@acme.io"


def pull_request(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "capability": "pull_requests",
        "related": [person(SARA)],
        "relationships": [("authored_by", PR, SARA), ("part_of", PR, "github.com/acme/api")],
        "url": "https://github.com/acme/api/pull/42",
        "state": "merged",
        "created_at": "2026-09-20T08:00:00Z",
        "updated_at": "2026-09-21T10:00:00Z",
        "quality": 1.0,
    }
    fields.update(overrides)
    return record("pull_request", PR, **fields)


# ── representative records pass ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "normalised",
    [
        pull_request(),
        record(
            "issue",
            "acme.atlassian.net/PAY-42",
            source_kind="jira",
            aliases=["ticket:PAY-42"],
            related=[person("person:acme.atlassian.net:5b10ac8d82e05b22cc7d4ef5")],
            relationships=[
                (
                    "reported_by",
                    "acme.atlassian.net/PAY-42",
                    "person:acme.atlassian.net:5b10ac8d82e05b22cc7d4ef5",
                )
            ],
            url="https://acme.atlassian.net/browse/PAY-42",
            state="in_progress",
            priority="high",
            created_at="2026-09-01T08:00:00Z",
            updated_at="2026-09-29T08:00:00Z",
        ),
        record(
            "incident",
            "incident:pagerduty:Q1ABC",
            capability="incidents",
            source_kind="pagerduty",
            relationships=[("affects", "incident:pagerduty:Q1ABC", "service:billing-api")],
            url="https://acme.pagerduty.com/incidents/Q1ABC",
            state="closed",
            priority="highest",
            created_at="2026-09-28T02:00:00Z",
        ),
        record(
            "infra_resource",
            "aws:arn:aws:ec2:eu-central-1:123456789012:instance/i-0abc",
            capability="instances",
            source_kind="aws",
            state="running",
            environment="production",
        ),
        record("person", SARA, capability="issues", name="Sara Martin"),
        record(
            "commit",
            "github.com/acme/api@9f2c",
            capability="commits",
            related=[person(SARA)],
            relationships=[
                ("authored_by", "github.com/acme/api@9f2c", SARA),
                ("part_of", "github.com/acme/api@9f2c", "github.com/acme/api"),
            ],
            created_at="2026-09-29T07:00:00Z",
        ),
    ],
    ids=[
        "github-pull-request",
        "jira-issue",
        "pagerduty-incident",
        "aws-instance",
        "person",
        "commit",
    ],
)
def test_representative_records_are_valid_and_scored(normalised: dict[str, Any]) -> None:
    result = validate(normalised, seen_at=SEEN, now=NOW)

    assert result.status == "valid", codes(result)
    assert result.issues == []
    assert (result.completeness, result.consistency, result.freshness) == (1.0, 1.0, 1.0)
    assert result.quality == 1.0


# ── errors quarantine ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("normalised", "code", "field"),
    [
        ({"entity": {"type": "issue"}}, "schema", "provenance"),
        ("not a record", "schema", "record"),
        (pull_request(confidence=1.5), "schema", "entity.confidence"),
        (record("person", "person:email:not-an-address"), "bad_key", "entity.key"),
        (record("service", "service:Billing API"), "bad_key", "entity.key"),
        (record("commit", "github.com/acme/api@not-a-sha"), "bad_key", "entity.key"),
        (
            pull_request(related=[person("sara@acme.io")]),
            "bad_related_key",
            "related.0.key",
        ),
        (pull_request(updated_at="yesterday"), "bad_date", "entity.attributes.updated_at"),
        (
            pull_request(relationships=[("authored_by", PR, "service:billing")]),
            "person_relationship_to_non_person",
            "relationships.0",
        ),
    ],
    ids=[
        "no-provenance",
        "not-json-object",
        "confidence-out-of-range",
        "address-that-is-none",
        "service-not-a-slug",
        "commit-without-sha",
        "related-person-key",
        "date-that-does-not-read",
        "author-that-is-a-service",
    ],
)
def test_an_error_quarantines_and_says_where_and_what_to_do(
    normalised: object, code: str, field: str
) -> None:
    result = validate(normalised, seen_at=SEEN, now=NOW)

    assert result.status == "quarantined"
    [issue] = [i for i in result.issues if i.code == code]
    assert (issue.severity, issue.field) == (Severity.ERROR, field)
    assert issue.remediation
    assert result.quality == 0.0


def test_an_issue_never_quotes_a_value_of_the_record() -> None:
    secret_title = "Salary review for Sara Martin"
    result = validate(
        pull_request(name=secret_title, updated_at="le 3 mars", state="Stuck-ish"),
        seen_at=SEEN,
        now=NOW,
    )

    said = " ".join(i.message + i.remediation for i in result.issues)
    assert "Salary" not in said
    assert "le 3 mars" not in said
    assert "Stuck-ish" not in said


# ── warnings flag ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("normalised", "code"),
    [
        (
            pull_request(state="stuck", diagnostics=["unknown state: kept as the vendor wrote it"]),
            "unknown_state",
        ),
        (pull_request(priority="p0"), "unknown_priority"),
        (pull_request(updated_at="2027-01-01T00:00:00Z"), "future_date"),
        (pull_request(created_at="1970-01-01T00:00:00Z"), "ancient_date"),
        (pull_request(created_at="2026-09-22T00:00:00Z"), "dates_out_of_order"),
        (pull_request(url="javascript:alert(1)"), "bad_url"),
        (
            pull_request(relationships=[("resolves", PR, PR), ("authored_by", PR, SARA)]),
            "self_relationship",
        ),
        (
            pull_request(
                relationships=[("haunts", PR, "github.com/acme/api#1"), ("authored_by", PR, SARA)]
            ),
            "unknown_relationship",
        ),
    ],
    ids=[
        "state-off-the-scale",
        "priority-off-the-scale",
        "future",
        "before-1990",
        "updated-before-created",
        "link-not-web",
        "related-to-itself",
        "relationship-unknown",
    ],
)
def test_a_doubt_is_a_warning_the_record_stays_usable(
    normalised: dict[str, Any], code: str
) -> None:
    result = validate(normalised, seen_at=SEEN, now=NOW)

    assert result.status == "warning", codes(result)
    assert codes(result)[code] == "warning"
    assert 0 < result.quality < 1
    assert result.consistency < 1.0


def test_a_record_one_source_makes_twice_is_a_duplicate() -> None:
    result = validate(pull_request(), seen_at=SEEN, now=NOW, duplicate=True)

    assert (result.status, codes(result)["duplicate_in_source"]) == ("warning", "warning")


def test_a_record_not_seen_for_weeks_is_stale_and_worth_less() -> None:
    fresh = validate(pull_request(), seen_at=NOW - timedelta(days=8), now=NOW)
    stale = validate(pull_request(), seen_at=NOW - timedelta(days=19), now=NOW)
    gone = validate(pull_request(), seen_at=NOW - timedelta(days=45), now=NOW)

    assert (fresh.status, fresh.freshness) == ("valid", 1.0)
    assert (stale.status, stale.freshness) == ("warning", 0.5)
    assert codes(stale) == {"stale": "warning"}
    assert gone.freshness == 0.0
    assert fresh.quality > stale.quality > gone.quality
    # Stale is age, not a contradiction: consistency is untouched.
    assert stale.consistency == 1.0


# ── what is missing lowers the score, nothing more ───────────────────────────


def test_what_is_missing_is_said_and_scored_not_quarantined() -> None:
    bare = record("issue", "linear.app/acme/ENG-7", source_kind="linear", state="open")

    result = validate(bare, seen_at=SEEN, now=NOW)

    assert result.status == "valid"
    [issue] = result.issues
    assert (issue.code, issue.severity) == ("incomplete", Severity.INFO)
    assert "url, created_at, updated_at, author" in issue.message
    assert result.completeness == 0.2
    assert result.quality < 1.0


def test_a_person_without_an_address_is_less_complete() -> None:
    by_login = validate(record("person", "person:github.com:sara"), seen_at=SEEN, now=NOW)
    by_alias = validate(
        record("person", "person:github.com:sara", aliases=["person:email:sara@acme.io"]),
        seen_at=SEEN,
        now=NOW,
    )

    assert by_login.completeness == 0.0
    assert by_alias.completeness == 1.0


def test_a_kind_of_thing_with_no_expectations_is_complete() -> None:
    result = validate(record("team", "team:payments"), seen_at=SEEN, now=NOW)

    assert (result.status, result.completeness) == ("valid", 1.0)


def test_confidence_is_the_source_s_and_the_parse_s() -> None:
    result = validate(pull_request(confidence=0.8, quality=0.5), seen_at=SEEN, now=NOW)

    assert result.confidence == 0.4
    assert result.status == "valid"
