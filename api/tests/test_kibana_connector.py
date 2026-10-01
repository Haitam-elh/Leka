"""The Kibana connector against a Kibana that is not there.

httpx.MockTransport stands in for the Kibana at the configured address. It
checks the other half of "LEKA reads": every request is a GET, to that
Kibana, with the Elastic API key as `ApiKey`. The address itself is checked
by leka/connectors/network.py when saved and when connecting.
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
from leka.connectors.kibana import KibanaConfig, KibanaConnector, KibanaCredentials
from leka.connectors.kibana import connector as kibana_module

API_KEY = "VnVhQ2ZHY0JDZGJrUW0tZTVhT3g6dWkybHAyYXhUTm1zeWFrdzl0dk5udw=="
HOST = "acme.kb.europe-west1.gcp.cloud.es.io"
C = Capability

RULE: dict[str, Any] = {
    "id": "r-5xx",
    "name": "Checkout 5xx",
    "tags": ["service:checkout", "team:payments"],
    "rule_type_id": "apm.error_rate",
    "consumer": "apm",
    "enabled": True,
    "schedule": {"interval": "1m"},
    "execution_status": {"status": "active", "last_execution_date": "2026-09-30T09:59:00Z"},
    "created_by": "nora",
    "created_at": "2026-09-01T08:00:00Z",
    "updated_at": "2026-09-29T08:00:00Z",
}
CASE: dict[str, Any] = {
    "id": "c-42",
    "title": "Checkout errors after deploy",
    "description": "5xx on **checkout** since 09:40",
    "status": "in-progress",
    "severity": "high",
    "tags": ["service:checkout"],
    "owner": "observability",
    "created_by": {"username": "nora", "full_name": "Nora Diallo", "email": "nora@acme.io"},
    "created_at": "2026-09-30T09:45:00Z",
    "updated_at": "2026-09-30T10:10:00Z",
    "closed_at": None,
    "totalComment": 3,
}
DASHBOARD: dict[str, Any] = {
    "id": "d-ops",
    "type": "dashboard",
    "attributes": {"title": "Ops overview", "description": "Errors and latency"},
    "updated_at": "2026-09-28T08:00:00Z",
}

Answer = object | Callable[[httpx.Request], httpx.Response]


class Kibana:
    """A healthy Kibana with two spaces, unless a path is overridden."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.rules = {"default": [RULE], "payments": [{**RULE, "id": "r-ledger"}]}
        self.cases = {"default": [CASE], "payments": []}
        self.dashboards = {"default": [DASHBOARD], "payments": []}
        self.answers: dict[str, Answer] = {
            "/api/status": {"name": "acme-kibana", "version": {"number": "8.15.0"}},
            "/api/spaces/space": [{"id": "default", "name": "Default"}, {"id": "payments"}],
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def _listing(self, request: httpx.Request, space: str, rest: str) -> httpx.Response | None:
        if rest == "/api/alerting/rules/_find":
            items, field, size = self.rules.get(space, []), "data", "per_page"
        elif rest == "/api/cases/_find":
            items, field, size = self.cases.get(space, []), "cases", "perPage"
        elif rest == "/api/saved_objects/_find":
            items, field, size = self.dashboards.get(space, []), "saved_objects", "per_page"
        else:
            return None
        per_page = int(request.url.params.get(size, 20))
        page = int(request.url.params.get("page", 1))
        body = {
            field: items[(page - 1) * per_page : page * per_page],
            "total": len(items),
            "page": page,
        }
        return httpx.Response(200, json=body)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads Kibana with GETs"
        assert (request.url.scheme, request.url.host) == ("https", HOST)
        assert request.headers["authorization"] == f"ApiKey {API_KEY}"
        self.asked.append(request)
        path = request.url.path
        answer = self.answers.get(path)
        if answer is None:
            space, rest = "default", path
            if path.startswith("/s/"):
                _, _, space, rest = path.split("/", 3)
                rest = "/" + rest
            listed = self._listing(request, space, rest)
            if listed is not None:
                return listed
            return httpx.Response(404, json={"statusCode": 404, "error": "Not Found"})
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def paths(self) -> list[str]:
        return [r.url.path for r in self.asked]


def _connector(kibana: Kibana) -> KibanaConnector:
    return KibanaConnector(
        KibanaConfig.model_validate({"base_url": f"https://{HOST}"}),
        KibanaCredentials(api_key=SecretStr(API_KEY)),
        transport=httpx.MockTransport(kibana),
    )


async def _failure(kibana: Kibana) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(kibana).test_connection()
    assert API_KEY not in repr(caught.value.diagnostic)
    return caught.value


async def _stream(kibana: Kibana, capability: Capability) -> list[RawRecord]:
    return [r async for r in _connector(kibana).iter_resources(capability)]


def test_kibana_is_in_the_catalogue_as_an_observability_source() -> None:
    manifest = next(m for m in manifests() if m.key == "kibana")
    key = manifest.credentials_schema.model_json_schema()["properties"]["api_key"]

    assert manifest.category is ConnectorCategory.OBSERVABILITY
    assert manifest.capabilities == {C.ALERTS, C.INCIDENTS, C.DASHBOARDS}
    assert manifest.listed_whole == {C.ALERTS, C.INCIDENTS, C.DASHBOARDS}
    assert key["writeOnly"] is True


@pytest.mark.parametrize("address", ["http://kibana.acme.io", "https://192.168.1.4:5601"])
def test_an_address_that_is_not_public_https_is_refused_on_save(address: str) -> None:
    with pytest.raises(ValidationError):
        KibanaConfig.model_validate({"base_url": address})


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_key_reports_the_kibana_and_what_it_can_read() -> None:
    result = await _connector(Kibana()).test_connection()

    assert result.account == "acme-kibana"
    assert result.metadata == {"url": f"https://{HOST}/", "version": "8.15.0"}
    assert set(result.capabilities) == {C.ALERTS, C.INCIDENTS, C.DASHBOARDS}
    assert result.warnings == []


async def test_a_key_that_reads_nothing_is_told_what_to_give() -> None:
    forbidden = httpx.Response(403, json={"statusCode": 403})
    kibana = Kibana(
        {
            "/api/alerting/rules/_find": forbidden,
            "/api/cases/_find": forbidden,
            "/api/saved_objects/_find": forbidden,
        }
    )

    result = await _connector(kibana).test_connection()

    assert result.capabilities == []
    assert "cas" in result.warnings[0]


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={}), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(403, json={}), DiagnosticCode.PERMISSION_DENIED),
        (httpx.Response(404, json={}), DiagnosticCode.NOT_FOUND),
        (httpx.Response(429, headers={"retry-after": "5"}), DiagnosticCode.RATE_LIMITED),
        (httpx.Response(503, text="unavailable"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Kibana({"/api/status": response}))

    assert error.diagnostic.code is code


async def test_an_echoed_key_is_removed_from_the_detail() -> None:
    error = await _failure(Kibana({"/api/status": httpx.Response(500, text=f"bad {API_KEY}")}))

    assert API_KEY not in (error.diagnostic.detail or "")


async def test_health_is_the_kibana_answering() -> None:
    assert (await _connector(Kibana()).check_health()).status is HealthStatus.HEALTHY


# ── what is read ─────────────────────────────────────────────────────────────


async def test_rules_are_read_in_every_space_each_its_container() -> None:
    kibana = Kibana()

    found = await _stream(kibana, C.ALERTS)

    assert [(r.external_id, r.container) for r in found] == [
        ("default/r-5xx", "default"),
        ("payments/r-ledger", "payments"),
    ]
    assert found[0].payload["web_url"] == (
        f"https://{HOST}/app/management/insightsAndAlerting/triggersActions/rule/r-5xx"
    )
    assert str(found[1].payload["web_url"]).startswith(f"https://{HOST}/s/payments/app/")
    assert "/s/payments/api/alerting/rules/_find" in kibana.paths()
    assert found[0].updated_at == datetime(2026, 9, 29, 8, 0, tzinfo=UTC)


async def test_cases_come_with_where_to_open_them() -> None:
    [case] = await _stream(Kibana(), C.INCIDENTS)

    assert case.external_id == "default/c-42"
    assert case.payload["web_url"] == f"https://{HOST}/app/observability/cases/c-42"
    assert case.payload["space"] == "default"


async def test_dashboards_are_read_with_their_title_only() -> None:
    kibana = Kibana()

    [dashboard] = await _stream(kibana, C.DASHBOARDS)

    assert dashboard.payload["web_url"] == f"https://{HOST}/app/dashboards#/view/d-ops"
    asked = next(r for r in kibana.asked if r.url.path == "/api/saved_objects/_find")
    assert asked.url.params.get_list("fields") == ["title", "description"]


async def test_a_kibana_without_spaces_is_its_default_space() -> None:
    kibana = Kibana({"/api/spaces/space": httpx.Response(404, json={})})

    found = await _stream(kibana, C.ALERTS)

    assert [r.container for r in found] == ["default"]


async def test_listings_are_read_page_after_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kibana_module, "PAGE_SIZE", 1)
    kibana = Kibana()
    kibana.cases["default"] = [CASE, {**CASE, "id": "c-43"}]

    found = await _stream(kibana, C.INCIDENTS)

    assert [r.external_id for r in found] == ["default/c-42", "default/c-43"]


async def test_kibana_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Kibana(), C.PAGES)
