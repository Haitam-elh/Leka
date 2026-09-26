"""What the GitHub connector streams to the sync engine (LEKA-345).

The same GitHub that is not there as test_github_connector.py: a
MockTransport answers every listing, pages included, and records which
requests were made — so a test can say what was fetched, and what was not.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from leka.connectors.github import GitHubConfig, GitHubConnector, GitHubCredentials

TOKEN = "github_pat_11ABCDEFG0123456789_secretpartthatmustneverleak"
SINCE = datetime(2026, 9, 20, tzinfo=UTC)

API = {"node_id": "R_api", "full_name": "acme/api", "updated_at": "2026-09-25T10:00:00Z"}
WEB = {"node_id": "R_web", "full_name": "acme/web", "updated_at": "2026-09-24T10:00:00Z"}

Handler = Callable[[httpx.Request], httpx.Response]


class GitHub:
    """Paths to answers; a list of answers is served as successive pages."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = {"/orgs/acme/repos": [API, WEB], **answers}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads"
        self.requests.append(request)
        answer = self.answers.get(request.url.path, [])
        if isinstance(answer, httpx.Response):
            return answer
        if isinstance(answer, tuple):  # pages
            page = int(request.url.params.get("page", "1"))
            headers = {}
            if page < len(answer):
                headers["link"] = f'<{request.url.copy_set_param("page", page + 1)}>; rel="next"'
            return httpx.Response(200, json=answer[page - 1], headers=headers)
        return httpx.Response(200, json=answer)

    def params(self, path: str) -> list[httpx.QueryParams]:
        return [r.url.params for r in self.requests if r.url.path == path]


async def _stream(
    github: Handler, capability: Capability, since: datetime | None = None
) -> list[RawRecord]:
    connector = GitHubConnector(
        GitHubConfig(organization="acme"),
        GitHubCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(github),
    )
    return [record async for record in connector.iter_resources(capability, since=since)]


async def test_repositories_are_read_across_every_page() -> None:
    other = {"node_id": "R_ops", "full_name": "acme/ops", "updated_at": None}
    github = GitHub({"/orgs/acme/repos": ([API, WEB], [other])})

    records = await _stream(github, Capability.REPOSITORIES)

    assert [r.external_id for r in records] == ["R_api", "R_web", "R_ops"]
    assert records[0].container is None
    assert records[0].payload == API
    assert records[0].updated_at == datetime(2026, 9, 25, 10, tzinfo=UTC)
    assert records[2].updated_at is None
    assert github.params("/orgs/acme/repos")[0]["per_page"] == "100"


async def test_the_token_owner_s_repositories_without_an_organisation() -> None:
    github = GitHub({"/user/repos": [API]})
    connector = GitHubConnector(
        GitHubConfig(),
        GitHubCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(github),
    )

    records = [r async for r in connector.iter_resources(Capability.REPOSITORIES)]

    assert [r.external_id for r in records] == ["R_api"]


async def test_commits_are_read_in_every_repository_since_the_last_pass() -> None:
    commit = {"node_id": "C_1", "commit": {"committer": {"date": "2026-09-22T08:00:00Z"}}}
    github = GitHub({"/repos/acme/api/commits": [commit]})

    records = await _stream(github, Capability.COMMITS, since=SINCE)

    assert [(r.external_id, r.container) for r in records] == [("C_1", "acme/api")]
    assert records[0].updated_at == datetime(2026, 9, 22, 8, tzinfo=UTC)
    assert github.params("/repos/acme/api/commits")[0]["since"] == SINCE.isoformat()
    assert github.params("/repos/acme/web/commits")[0]["since"] == SINCE.isoformat()


async def test_an_initial_pass_asks_for_everything() -> None:
    github = GitHub({})

    await _stream(github, Capability.COMMITS)

    assert "since" not in github.params("/repos/acme/api/commits")[0]


