"""What the Datadog connector reads for the sync engine (LEKA-348).

The same stand-in Datadog as test_datadog_connector.py. What matters here:
the services in scope and nothing else; monitors and incidents whole; the
streams — events and logs — from the last pass, newest first, capped;
Datadog's own ids and timestamps kept; the quota spared.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from leka.connectors.datadog import connector as datadog_module
from leka.connectors.http import dig
from tests.test_datadog_connector import Datadog, _connector

C = Capability
SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    datadog: Datadog, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(datadog, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def event(number: int, service: str = "checkout") -> dict[str, Any]:
    return {
        "id": f"AQAAAY{number:04d}",
        "type": "event",
        "attributes": {
            "timestamp": f"2026-09-21T12:{number:02d}:00.000Z",
            "message": f"Deploy {number} of {service}",
            "tags": [f"service:{service}", "env:prod"],
            "attributes": {"title": f"Deploy {number}", "service": service, "status": "info"},
        },
    }


def log(number: int, service: str = "checkout") -> dict[str, Any]:
    return {
        "id": f"AwAAAX{number:04d}",
        "type": "log",
        "attributes": {
            "timestamp": f"2026-09-21T12:{number:02d}:00.000Z",
            "message": f"payment failed {number}",
            "status": "error",
            "service": service,
            "host": "i-0abc",
            "tags": ["env:prod"],
        },
    }


def incident(number: int, *services: str) -> dict[str, Any]:
    return {
        "id": f"00000000-0000-0000-0000-{number:012d}",
        "type": "incidents",
        "attributes": {
            "public_id": number,
            "title": f"Checkout down {number}",
            "state": "active",
            "severity": "SEV-2",
            "created": "2026-09-21T12:00:00+00:00",
            "modified": "2026-09-21T13:00:00+00:00",
            "fields": {"services": {"type": "autocomplete", "value": list(services)}},
        },
        "relationships": {"commander_user": {"data": {"id": "u-7", "type": "users"}}},
    }


async def test_every_monitor_is_read_whole_with_its_service_and_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(datadog_module, "MONITOR_PAGE", 2)
    datadog = Datadog()

    records = await _stream(datadog, C.ALERTS)

    assert [(r.external_id, r.container) for r in records] == [
        ("101", "checkout"),
        ("102", "search"),
        ("103", None),
    ]
    assert records[0].payload["web_url"] == "https://app.datadoghq.eu/monitors/101"
    assert records[0].updated_at == datetime(2026, 9, 25, 9, tzinfo=UTC)
    assert [p["page"] for p in datadog.params("/api/v1/monitor")] == ["0", "1"]


async def test_only_the_monitors_of_the_services_in_scope_are_read() -> None:
    records = await _stream(Datadog(), C.ALERTS, services=["search"])

    assert [r.external_id for r in records] == ["102"]


async def test_an_initial_pass_reads_a_month_of_events_newest_first() -> None:
    datadog = Datadog()
    datadog.events = [event(2), event(1)]

    records = await _stream(datadog, C.EVENTS)

    assert [(r.external_id, r.container) for r in records] == [
        ("AQAAAY0002", "checkout"),
        ("AQAAAY0001", "checkout"),
    ]
    assert records[0].updated_at == datetime(2026, 9, 21, 12, 2, tzinfo=UTC)
    params = datadog.params("/api/v2/events")[0]
    assert params["sort"] == "-timestamp"
    started = datetime.fromtimestamp(int(params["filter[from]"]) / 1000, tz=UTC)
    assert abs(datetime.now(UTC) - timedelta(days=30) - started) < timedelta(minutes=1)
    assert "filter[query]" not in params


async def test_an_incremental_pass_reads_events_since_the_last_one_less_a_margin() -> None:
    datadog = Datadog()

    await _stream(datadog, C.EVENTS, since=SINCE, services=["checkout", "billing"])

    params = datadog.params("/api/v2/events")[0]
    assert int(params["filter[from]"]) == int((SINCE - timedelta(minutes=5)).timestamp() * 1000)
    assert params["filter[query]"] == "service:(checkout OR billing)"


async def test_the_streams_are_followed_across_cursors_and_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(datadog_module, "STREAM_PAGE", 2)
    monkeypatch.setattr(datadog_module, "MAX_EVENTS", 3)
    datadog = Datadog()
    datadog.events = [event(n) for n in range(5, 0, -1)]

    records = await _stream(datadog, C.EVENTS)

    assert [r.external_id for r in records] == ["AQAAAY0005", "AQAAAY0004", "AQAAAY0003"]
    assert [p.get("page[cursor]") for p in datadog.params("/api/v2/events")] == [None, "2"]


async def test_a_cursor_datadog_repeats_ends_the_pass_rather_than_loop() -> None:
    again = {"data": [event(1)], "meta": {"page": {"after": "same"}}}
    datadog = Datadog({"/api/v2/events": again})

    with pytest.raises(ConnectorError) as caught:
        await _stream(datadog, C.EVENTS)

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR


async def test_logs_are_read_by_the_query_and_the_services_in_scope() -> None:
    datadog = Datadog()
    datadog.logs = [log(1)]

    records = await _stream(datadog, C.LOGS, since=SINCE, services=["checkout"])

    assert [(r.external_id, r.container) for r in records] == [("AwAAAX0001", "checkout")]
    assert records[0].payload["web_url"] == "https://app.datadoghq.eu/logs?event=AwAAAX0001"
    params = datadog.params("/api/v2/logs/events")[0]
    assert params["filter[query]"] == "(status:error) service:(checkout)"
    assert params["filter[from]"] == (SINCE - timedelta(minutes=5)).isoformat()


async def test_a_query_of_their_own_is_the_logs_read() -> None:
    datadog = Datadog()

    await _stream(datadog, C.LOGS, logs_query="status:(error OR warn) env:prod")

    assert datadog.params("/api/v2/logs/events")[0]["filter[query]"] == (
        "status:(error OR warn) env:prod"
    )


async def test_incidents_come_whole_with_their_people_and_services() -> None:
    datadog = Datadog()
    datadog.incidents = [incident(1, "checkout"), incident(2, "billing"), incident(3)]
    datadog.users = [
        {"id": "u-7", "type": "users", "attributes": {"name": "Nora", "email": "n@a.t"}}
    ]

    records = await _stream(datadog, C.INCIDENTS)

    assert [(r.external_id[-1], r.container) for r in records] == [
        ("1", "checkout"),
        ("2", "billing"),
        ("3", None),
    ]
    assert dig(records[0].payload, "people.commander_user") == {"name": "Nora", "email": "n@a.t"}
    assert records[0].payload["web_url"] == "https://app.datadoghq.eu/incidents/1"


async def test_incidents_are_followed_across_offsets_those_in_scope_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(datadog_module, "INCIDENT_PAGE", 2)
    datadog = Datadog()
    datadog.incidents = [incident(n, "checkout" if n % 2 else "billing") for n in range(1, 6)]

    records = await _stream(datadog, C.INCIDENTS, services=["checkout"])

    assert [dig(r.payload, "attributes.public_id") for r in records] == [1, 3, 5]
    assert [p["page[offset]"] for p in datadog.params("/api/v2/incidents")] == ["0", "2", "4"]


async def test_metrics_are_read_by_cursor_those_of_the_services_in_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(datadog_module, "METRIC_PAGE", 2)
    datadog = Datadog()
    datadog.metrics = [
        {"id": f"checkout.latency.p{n}", "type": "metrics", "attributes": {"metric_type": "gauge"}}
        for n in range(3)
    ]

    records = await _stream(datadog, C.METRICS, services=["checkout"])

    assert [r.external_id for r in records] == [f"checkout.latency.p{n}" for n in range(3)]
    asked = datadog.params("/api/v2/metrics")
    assert asked[0]["filter[tags]"] == "service:checkout"
    assert [p.get("page[cursor]") for p in asked] == [None, "2"]


async def test_a_low_quota_mid_stream_keeps_what_was_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(datadog_module, "STREAM_PAGE", 1)
    headers = {"x-ratelimit-limit": "100", "x-ratelimit-remaining": "2", "x-ratelimit-reset": "30"}

    def low(request: httpx.Request) -> httpx.Response:
        body = {"data": [event(1)], "meta": {"page": {"after": "1"}}}
        return httpx.Response(200, json=body, headers=headers)

    connector = _connector(Datadog({"/api/v2/events": low}))
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(C.EVENTS):
            read.append(item)

    assert [r.external_id for r in read] == ["AQAAAY0001"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after is not None
    assert 25 <= caught.value.diagnostic.retry_after <= 30


async def test_a_refused_read_names_the_permission() -> None:
    forbidden = httpx.Response(403, json={"errors": ["Forbidden"]})

    with pytest.raises(ConnectorError) as caught:
        await _stream(Datadog({"/api/v2/incidents": forbidden}), C.INCIDENTS)

    assert caught.value.diagnostic.code is DiagnosticCode.PERMISSION_DENIED
    assert "incident_read" in caught.value.diagnostic.message


async def test_datadog_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Datadog(), C.PAGES)
