"""Datadog's and PagerDuty's records, extracted for what comes after
(LEKA-348 → LEKA-354).

The payloads are the ones the Datadog connector stores — its stand-in's,
in tests/test_datadog_*.py. What matters: Datadog's own id and timestamp
kept, the state lower-cased, the text as content, and what an operations
question needs as signals: service, env, host, tags.
"""

from __future__ import annotations

from datetime import UTC, datetime

from leka.connectors import Capability, SourceKind
from leka.ingestion.extraction import FailureCode
from tests.test_datadog_connector import CHECKOUT
from tests.test_datadog_resources import event, incident, log
from tests.test_extraction import SECRET, _extract, _failure
from tests.test_pagerduty_connector import CHECKOUT as PAGERDUTY_CHECKOUT
from tests.test_pagerduty_connector import incident as pagerduty_incident

C = Capability
DATADOG = SourceKind.DATADOG


def test_a_monitor_is_an_alert_with_its_state_its_query_and_its_service() -> None:
    payload = {**CHECKOUT, "web_url": "https://app.datadoghq.eu/monitors/101"}

    alert = _extract(DATADOG, C.ALERTS, payload, external_id="101", container="checkout")

    assert (alert.title, alert.state) == ("Checkout p99 latency", "alert")
    assert alert.url == "https://app.datadoghq.eu/monitors/101"
    assert alert.updated_at == datetime(2026, 9, 25, 9, tzinfo=UTC)
    assert alert.content[0].text == "Latency is high @pagerduty"
    assert alert.metadata["query"] == CHECKOUT["query"]
    assert alert.metadata["priority"] == 2
    assert (alert.signals["service"], alert.signals["env"], alert.signals["team"]) == (
        "checkout",
        "prod",
        "payments",
    )
    assert alert.provenance.external_id == "101"
    assert alert.extractor == "datadog.alerts"


def test_an_event_keeps_datadog_s_timestamp_and_says_its_service() -> None:
    found = _extract(DATADOG, C.EVENTS, event(7), external_id="AQAAAY0007")

    assert (found.title, found.state) == ("Deploy 7", "info")
    assert found.created_at == found.updated_at == datetime(2026, 9, 21, 12, 7, tzinfo=UTC)
    assert found.signals["service"] == "checkout"
    assert found.signals["env"] == "prod"
    assert found.provenance.external_id == "AQAAAY0007"


def test_an_incident_names_its_people_severity_and_services() -> None:
    payload = {
        **incident(4, "checkout", "billing"),
        "people": {"commander_user": {"name": "Nora", "email": "nora@acme.test"}},
        "web_url": "https://app.datadoghq.eu/incidents/4",
    }

    found = _extract(DATADOG, C.INCIDENTS, payload)

    assert (found.title, found.state) == ("Checkout down 4", "active")
    assert found.metadata["severity"] == "SEV-2"
    assert found.metadata["public_id"] == 4
    assert found.signals["services"] == ["checkout", "billing"]
    assert [(r.role, r.email) for r in found.references] == [("commander", "nora@acme.test")]


def test_a_metric_is_its_definition() -> None:
    payload = {
        "id": "checkout.latency",
        "type": "manage_tags",
        "attributes": {"metric_type": "Distribution", "tags": ["env", "service"]},
    }

    found = _extract(DATADOG, C.METRICS, payload)

    assert found.title == "checkout.latency"
    assert found.metadata["metric_type"] == "distribution"
    assert found.signals["tags"] == ["env", "service"]


def test_a_log_is_its_first_line_its_status_and_its_host() -> None:
    found = _extract(DATADOG, C.LOGS, log(3))

    assert (found.title, found.state) == ("payment failed 3", "error")
    assert (found.signals["service"], found.signals["host"]) == ("checkout", "i-0abc")
    assert found.content[0].text == "payment failed 3"


def test_a_monitor_without_a_name_is_malformed_and_nothing_of_it_leaks() -> None:
    failure = _failure(DATADOG, C.ALERTS, {"id": 9, "message": SECRET})

    assert failure.code is FailureCode.MALFORMED


# ── PagerDuty ────────────────────────────────────────────────────────────────


def test_a_pagerduty_incident_names_its_service_and_who_is_on_it() -> None:
    payload = {
        **pagerduty_incident(3),
        "priority": {"summary": "P1"},
        "teams": [{"summary": "Payments"}],
        "resolved_at": "2026-09-21T13:00:00Z",
    }

    found = _extract(SourceKind.PAGERDUTY, C.INCIDENTS, payload, container="PCHKOUT")

    assert (found.title, found.state) == ("Checkout errors 3", "resolved")
    assert found.url == payload["html_url"]
    assert found.updated_at == datetime(2026, 9, 21, 13, tzinfo=UTC)
    assert (found.metadata["urgency"], found.metadata["priority"]) == ("high", "P1")
    assert found.metadata["incident_number"] == 3
    assert found.signals["teams"] == ["Payments"]
    roles = {(r.role, r.kind, r.name) for r in found.references}
    assert roles == {("assignee", "person", "Nora"), ("service", "service", "Checkout")}
    assert found.extractor == "pagerduty.incidents"


def test_a_pagerduty_service_is_its_name_status_and_last_incident() -> None:
    found = _extract(SourceKind.PAGERDUTY, C.SERVICES, PAGERDUTY_CHECKOUT)

    assert (found.title, found.state) == ("Checkout", "active")
    assert found.content[0].text == "Payments at checkout"
    assert found.metadata["last_incident_at"] == "2026-09-24T08:00:00+00:00"