async def test_an_empty_repository_has_no_commits_and_is_not_an_error() -> None:
    empty = httpx.Response(409, json={"message": "Git Repository is empty."})
    commit = {"node_id": "C_1", "commit": {"committer": {"date": "2026-09-22T08:00:00Z"}}}
    github = GitHub({"/repos/acme/api/commits": empty, "/repos/acme/web/commits": [commit]})

    records = await _stream(github, Capability.COMMITS)

    assert [r.external_id for r in records] == ["C_1"]


async def test_pull_requests_stop_at_the_first_one_older_than_the_last_pass() -> None:
    recent = {"node_id": "PR_2", "updated_at": "2026-09-25T00:00:00Z"}
    old = {"node_id": "PR_1", "updated_at": "2026-09-10T00:00:00Z"}
    github = GitHub({"/repos/acme/api/pulls": ([recent, old], [old])})

    records = await _stream(github, Capability.PULL_REQUESTS, since=SINCE)

    assert [r.external_id for r in records] == ["PR_2"]
    # The second page is never asked for.
    assert len(github.params("/repos/acme/api/pulls")) == 1
    query = github.params("/repos/acme/api/pulls")[0]
    assert (query["state"], query["sort"], query["direction"]) == ("all", "updated", "desc")


async def test_issues_leave_pull_requests_to_their_own_capability() -> None:
    issue = {"node_id": "I_1", "updated_at": "2026-09-21T00:00:00Z"}
    pull = {"node_id": "PR_1", "updated_at": "2026-09-21T00:00:00Z", "pull_request": {}}
    github = GitHub({"/repos/acme/api/issues": [issue, pull]})

    records = await _stream(github, Capability.ISSUES, since=SINCE)

    assert [r.external_id for r in records] == ["I_1"]
    query = github.params("/repos/acme/api/issues")[0]
    assert (query["state"], query["since"]) == ("all", SINCE.isoformat())


async def test_a_branch_is_known_by_its_repository_and_its_name() -> None:
    github = GitHub({"/repos/acme/api/branches": [{"name": "main", "commit": {"sha": "abc"}}]})

    records = await _stream(github, Capability.BRANCHES)

    assert [(r.external_id, r.container) for r in records] == [("R_api:main", "acme/api")]
    assert records[0].updated_at is None


async def test_a_draft_release_is_dated_by_its_creation() -> None:
    published = {"node_id": "RE_1", "published_at": "2026-09-21T00:00:00Z", "created_at": "x"}
    draft = {"node_id": "RE_2", "published_at": None, "created_at": "2026-09-23T00:00:00Z"}
    github = GitHub({"/repos/acme/api/releases": [published, draft]})

    records = await _stream(github, Capability.RELEASES)

    assert [r.updated_at for r in records] == [
        datetime(2026, 9, 21, tzinfo=UTC),
        datetime(2026, 9, 23, tzinfo=UTC),
    ]


async def test_a_page_link_to_another_host_is_not_followed_with_the_token() -> None:
    link = '<https://evil.example/orgs/acme/repos?page=2>; rel="next"'
    elsewhere = httpx.Response(200, json=[API], headers={"link": link})
    github = GitHub({"/orgs/acme/repos": elsewhere})

    with pytest.raises(ConnectorError) as caught:
        await _stream(github, Capability.REPOSITORIES)

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert all(r.url.host == "api.github.com" for r in github.requests)


async def test_an_exhausted_quota_mid_stream_keeps_what_was_read() -> None:
    limited = httpx.Response(
        403, json={"message": "API rate limit exceeded"}, headers={"x-ratelimit-remaining": "0"}
    )
    commit = {"node_id": "C_1", "commit": {"committer": {"date": "2026-09-22T08:00:00Z"}}}
    github = GitHub({"/repos/acme/api/commits": [commit], "/repos/acme/web/commits": limited})
    connector = GitHubConnector(
        GitHubConfig(organization="acme"),
        GitHubCredentials(token=SecretStr(TOKEN)),
        transport=httpx.MockTransport(github),
    )
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for record in connector.iter_resources(Capability.COMMITS):
            read.append(record)

    assert [r.external_id for r in read] == ["C_1"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert TOKEN not in repr(caught.value.diagnostic)
