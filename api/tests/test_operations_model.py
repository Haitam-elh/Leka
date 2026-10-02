"""Incidents, changes and deployments, as normalisation writes them (LEKA-367).

From the connectors' payloads through extraction, parsing and
normalisation: a GitHub and a GitLab deployment, with their statuses; a
PagerDuty change event; a deploy event Datadog recorded, a deploy Grafana
annotated; Jira Service Management's incidents and change requests, and
the links saying what caused what; a change management tool's change and a
CI/CD tool's deployment, read as custom sources.

What these protect: a deployment keyed in its repository, deploying its
commit, to a canonical environment, each status kept with when; a change
affecting its service; an event made an entity only when it says it is a
deployment or a change; a ticket that is an incident or a change typed so;
causes kept as the tool states them; every date kept as its record gives
it.
"""

from __future__ import annotations

from typing import Any

from leka.connectors import Capability, SourceKind
from leka.ingestion.normalisation import NormalisationFailure, NormalisedRecord, normalise
from leka.ingestion.parsing import ParsedRecord, parse
from tests.test_extraction import _extract

C = Capability
K = SourceKind
SHA = "a" * 40
SITE = "acme.atlassian.net"


def _normalised(
    kind: SourceKind, capability: Capability, payload: dict[str, Any], **extra: Any
) -> NormalisedRecord:
    extracted = _extract(kind, capability, payload, **extra)
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)
    result = normalise(extracted, parsed)
    assert isinstance(result, NormalisedRecord), result
    return result


def _edges(record: NormalisedRecord) -> set[tuple[str, str, str]]:
    return {(r.from_key, r.type, r.to_key) for r in record.relationships}


# ── deployments ──────────────────────────────────────────────────────────────


def test_a_github_deployment_its_repository_commit_environment_and_statuses() -> None:
    deployment = _normalised(
        K.GITHUB,
        C.DEPLOYMENTS,
        {
            "url": "https://api.github.com/repos/acme/billing-api/deployments/42",
            "id": 42,
            "node_id": "DE_42",
            "sha": SHA,
            "ref": "v1.4.0",
            "environment": "prod",
            "creator": {"login": "sara"},
            "created_at": "2026-09-28T10:00:00Z",
            "updated_at": "2026-09-28T10:07:00Z",
            "statuses": [
                {
                    "state": "success",
                    "created_at": "2026-09-28T10:07:00Z",
                    # Its pipeline's link — not where its repository lives.
                    "log_url": "https://ci.acme.io/runs/9",
                },
                {"state": "in_progress", "created_at": "2026-09-28T10:01:00Z"},
            ],
        },
        external_id="DE_42",
        container="acme/billing-api",
    )

    entity = deployment.entity
    key = "github.com/acme/billing-api/deployments/42"
    assert (entity.type, entity.key, entity.name) == ("deployment", key, "v1.4.0 to prod")
    a = entity.attributes
    assert (a["state"], a["environment"], a["started_at"], a["finished_at"]) == (
        "succeeded",
        "production",
        "2026-09-28T10:01:00Z",
        "2026-09-28T10:07:00Z",
    )
    assert a["status_history"] == [
        {"state": "in_progress", "at": "2026-09-28T10:01:00Z"},
        {"state": "succeeded", "at": "2026-09-28T10:07:00Z"},
    ]
    assert _edges(deployment) >= {
        (key, "part_of", "github.com/acme/billing-api"),
        (key, "deploys", f"github.com/acme/billing-api@{SHA}"),
        (key, "deploys", "github.com/acme/billing-api/releases/v1.4.0"),
        (key, "deployed_to", "environment:production"),
        (key, "created_by", "person:github.com:sara"),
    }


def test_a_gitlab_deployment_its_tier_and_how_it_went() -> None:
    deployment = _normalised(
        K.GITLAB,
        C.DEPLOYMENTS,
        {
            "id": 77,
            "ref": "main",
            "sha": SHA,
            "status": "failed",
            "created_at": "2026-09-28T09:00:00Z",
            "finished_at": "2026-09-28T09:05:00Z",
            "environment": {"name": "eu-review", "tier": "staging"},
            "deployable": {"web_url": "https://gitlab.com/acme/ledger/-/jobs/1"},
        },
        external_id="77",
        container="acme/ledger",
    )

    key = "gitlab.com/acme/ledger/deployments/77"
    assert deployment.entity.key == key
    assert deployment.entity.attributes["state"] == "failed"
    assert (key, "deployed_to", "environment:staging") in _edges(deployment)


