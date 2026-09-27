"""The Linear connector against a Linear that is not there (LEKA-346).

httpx.MockTransport stands in for api.linear.app. Linear speaks GraphQL
through POST only, so the stand-in checks the other half of "LEKA reads":
every request is a POST to /graphql, carrying a `query` — never a
mutation — with the key configured.
"""

from __future__ import annotations

import json
import re
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
from leka.connectors.linear import LinearConfig, LinearConnector, LinearCredentials
from leka.connectors.linear import connector as linear_module
from leka.connectors.linear.connector import DOCUMENTS, read_only

KEY = "lin_api_Abcdefghijklmnop0123456789abcdefghijKLMN"
EMAIL = "nora@acme.test"

ENG = {
    "id": "team-eng",
    "key": "ENG",
    "name": "Engineering",
    "description": "Builds the product",
    "private": False,
    "updatedAt": "2026-09-25T09:00:00.000Z",
}
OPS = {"id": "team-ops", "key": "OPS", "name": "Operations", "private": True}


def connection(nodes: list[Any], end: str | None = None) -> dict[str, Any]:
    return {"nodes": nodes, "pageInfo": {"hasNextPage": end is not None, "endCursor": end}}


def _teams(variables: dict[str, Any]) -> httpx.Response:
    wanted = (variables.get("filter") or {}).get("key", {}).get("in")
    nodes = [team for team in (ENG, OPS) if not wanted or team["key"] in wanted]
    return httpx.Response(200, json={"data": {"teams": connection(nodes)}})


Answer = object | Callable[[dict[str, Any]], httpx.Response]


