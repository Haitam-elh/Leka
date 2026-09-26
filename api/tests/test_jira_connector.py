"""The Jira connector against a Jira that is not there (LEKA-346).

httpx.MockTransport stands in for acme.atlassian.net: no network, and every
answer Jira can give is given on purpose. Every request is checked to be a
GET, to the site configured, signed in as the account configured.
"""

from __future__ import annotations

import base64
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
from leka.connectors.jira import JiraConfig, JiraConnector, JiraCredentials
from leka.connectors.jira import connector as jira_module

TOKEN = "ATATT3xFfGF0Abcdefghij0123456789_secretpart"
EMAIL = "nora@acme.test"
HOST = "acme.atlassian.net"
V3 = "/rest/api/3"

PAY = {
    "id": "10000",
    "key": "PAY",
    "name": "Payments",
    "description": "The payment flow",
    "isPrivate": True,
    "insight": {"totalIssueCount": 42, "lastIssueUpdateTime": "2026-09-25T09:00:00.000+0000"},
}
OPS = {"id": "10001", "key": "OPS", "name": "Operations", "isPrivate": False}

Answer = object | Callable[[httpx.Request], httpx.Response]


class Jira:
    """A healthy Jira, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.answers: dict[str, Answer] = {
            "/myself": {
                "accountId": "5b10ac8d82e05b22cc7d4ef5",
                "displayName": "Nora Admin",
                "emailAddress": EMAIL,
                "timeZone": "Europe/Paris",
            },
            "/mypermissions": {"permissions": {"ADMINISTER": {"havePermission": False}}},
            "/project/search": [PAY, OPS],
            "/search/jql": {"issues": [], "isLast": True},
            **(overrides or {}),
        }
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads"
        assert request.url.host == HOST
        pair = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
        assert request.headers["authorization"] == f"Basic {pair}"
        self.requests.append(request)
        path = request.url.path.removeprefix(V3)
        answer = self.answers.get(path)
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        if path == "/project/search" and isinstance(answer, list):
            keys = request.url.params.get_list("keys")
            values = [p for p in answer if not keys or p["key"] in keys]
            return httpx.Response(200, json={"values": values, "total": len(values)})
        if answer is not None:
            return httpx.Response(200, json=answer)
        return httpx.Response(404, json={"errorMessages": ["Not found"]})

    def asked(self, path: str) -> list[httpx.QueryParams]:
        return [r.url.params for r in self.requests if r.url.path == V3 + path]


def _connector(jira: Jira, **config: Any) -> JiraConnector:
    return JiraConnector(
        JiraConfig.model_validate({"site": "acme", **config}),
        JiraCredentials(token=SecretStr(TOKEN), email=EMAIL),
        transport=httpx.MockTransport(jira),
    )


async def _failure(jira: Jira, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(jira, **config).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


# ── the catalogue ────────────────────────────────────────────────────────────


def test_jira_is_in_the_catalogue_as_a_project_tool_with_a_write_only_token() -> None:
    manifest = next(m for m in manifests() if m.key == "jira")
    token = manifest.credentials_schema.model_json_schema()["properties"]["token"]

    assert manifest.category is ConnectorCategory.PROJECT
    assert manifest.capabilities == {Capability.PROJECTS, Capability.ISSUES}
    assert manifest.read_only is True
    assert token["writeOnly"] is True


# ── the configuration ────────────────────────────────────────────────────────


def test_the_site_is_kept_as_its_name_and_the_keys_in_capitals() -> None:
    config = JiraConfig.model_validate(
        {"site": "https://ACME.atlassian.net/jira", "projects": ["pay", " ops", "PAY"]}
    )

    assert config.site == "acme"
    assert config.projects == ["PAY", "OPS"]


@pytest.mark.parametrize(
    "config",
    [
        {"site": "evil.example"},
        {"site": "10.0.0.1"},
        {"site": "acme", "projects": []},
        {"site": "acme", "projects": ["1PAY"]},
        {"site": "acme", "projects": ["PAY-1"]},
        {"site": "acme", "projects": ['PAY" OR project = "SEC']},
        {"site": "acme", "unknown": True},
    ],
)
def test_a_configuration_that_could_reach_elsewhere_or_inject_is_refused(
    config: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        JiraConfig.model_validate(config)


def test_the_token_never_shows_in_a_repr() -> None:
    connector = _connector(Jira())

    assert TOKEN not in repr(connector.credentials)
    assert TOKEN not in str(connector.credentials.model_dump())


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_account_reports_itself_and_what_it_can_read() -> None:
    jira = Jira()

    result = await _connector(jira).test_connection()

    assert result.account == "Nora Admin"
    assert result.metadata == {
        "site": "acme.atlassian.net",
        "timezone": "Europe/Paris",
        "projects_visible": 2,
    }
    assert set(result.capabilities) == JiraConnector.manifest.capabilities
    assert result.warnings == []
    # The first visible project is the sample.
    assert jira.asked("/search/jql")[0]["jql"] == 'project = "PAY" ORDER BY updated ASC'


async def test_issues_that_cannot_be_searched_are_left_out_not_failed() -> None:
    refused = httpx.Response(403, json={"errorMessages": ["No permission"]})

    result = await _connector(Jira({"/search/jql": refused})).test_connection()

    assert result.capabilities == [Capability.PROJECTS]


async def test_an_account_that_administers_jira_is_accepted_with_a_warning() -> None:
    admin = {"permissions": {"ADMINISTER": {"havePermission": True}}}

    result = await _connector(Jira({"/mypermissions": admin})).test_connection()

    assert len(result.warnings) == 1
    assert "administre Jira" in result.warnings[0]


async def test_a_jira_that_says_nothing_about_permissions_is_not_a_failure() -> None:
    silent = httpx.Response(404, json={})

    result = await _connector(Jira({"/mypermissions": silent})).test_connection()

    assert result.warnings == []


async def test_an_account_that_sees_no_project_is_told_so() -> None:
    result = await _connector(Jira({"/project/search": []})).test_connection()

    assert result.capabilities == []
    assert result.warnings == ["Aucun projet n'est visible avec ce compte."]


async def test_the_probe_searches_a_project_in_scope() -> None:
    jira = Jira()

    result = await _connector(jira, projects=["OPS"]).test_connection()

    assert result.metadata["projects_visible"] == 1
    assert jira.asked("/search/jql")[0]["jql"] == 'project = "OPS" ORDER BY updated ASC'


async def test_a_project_in_scope_that_jira_does_not_show_fails_the_test() -> None:
    error = await _failure(Jira(), projects=["PAY", "SEC"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == "Jira ne montre pas ces projets à ce compte : SEC."


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, text="Unauthorized"), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(403, json={"message": "scope does not match"}), "INSUFFICIENT_SCOPE"),
        (httpx.Response(403, json={}), DiagnosticCode.PERMISSION_DENIED),
        (httpx.Response(404, json={}), DiagnosticCode.NOT_FOUND),
        (httpx.Response(302, headers={"location": "https://x.example"}), "NOT_FOUND"),
        (httpx.Response(503, text="maintenance"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(response: httpx.Response, code: str) -> None:
    error = await _failure(Jira({"/myself": response}))

    assert error.diagnostic.code == code


async def test_a_site_that_does_not_exist_is_named_as_such() -> None:
    error = await _failure(Jira({"/myself": httpx.Response(404, json={})}))

    assert error.diagnostic.message == (
        "Jira ne trouve pas ce site Atlassian, ou ce compte ne le voit pas."
    )


async def test_an_exhausted_quota_says_when_to_come_back() -> None:
    busy = httpx.Response(429, headers={"retry-after": "42"})

    error = await _failure(Jira({"/myself": busy}))

    assert error.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert error.diagnostic.retry_after == 42


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (httpx.ConnectTimeout("slow"), DiagnosticCode.TIMEOUT),
        (httpx.ConnectError("unreachable"), DiagnosticCode.NETWORK_UNREACHABLE),
    ],
)
async def test_a_jira_that_does_not_answer_or_cannot_be_reached(
    raised: httpx.HTTPError, code: DiagnosticCode
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise raised

    error = await _failure(Jira({"/myself": fail}))

    assert error.diagnostic.code is code


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    echo = httpx.Response(500, text=f"Internal error for token {TOKEN}")

    error = await _failure(Jira({"/myself": echo}))

    assert TOKEN not in (error.diagnostic.detail or "")


# ── health ───────────────────────────────────────────────────────────────────


async def test_health_reads_the_quota_atlassian_announces() -> None:
    near = httpx.Response(200, json={}, headers={"x-ratelimit-nearlimit": "true"})

    healthy = await _connector(Jira()).check_health()
    degraded = await _connector(Jira({"/myself": near})).check_health()

    assert healthy.status is HealthStatus.HEALTHY
    assert degraded.status is HealthStatus.DEGRADED


async def test_health_fails_like_a_test_when_the_token_is_revoked() -> None:
    with pytest.raises(ConnectorError) as caught:
        await _connector(Jira({"/myself": httpx.Response(401)})).check_health()

    assert caught.value.diagnostic.code is DiagnosticCode.AUTH_INVALID


# ── the scope ────────────────────────────────────────────────────────────────


async def test_the_scope_is_chosen_from_every_visible_project() -> None:
    listing = await _connector(Jira(), projects=["OPS"]).list_scope()

    assert [(o.key, o.name, o.private) for o in listing.options] == [
        ("PAY", "Payments", True),
        ("OPS", "Operations", False),
    ]
    assert listing.options[0].description == "The payment flow"
    assert listing.options[0].updated_at is not None
    assert listing.truncated is False


async def test_a_listing_too_long_to_offer_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jira_module, "MAX_SCOPE_OPTIONS", 1)

    listing = await _connector(Jira()).list_scope()

    assert [o.key for o in listing.options] == ["PAY"]
    assert listing.truncated is True


async def test_a_page_link_to_another_host_is_not_followed_with_the_token() -> None:
    def elsewhere(request: httpx.Request) -> httpx.Response:
        following = "https://evil.example/rest/api/3/project/search?startAt=50"
        return httpx.Response(200, json={"values": [PAY], "nextPage": following})

    with pytest.raises(ConnectorError) as caught:
        await _connector(Jira({"/project/search": elsewhere})).list_scope()

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert "evil.example" in (caught.value.diagnostic.detail or "")