# ── changes ──────────────────────────────────────────────────────────────────


def test_a_pagerduty_change_event_is_a_change_done_that_affects_its_services() -> None:
    change = _normalised(
        K.PAGERDUTY,
        C.CHANGES,
        {
            "id": "PCE1",
            "summary": "Deploy billing-api v1.4.0",
            "timestamp": "2026-09-28T10:07:00Z",
            "source": "github-actions",
            "services": [{"id": "PBILL01", "summary": "Billing API"}],
            "links": [{"href": "https://ci.acme.io/runs/9"}],
            "custom_details": {"version": "v1.4.0"},
        },
        external_id="PCE1",
        container="PBILL01",
    )

    entity = change.entity
    assert (entity.type, entity.key) == ("change", "change:pagerduty:PCE1")
    assert (entity.attributes["state"], entity.attributes["created_at"]) == (
        "completed",
        "2026-09-28T10:07:00Z",
    )
    assert ("change:pagerduty:PCE1", "affects", "service:billing-api") in _edges(change)


def _datadog_event(event_id: str, tags: list[str], **inner: Any) -> dict[str, Any]:
    return {
        "id": event_id,
        "attributes": {
            "timestamp": "2026-09-28T10:07:00Z",
            "message": "Deployed billing-api",
            "tags": tags,
            "attributes": {"title": "Deployed billing-api v1.4.0", **inner},
        },
    }


def test_a_monitoring_tool_s_deploy_event_is_a_deployment_of_its_service() -> None:
    event = _normalised(
        K.DATADOG,
        C.EVENTS,
        _datadog_event(
            "E1",
            ["service:billing-api", "env:prod", "event_type:deployment", "version:v1.4.0"],
            status="success",
        ),
        external_id="E1",
        container=None,
    )

    key = "deployment:datadog:E1"
    assert (event.entity.type, event.entity.key) == ("deployment", key)
    assert (event.entity.attributes["ref"], event.entity.attributes["state"]) == (
        "v1.4.0",
        "succeeded",
    )
    assert _edges(event) >= {
        (key, "part_of", "service:billing-api"),
        (key, "deployed_to", "environment:production"),
    }


def test_a_grafana_region_tagged_deploy_ends_when_the_deployment_finished() -> None:
    event = _normalised(
        K.GRAFANA,
        C.EVENTS,
        {
            "id": 7,
            "time": 1790000000000,
            "timeEnd": 1790000300000,
            "text": "Deploy ledger",
            "tags": ["deploy", "service:ledger"],
        },
        external_id="7",
        container=None,
    )

    assert event.entity.key == "deployment:grafana:7"
    # 1 790 000 300 000 ms after the epoch.
    assert event.entity.attributes["finished_at"] == "2026-09-21T14:18:20Z"
    assert ("deployment:grafana:7", "part_of", "service:ledger") in _edges(event)


def test_an_event_that_says_nothing_of_a_change_stays_evidence() -> None:
    extracted = _extract(
        K.DATADOG, C.EVENTS, _datadog_event("E2", ["service:billing-api"]), external_id="E2"
    )
    parsed = parse(extracted)
    assert isinstance(parsed, ParsedRecord)

    result = normalise(extracted, parsed)

    assert isinstance(result, NormalisationFailure)
    assert result.code.value == "unsupported"


# ── tickets ──────────────────────────────────────────────────────────────────


def _jira(key: str, kind: str, status: str, category: str, **fields: Any) -> dict[str, Any]:
    return {
        "key": key,
        "self": f"https://{SITE}/rest/api/3/issue/{key}",
        "fields": {
            "summary": f"{kind} {key}",
            "issuetype": {"name": kind},
            "status": {"name": status, "statusCategory": {"key": category}},
            "created": "2026-09-28T10:30:00.000+0000",
            "updated": "2026-09-28T12:00:00.000+0000",
            **fields,
        },
    }


