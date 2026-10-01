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
from tests.test_asana_connector import LAUNCH as ASANA_LAUNCH
from tests.test_asana_resources import _task as asana_task
from tests.test_clickup_resources import _task as clickup_task
from tests.test_confluence_connector import ENG as CONFLUENCE_ENG
from tests.test_confluence_resources import _page as confluence_page
from tests.test_datadog_connector import CHECKOUT as DATADOG_MONITOR
from tests.test_datadog_resources import incident as datadog_incident
from tests.test_extraction import BITBUCKET_PR, GITHUB_PR, GITLAB_MR, JIRA_ISSUE, _extract
from tests.test_extraction_tools import LINEAR_ISSUE, NOTION_PAGE
from tests.test_kibana_connector import CASE as KIBANA_CASE
from tests.test_microsoft_365_resources import item as m365_item
from tests.test_monday_resources import _item as monday_item
from tests.test_notion_connector import WIKI
from tests.test_pagerduty_connector import CHECKOUT as PAGERDUTY_CHECKOUT
from tests.test_pagerduty_connector import incident as pagerduty_incident
from tests.test_trello_resources import _card as trello_card

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
        ("environment", "environment:production", "production"),
        # The account it is in, named by its id until its own record names it.
        ("cloud_account", "aws:account:123456789012", "123456789012"),
    }
    edges = _edges(instance)
    assert {
        ("part_of", "service:billing-api"),
        ("owned_by", "team:payments"),
        ("runs_in", "environment:production"),
        ("part_of", "aws:account:123456789012"),
    } <= edges
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
        # Gone at the provider, still listed a while (LEKA-363).
        ("terminated", "terminated"),
        ("deleted", "terminated"),
        ("stopped", "stopped"),
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


# ── operations: incidents and services (LEKA-348) ────────────────────────────


def test_a_pagerduty_incident_is_an_incident_on_leka_s_scales() -> None:
    payload = {
        **pagerduty_incident(3),
        "priority": {"summary": "P1"},
        "teams": [{"summary": "Payments"}],
    }

    record = _normalised(
        SourceKind.PAGERDUTY,
        Capability.INCIDENTS,
        payload,
        external_id=payload["id"],
        container="PCHKOUT",
    )

    assert record.entity.type == "incident"
    assert record.entity.key == "incident:pagerduty:Q0000000000003"
    attributes = record.entity.attributes
    assert (attributes["state"], attributes["state_raw"]) == ("closed", "resolved")
    assert (attributes["priority"], attributes["priority_raw"]) == ("highest", "P1")
    assert ("affects", "service:checkout") in _edges(record)
    assert ("assigned_to", "person:acme.pagerduty.com:puser1") in _edges(record)
    assert not record.diagnostics


def test_a_datadog_incident_says_its_severity_commander_and_services() -> None:
    payload = {
        **datadog_incident(4, "checkout", "billing"),
        "people": {"commander_user": {"name": "Nora", "email": "Nora@Acme.test"}},
        "web_url": "https://app.datadoghq.eu/incidents/4",
    }

    record = _normalised(
        SourceKind.DATADOG, Capability.INCIDENTS, payload, external_id=payload["id"]
    )

    assert record.entity.key == f"incident:datadog:{payload['id']}"
    assert (record.entity.attributes["state"], record.entity.attributes["priority"]) == (
        "open",
        "high",
    )
    assert _edges(record) >= {
        ("led_by", "person:email:nora@acme.test"),
        ("affects", "service:checkout"),
        ("affects", "service:billing"),
    }


def test_a_pagerduty_service_meets_a_datadog_service_tag_on_one_key() -> None:
    service = _normalised(
        SourceKind.PAGERDUTY,
        Capability.SERVICES,
        {**PAGERDUTY_CHECKOUT, "teams": [{"summary": "Payments"}]},
    )
    incident = _normalised(
        SourceKind.DATADOG, Capability.INCIDENTS, datadog_incident(5, "checkout")
    )

    assert (service.entity.type, service.entity.key) == ("service", "service:checkout")
    assert ("owned_by", "team:payments") in _edges(service)
    assert ("affects", service.entity.key) in _edges(incident)


def test_a_kibana_case_is_an_incident_on_leka_s_scales() -> None:
    payload = {**KIBANA_CASE, "space": "default", "web_url": "https://kb.test/c-42"}

    record = _normalised(SourceKind.KIBANA, Capability.INCIDENTS, payload, external_id="c-42")

    attributes = record.entity.attributes
    assert (record.entity.type, record.entity.key) == ("incident", "incident:kibana:c-42")
    assert (attributes["state"], attributes["state_raw"]) == ("in_progress", "in-progress")
    assert attributes["priority"] == "high"
    assert ("affects", "service:checkout") in _edges(record)
    assert ("created_by", "person:email:nora@acme.io") in _edges(record)


