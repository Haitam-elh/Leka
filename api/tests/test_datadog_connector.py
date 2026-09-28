"""The Datadog connector against a Datadog that is not there (LEKA-348).

httpx.MockTransport stands in for api.<site>. It checks the other half of
"LEKA reads": every request is a GET, to the organisation's own site, with
the API key and the application key in Datadog's headers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from leka.connectors import (
    Capability,
    ConnectorCategory,
    ConnectorError,
    DiagnosticCode,
    HealthStatus,
    manifests,
)
from leka.connectors.datadog import DatadogConfig, DatadogConnector, DatadogCredentials

API_KEY = "0123456789abcdef0123456789abcdef"
APP_KEY = "fedcba9876543210fedcba9876543210fedcba98"
HOST = "api.datadoghq.eu"
C = Capability

CHECKOUT: dict[str, Any] = {
    "id": 101,
    "name": "Checkout p99 latency",
    "type": "query alert",
    "query": "avg(last_5m):p99:trace.http.request{service:checkout} > 2",
    "message": "Latency is high @pagerduty",
    "tags": ["service:checkout", "env:prod", "team:payments"],
    "overall_state": "Alert",
    "created": "2026-01-10T09:00:00.000000+00:00",
    "modified": "2026-09-25T09:00:00.000000+00:00",
    "priority": 2,
}
DISK: dict[str, Any] = {
    "id": 102,
    "name": "Disk almost full",
    "type": "metric alert",
    "tags": ["service:search", "env:prod"],
    "overall_state": "OK",
    "modified": "2026-09-20T09:00:00.000000+00:00",
}
UNTAGGED: dict[str, Any] = {"id": 103, "name": "Heartbeat", "tags": [], "overall_state": "OK"}

Answer = object | Callable[[httpx.Request], httpx.Response]


def refused(status: int, *errors: str, **headers: str) -> httpx.Response:
    return httpx.Response(status, json={"errors": list(errors) or ["Forbidden"]}, headers=headers)


class Datadog:
    """A healthy Datadog, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.monitors = [CHECKOUT, DISK, UNTAGGED]
        self.events: list[dict[str, Any]] = []
        self.logs: list[dict[str, Any]] = []
        self.incidents: list[dict[str, Any]] = []
        self.users: list[dict[str, Any]] = []
        self.metrics: list[dict[str, Any]] = []
        self.catalog = ["checkout", "billing"]
        self.answers: dict[str, Answer] = {
            "/api/v1/validate": {"valid": True},
            "/api/v2/current_user": {
                "data": {"id": "u-1", "attributes": {"email": "leka@acme.test", "handle": "leka"}}
            },
            "/api/v1/monitor": self._monitors,
            "/api/v2/events": lambda r: self._stream(r, self.events),
            "/api/v2/logs/events": lambda r: self._stream(r, self.logs),
            "/api/v2/incidents": self._incidents,
            "/api/v2/metrics": self._metrics,
            "/api/v2/services/definitions": self._catalog,
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def _monitors(self, request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        size = int(request.url.params["page_size"])
        return httpx.Response(200, json=self.monitors[page * size : (page + 1) * size])

    def _stream(self, request: httpx.Request, items: list[dict[str, Any]]) -> httpx.Response:
        size = int(request.url.params["page[limit]"])
        start = int(request.url.params.get("page[cursor]", "0"))
        body: dict[str, Any] = {"data": items[start : start + size], "meta": {"page": {}}}
        if start + size < len(items):
            body["meta"]["page"]["after"] = str(start + size)
        return httpx.Response(200, json=body)

    def _incidents(self, request: httpx.Request) -> httpx.Response:
        size = int(request.url.params["page[size]"])
        offset = int(request.url.params.get("page[offset]", "0"))
        found = self.incidents[offset : offset + size]
        pagination: dict[str, Any] = {"offset": offset, "size": len(found)}
        if offset + size < len(self.incidents):
            pagination["next_offset"] = offset + size
        body = {"data": found, "included": self.users, "meta": {"pagination": pagination}}
        return httpx.Response(200, json=body)

    def _metrics(self, request: httpx.Request) -> httpx.Response:
        size = int(request.url.params["page[size]"])
        start = int(request.url.params.get("page[cursor]", "0"))
        cursor = str(start + size) if start + size < len(self.metrics) else None
        body = {
            "data": self.metrics[start : start + size],
            "meta": {"pagination": {"next_cursor": cursor}},
        }
        return httpx.Response(200, json=body)

    def _catalog(self, request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page[number]"])
        size = int(request.url.params["page[size]"])
        names = self.catalog[page * size : (page + 1) * size]
        data = [{"attributes": {"schema": {"dd-service": name}}} for name in names]
        return httpx.Response(200, json={"data": data})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads Datadog with GETs"
        assert request.url.host == HOST, "the keys go to the organisation's own site"
        assert request.headers["dd-api-key"] == API_KEY
        assert request.headers["dd-application-key"] == APP_KEY
        self.asked.append(request)
        answer = self.answers.get(request.url.path)
        if answer is None:
            return refused(404, "Not found")
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def params(self, path: str) -> list[dict[str, str]]:
        return [dict(r.url.params) for r in self.asked if r.url.path == path]


def _connector(datadog: Datadog, **config: Any) -> DatadogConnector:
    return DatadogConnector(
        DatadogConfig.model_validate({"site": "datadoghq.eu", **config}),
        DatadogCredentials(application_key=SecretStr(APP_KEY), api_key=SecretStr(API_KEY)),
        transport=httpx.MockTransport(datadog),
    )


async def _failure(datadog: Datadog, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(datadog, **config).test_connection()
    for key in (API_KEY, APP_KEY):
        assert key not in repr(caught.value.diagnostic)
    return caught.value


def test_datadog_is_in_the_catalogue_as_an_observability_source() -> None:
    manifest = next(m for m in manifests() if m.key == "datadog")
    secrets = manifest.credentials_schema.model_json_schema()["properties"]

    assert manifest.category is ConnectorCategory.OBSERVABILITY
    assert manifest.capabilities == {C.ALERTS, C.EVENTS, C.INCIDENTS, C.METRICS, C.LOGS}
    assert manifest.listed_whole == {C.ALERTS, C.INCIDENTS}
    assert list(secrets) == ["application_key", "api_key"]
    assert all(field["writeOnly"] is True for field in secrets.values())


# ── the configuration ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("datadoghq.com", "datadoghq.com"),
        (" DATADOGHQ.EU ", "datadoghq.eu"),
        ("https://app.datadoghq.eu/dashboard/abc-123", "datadoghq.eu"),
        ("https://us5.datadoghq.com/monitors/manage", "us5.datadoghq.com"),
        ("api.ddog-gov.com", "ddog-gov.com"),
    ],
)
def test_the_site_is_kept_as_datadog_names_it(given: str, kept: str) -> None:
    assert DatadogConfig.model_validate({"site": given}).site == kept


@pytest.mark.parametrize(
    "config",
    [
        {"site": "evil.test"},
        {"site": "datadoghq.com.evil.test"},
        {"site": "http://10.0.0.1/admin"},
        {"services": []},
        {"services": ["Check out!"]},
        {"logs_query": ""},
        {"org": "acme"},
    ],
)
def test_a_configuration_datadog_would_not_know_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DatadogConfig.model_validate(config)


def test_services_are_kept_in_small_letters_once() -> None:
    config = DatadogConfig.model_validate({"services": ["Checkout", "service:checkout", "billing"]})

    assert config.services == ["checkout", "billing"]
    assert config.logs_query == "status:error"


# ── the connection test ──────────────────────────────────────────────────────


async def test_working_keys_report_the_account_and_all_it_can_read() -> None:
    datadog = Datadog()

    result = await _connector(datadog).test_connection()

    assert result.account == "leka@acme.test"
    assert result.metadata == {"site": "datadoghq.eu", "services": None}
    assert set(result.capabilities) == DatadogConnector.manifest.capabilities
    assert result.warnings == []
    probe = next(p for p in datadog.params("/api/v2/logs/events"))
    assert probe["filter[query]"] == "status:error"


async def test_a_permission_the_application_key_lacks_leaves_its_data_out() -> None:
    datadog = Datadog({"/api/v2/logs/events": refused(403)})

    result = await _connector(datadog).test_connection()

    assert C.LOGS not in result.capabilities
    assert C.ALERTS in result.capabilities


async def test_a_key_that_can_read_nothing_is_told_which_permissions_to_give() -> None:
    nothing: dict[str, Answer] = {
        path: refused(403)
        for path in (
            "/api/v1/monitor",
            "/api/v2/events",
            "/api/v2/incidents",
            "/api/v2/metrics",
            "/api/v2/logs/events",
        )
    }

    result = await _connector(Datadog(nothing)).test_connection()

    assert result.capabilities == []
    assert "monitors_read" in result.warnings[0]


async def test_a_refused_api_key_is_named() -> None:
    error = await _failure(Datadog({"/api/v1/validate": refused(403)}))

    assert error.diagnostic.code is DiagnosticCode.AUTH_INVALID
    assert "clé d'API" in error.diagnostic.message


async def test_a_refused_application_key_is_named() -> None:
    error = await _failure(Datadog({"/api/v2/current_user": refused(403)}))

    assert error.diagnostic.code is DiagnosticCode.AUTH_INVALID
    assert "clé d'application" in error.diagnostic.message


async def test_an_exhausted_quota_says_when_to_come_back() -> None:
    busy = refused(429, "Too many requests", **{"x-ratelimit-reset": "17"})

    error = await _failure(Datadog({"/api/v1/validate": busy}))

    assert (error.diagnostic.code, error.diagnostic.retry_after) == (
        DiagnosticCode.RATE_LIMITED,
        17,
    )


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (refused(404), DiagnosticCode.NOT_FOUND),
        (httpx.Response(503, text="down"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Datadog({"/api/v2/current_user": response}))

    assert error.diagnostic.code is code


async def test_both_keys_are_removed_from_an_echoed_detail() -> None:
    echo = httpx.Response(500, text=f"bad keys {API_KEY} and {APP_KEY}")

    error = await _failure(Datadog({"/api/v2/current_user": echo}))

    assert API_KEY not in (error.diagnostic.detail or "")
    assert APP_KEY not in (error.diagnostic.detail or "")


# ── health, the scope ────────────────────────────────────────────────────────


async def test_health_reads_what_is_left_of_the_quota() -> None:
    headers = {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "40", "x-ratelimit-reset": "9"}
    low = httpx.Response(200, json={"valid": True}, headers=headers)

    healthy = await _connector(Datadog()).check_health()
    degraded = await _connector(Datadog({"/api/v1/validate": low})).check_health()

    assert healthy.status is HealthStatus.HEALTHY
    assert (degraded.status, degraded.detail) == (HealthStatus.DEGRADED, "quota 40/1000")


async def test_the_scope_is_chosen_from_the_catalog_and_the_monitors_tags() -> None:
    listing = await _connector(Datadog()).list_scope()

    assert [(o.key, o.description) for o in listing.options] == [
        ("billing", "Catalogue de services"),
        ("checkout", "Catalogue de services"),
        ("search", "Tag des moniteurs"),
    ]


async def test_without_the_catalog_the_monitors_tags_still_offer_services() -> None:
    datadog = Datadog({"/api/v2/services/definitions": refused(403)})

    listing = await _connector(datadog).list_scope()

    assert [o.key for o in listing.options] == ["checkout", "search"]