def test_a_jira_incident_is_an_incident_and_says_what_caused_it() -> None:
    incident = _normalised(
        K.JIRA,
        C.ISSUES,
        _jira(
            "OPS-7",
            "Incident",
            "Resolved",
            "done",
            resolutiondate="2026-09-28T12:00:00.000+0000",
            issuelinks=[
                {
                    "type": {"name": "Problem/Incident", "inward": "is caused by"},
                    "inwardIssue": {"key": "CHG-3"},
                },
                {"type": {"name": "Relates"}, "outwardIssue": {"key": "OPS-1"}},
            ],
        ),
        external_id="OPS-7",
        container="OPS",
    )

    entity = incident.entity
    assert (entity.type, entity.attributes["state"]) == ("incident", "closed")
    assert entity.attributes["resolved_at"] == "2026-09-28T12:00:00Z"
    edges = _edges(incident)
    assert (f"{SITE}/OPS-7", "caused_by", f"{SITE}/CHG-3") in edges
    assert not any(kind == "caused_by" and to.endswith("OPS-1") for _, kind, to in edges)


def test_a_jira_change_request_its_type_its_state_and_what_it_causes() -> None:
    change = _normalised(
        K.JIRA,
        C.ISSUES,
        _jira(
            "CHG-3",
            "Normal change",
            "Implementing",
            "indeterminate",
            issuelinks=[
                {"type": {"name": "Causes", "outward": "causes"}, "outwardIssue": {"key": "OPS-7"}}
            ],
        ),
        external_id="CHG-3",
        container="CHG",
    )

    entity = change.entity
    assert (entity.type, entity.attributes["change_type"], entity.attributes["state"]) == (
        "change",
        "normal",
        "in_progress",
    )
    assert (f"{SITE}/OPS-7", "caused_by", f"{SITE}/CHG-3") in _edges(change)


# ── a change management tool, a CI/CD tool ───────────────────────────────────


def _declared(entity: str, record_id: str, title: str, **fields: Any) -> NormalisedRecord:
    return _normalised(
        K.CUSTOM_REST,
        C.RECORDS,
        {
            "resource": f"{entity}s",
            "entity": entity,
            "fields": {"id": record_id, "title": title, **fields},
        },
        external_id=f"{entity}s:{record_id}",
    )


def test_a_change_request_its_plan_what_it_affects_and_who() -> None:
    change = _declared(
        "change",
        "CHG0030001",
        "Rotate billing DB credentials",
        state="Scheduled",
        metadata={
            "type": "Standard",
            "risk": "Low",
            "cmdb_ci": "Billing API",
            "planned_start": "2026-10-03T22:00:00Z",
            "planned_end": "2026-10-03T23:00:00Z",
            "assigned_to": "nora@acme.io",
            "requested_by": "sara@acme.io",
            "environment": "prod",
        },
    )

    entity = change.entity
    key = entity.key
    a = entity.attributes
    assert (a["state"], a["change_type"], a["risk"], a["environment"]) == (
        "scheduled",
        "standard",
        "low",
        "production",
    )
    assert (a["planned_start_at"], a["planned_end_at"]) == (
        "2026-10-03T22:00:00Z",
        "2026-10-03T23:00:00Z",
    )
    assert _edges(change) >= {
        (key, "affects", "service:billing-api"),
        (key, "assigned_to", "person:email:nora@acme.io"),
        (key, "reported_by", "person:email:sara@acme.io"),
    }


def test_a_ci_cd_tool_s_deployment_its_service_version_and_commit() -> None:
    deployment = _declared(
        "deployment",
        "run-9",
        "billing-api v1.4.0",
        state="SUCCESS",
        metadata={
            "service": "Billing API",
            "environment": "production",
            "version": "v1.4.0",
            "commit": SHA,
            "repository": "github.com/acme/billing-api",
            "deployer": "sara@acme.io",
        },
    )

    key = deployment.entity.key
    assert (deployment.entity.attributes["state"], deployment.entity.attributes["ref"]) == (
        "succeeded",
        "v1.4.0",
    )
    assert _edges(deployment) >= {
        (key, "part_of", "service:billing-api"),
        (key, "deployed_to", "environment:production"),
        (key, "deploys", f"github.com/acme/billing-api@{SHA}"),
        (key, "created_by", "person:email:sara@acme.io"),
    }
