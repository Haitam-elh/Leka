"""The GitHub connector against a GitHub that is not there (LEKA-344).

httpx.MockTransport stands in for api.github.com: no network, and every
answer GitHub can give is given on purpose. Each failure must come back as
the diagnostic its code promises, with nothing secret in it.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from leka.connectors import Capability, ConnectorError, DiagnosticCode, HealthStatus
from leka.connectors.github import GitHubConfig, GitHubConnector, GitHubCredentials

TOKEN = "github_pat_11ABCDEFG0123456789_secretpartthatmustneverleak"

Handler = Callable[[httpx.Request], httpx.Response]


def _connector(handler: Handler, organization: str | None = "acme") -> GitHubConnector:
    return GitHubConnector(
        GitHubConfig(organization=organization),
        GitHubCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(handler),
    )


def github(overrides: dict[str, httpx.Response] | None = None) -> Handler:
    """A healthy GitHub, unless a path is overridden."""
    answers = {
        "/user": httpx.Response(200, json={"login": "nora"}),
        "/orgs/acme": httpx.Response(200, json={"login": "acme"}),
        "/orgs/acme/repos": httpx.Response(200, json=[{"full_name": "acme/api"}]),
        "/repos/acme/api": httpx.Response(200, json={"full_name": "acme/api"}),
        "/rate_limit": httpx.Response(
            200, json={"resources": {"core": {"limit": 5000, "remaining": 4900}}}
        ),
    }
    answers.update(overrides or {})

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if request.url.path in answers:
            return answers[request.url.path]
        if request.url.path.startswith("/repos/acme/api/"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "Not Found"})

    return handle


async def _failure(handler: Handler) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(handler).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


async def test_a_working_token_reports_the_account_and_what_it_can_read() -> None:
    result = await _connector(github()).test_connection()

    assert result.account == "nora"
    assert result.metadata["organization"] == "acme"
    assert result.metadata["repositories_visible"] == 1
    assert set(result.capabilities) == set(Capability)
    assert result.warnings == []


async def test_capabilities_are_discovered_not_assumed() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/api/issues":
            return httpx.Response(403, json={"message": "Resource not accessible"})
        return github()(request)

    result = await _connector(handle).test_connection()

    assert Capability.ISSUES not in result.capabilities
    assert Capability.COMMITS in result.capabilities


async def test_a_token_that_can_write_is_accepted_with_a_warning() -> None:
    user = httpx.Response(200, json={"login": "nora"}, headers={"x-oauth-scopes": "repo, read:org"})
    result = await _connector(github({"/user": user})).test_connection()

    assert len(result.warnings) == 1
    assert "repo" in result.warnings[0]


@pytest.mark.parametrize(
    ("overrides", "code", "retryable"),
    [
        (
            {"/user": httpx.Response(401, json={"message": "Bad credentials"})},
            "AUTH_INVALID",
            False,
        ),
        ({"/user": httpx.Response(403, json={"message": "Forbidden"})}, "PERMISSION_DENIED", False),
        (
            {
                "/orgs/acme/repos": httpx.Response(
                    403, json={"message": "Resource not accessible by personal access token"}
                )
            },
            "INSUFFICIENT_SCOPE",
            False,
        ),
        ({"/orgs/acme": httpx.Response(404, json={"message": "Not Found"})}, "NOT_FOUND", False),
        ({"/user": httpx.Response(502, text="Bad Gateway")}, "PROVIDER_ERROR", True),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    overrides: dict[str, httpx.Response], code: str, retryable: bool
) -> None:
    error = await _failure(github(overrides))

    assert error.diagnostic.code == DiagnosticCode(code)
    assert error.diagnostic.retryable is retryable
    assert error.diagnostic.remediation


async def test_an_exhausted_quota_says_when_to_come_back() -> None:
    reset = int(time.time()) + 120
    limited = httpx.Response(
        403,
        json={"message": "API rate limit exceeded"},
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)},
    )
    error = await _failure(github({"/user": limited}))

    assert error.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert error.diagnostic.retryable is True
    assert error.diagnostic.retry_after is not None
    assert 100 <= error.diagnostic.retry_after <= 120
    assert error.diagnostic.provider_status == 403


async def test_a_github_that_does_not_answer_is_a_timeout() -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    error = await _failure(hang)
    assert error.diagnostic.code is DiagnosticCode.TIMEOUT


async def test_a_github_that_cannot_be_reached_is_said_so() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    error = await _failure(refuse)
    assert error.diagnostic.code is DiagnosticCode.NETWORK_UNREACHABLE


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    echo = httpx.Response(401, text=f"token {TOKEN} is not valid; Authorization: Bearer {TOKEN}")
    error = await _failure(github({"/user": echo}))

    assert error.diagnostic.detail is not None
    assert TOKEN not in error.diagnostic.detail
    assert "Bearer" not in error.diagnostic.detail


async def test_health_reads_the_quota_without_spending_it() -> None:
    assert (await _connector(github()).check_health()).status is HealthStatus.HEALTHY

    low = httpx.Response(200, json={"resources": {"core": {"limit": 5000, "remaining": 12}}})
    assert (await _connector(github({"/rate_limit": low})).check_health()).status is (
        HealthStatus.DEGRADED
    )


def test_the_token_never_shows_in_a_repr() -> None:
    credentials = GitHubCredentials(token=SecretStr(TOKEN))

    assert TOKEN not in repr(credentials)
    assert TOKEN not in str(credentials.model_dump())