class Linear:
    """A healthy Linear, unless an operation is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, Answer] | None = None) -> None:
        self.answers: dict[str, Answer] = {
            "Viewer": {
                "data": {
                    "viewer": {
                        "id": "user-1",
                        "name": "Nora",
                        "email": EMAIL,
                        "admin": False,
                        "organization": {"id": "org-1", "name": "Acme", "urlKey": "acme"},
                    }
                }
            },
            "Health": {"data": {"viewer": {"id": "user-1"}}},
            "Teams": _teams,
            "TeamProjects": {"data": {"team": {"projects": connection([])}}},
            "TeamIssues": {"data": {"team": {"issues": connection([])}}},
            **(overrides or {}),
        }
        self.asked: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.host, request.url.path) == (
            "POST",
            "api.linear.app",
            "/graphql",
        ), "LEKA reads Linear through its one GraphQL endpoint"
        assert request.headers["authorization"] == KEY
        body = json.loads(request.content)
        document: str = body["query"]
        assert document.startswith("query") and "mutation" not in document, "LEKA reads"
        found = re.match(r"query\s+(\w+)", document)
        assert found is not None
        operation, variables = found.group(1), body.get("variables") or {}
        self.asked.append((operation, variables))
        answer = self.answers[operation]
        if callable(answer):
            response: httpx.Response = answer(variables)
            return response
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def variables(self, operation: str) -> list[dict[str, Any]]:
        return [variables for name, variables in self.asked if name == operation]


def _connector(linear: Linear, **config: Any) -> LinearConnector:
    return LinearConnector(
        LinearConfig.model_validate(config),
        LinearCredentials(api_key=SecretStr(KEY)),
        transport=httpx.MockTransport(linear),
    )


async def _failure(linear: Linear, **config: Any) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(linear, **config).test_connection()
    assert KEY not in repr(caught.value.diagnostic)
    return caught.value


def refused(code: str, status: int = 400, headers: dict[str, str] | None = None) -> httpx.Response:
    body = {"errors": [{"message": code.lower(), "extensions": {"code": code}}]}
    return httpx.Response(status, json=body, headers=headers or {})


# ── LEKA only reads ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("document", DOCUMENTS)
def test_every_document_sent_to_linear_is_a_query(document: str) -> None:
    assert read_only(document).startswith("query")


@pytest.mark.parametrize(
    "document",
    [
        'mutation { issueDelete(id: "x") { success } }',
        "query A { viewer { id } }\nmutation B { issueArchive(id: 1) { success } }",
        "subscription S { issueUpdated { id } }",
        "{ viewer { id } }",
        "# query\nmutation M { x }",
    ],
)
def test_a_document_that_could_write_is_refused(document: str) -> None:
    with pytest.raises(ValueError, match="queries only"):
        read_only(document)


def test_linear_is_in_the_catalogue_as_a_project_tool_with_a_write_only_key() -> None:
    manifest = next(m for m in manifests() if m.key == "linear")
    key = manifest.credentials_schema.model_json_schema()["properties"]["api_key"]

    assert manifest.category is ConnectorCategory.PROJECT
    assert manifest.capabilities == {Capability.PROJECTS, Capability.ISSUES}
    assert manifest.read_only is True
    assert key["writeOnly"] is True


# ── the configuration ────────────────────────────────────────────────────────


def test_team_keys_are_kept_in_capitals_once() -> None:
    assert LinearConfig.model_validate({"teams": ["eng", " OPS", "ENG"]}).teams == ["ENG", "OPS"]


@pytest.mark.parametrize(
    "config",
    [{"teams": []}, {"teams": ["ENG-1"]}, {"teams": ['ENG"}']}, {"teams": [""]}, {"site": "x"}],
)
def test_a_configuration_that_is_not_team_keys_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LinearConfig.model_validate(config)


def test_the_key_never_shows_in_a_repr() -> None:
    credentials = LinearCredentials(api_key=SecretStr(KEY))

    assert KEY not in repr(credentials)
    assert KEY not in str(credentials.model_dump())


# ── the connection test ──────────────────────────────────────────────────────


async def test_a_working_key_reports_the_account_and_what_it_can_read() -> None:
    linear = Linear()

    result = await _connector(linear).test_connection()

    assert result.account == EMAIL
    assert result.metadata == {"workspace": "Acme", "url_key": "acme", "teams_visible": 2}
    assert set(result.capabilities) == LinearConnector.manifest.capabilities
    assert result.warnings == []
    # The first visible team is the sample, for both probes.
    assert linear.variables("TeamProjects")[0]["team"] == "team-eng"
    assert linear.variables("TeamIssues")[0]["team"] == "team-eng"


async def test_a_capability_linear_refuses_is_left_out_not_failed() -> None:
    forbidden = refused("FORBIDDEN")

    result = await _connector(Linear({"TeamIssues": forbidden})).test_connection()

    assert result.capabilities == [Capability.PROJECTS]


async def test_an_admin_s_key_is_accepted_with_a_warning() -> None:
    admin = {"data": {"viewer": {"id": "u", "email": EMAIL, "admin": True, "organization": {}}}}

    result = await _connector(Linear({"Viewer": admin})).test_connection()

    assert len(result.warnings) == 1
    assert "administrateur" in result.warnings[0]


async def test_a_key_that_sees_no_team_is_told_so() -> None:
    nobody = {"data": {"teams": connection([])}}

    result = await _connector(Linear({"Teams": nobody})).test_connection()

    assert result.capabilities == []
    assert result.warnings == ["Aucune équipe n'est visible avec cette clé."]


async def test_the_probes_read_a_team_in_scope() -> None:
    linear = Linear()

    result = await _connector(linear, teams=["ops"]).test_connection()

    assert result.metadata["teams_visible"] == 1
    assert linear.variables("Teams")[0]["filter"] == {"key": {"in": ["OPS"]}}
    assert linear.variables("TeamIssues")[0]["team"] == "team-ops"


async def test_a_team_in_scope_that_linear_does_not_show_fails_the_test() -> None:
    error = await _failure(Linear(), teams=["ENG", "SEC"])

    assert error.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert error.diagnostic.message == "Linear ne montre pas ces équipes à cette clé : SEC."


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (refused("AUTHENTICATION_ERROR"), DiagnosticCode.AUTH_INVALID),
        (httpx.Response(401, text="Unauthorized"), DiagnosticCode.AUTH_INVALID),
        (refused("FORBIDDEN", status=200), DiagnosticCode.PERMISSION_DENIED),
        (httpx.Response(403, json={}), DiagnosticCode.PERMISSION_DENIED),
        (refused("ENTITY_NOT_FOUND", status=200), DiagnosticCode.NOT_FOUND),
        (httpx.Response(502, text="bad gateway"), DiagnosticCode.PROVIDER_ERROR),
        (refused("SOMETHING_NEW", status=200), DiagnosticCode.UNKNOWN),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    response: httpx.Response, code: DiagnosticCode
) -> None:
    error = await _failure(Linear({"Viewer": response}))

    assert error.diagnostic.code is code


async def test_an_exhausted_quota_says_when_to_come_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("leka.connectors.linear.connector.time.time", lambda: 1_790_000_000)
    busy = refused("RATELIMITED", headers={"x-ratelimit-requests-reset": "1790000042000"})

    error = await _failure(Linear({"Viewer": busy}))

    assert error.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert error.diagnostic.retry_after == 42


async def test_a_linear_that_does_not_answer() -> None:
    def slow(variables: dict[str, Any]) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    error = await _failure(Linear({"Viewer": slow}))

    assert error.diagnostic.code is DiagnosticCode.TIMEOUT


async def test_an_echoed_key_is_removed_from_the_detail() -> None:
    echo = httpx.Response(500, text=f"Internal error for {KEY}")

    error = await _failure(Linear({"Viewer": echo}))

    assert KEY not in (error.diagnostic.detail or "")


# ── health ───────────────────────────────────────────────────────────────────


async def test_health_reads_the_requests_left_in_the_hour() -> None:
    headers = {"x-ratelimit-requests-limit": "1500", "x-ratelimit-requests-remaining": "100"}
    low = httpx.Response(200, json={"data": {"viewer": {"id": "u"}}}, headers=headers)

    healthy = await _connector(Linear()).check_health()
    degraded = await _connector(Linear({"Health": low})).check_health()

    assert healthy.status is HealthStatus.HEALTHY
    assert (degraded.status, degraded.detail) == (HealthStatus.DEGRADED, "quota 100/1500")


async def test_health_fails_like_a_test_when_the_key_is_revoked() -> None:
    with pytest.raises(ConnectorError) as caught:
        await _connector(Linear({"Health": refused("AUTHENTICATION_ERROR")})).check_health()

    assert caught.value.diagnostic.code is DiagnosticCode.AUTH_INVALID


# ── the scope ────────────────────────────────────────────────────────────────


async def test_the_scope_is_chosen_from_every_visible_team() -> None:
    linear = Linear()

    listing = await _connector(linear, teams=["OPS"]).list_scope()

    assert [(o.key, o.name, o.private) for o in listing.options] == [
        ("ENG", "Engineering", False),
        ("OPS", "Operations", True),
    ]
    assert listing.options[0].description == "Builds the product"
    assert listing.options[0].updated_at is not None
    assert linear.variables("Teams")[0]["filter"] is None


async def test_a_listing_too_long_to_offer_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(linear_module, "MAX_SCOPE_OPTIONS", 1)

    listing = await _connector(Linear()).list_scope()

    assert [o.key for o in listing.options] == ["ENG"]
    assert listing.truncated is True


def test_linear_says_what_it_lists_whole_so_a_pass_sweeps_it() -> None:
    """Projects come whole every pass, so what a pass did not see is gone;
    issues are filtered by `updatedAt`, so those wait for the weekly full pass."""
    manifest = next(m for m in manifests() if m.key == "linear")

    assert manifest.listed_whole == {Capability.PROJECTS}
