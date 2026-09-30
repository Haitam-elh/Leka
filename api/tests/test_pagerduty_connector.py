"""The PagerDuty connector against a PagerDuty that is not there (LEKA-348).

httpx.MockTransport stands in for api.pagerduty.com. It checks the other
half of "LEKA reads": every request is a GET, to PagerDuty's API in the
account's region, with the key as `Token token=…` and the API version asked.
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
from leka.connectors.pagerduty import PagerDutyConfig, PagerDutyConnector, PagerDutyCredentials
from leka.connectors.pagerduty import connector as pagerduty_module

KEY = "u+AbCdEfGhIjKlMnOpQr"
C = Capability

CHECKOUT: dict[str, Any] = {
    "id": "PCHKOUT",
    "name": "Checkout",
    "description": "Payments at checkout",
    "status": "active",
    "updated_at": "2026-09-25T09:00:00Z",
    "last_incident_timestamp": "2026-09-24T08:00:00Z",
    "html_url": "https://acme.pagerduty.com/service-directory/PCHKOUT",
}
SEARCH: dict[str, Any] = {"id": "PSEARCH", "name": "Search", "status": "active"}


def incident(number: int, service: str = "PCHKOUT") -> dict[str, Any]:
    return {
        "id": f"Q{number:013d}",
        "incident_number": number,
        "title": f"Checkout errors {number}",
        "status": "resolved",
        "urgency": "high",
        "created_at": "2026-09-21T12:00:00Z",
        "updated_at": "2026-09-21T13:00:00Z",
        "service": {"id": service, "summary": "Checkout"},
        "assignments": [{"assignee": {"id": "PUSER1", "summary": "Nora"}}],
        "html_url": f"https://acme.pagerduty.com/incidents/Q{number:013d}",
    }


Answer = object | Callable[[httpx.Request], httpx.Response]


class PagerDuty:
    """A healthy PagerDuty, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None, host: str = "") -> None:
        self.host = host or "api.pagerduty.com"
        self.services = [CHECKOUT, SEARCH]
        self.incidents: list[dict[str, Any]] = []
        self.answers: dict[str, Answer] = {
            "/abilities": {"abilities": ["teams", "urgencies"]},
            "/services": lambda r: self._page(r, "services", self.services),
            "/incidents": lambda r: self._page(r, "incidents", self._incidents(r)),
            **(overrides or {}),
        }
        self.asked: list[httpx.Request] = []

    def _incidents(self, request: httpx.Request) -> list[dict[str, Any]]:
        wanted = request.url.params.get_list("service_ids[]")
        return [i for i in self.incidents if not wanted or i["service"]["id"] in wanted]

    def _page(self, request: httpx.Request, field: str, items: list[Any]) -> httpx.Response:
        limit = int(request.url.params.get("limit", 25))
        offset = int(request.url.params.get("offset", 0))
        found = items[offset : offset + limit]
        more = offset + limit < len(items)
        body = {field: found, "limit": limit, "offset": offset, "more": more, "total": None}
        return httpx.Response(200, json=body)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads PagerDuty with GETs"
        assert request.url.host == self.host
        assert request.headers["authorization"] == f"Token token={KEY}"
        assert request.headers["accept"] == "application/vnd.pagerduty+json;version=2"
        self.asked.append(request)
        answer = self.answers.get(request.url.path)
        if answer is None:
            return httpx.Response(404, json={"error": {"message": "Not Found", "code": 2100}})
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def requests(self, path: str) -> list[httpx.Request]:
        return [r for r in self.asked if r.url.path == path]


def _connector(pagerduty: PagerDuty, **config: Any) -> PagerDutyConnector:
    return PagerDutyConnector(
        PagerDutyConfig.model_validate(config),
        PagerDutyCredentials(api_key=SecretStr(KEY)),
        transport=httpx.MockTransport(pagerduty),
    )


