"""The GitLab connector against a GitLab that is not there (LEKA-345).

httpx.MockTransport stands in for gitlab.com: no network, and every answer
GitLab can give is given on purpose. Paths are matched as sent — encoded —
because GitLab takes "acme/api" as "acme%2Fapi" in a URL.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from leka.connectors import Capability, ConnectorError, DiagnosticCode, HealthStatus
from leka.connectors.gitlab import GitLabConfig, GitLabConnector, GitLabCredentials
from leka.connectors.gitlab import connector as gitlab_module

TOKEN = "glpat-Abcdefghij0123456789_secretpart"
V4 = "/api/v4"

API = {
    "id": 11,
    "path_with_namespace": "acme/api",
    "description": "The API",
    "visibility": "private",
    "last_activity_at": "2026-09-25T09:00:00.000Z",
}
WEB = {"id": 12, "path_with_namespace": "acme/web", "visibility": "public"}


class GitLab:
    """A healthy GitLab, unless a path is overridden. Records what was asked."""

    def __init__(self, overrides: dict[str, object] | None = None) -> None:
        self.answers: dict[str, object] = {
            "/user": {"username": "nora"},
            "/personal_access_tokens/self": {"scopes": ["read_api"], "expires_at": "2026-12-31"},
            "/groups/acme": {"full_path": "acme"},
            "/groups/acme/projects": [API, WEB],
            "/projects/acme%2Fweb": WEB,
            **(overrides or {}),
        }
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads"
        assert request.headers["private-token"] == TOKEN
        path = request.url.raw_path.decode().split("?")[0].removeprefix(V4)
        self.paths.append(path)
        answer = self.answers.get(path)
        if isinstance(answer, httpx.Response):
            return answer
        if isinstance(answer, tuple):  # pages
            page = int(request.url.params.get("page", "1"))
            headers = {}
            if page < len(answer):
                headers["link"] = f'<{request.url.copy_set_param("page", page + 1)}>; rel="next"'
            return httpx.Response(200, json=answer[page - 1], headers=headers)
        if answer is not None:
            return httpx.Response(200, json=answer)
        if path.startswith("/projects/") and path.count("/") > 2:  # a project's listing
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "404 Not Found"})


def _connector(gitlab: GitLab, **config: object) -> GitLabConnector:
    return GitLabConnector(
        GitLabConfig.model_validate({"group": "acme", **config}),
        GitLabCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(gitlab),
    )


async def _failure(gitlab: GitLab) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        await _connector(gitlab).test_connection()
    assert TOKEN not in repr(caught.value.diagnostic)
    return caught.value


async def test_a_working_token_reports_the_account_and_what_it_can_read() -> None:
    gitlab = GitLab()

    result = await _connector(gitlab).test_connection()

    assert result.account == "nora"
    assert result.metadata["group"] == "acme"
    assert result.metadata["projects_visible"] == 2
    assert result.metadata["token_expires_at"] == "2026-12-31"
    assert set(result.capabilities) == set(Capability)
    assert result.warnings == []
    # The first visible project is the sample, by id.
    assert "/projects/11/merge_requests" in gitlab.paths


async def test_capabilities_are_discovered_not_assumed() -> None:
    forbidden = httpx.Response(403, json={"message": "403 Forbidden"})
    result = await _connector(GitLab({"/projects/11/issues": forbidden})).test_connection()

    assert Capability.ISSUES not in result.capabilities
    assert Capability.PULL_REQUESTS in result.capabilities


async def test_a_token_that_can_write_is_accepted_with_a_warning() -> None:
    token = {"scopes": ["api", "read_user"]}
    result = await _connector(GitLab({"/personal_access_tokens/self": token})).test_connection()

    assert len(result.warnings) == 1
    assert "api" in result.warnings[0]


async def test_a_gitlab_that_says_nothing_about_its_token_is_not_a_failure() -> None:
    silent = httpx.Response(404, json={"message": "404 Not Found"})
    result = await _connector(GitLab({"/personal_access_tokens/self": silent})).test_connection()

    assert result.warnings == []
    assert "token_expires_at" not in result.metadata


async def test_without_a_group_it_reads_the_owner_s_projects() -> None:
    gitlab = GitLab({"/projects": [API]})
    connector = GitLabConnector(
        GitLabConfig(),
        GitLabCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(gitlab),
    )

    result = await connector.test_connection()

    assert result.metadata["projects_visible"] == 1
    assert "/groups/acme" not in gitlab.paths


async def test_a_nested_group_is_sent_encoded() -> None:
    gitlab = GitLab({"/groups/acme%2Fplatform": {"full_path": "acme/platform"}})

    with pytest.raises(ConnectorError):  # its projects are not in this GitLab
        await _connector(gitlab, group="acme/platform").test_connection()

    assert "/groups/acme%2Fplatform" in gitlab.paths


@pytest.mark.parametrize(
    ("overrides", "code", "retryable"),
    [
        (
            {"/user": httpx.Response(401, json={"message": "401 Unauthorized"})},
            "AUTH_INVALID",
            False,
        ),
        (
            {"/user": httpx.Response(401, json={"error_description": "Token is expired."})},
            "AUTH_EXPIRED",
            False,
        ),
        (
            {"/user": httpx.Response(403, json={"message": "403 Forbidden"})},
            "PERMISSION_DENIED",
            False,
        ),
        (
            {"/user": httpx.Response(403, json={"error": "insufficient_scope"})},
            "INSUFFICIENT_SCOPE",
            False,
        ),
        (
            {"/groups/acme": httpx.Response(404, json={"message": "404 Group Not Found"})},
            "NOT_FOUND",
            False,
        ),
        ({"/user": httpx.Response(502, text="Bad Gateway")}, "PROVIDER_ERROR", True),
    ],
)
async def test_each_refusal_has_its_diagnostic(
    overrides: dict[str, object], code: str, retryable: bool
) -> None:
    error = await _failure(GitLab(overrides))

    assert error.diagnostic.code == DiagnosticCode(code)
    assert error.diagnostic.retryable is retryable
    assert error.diagnostic.remediation


async def test_an_exhausted_quota_says_when_to_come_back() -> None:
    limited = httpx.Response(429, text="Retry later", headers={"retry-after": "60"})
    error = await _failure(GitLab({"/user": limited}))

    assert error.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert error.diagnostic.retry_after == 60


async def test_a_gitlab_that_does_not_answer_or_cannot_be_reached() -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    for handler, code in (
        (hang, DiagnosticCode.TIMEOUT),
        (refuse, DiagnosticCode.NETWORK_UNREACHABLE),
    ):
        with pytest.raises(ConnectorError) as caught:
            await GitLabConnector(
                GitLabConfig(),
                GitLabCredentials(token=SecretStr(TOKEN)),
                transport=httpx.MockTransport(handler),
            ).test_connection()
        assert caught.value.diagnostic.code is code


async def test_an_echoed_token_is_removed_from_the_detail() -> None:
    other = "glpat-SomeoneElse0123456789"
    echo = httpx.Response(401, text=f"token {TOKEN} refused; also {other}")
    error = await _failure(GitLab({"/user": echo}))

    assert error.diagnostic.detail is not None
    assert TOKEN not in error.diagnostic.detail
    assert other not in error.diagnostic.detail


async def test_health_reads_the_quota_gitlab_sends() -> None:
    plenty = {"ratelimit-limit": "2000", "ratelimit-remaining": "1900"}
    low = {"ratelimit-limit": "2000", "ratelimit-remaining": "10"}
    for headers, status in ((plenty, HealthStatus.HEALTHY), (low, HealthStatus.DEGRADED)):
        answer = httpx.Response(200, json={"username": "nora"}, headers=headers)
        assert (await _connector(GitLab({"/user": answer})).check_health()).status is status

    assert (await _connector(GitLab()).check_health()).status is HealthStatus.HEALTHY


def test_the_token_never_shows_in_a_repr() -> None:
    credentials = GitLabCredentials(token=SecretStr(TOKEN))

    assert TOKEN not in repr(credentials)
    assert TOKEN not in str(credentials.model_dump())


# ── scope ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [
        {"group": "acme", "projects": ["api"]},
        {"group": "acme", "projects": ["globex/api"]},
        {"group": "acme", "projects": []},
        {"group": "acme/../x"},
    ],
    ids=["not-a-full-path", "another-group", "empty", "not-a-group-path"],
)
def test_a_scope_that_cannot_be_read_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GitLabConfig.model_validate(config)


def test_a_project_in_a_subgroup_is_in_the_group() -> None:
    config = GitLabConfig(group="acme", projects=["acme/platform/api"])

    assert config.projects == ["acme/platform/api"]


async def test_the_connection_test_probes_a_project_in_scope() -> None:
    gitlab = GitLab()

    await _connector(gitlab, projects=["acme/web"]).test_connection()

    assert "/projects/acme%2Fweb" in gitlab.paths
    assert "/projects/12/repository/commits" in gitlab.paths
    assert "/projects/11/repository/commits" not in gitlab.paths


async def test_a_project_in_scope_that_gitlab_does_not_show_fails_the_test() -> None:
    with pytest.raises(ConnectorError) as caught:
        await _connector(GitLab(), projects=["acme/gone"]).test_connection()

    assert caught.value.diagnostic.code is DiagnosticCode.NOT_FOUND
    assert "projet" in caught.value.diagnostic.message


async def test_the_scope_is_chosen_from_every_visible_project() -> None:
    gitlab = GitLab({"/groups/acme/projects": ([API], [WEB])})

    listing = await _connector(gitlab, projects=["acme/web"]).list_scope()

    assert [option.key for option in listing.options] == ["acme/api", "acme/web"]
    api, web = listing.options
    assert (api.description, api.private, web.private) == ("The API", True, False)
    assert api.updated_at is not None and web.updated_at is None
    assert listing.truncated is False


async def test_a_listing_too_long_to_offer_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitlab_module, "MAX_SCOPE_OPTIONS", 1)

    listing = await _connector(GitLab()).list_scope()

    assert [option.key for option in listing.options] == ["acme/api"]
    assert listing.truncated is True


async def test_a_page_link_to_another_host_is_not_followed_with_the_token() -> None:
    link = '<https://evil.example/api/v4/groups/acme/projects?page=2>; rel="next"'
    elsewhere = httpx.Response(200, json=[API], headers={"link": link})
    gitlab = GitLab({"/groups/acme/projects": elsewhere})

    with pytest.raises(ConnectorError) as caught:
        await _connector(gitlab).list_scope()

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
