"""Datadog's, PagerDuty's and Grafana's records, extracted for what comes
after (LEKA-348 → LEKA-354).

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
from tests.test_datadog_resources import BILLING_V22, LEDGER_V3, event, incident, log
from tests.test_extraction import SECRET, _extract, _failure
from tests.test_grafana_connector import FIRING as GRAFANA_FIRING
from tests.test_grafana_connector import LATENCY as GRAFANA_LATENCY
from tests.test_grafana_connector import annotation as grafana_annotation
from tests.test_pagerduty_connector import CHECKOUT as PAGERDUTY_CHECKOUT
from tests.test_pagerduty_connector import ONLINE_SHOP
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


def test_a_pagerduty_service_names_the_services_it_depends_on() -> None:
    payload = {
        **PAGERDUTY_CHECKOUT,
        "dependencies": [
            {"id": "PSEARCH", "name": "Search", "type": "technical"},
            {"id": "PBSHOP1", "name": "Online shop", "type": "business"},
        ],
    }

    found = _extract(SourceKind.PAGERDUTY, C.SERVICES, payload)

    assert found.signals["depends_on"] == ["Search"]
    assert "kind" not in found.signals


def test_a_pagerduty_business_service_is_an_application_and_its_services() -> None:
    payload = {
        **ONLINE_SHOP,
        "dependencies": [
            {"id": "PCHKOUT", "name": "Checkout", "type": "technical"},
            {"id": "PBPAY01", "name": "Payments", "type": "business"},
        ],
    }

    found = _extract(SourceKind.PAGERDUTY, C.SERVICES, payload)

    assert found.title == "Online shop"
    assert found.signals["kind"] == "application"
    assert found.signals["teams"] == ["Commerce"]
    assert found.signals["services"] == ["Checkout"]
    assert found.signals["depends_on"] == ["Payments"]
    assert found.metadata["point_of_contact"] == "shop-leads@acme.test"
    assert found.extractor == "pagerduty.services"


# ── the Datadog service catalog (LEKA-362) ───────────────────────────────────


def test_a_catalog_service_v2_is_its_team_application_tier_and_links() -> None:
    found = _extract(DATADOG, C.SERVICES, BILLING_V22)

    assert found.title == "billing-api"
    assert found.content[0].text == "Invoices and refunds"
    assert found.signals["teams"] == ["payments"]
    assert found.signals["application"] == "Billing"
    assert "depends_on" not in found.signals  # nothing: not said
    assert {k: found.metadata[k] for k in ("tier", "lifecycle", "service_type")} == {
        "tier": "1",
        "lifecycle": "production",
        "service_type": "web",
    }
    assert found.metadata["languages"] == ["python"]
    assert found.metadata["runbook_url"] == "https://wiki.acme.test/billing"
    assert found.metadata["repository_url"] == "https://github.com/acme/billing-api"
    assert found.updated_at == datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


def test_a_catalog_service_v3_says_its_owner_system_and_dependencies() -> None:
    found = _extract(DATADOG, C.SERVICES, LEDGER_V3)

    assert found.title == "ledger"
    assert found.signals["teams"] == ["finance-platform"]
    assert found.signals["application"] == "billing"
    assert found.signals["depends_on"] == ["postgres-ledger", "billing-api"]
    assert (found.metadata["tier"], found.metadata["lifecycle"]) == ("2", "deprecated")
    assert found.metadata["display_name"] == "Ledger"
    assert found.metadata["dashboard_url"] == "https://x.test"


def test_a_catalog_definition_without_a_name_is_malformed() -> None:
    failure = _failure(DATADOG, C.SERVICES, {"attributes": {"schema": {"team": "x"}}})

    assert failure.code is FailureCode.MALFORMED


# ── Grafana ──────────────────────────────────────────────────────────────────


def test_a_grafana_rule_is_an_alert_with_its_state_labels_and_summary() -> None:
    payload = {**GRAFANA_FIRING, "group": "checkout", "folder": "Payments"}

    found = _extract(SourceKind.GRAFANA, C.ALERTS, payload, external_id="rule-1")

    assert (found.title, found.state) == ("Checkout 5xx", "firing")
    assert found.content[0].text == "Checkout is failing"
    assert found.updated_at == datetime(2026, 9, 25, 9, tzinfo=UTC)
    assert (found.signals["service"], found.signals["severity"]) == ("checkout", "critical")
    assert found.signals["tags"] == ["service:checkout", "severity:critical"]
    assert (found.metadata["group"], found.metadata["folder"]) == ("checkout", "Payments")


def test_a_grafana_dashboard_is_its_title_folder_and_tags() -> None:
    payload = {**GRAFANA_LATENCY, "web_url": "https://acme.grafana.net/d/abc123/checkout-latency"}

    found = _extract(SourceKind.GRAFANA, C.DASHBOARDS, payload)

    assert found.title == "Checkout latency"
    assert found.url == payload["web_url"]
    assert found.metadata["folder"] == "Payments"
    assert found.signals["tags"] == ["checkout", "slo"]


def test_a_grafana_annotation_keeps_its_time_from_milliseconds() -> None:
    when = datetime(2026, 9, 21, 12, tzinfo=UTC)

    found = _extract(SourceKind.GRAFANA, C.EVENTS, grafana_annotation(7, when))

    assert found.title == "Deploy 7"
    assert found.created_at == found.updated_at == when
    assert found.metadata["dashboard_uid"] == "abc123"
