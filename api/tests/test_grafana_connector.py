"""The Grafana connector against a Grafana that is not there (LEKA-348).

httpx.MockTransport stands in for the Grafana at the configured address. It
checks the other half of "LEKA reads": every request is a GET, to that
Grafana, with the service account's token as Bearer. The address itself is
checked by leka/connectors/network.py when saved and when connecting.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
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
from leka.connectors.grafana import GrafanaConfig, GrafanaConnector, GrafanaCredentials
from leka.connectors.grafana import connector as grafana_module

TOKEN = "glsa_" + "AbCdEfGhIjKlMnOpQrStUvWxYz012345_1a2b3c4d"
HOST = "acme.grafana.net"
C = Capability

LATENCY: dict[str, Any] = {
    "uid": "abc123",
    "title": "Checkout latency",
    "url": "/d/abc123/checkout-latency",
    "type": "dash-db",
    "tags": ["checkout", "slo"],
    "folderUid": "f-pay",
    "folderTitle": "Payments",
}
FIRING: dict[str, Any] = {
    "uid": "rule-1",
    "name": "Checkout 5xx",
    "state": "firing",
    "health": "ok",
    "type": "alerting",
    "query": "sum(rate(http_requests_total{code=~'5..'}[5m])) > 1",
    "labels": {"service": "checkout", "severity": "critical"},
    "annotations": {"summary": "Checkout is failing"},
    "lastEvaluation": "2026-09-25T09:00:00Z",
}

Answer = object | Callable[[httpx.Request], httpx.Response]


def annotation(number: int, when: datetime) -> dict[str, Any]:
    ms = int(when.timestamp() * 1000)
    return {
        "id": number,
        "dashboardUID": "abc123",
        "panelId": 2,
        "time": ms,
        "updated": ms,
        "text": f"Deploy {number}",
        "tags": ["deploy", "checkout"],
    }


class Grafana:
    """A healthy Grafana, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.dashboards = [LATENCY]
        self.groups: list[dict[str, Any]] = [
            {"name": "checkout", "file": "Payments", "rules": [FIRING]},
        ]
        self.annotations: list[dict[str, Any]] = []
        self.answers: dict[str, Answer] = {
            "/api/org": {"id": 1, "name": "Acme"},
            "/api/search": self._search,
            "/api/prometheus/grafana/api/v1/rules": lambda _: httpx.Response(
                200, json={"status": "success", "data": {"groups": self.groups}}
            ),
            "/api/annotations": lambda _: httpx.Response(200, json=self.annotations),
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def _search(self, request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params.get("limit", 1000))
        page = int(request.url.params.get("page", 1))
        return httpx.Response(200, json=self.dashboards[(page - 1) * limit : page * limit])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads Grafana with GETs"
        assert (request.url.scheme, request.url.host) == ("https", HOST)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        self.asked.append(request)
        answer = self.answers.get(request.url.path)
        if answer is None:
            return httpx.Response(404, json={"message": "Not found"})
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def requests(self, path: str) -> list[httpx.Request]:
        return [r for r in self.asked if r.url.path == path]


def _connector(grafana: Grafana, **config: Any) -> GrafanaConnector:
    return GrafanaConnector(
        GrafanaConfig.model_validate({"base_url": f"https://{HOST}", **config}),
        GrafanaCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(grafana),
    )


async def _failure(grafana: Grafana) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(grafana).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


async def _stream(
    grafana: Grafana, capability: Capability, since: datetime | None = None
) -> list[RawRecord]:
    return [r async for r in _connector(grafana).iter_resources(capability, since=since)]


def test_grafana_is_in_the_catalogue_as_an_observability_source() -> None:
    manifest = next(m for m in manifests() if m.key == "grafana")
    token = manifest.credentials_schema.model_json_schema()["properties"]["token"]

    assert manifest.category is ConnectorCategory.OBSERVABILITY
    assert manifest.capabilities == {C.DASHBOARDS, C.ALERTS, C.EVENTS}
    assert manifest.listed_whole == {C.DASHBOARDS, C.ALERTS}
    assert token["writeOnly"] is True


@pytest.mark.parametrize(
    "address",
    [
        "http://acme.grafana.net",
        "https://127.0.0.1:3000",
        "https://10.0.0.5",
        "https://169.254.169.254",
        "https://[::1]",
        "not an address",
    ],
)
def test_an_address_that_is_not_public_https_is_refused_on_save(address: str) -> None:
    with pytest.raises(ValidationError):
        GrafanaConfig.model_validate({"base_url": address})


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_token_reports_the_organisation_and_what_it_can_read() -> None:
    result = await _connector(Grafana()).test_connection()

    assert result.account == "Acme"
    assert result.metadata == {"url": f"https://{HOST}/"}
    assert set(result.capabilities) == {C.DASHBOARDS, C.ALERTS, C.EVENTS}
    assert result.warnings == []


async def test_what_the_token_may_not_read_is_left_out() -> None:
    forbidden = httpx.Response(403, json={"message": "Permission denied"})
    grafana = Grafana({"/api/prometheus/grafana/api/v1/rules": forbidden})

    result = await _connector(grafana).test_connection()

    assert set(result.capabilities) == {C.DASHBOARDS, C.EVENTS}


async def test_a_token_that_reads_nothing_is_told_the_role_to_give() -> None:
    forbidden = httpx.Response(403, json={"message": "Permission denied"})
    grafana = Grafana(
        {
            "/api/search": forbidden,
            "/api/prometheus/grafana/api/v1/rules": forbidden,
            "/api/annotations": forbidden,
        }
    )

    result = await _connector(grafana).test_connection()

    assert result.capabilities == []
    assert "Viewer" in result.warnings[0]


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={"message": "invalid API key"}), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(403, json={}), DiagnosticCode.PERMISSION_DENIED),
        (httpx.Response(404, text="Not found"), DiagnosticCode.NOT_FOUND),
        (httpx.Response(429, headers={"retry-after": "5"}), DiagnosticCode.RATE_LIMITED),
        (httpx.Response(502, text="bad gateway"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Grafana({"/api/org": response}))

    assert error.diagnostic.code is code


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    error = await _failure(Grafana({"/api/org": httpx.Response(500, text=f"bad {TOKEN}")}))

    assert TOKEN not in (error.diagnostic.detail or "")


async def test_health_is_the_organisation_answering() -> None:
    assert (await _connector(Grafana()).check_health()).status is HealthStatus.HEALTHY


# ── what is read ─────────────────────────────────────────────────────────────


async def test_dashboards_come_whole_in_their_folder_with_their_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(grafana_module, "SEARCH_PAGE", 1)
    grafana = Grafana()
    grafana.dashboards = [LATENCY, {**LATENCY, "uid": "def456", "folderTitle": None}]

    records = await _stream(grafana, C.DASHBOARDS)

    assert [(r.external_id, r.container) for r in records] == [
        ("abc123", "Payments"),
        ("def456", None),
    ]
    assert records[0].payload["web_url"] == f"https://{HOST}/d/abc123/checkout-latency"
    assert [r.url.params["page"] for r in grafana.requests("/api/search")] == ["1", "2", "3"]


async def test_alert_rules_come_with_their_state_group_and_folder() -> None:
    grafana = Grafana()
    grafana.groups.append(
        {"name": "rec", "file": "Payments", "rules": [{"name": "rate", "type": "recording"}]}
    )

    records = await _stream(grafana, C.ALERTS)

    assert [(r.external_id, r.container) for r in records] == [("rule-1", "Payments")]
    assert (records[0].payload["state"], records[0].payload["group"]) == ("firing", "checkout")
    assert records[0].updated_at == datetime(2026, 9, 25, 9, tzinfo=UTC)


async def test_a_rule_without_a_uid_is_known_by_its_folder_group_and_name() -> None:
    grafana = Grafana()
    grafana.groups = [{"name": "g", "file": "Ops", "rules": [{"name": "Disk", "type": "alerting"}]}]

    records = await _stream(grafana, C.ALERTS)

    assert records[0].external_id == "Ops/g/Disk"


async def test_annotations_are_read_since_the_last_pass_less_a_margin() -> None:
    grafana = Grafana()
    since = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)
    grafana.annotations = [annotation(7, datetime(2026, 9, 21, 12, tzinfo=UTC))]

    records = await _stream(grafana, C.EVENTS, since=since)

    assert [(r.external_id, r.container) for r in records] == [("7", "abc123")]
    assert records[0].updated_at == datetime(2026, 9, 21, 12, tzinfo=UTC)
    params = grafana.requests("/api/annotations")[0].url.params
    assert int(params["from"]) == int((since - timedelta(minutes=5)).timestamp() * 1000)
    assert params["limit"] == str(grafana_module.MAX_ANNOTATIONS)


async def test_an_initial_pass_reads_a_month_of_annotations() -> None:
    grafana = Grafana()

    await _stream(grafana, C.EVENTS)

    started = int(grafana.requests("/api/annotations")[0].url.params["from"]) / 1000
    expected = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    assert abs(started - expected) < 60


async def test_grafana_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Grafana(), C.PAGES)