async def _failure(pagerduty: PagerDuty, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(pagerduty, **config).test_connection()
    assert KEY not in repr(caught.value.diagnostic)
    return caught.value


async def _stream(
    pagerduty: PagerDuty, capability: Capability, since: datetime | None = None, **config: Any
) -> list[RawRecord]:
    connector = _connector(pagerduty, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def test_pagerduty_is_in_the_catalogue_as_an_observability_source() -> None:
    manifest = next(m for m in manifests() if m.key == "pagerduty")
    key = manifest.credentials_schema.model_json_schema()["properties"]["api_key"]

    assert manifest.category is ConnectorCategory.OBSERVABILITY
    assert manifest.capabilities == {C.SERVICES, C.INCIDENTS}
    assert manifest.listed_whole == {C.SERVICES}
    assert key["writeOnly"] is True


def test_services_are_kept_as_pagerduty_ids_whether_typed_or_pasted() -> None:
    config = PagerDutyConfig.model_validate(
        {
            "region": "EU",
            "services": ["pchkout", "https://acme.pagerduty.com/service-directory/PSEARCH"],
        }
    )

    assert config.region == "eu"
    assert config.services == ["PCHKOUT", "PSEARCH"]


@pytest.mark.parametrize(
    "config",
    [{"region": "asia"}, {"services": []}, {"services": ["checkout"]}, {"team": "x"}],
)
def test_a_configuration_pagerduty_would_not_know_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PagerDutyConfig.model_validate(config)


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_key_reads_services_and_incidents() -> None:
    pagerduty = PagerDuty()

    result = await _connector(pagerduty).test_connection()

    assert result.metadata == {"region": "us", "services_visible": 2, "abilities": 2}
    assert set(result.capabilities) == {C.SERVICES, C.INCIDENTS}
    assert result.warnings == []


async def test_an_eu_account_is_read_in_the_eu() -> None:
    pagerduty = PagerDuty(host="api.eu.pagerduty.com")

    result = await _connector(pagerduty, region="eu").test_connection()

    assert result.capabilities


async def test_a_key_refused_its_incidents_still_reads_services() -> None:
    forbidden = httpx.Response(403, json={"error": {"message": "Forbidden", "code": 2010}})

    result = await _connector(PagerDuty({"/incidents": forbidden})).test_connection()

    assert result.capabilities == [C.SERVICES]


async def test_a_service_in_scope_pagerduty_does_not_show_fails_the_test() -> None:
    error = await _failure(PagerDuty(), services=["PCHKOUT", "PGONE00"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert "PGONE00" in error.diagnostic.message


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, json={"error": {"code": 2006}}), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(403, json={"error": {"code": 2010}}), DiagnosticCode.PERMISSION_DENIED),
        (httpx.Response(429, headers={"ratelimit-reset": "12"}), DiagnosticCode.RATE_LIMITED),
        (httpx.Response(502, text="bad gateway"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(PagerDuty({"/abilities": response}))

    assert error.diagnostic.code is code


async def test_an_echoed_key_is_removed_from_the_detail() -> None:
    error = await _failure(PagerDuty({"/abilities": httpx.Response(500, text=f"bad {KEY}")}))

    assert KEY not in (error.diagnostic.detail or "")


async def test_health_reads_what_is_left_of_the_quota() -> None:
    headers = {"ratelimit-limit": "960", "ratelimit-remaining": "20", "ratelimit-reset": "30"}
    low = httpx.Response(200, json={"abilities": []}, headers=headers)

    healthy = await _connector(PagerDuty()).check_health()
    degraded = await _connector(PagerDuty({"/abilities": low})).check_health()

    assert healthy.status is HealthStatus.HEALTHY
    assert (degraded.status, degraded.detail) == (HealthStatus.DEGRADED, "quota 20/960")


async def test_the_scope_is_chosen_from_every_service() -> None:
    listing = await _connector(PagerDuty()).list_scope()

    assert [(o.key, o.name, o.description) for o in listing.options] == [
        ("PCHKOUT", "Checkout", "Payments at checkout"),
        ("PSEARCH", "Search", None),
    ]


# ── what is read ─────────────────────────────────────────────────────────────


async def test_services_come_whole_those_in_scope_only() -> None:
    every = await _stream(PagerDuty(), C.SERVICES)
    some = await _stream(PagerDuty(), C.SERVICES, services=["PSEARCH"])

    assert [r.external_id for r in every] == ["PCHKOUT", "PSEARCH"]
    assert [r.external_id for r in some] == ["PSEARCH"]
    assert every[0].updated_at == datetime(2026, 9, 25, 9, tzinfo=UTC)


# ── dependencies and business services (LEKA-362) ────────────────────────────

ONLINE_SHOP: dict[str, Any] = {
    "id": "PBSHOP1",
    "type": "business_service",
    "name": "Online shop",
    "description": "What customers buy through",
    "point_of_contact": "shop-leads@acme.test",
    "team": {"id": "PTEAM01", "type": "team_reference", "summary": "Commerce"},
    "html_url": "https://acme.pagerduty.com/business_services/PBSHOP1",
}


def depends(dependent: str, supporting: str, kind: str = "technical") -> dict[str, Any]:
    reference = f"{kind}_service_reference"
    return {
        "type": "service_dependency",
        "supporting_service": {"id": supporting, "type": reference},
        "dependent_service": {"id": dependent, "type": "technical_service_reference"},
    }


def mapped(pagerduty: PagerDuty) -> PagerDuty:
    """Checkout depends on Search; the Online shop is Checkout's and Search's."""
    pagerduty.answers |= {
        "/business_services": lambda r: pagerduty._page(r, "business_services", [ONLINE_SHOP]),
        "/service_dependencies/technical_services/PCHKOUT": {
            "relationships": [depends("PCHKOUT", "PSEARCH"), depends("PBSHOP1", "PCHKOUT")]
        },
        "/service_dependencies/technical_services/PSEARCH": {
            "relationships": [depends("PCHKOUT", "PSEARCH")]
        },
        "/service_dependencies/business_services/PBSHOP1": {
            "relationships": [depends("PBSHOP1", "PCHKOUT"), depends("PBSHOP1", "PSEARCH")]
        },
    }
    return pagerduty


async def test_each_service_comes_with_what_it_depends_on() -> None:
    found = {r.external_id: r.payload for r in await _stream(mapped(PagerDuty()), C.SERVICES)}

    # Its own side only: Checkout depends on Search, not on what depends on it.
    assert found["PCHKOUT"]["dependencies"] == [
        {"id": "PSEARCH", "name": "Search", "type": "technical"}
    ]
    assert found["PSEARCH"]["dependencies"] == []


async def test_business_services_come_with_the_services_that_support_them() -> None:
    found = {r.external_id: r.payload for r in await _stream(mapped(PagerDuty()), C.SERVICES)}

    shop: dict[str, Any] = found["PBSHOP1"]
    assert shop["type"] == "business_service"
    assert shop["name"] == "Online shop"
    assert [d["name"] for d in shop["dependencies"]] == ["Checkout", "Search"]


async def test_a_scope_keeps_the_business_services_its_services_support() -> None:
    pagerduty = mapped(PagerDuty())
    pagerduty.services = [*pagerduty.services, {"id": "PADMIN1", "name": "Admin"}]
    pagerduty.answers["/service_dependencies/business_services/PBSHOP1"] = {
        "relationships": [depends("PBSHOP1", "PCHKOUT")]
    }

    shopping = await _stream(pagerduty, C.SERVICES, services=["PCHKOUT"])
    admin = await _stream(pagerduty, C.SERVICES, services=["PADMIN1"])

    assert [r.external_id for r in shopping] == ["PCHKOUT", "PBSHOP1"]
    assert [r.external_id for r in admin] == ["PADMIN1"]


async def test_an_account_without_dependencies_or_business_services_reads_services() -> None:
    forbidden = httpx.Response(403, json={"error": {"message": "Forbidden", "code": 2010}})
    pagerduty = PagerDuty({"/business_services": forbidden})

    found = await _stream(pagerduty, C.SERVICES)

    # The dependency paths answer 404 here: read without them.
    assert [(r.external_id, r.payload["dependencies"]) for r in found] == [
        ("PCHKOUT", []),
        ("PSEARCH", []),
    ]


async def test_past_the_dependency_budget_services_are_read_without(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pagerduty_module, "MAX_DEPENDENCY_READS", 1)
    pagerduty = mapped(PagerDuty())

    found = {r.external_id: r.payload for r in await _stream(pagerduty, C.SERVICES)}

    assert found["PCHKOUT"]["dependencies"] != []
    assert found["PSEARCH"]["dependencies"] == []
    assert pagerduty.requests("/service_dependencies/technical_services/PSEARCH") == []


async def test_each_pass_reads_the_incidents_of_the_last_ninety_days() -> None:
    pagerduty = PagerDuty()
    pagerduty.incidents = [incident(1), incident(2, "PSEARCH")]

    records = await _stream(pagerduty, C.INCIDENTS, since=datetime(2026, 9, 20, tzinfo=UTC))

    assert [(r.external_id, r.container) for r in records] == [
        ("Q0000000000001", "PCHKOUT"),
        ("Q0000000000002", "PSEARCH"),
    ]
    assert records[0].updated_at == datetime(2026, 9, 21, 13, tzinfo=UTC)
    params = pagerduty.requests("/incidents")[0].url.params
    since = datetime.fromisoformat(params["since"])
    assert abs(datetime.now(UTC) - timedelta(days=90) - since) < timedelta(minutes=1)


async def test_only_the_incidents_of_the_services_in_scope_are_read() -> None:
    pagerduty = PagerDuty()
    pagerduty.incidents = [incident(1), incident(2, "PSEARCH")]

    records = await _stream(pagerduty, C.INCIDENTS, services=["PSEARCH"])

    assert [r.container for r in records] == ["PSEARCH"]
    assert pagerduty.requests("/incidents")[0].url.params.get_list("service_ids[]") == ["PSEARCH"]


async def test_incidents_are_followed_across_offsets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pagerduty_module, "PAGE_SIZE", 2)
    pagerduty = PagerDuty()
    pagerduty.incidents = [incident(n) for n in range(1, 6)]

    records = await _stream(pagerduty, C.INCIDENTS)

    assert len(records) == 5
    assert [r.url.params["offset"] for r in pagerduty.requests("/incidents")] == ["0", "2", "4"]


async def test_a_low_quota_mid_stream_keeps_what_was_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pagerduty_module, "PAGE_SIZE", 1)
    headers = {"ratelimit-limit": "960", "ratelimit-remaining": "5", "ratelimit-reset": "40"}

    def low(request: httpx.Request) -> httpx.Response:
        body = {"incidents": [incident(1)], "more": True}
        return httpx.Response(200, json=body, headers=headers)

    connector = _connector(PagerDuty({"/incidents": low}))
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(C.INCIDENTS):
            read.append(item)

    assert len(read) == 1
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED


async def test_pagerduty_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(PagerDuty(), C.PAGES)
