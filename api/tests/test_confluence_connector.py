"""The Confluence connector against a Confluence that is not there (LEKA-346).

httpx.MockTransport stands in for acme.atlassian.net/wiki: no network, and
every answer Confluence can give is given on purpose. Every request is
checked to be a GET, to the site configured, signed in as the account
configured.
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
from leka.connectors.confluence import (
    ConfluenceConfig,
    ConfluenceConnector,
    ConfluenceCredentials,
)
from leka.connectors.confluence import connector as confluence_module

TOKEN = "ATATT3xFfGF0Abcdefghij0123456789_secretpart"
EMAIL = "nora@acme.test"
HOST = "acme.atlassian.net"
WIKI = "/wiki"

ENG = {
    "id": "98304",
    "key": "ENG",
    "name": "Engineering",
    "type": "global",
    "status": "current",
    "description": {"plain": {"value": "How we build", "representation": "plain"}},
}
OPS = {"id": "98305", "key": "OPS", "name": "Operations", "type": "global", "status": "current"}

Answer = object | Callable[[httpx.Request], httpx.Response]


class Confluence:
    """A healthy Confluence, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.answers: dict[str, Answer] = {
            "/rest/api/user/current": {
                "type": "known",
                "accountId": "5b10ac8d82e05b22cc7d4ef5",
                "displayName": "Nora Admin",
                "email": EMAIL,
            },
            "/api/v2/spaces": [ENG, OPS],
            **(overrides or {}),
        }
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads"
        assert request.url.host == HOST
        pair = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
        assert request.headers["authorization"] == f"Basic {pair}"
        self.requests.append(request)
        path = request.url.path.removeprefix(WIKI)
        answer = self.answers.get(path)
        if callable(answer):
            response: httpx.Response = answer(request)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        if path == "/api/v2/spaces" and isinstance(answer, list):
            keys = request.url.params.get("keys")
            wanted = keys.split(",") if keys else None
            results = [space for space in answer if not wanted or space["key"] in wanted]
            return httpx.Response(200, json={"results": results, "_links": {}})
        if answer is not None:
            return httpx.Response(200, json=answer)
        if path.startswith("/api/v2/spaces/") and path.endswith("/pages"):
            return httpx.Response(200, json={"results": [], "_links": {}})
        return httpx.Response(404, json={"errors": [{"status": 404, "title": "Not Found"}]})

    def asked(self, path: str) -> list[httpx.QueryParams]:
        return [r.url.params for r in self.requests if r.url.path == WIKI + path]


def _connector(confluence: Confluence, **config: Any) -> ConfluenceConnector:
    return ConfluenceConnector(
        ConfluenceConfig.model_validate({"site": "acme", **config}),
        ConfluenceCredentials(token=SecretStr(TOKEN), email=EMAIL),
        transport=httpx.MockTransport(confluence),
    )


