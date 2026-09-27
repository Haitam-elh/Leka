"""Parsing (LEKA-355): what an extracted record means, and how sure we are.

Vendor payloads go through the extraction first (tests/test_extraction.py
has them), so what is parsed is exactly what the pipeline would hand over.
Pure functions: no database.
"""

from __future__ import annotations

from typing import Any

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction import ExtractedRecord
from leka.ingestion.parsing import (
    MAX_EXCERPT,
    Fact,
    FactType,
    ParsedRecord,
    ParseFailure,
    parse,
    parse_stored,
)
from tests.test_extraction import GITHUB_PR, JIRA_ISSUE, _extract


def _parsed(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> ParsedRecord:
    result = parse(_extract(kind, capability, payload, **extra))
    assert isinstance(result, ParsedRecord), result
    return result


def _pr(**changes: Any) -> ParsedRecord:
    return _parsed(SourceKind.GITHUB, Capability.PULL_REQUESTS, {**GITHUB_PR, **changes})


def _of(parsed: ParsedRecord, kind: FactType) -> list[Fact]:
    return [f for f in parsed.facts if f.type is kind]


def _refs(parsed: ParsedRecord) -> dict[str, tuple[str | None, str | None, float]]:
    """key → (how, system, confidence) of every reference."""
    return {
        f.target.key: (f.value, f.target.system, f.confidence)
        for f in _of(parsed, FactType.REFERENCES)
        if f.target
    }


# ── references ───────────────────────────────────────────────────────────────


def test_a_closing_keyword_says_the_change_closes_the_issue() -> None:
    parsed = _pr(body="Fixes #41, and see #43.")

    refs = _refs(parsed)
    assert refs["#41"] == ("closes", "github", 0.95)
    assert refs["#43"] == ("mentions", "github", 0.7)
    closes = next(f for f in _of(parsed, FactType.REFERENCES) if f.value == "closes")
    assert closes.evidence.field == "content.body"
    assert closes.evidence.excerpt is not None and "Fixes #41" in closes.evidence.excerpt


def test_the_same_reference_twice_is_one_fact_the_surest() -> None:
    parsed = _pr(body="Fixes #41. More on #41 below. #41!")

    assert [f.value for f in _of(parsed, FactType.REFERENCES)] == ["closes"]


def test_links_to_work_items_are_references_and_other_links_are_links() -> None:
    parsed = _pr(
        body="See https://github.com/acme/api/issues/12, "
        "https://acme.atlassian.net/browse/PAY-7 and https://grafana.acme.io/d/abc."
    )

    refs = _refs(parsed)
    assert refs["acme/api#12"] == ("mentions", "github", 0.9)
    assert refs["PAY-7"] == ("mentions", "jira", 0.9)
    assert "#12" not in refs  # the link's own number is not read again
    (link,) = _of(parsed, FactType.LINKS_TO)
    assert link.value == "grafana.acme.io"


def test_a_ticket_key_in_text_is_a_reference_but_utf_8_is_not() -> None:
    parsed = _pr(body="Part of PAY-42. Encoded in UTF-8, hashed with SHA-256.")

    assert set(_refs(parsed)) == {"PAY-42"}


def test_code_is_not_read_for_references_or_people() -> None:
    parsed = _pr(body="Retry.\n\n```java\n@Override // see #1\nint x = PAY-9;\n```\nand `#2`.")

    assert _refs(parsed) == {}
    assert _of(parsed, FactType.MENTIONS) == []
    assert parsed.structure.code_languages == ["java"]


def test_people_are_mentioned_by_handle_not_by_email() -> None:
    parsed = _pr(body="Thanks @omar-b, cc sara@acme.io and @here.")

    assert [f.target.key for f in _of(parsed, FactType.MENTIONS) if f.target] == ["omar-b"]


def test_a_bare_number_means_nothing_outside_a_code_host() -> None:
    payload = {**JIRA_ISSUE, "fields": {**JIRA_ISSUE["fields"], "summary": "Retry, as in #41"}}

    parsed = _parsed(SourceKind.JIRA, Capability.ISSUES, payload)

    assert "#41" not in _refs(parsed)


def test_a_gitlab_merge_request_is_referenced_by_its_bang() -> None:
    parsed = _parsed(
        SourceKind.GITLAB,
        Capability.COMMITS,
        {
            "id": "9f2c",
            "title": "Merge branch 'x' into 'main'",
            "message": "See merge request acme/api!12",
        },
    )

    assert _refs(parsed)["acme/api!12"] == ("mentions", "gitlab", 0.7)


# ── work items ───────────────────────────────────────────────────────────────


def test_a_conventional_title_says_the_kind_of_change() -> None:
    parsed = _pr(title="fix(payments)!: retry the webhook")

    values = {(f.type, f.value) for f in parsed.facts}
    assert {
        (FactType.CHANGE_TYPE, "fix"),
        (FactType.SCOPE, "payments"),
        (FactType.BREAKING, "true"),
        (FactType.CATEGORY, "bug"),
    } <= values


def test_a_branch_carries_its_ticket() -> None:
    parsed = _pr(head={"ref": "feature/pay-42-webhook-retry"})

    assert _refs(parsed)["PAY-42"] == ("implements", None, 0.8)


def test_a_release_branch_is_not_a_ticket() -> None:
    parsed = _pr(head={"ref": "release-2026"})

    assert set(_refs(parsed)) == {"#41"}  # the body's "Fixes #41", nothing from the branch


def test_a_github_merge_commit_names_its_pull_request_and_ticket() -> None:
    parsed = _parsed(
        SourceKind.GITHUB,
        Capability.COMMITS,
        {
            "sha": "9f2c",
            "commit": {"message": "Merge pull request #12 from sara/PAY-42-retry\n\nRetry"},
        },
    )

    refs = _refs(parsed)
    assert refs["#12"][0] == "merges"
    assert refs["PAY-42"] == ("implements", None, 0.8)


def test_the_vendor_s_issue_type_and_labels_say_the_category() -> None:
    parsed = _parsed(SourceKind.JIRA, Capability.ISSUES, JIRA_ISSUE)
    labelled = _pr(labels=[{"name": "security"}, {"name": "sev-1"}])

    assert [(f.value, f.confidence) for f in _of(parsed, FactType.CATEGORY)] == [("bug", 0.95)]
    assert {f.value for f in _of(labelled, FactType.CATEGORY)} == {"security", "incident"}


# ── cloud resources ──────────────────────────────────────────────────────────


def _instance(tags: list[dict[str, str]], **extra: Any) -> ParsedRecord:
    return _parsed(
        SourceKind.AWS,
        Capability.INSTANCES,
        {"InstanceId": "i-1", "Tags": tags, **extra},
        container="eu-west-3",
    )


def test_tags_say_the_environment_the_service_and_the_team() -> None:
    parsed = _instance(
        [
            {"Key": "Environment", "Value": "Prod"},
            {"Key": "service", "Value": "billing"},
            {"Key": "team", "Value": "payments"},
        ]
    )

    found = {(f.type, f.value, f.confidence) for f in parsed.facts}
    assert (FactType.ENVIRONMENT, "production", 0.95) in found
    assert (FactType.SERVICE, "billing", 0.9) in found
    assert (FactType.OWNER, "payments", 0.9) in found


def test_a_name_is_only_a_guess_at_the_environment() -> None:
    guessed = _instance([{"Key": "Name", "Value": "api-prod-1"}])
    products = _instance([{"Key": "Name", "Value": "products-api"}])

    assert [(f.value, f.confidence) for f in _of(guessed, FactType.ENVIRONMENT)] == [
        ("production", 0.5)
    ]
    assert _of(products, FactType.ENVIRONMENT) == []


def test_configuration_says_whether_the_internet_reaches_it() -> None:
    database = _parsed(
        SourceKind.AWS,
        Capability.DB_INSTANCES,
        {"DBInstanceIdentifier": "db", "PubliclyAccessible": True},
        container="eu-west-3",
    )
    balancer = _parsed(
        SourceKind.AWS,
        Capability.LOAD_BALANCERS,
        {"LoadBalancerName": "lb", "Scheme": "internet-facing"},
        container="eu-west-3",
    )

    assert [f.value for f in _of(database, FactType.EXPOSURE)] == ["public"]
    assert [f.value for f in _of(balancer, FactType.EXPOSURE)] == ["public"]


# ── structure and quality ────────────────────────────────────────────────────


def test_the_shape_of_the_text() -> None:
    parsed = _pr(
        body="## Why\nRetries.\n\n## Checklist\n- [x] tests\n- [ ] docs\n\n"
        "```python\nretry()\n```\nhttps://example.com"
    )

    assert parsed.structure.headings == ["Why", "Checklist"]
    assert (parsed.structure.tasks_total, parsed.structure.tasks_done) == (2, 1)
    assert (parsed.structure.code_blocks, parsed.structure.links) == (1, 1)


def test_an_undescribed_issue_is_of_lesser_quality() -> None:
    parsed = _parsed(SourceKind.GITHUB, Capability.ISSUES, {"title": "Webhook lost"})

    assert (parsed.quality.score, parsed.quality.notes) == (0.8, ["no description"])
    assert _pr().quality.score == 1.0


def test_an_excerpt_is_short() -> None:
    parsed = _pr(body="x " * 500 + "Fixes #41 " + "y " * 500)

    closes = next(f for f in _of(parsed, FactType.REFERENCES) if f.value == "closes")
    assert closes.evidence.excerpt is not None
    assert len(closes.evidence.excerpt) <= MAX_EXCERPT + 2  # and its two ellipses


# ── provenance, contract, failures ───────────────────────────────────────────


def test_the_provenance_is_the_extraction_s() -> None:
    extracted = _extract(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR)

    parsed = parse(extracted)

    assert isinstance(parsed, ParsedRecord)
    assert parsed.provenance == extracted.provenance
    assert (parsed.extractor, parsed.extractor_version) == ("github.pull_requests", 1)
    assert ParsedRecord.model_validate_json(parsed.model_dump_json()) == parsed


def test_a_stored_result_that_is_not_an_extracted_record_is_malformed() -> None:
    failure = parse_stored({"title": "the-customer-text-that-must-not-leak"})

    assert isinstance(failure, ParseFailure)
    assert failure.code.value == "malformed"
    assert failure.provenance is None
    assert "the-customer-text" not in failure.message
    assert "provenance" in failure.message


def test_one_bad_result_does_not_stop_its_neighbours() -> None:
    good = _extract(SourceKind.GITHUB, Capability.PULL_REQUESTS, GITHUB_PR).model_dump(mode="json")

    results = [parse_stored(r) for r in (good, {"nope": 1}, good)]

    assert [r.status for r in results] == ["parsed", "failed", "parsed"]


def test_every_extracted_record_can_be_parsed() -> None:
    """A capability no rule knows still has its text read: never unsupported."""
    record = ExtractedRecord.model_validate(
        {
            **_extract(
                SourceKind.GITHUB, Capability.RELEASES, {"tag_name": "v1", "body": "Fixes #3"}
            ).model_dump(),
        }
    )

    parsed = parse(record)

    assert isinstance(parsed, ParsedRecord)
    assert "#3" in _refs(parsed)
