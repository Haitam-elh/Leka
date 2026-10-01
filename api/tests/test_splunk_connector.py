"""The Splunk connector against a Splunk that is not there.

httpx.MockTransport stands in for Splunk's REST API on its management port.
It checks the other half of "LEKA reads": every request is a GET, to that
Splunk, with the token as Bearer, asking for JSON. The address itself is
checked by leka/connectors/network.py when saved and when connecting.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
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
    RawRecord,
    manifests,
)
from leka.connectors.splunk import SplunkConfig, SplunkConnector, SplunkCredentials
from leka.connectors.splunk import connector as splunk_module
from leka.connectors.splunk.connector import entry_key, is_alert

TOKEN = "eyJraWQiOiJzcGx1bmsuc2VjcmV0IiwiYWxnIjoiSFM1MTIifQ.leka-test-token"
HOST = "acme.splunkcloud.com"
PORT = 8089
C = Capability


def saved(name: str, app: str = "search", **content: Any) -> dict[str, Any]:
    quoted = name.replace(" ", "%20")
    return {
        "name": name,
        "id": f"https://{HOST}:{PORT}/servicesNS/nobody/{app}/saved/searches/{quoted}",
        "updated": "2026-09-30T10:00:00+02:00",
        "author": "nora",
        "acl": {"app": app, "owner": "nobody"},
        "content": {"search": "index=web status>=500 | stats count", **content},
    }


DISK_FULL = saved(
    "Disk full",
    is_scheduled=True,
    cron_schedule="*/5 * * * *",
    alert_type="number of events",
    **{"alert.severity": "4"},
    actions="email,webhook",
)
WEEKLY_REPORT = saved("Weekly report", is_scheduled=True, alert_type="always")
TRACKED = saved(
    "Logins", app="security", is_scheduled="1", alert_type="always", **{"alert.track": "1"}
)
FIRED: dict[str, Any] = {
    "name": "Disk full",
    "id": f"https://{HOST}:{PORT}/servicesNS/nobody/search/alerts/fired_alerts/Disk%20full",
    "updated": "2026-09-30T10:05:00+02:00",
    "acl": {"app": "search"},
    "content": {
        "savedsearch_name": "Disk full",
        "sid": "scheduler__nobody__search__RMD5_at_1790762700_42",
        "trigger_time": 1790762700,
        "severity": 4,
        "app": "search",
    },
}
OPS = {
    "name": "ops_overview",
    "id": f"https://{HOST}:{PORT}/servicesNS/nobody/search/data/ui/views/ops_overview",
    "updated": "2026-09-29T08:00:00+02:00",
    "author": "nora",
    "acl": {"app": "search", "owner": "nobody"},
    "content": {"label": "Ops overview", "description": "5xx and latency", "isDashboard": True},
}
SEARCH_VIEW = {**OPS, "name": "search", "content": {"label": "Search", "isDashboard": False}}

Answer = object | Callable[[httpx.Request], httpx.Response]


class Splunk:
    """A healthy Splunk, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.searches: list[dict[str, Any]] = [DISK_FULL, WEEKLY_REPORT, TRACKED]
        self.fired: list[dict[str, Any]] = [FIRED]
        self.views: list[dict[str, Any]] = [OPS, SEARCH_VIEW]
        self.answers: dict[str, Answer] = {
            "/services/authentication/current-context": {
                "entry": [
                    {"content": {"username": "leka", "realname": "LEKA reader", "roles": ["user"]}}
                ]
            },
            "/servicesNS/-/-/saved/searches": lambda r: self._page(r, self.searches),
            "/services/alerts/fired_alerts/-": lambda r: self._page(r, self.fired),
            "/servicesNS/-/-/data/ui/views": lambda r: self._page(r, self.views),
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def _page(self, request: httpx.Request, items: list[dict[str, Any]]) -> httpx.Response:
        count = int(request.url.params.get("count", 30))
        offset = int(request.url.params.get("offset", 0))
        body = {
            "entry": items[offset : offset + count],
            "paging": {"total": len(items), "perPage": count, "offset": offset},
        }
        return httpx.Response(200, json=body)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads Splunk with GETs"
        assert (request.url.scheme, request.url.host, request.url.port) == ("https", HOST, PORT)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.url.params.get("output_mode") == "json"
        self.asked.append(request)
        answer = self.answers.get(request.url.path)
        if answer is None:
            return httpx.Response(404, json={"messages": [{"type": "ERROR", "text": "Not Found"}]})
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def requests(self, path: str) -> list[httpx.Request]:
        return [r for r in self.asked if r.url.path == path]


def _connector(splunk: Splunk) -> SplunkConnector:
    return SplunkConnector(
        SplunkConfig.model_validate({"base_url": f"https://{HOST}:{PORT}"}),
        SplunkCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(splunk),
    )


async def _failure(splunk: Splunk) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(splunk).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


async def _stream(splunk: Splunk, capability: Capability) -> list[RawRecord]:
    return [r async for r in _connector(splunk).iter_resources(capability)]


def test_splunk_is_in_the_catalogue_as_an_observability_source() -> None:
    manifest = next(m for m in manifests() if m.key == "splunk")
    token = manifest.credentials_schema.model_json_schema()["properties"]["token"]

    assert manifest.category is ConnectorCategory.OBSERVABILITY
    assert manifest.capabilities == {C.ALERTS, C.EVENTS, C.DASHBOARDS}
    assert manifest.listed_whole == {C.ALERTS, C.DASHBOARDS}
    assert token["writeOnly"] is True


@pytest.mark.parametrize(
    "address",
    ["http://acme.splunkcloud.com:8089", "https://127.0.0.1:8089", "https://10.1.2.3:8089"],
)
def test_an_address_that_is_not_public_https_is_refused_on_save(address: str) -> None:
    with pytest.raises(ValidationError):
        SplunkConfig.model_validate({"base_url": address})


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_token_reports_whose_it_is_and_what_it_can_read() -> None:
    result = await _connector(Splunk()).test_connection()

    assert result.account == "LEKA reader"
    assert result.metadata == {"url": f"https://{HOST}:{PORT}/", "roles": ["user"]}
    assert set(result.capabilities) == {C.ALERTS, C.EVENTS, C.DASHBOARDS}
    assert result.warnings == []


async def test_what_the_role_may_not_read_is_left_out() -> None:
    forbidden = httpx.Response(403, json={"messages": [{"text": "forbidden"}]})
    splunk = Splunk({"/services/alerts/fired_alerts/-": forbidden})

    result = await _connector(splunk).test_connection()

    assert set(result.capabilities) == {C.ALERTS, C.DASHBOARDS}


async def test_a_token_that_reads_nothing_is_told_what_role_to_give() -> None:
    forbidden = httpx.Response(403, json={})
    splunk = Splunk(
        {
            "/servicesNS/-/-/saved/searches": forbidden,
            "/services/alerts/fired_alerts/-": forbidden,
            "/servicesNS/-/-/data/ui/views": forbidden,
        }
    )

    result = await _connector(splunk).test_connection()

    assert result.capabilities == []
    assert "rôle" in result.warnings[0]


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={}), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(403, json={}), DiagnosticCode.PERMISSION_DENIED),
        (httpx.Response(404, text="Not found"), DiagnosticCode.NOT_FOUND),
        (httpx.Response(429, headers={"retry-after": "5"}), DiagnosticCode.RATE_LIMITED),
        (httpx.Response(503, text="unavailable"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Splunk({"/services/authentication/current-context": response}))

    assert error.diagnostic.code is code


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    echoed = httpx.Response(500, text=f"bad token {TOKEN}")
    error = await _failure(Splunk({"/services/authentication/current-context": echoed}))

    assert TOKEN not in (error.diagnostic.detail or "")


async def test_health_is_the_token_answering() -> None:
    assert (await _connector(Splunk()).check_health()).status is HealthStatus.HEALTHY


# ── what is read ─────────────────────────────────────────────────────────────


async def test_alerts_are_the_saved_searches_that_alert_in_their_app() -> None:
    found = await _stream(Splunk(), C.ALERTS)

    assert [(r.external_id, r.container) for r in found] == [
        ("nobody/search/saved/searches/Disk full", "search"),
        ("nobody/security/saved/searches/Logins", "security"),
    ]
    assert found[0].payload == DISK_FULL
    assert found[0].updated_at == datetime(2026, 9, 30, 8, 0, tzinfo=UTC)


async def test_saved_searches_are_read_page_after_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(splunk_module, "PAGE_SIZE", 2)
    splunk = Splunk()

    found = await _stream(splunk, C.ALERTS)

    assert len(found) == 2
    offsets = [r.url.params["offset"] for r in splunk.requests("/servicesNS/-/-/saved/searches")]
    assert offsets == ["0", "2"]


async def test_fired_alerts_come_with_when_they_fired() -> None:
    [fired] = await _stream(Splunk(), C.EVENTS)

    assert fired.external_id == "scheduler__nobody__search__RMD5_at_1790762700_42"
    assert fired.container == "search"
    assert fired.updated_at == datetime.fromtimestamp(1790762700, tz=UTC)


async def test_dashboards_are_the_views_that_are_dashboards_without_their_source() -> None:
    splunk = Splunk()

    found = await _stream(splunk, C.DASHBOARDS)

    assert [r.external_id for r in found] == ["nobody/search/data/ui/views/ops_overview"]
    asked = splunk.requests("/servicesNS/-/-/data/ui/views")[0]
    assert asked.url.params.get_list("f") == ["label", "description", "isDashboard", "isVisible"]


async def test_splunk_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Splunk(), C.PAGES)


@pytest.mark.parametrize(
    ("content", "alerting"),
    [
        ({"is_scheduled": True, "alert_type": "number of events"}, True),
        ({"is_scheduled": "1", "alert_type": "always", "alert.track": "1"}, True),
        ({"is_scheduled": True, "alert_type": "always"}, False),
        ({"is_scheduled": False, "alert_type": "custom"}, False),
        ({}, False),
    ],
)
def test_a_report_is_not_an_alert(content: dict[str, Any], alerting: bool) -> None:
    assert is_alert({"content": content}) is alerting


def test_an_entry_is_known_by_its_place_not_its_host() -> None:
    entry: dict[str, Any] = {
        "id": "https://elsewhere.example:8089/servicesNS/nora/search/saved/searches/A%20b"
    }

    assert entry_key(entry) == "nora/search/saved/searches/A b"
    assert entry_key({"name": "plain"}) == "plain"