async def _failure(confluence: Confluence, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(confluence, **config).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


# ── the catalogue ────────────────────────────────────────────────────────────


def test_confluence_is_in_the_catalogue_as_a_documentation_tool() -> None:
    manifest = next(m for m in manifests() if m.key == "confluence")
    token = manifest.credentials_schema.model_json_schema()["properties"]["token"]

    assert manifest.category is ConnectorCategory.DOCS
    assert manifest.capabilities == {Capability.SPACES, Capability.PAGES}
    assert manifest.read_only is True
    assert token["writeOnly"] is True


# ── the configuration ────────────────────────────────────────────────────────


def test_the_site_is_kept_as_its_name_and_the_keys_as_typed() -> None:
    config = ConfluenceConfig.model_validate(
        {
            "site": "https://acme.atlassian.net/wiki/spaces/ENG/overview",
            "spaces": ["ENG", " ~5b10ac8d82e05b22cc7d4ef5", "ENG"],
        }
    )

    assert config.site == "acme"
    assert config.spaces == ["ENG", "~5b10ac8d82e05b22cc7d4ef5"]


@pytest.mark.parametrize(
    "config",
    [
        {"site": "evil.example"},
        {"site": "192.168.1.10"},
        {"site": "acme", "spaces": []},
        {"site": "acme", "spaces": ["ENG-1"]},
        {"site": "acme", "spaces": ["EN G"]},
        {"site": "acme", "spaces": ["ENG,OPS"]},
        {"site": "acme", "unknown": True},
    ],
)
def test_a_configuration_that_could_reach_elsewhere_or_widen_is_refused(
    config: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ConfluenceConfig.model_validate(config)


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_account_reports_itself_and_what_it_can_read() -> None:
    confluence = Confluence()

    result = await _connector(confluence).test_connection()

    assert result.account == "Nora Admin"
    assert result.metadata == {"site": "acme.atlassian.net", "spaces_visible": 2}
    assert set(result.capabilities) == ConfluenceConnector.manifest.capabilities
    assert result.warnings == []
    # The first visible space is the sample.
    assert confluence.asked("/api/v2/spaces/98304/pages") != []


async def test_pages_that_cannot_be_read_are_left_out_not_failed() -> None:
    refused = httpx.Response(403, json={"errors": [{"title": "Forbidden"}]})

    connector = _connector(Confluence({"/api/v2/spaces/98304/pages": refused}))
    result = await connector.test_connection()

    assert result.capabilities == [Capability.SPACES]


async def test_an_account_that_sees_no_space_is_told_so() -> None:
    result = await _connector(Confluence({"/api/v2/spaces": []})).test_connection()

    assert result.capabilities == []
    assert result.warnings == ["Aucun espace n'est visible avec ce compte."]


async def test_more_spaces_than_one_page_are_counted_as_such() -> None:
    more = {"results": [ENG], "_links": {"next": "/wiki/api/v2/spaces?cursor=c2"}}

    result = await _connector(Confluence({"/api/v2/spaces": more})).test_connection()

    assert result.metadata["spaces_visible"] == "1+"


async def test_an_anonymous_answer_is_a_refused_sign_in() -> None:
    anonymous = {"type": "anonymous", "displayName": "Anonymous"}

    error = await _failure(Confluence({"/rest/api/user/current": anonymous}))

    assert error.diagnostic.code is DiagnosticCode.AUTH_INVALID


async def test_the_probe_reads_a_space_in_scope() -> None:
    confluence = Confluence()

    result = await _connector(confluence, spaces=["OPS"]).test_connection()

    assert result.metadata["spaces_visible"] == 1
    assert confluence.asked("/api/v2/spaces/98305/pages") != []
    assert confluence.asked("/api/v2/spaces/98304/pages") == []


async def test_a_space_in_scope_that_confluence_does_not_show_fails_the_test() -> None:
    error = await _failure(Confluence(), spaces=["ENG", "SEC"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == "Confluence ne montre pas ces espaces à ce compte : SEC."


async def test_a_site_without_confluence_is_named_as_such() -> None:
    error = await _failure(Confluence({"/rest/api/user/current": httpx.Response(404)}))

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == (
        "Confluence ne trouve pas ce site Atlassian, ou ce compte ne le voit pas."
    )


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(401, text="Unauthorized"), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(403, json={"message": "scope does not match"}), "INSUFFICIENT_SCOPE"),
        (httpx.Response(403, json={}), DiagnosticCode.PERMISSION_DENIED),
        (httpx.Response(302, headers={"location": "https://x.example"}), "NOT_FOUND"),
        (httpx.Response(503, text="maintenance"), DiagnosticCode.PROVIDER_ERROR),
    ],
)
async def test_each_refusal_has_its_diagnostic(response: httpx.Response, code: str) -> None:
    error = await _failure(Confluence({"/rest/api/user/current": response}))

    assert error.diagnostic.code == code


async def test_an_exhausted_quota_says_when_to_come_back() -> None:
    busy = httpx.Response(429, headers={"retry-after": "42"})

    error = await _failure(Confluence({"/rest/api/user/current": busy}))

    assert error.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert error.diagnostic.retry_after == 42


async def test_a_confluence_that_does_not_answer() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    error = await _failure(Confluence({"/rest/api/user/current": slow}))

    assert error.diagnostic.code is DiagnosticCode.TIMEOUT


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    echo = httpx.Response(500, text=f"Internal error for token {TOKEN}")

    error = await _failure(Confluence({"/rest/api/user/current": echo}))

    assert TOKEN not in (error.diagnostic.detail or "")


# ── health ───────────────────────────────────────────────────────────────────


async def test_health_reads_the_quota_atlassian_announces() -> None:
    near = httpx.Response(
        200, json={"results": [], "_links": {}}, headers={"x-ratelimit-nearlimit": "true"}
    )

    healthy = await _connector(Confluence()).check_health()
    degraded = await _connector(Confluence({"/api/v2/spaces": near})).check_health()

    assert healthy.status is HealthStatus.HEALTHY
    assert degraded.status is HealthStatus.DEGRADED


# ── the scope ────────────────────────────────────────────────────────────────


async def test_the_scope_is_chosen_from_every_visible_space() -> None:
    confluence = Confluence()

    listing = await _connector(confluence, spaces=["OPS"]).list_scope()

    assert [(o.key, o.name, o.description) for o in listing.options] == [
        ("ENG", "Engineering", "How we build"),
        ("OPS", "Operations", None),
    ]
    assert listing.truncated is False
    assert confluence.asked("/api/v2/spaces")[0]["description-format"] == "plain"


async def test_a_listing_too_long_to_offer_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(confluence_module, "MAX_SCOPE_OPTIONS", 1)

    listing = await _connector(Confluence()).list_scope()

    assert [o.key for o in listing.options] == ["ENG"]
    assert listing.truncated is True


def test_confluence_says_what_it_lists_whole_so_a_pass_sweeps_it() -> None:
    """Spaces come whole every pass, so what a pass did not see is gone;
    pages stop at the last pass, so those wait for the weekly full pass."""
    manifest = next(m for m in manifests() if m.key == "confluence")

    assert manifest.listed_whole == {Capability.SPACES}