def test_an_unknown_incident_state_is_kept_and_said() -> None:
    payload = {**pagerduty_incident(6), "status": "snoozed"}

    record = _normalised(SourceKind.PAGERDUTY, Capability.INCIDENTS, payload)

    assert record.entity.attributes["state"] == "snoozed"
    assert "unknown state: kept as the vendor wrote it" in record.diagnostics


def test_alerts_events_and_logs_are_not_entities_yet() -> None:
    extracted, parsed = _pipeline(SourceKind.DATADOG, Capability.ALERTS, DATADOG_MONITOR)

    failure = _failure(normalise(extracted, parsed))

    assert failure.code.value == "unsupported"


# ── project and documentation tools (LEKA-346) ───────────────────────────────


def test_a_linear_issue_is_its_identifier_in_its_workspace_with_a_ticket_alias() -> None:
    record = _normalised(
        SourceKind.LINEAR, Capability.ISSUES, LINEAR_ISSUE, external_id=LINEAR_ISSUE["id"]
    )

    assert (record.entity.type, record.entity.key) == ("issue", "linear.app/acme/ENG-42")
    assert "ticket:ENG-42" in record.entity.aliases
    attributes = record.entity.attributes
    assert (attributes["state"], attributes["state_raw"]) == ("in_progress", "in review")
    assert attributes["priority"] == "high"
    assert _edges(record) >= {
        ("part_of", "linear:project:proj-1"),
        ("child_of", "linear.app/acme/ENG-40"),
        ("assigned_to", "person:email:nora@acme.test"),
    }


def test_a_task_of_another_tool_is_part_of_its_project() -> None:
    asana = _normalised(
        SourceKind.ASANA,
        Capability.ISSUES,
        asana_task("7", "1001"),
        external_id="7",
        container="1001",
    )
    trello = _normalised(
        SourceKind.TRELLO, Capability.ISSUES, trello_card(2), external_id="c2", container="b1"
    )
    clickup = _normalised(
        SourceKind.CLICKUP, Capability.ISSUES, clickup_task(1), external_id="t1", container="l-1"
    )

    assert asana.entity.key == "asana:issue:7"
    assert ("part_of", "asana:project:1001") in _edges(asana)
    assert ("part_of", "trello:project:b1") in _edges(trello)
    assert trello.entity.attributes["state"] == "closed"  # card 2 is archived
    assert ("part_of", "clickup:project:l-1") in _edges(clickup)


def test_a_monday_status_label_is_on_leka_s_scale() -> None:
    item = {**monday_item(1), "column_values": [{"type": "status", "text": "Working on it"}]}

    record = _normalised(SourceKind.MONDAY, Capability.ISSUES, item, container="111")

    assert record.entity.attributes["state"] == "in_progress"


def test_a_project_of_a_tool_is_a_project() -> None:
    record = _normalised(SourceKind.ASANA, Capability.PROJECTS, ASANA_LAUNCH, external_id="1001")

    assert (record.entity.type, record.entity.key) == ("project", "asana:project:1001")


def test_a_confluence_page_is_a_document_of_its_site_and_its_author_jira_s_person() -> None:
    payload = {
        **confluence_page(1, "2026-09-21T12:05:00Z"),
        "authorId": "5b10ac8d",
        "web_url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/1001/Runbook",
    }

    record = _normalised(SourceKind.CONFLUENCE, Capability.PAGES, payload, external_id="1001")

    assert (record.entity.type, record.entity.key) == (
        "document",
        "acme.atlassian.net/wiki/pages/1001",
    )
    assert _edges(record) >= {
        ("authored_by", "person:acme.atlassian.net:5b10ac8d"),
        ("child_of", "acme.atlassian.net/wiki/pages/999"),
    }


def test_documents_of_the_other_tools_are_keyed_by_tool_and_id() -> None:
    notion = _normalised(SourceKind.NOTION, Capability.PAGES, NOTION_PAGE, external_id=WIKI)
    microsoft = _normalised(
        SourceKind.MICROSOFT_365,
        Capability.FILES,
        m365_item("report", name="Report.docx"),
        external_id="report",
        container="b!docs",
    )

    assert notion.entity.key == f"notion:document:{WIKI}"
    assert ("child_of", "notion:document:parent-page") in _edges(notion)
    assert microsoft.entity.key == "microsoft_365:document:b!docs/report"


def test_containers_of_documents_are_not_entities() -> None:
    extracted, parsed = _pipeline(SourceKind.CONFLUENCE, Capability.SPACES, CONFLUENCE_ENG)

    assert _failure(normalise(extracted, parsed)).code.value == "unsupported"
