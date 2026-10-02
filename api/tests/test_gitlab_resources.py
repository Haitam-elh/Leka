"""What the GitLab connector streams to the sync engine (LEKA-345).

The GitLab of test_gitlab_connector.py, which records every path and query
it is asked for — so a test can say what was fetched, and what was not.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from tests.test_gitlab_connector import API, WEB, GitLab, _connector

SINCE = datetime(2026, 9, 20, tzinfo=UTC)


class Recording(GitLab):
    def __init__(self, overrides: dict[str, object] | None = None) -> None:
        super().__init__(overrides)
        self.queries: dict[str, list[httpx.QueryParams]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode().split("?")[0].removeprefix("/api/v4")
        self.queries.setdefault(path, []).append(request.url.params)
        return super().__call__(request)


async def _stream(
    gitlab: GitLab, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(gitlab, **config)
    return [record async for record in connector.iter_resources(capability, since=since)]


async def test_projects_are_read_across_every_page_with_their_subgroups() -> None:
    other = {"id": 13, "path_with_namespace": "acme/platform/ops"}
    gitlab = Recording({"/groups/acme/projects": ([API, WEB], [other])})

    records = await _stream(gitlab, Capability.REPOSITORIES)

    assert [r.external_id for r in records] == ["11", "12", "13"]
    assert records[0].updated_at == datetime(2026, 9, 25, 9, tzinfo=UTC)
    assert records[1].updated_at is None
    query = gitlab.queries["/groups/acme/projects"][0]
    assert (query["include_subgroups"], query["per_page"]) == ("true", "100")


async def test_only_the_projects_in_scope_are_read() -> None:
    gitlab = Recording()

    projects = await _stream(gitlab, Capability.REPOSITORIES, projects=["Acme/Web"])
    await _stream(gitlab, Capability.ISSUES, projects=["acme/web"])

    assert [r.external_id for r in projects] == ["12"]
    assert "/projects/12/issues" in gitlab.queries
    assert "/projects/11/issues" not in gitlab.queries


async def test_commits_are_read_since_the_last_pass() -> None:
    commit = {"id": "abc123", "committed_date": "2026-09-22T08:00:00.000+00:00"}
    gitlab = Recording({"/projects/11/repository/commits": [commit]})

    records = await _stream(gitlab, Capability.COMMITS, since=SINCE)

    assert [(r.external_id, r.container) for r in records] == [("11:abc123", "acme/api")]
    assert records[0].updated_at == datetime(2026, 9, 22, 8, tzinfo=UTC)
    assert gitlab.queries["/projects/11/repository/commits"][0]["since"] == SINCE.isoformat()


async def test_an_initial_pass_asks_for_everything() -> None:
    gitlab = Recording()

    await _stream(gitlab, Capability.PULL_REQUESTS)

    assert "updated_after" not in gitlab.queries["/projects/11/merge_requests"][0]


@pytest.mark.parametrize(
    ("capability", "endpoint"),
    [(Capability.PULL_REQUESTS, "merge_requests"), (Capability.ISSUES, "issues")],
)
async def test_merge_requests_and_issues_are_those_updated_since_the_last_pass(
    capability: Capability, endpoint: str
) -> None:
    item = {"id": 901, "iid": 4, "updated_at": "2026-09-23T00:00:00Z"}
    gitlab = Recording({f"/projects/11/{endpoint}": [item]})

    records = await _stream(gitlab, capability, since=SINCE)

    assert [(r.external_id, r.kind) for r in records] == [("901", capability)]
    query = gitlab.queries[f"/projects/11/{endpoint}"][0]
    assert query["updated_after"] == SINCE.isoformat()
    assert "state" not in query  # every state: open, merged, closed


async def test_branches_and_releases_are_known_by_their_project_and_name() -> None:
    release = {"tag_name": "v1.2", "released_at": None, "created_at": "2026-09-21T00:00:00Z"}
    gitlab = Recording(
        {
            "/projects/11/repository/branches": [{"name": "main"}],
            "/projects/11/releases": [release],
        }
    )

    branches = await _stream(gitlab, Capability.BRANCHES)
    releases = await _stream(gitlab, Capability.RELEASES)

    assert [r.external_id for r in branches] == ["11:main"]
    assert [(r.external_id, r.updated_at) for r in releases] == [
        ("11:v1.2", datetime(2026, 9, 21, tzinfo=UTC))
    ]


async def test_a_switched_off_feature_or_an_empty_repository_is_not_asked_for() -> None:
    no_issues = {**API, "issues_access_level": "disabled"}
    empty = {**WEB, "empty_repo": True}
    gitlab = Recording({"/groups/acme/projects": [no_issues, empty]})

    await _stream(gitlab, Capability.ISSUES)
    await _stream(gitlab, Capability.COMMITS)

    assert "/projects/11/issues" not in gitlab.queries
    assert "/projects/12/issues" in gitlab.queries
    assert "/projects/11/repository/commits" in gitlab.queries
    assert "/projects/12/repository/commits" not in gitlab.queries


async def test_an_exhausted_quota_mid_stream_keeps_what_was_read() -> None:
    limited = httpx.Response(429, text="Retry later", headers={"retry-after": "30"})
    gitlab = Recording(
        {
            "/projects/11/issues": [{"id": 901, "updated_at": "2026-09-23T00:00:00Z"}],
            "/projects/12/issues": limited,
        }
    )
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for record in _connector(gitlab).iter_resources(Capability.ISSUES):
            read.append(record)

    assert [r.external_id for r in read] == ["901"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 30


# ── deployments (LEKA-367) ───────────────────────────────────────────────────


async def test_deployments_are_those_updated_since_the_last_pass() -> None:
    deployment = {"id": 77, "iid": 3, "ref": "main", "sha": "b" * 40, "status": "success"}
    gitlab = Recording({"/projects/11/deployments": [deployment]})

    records = await _stream(gitlab, Capability.DEPLOYMENTS, since=SINCE, projects=["acme/api"])

    assert [(r.external_id, r.container) for r in records] == [("77", "acme/api")]
    [query] = gitlab.queries["/projects/11/deployments"]
    assert (query["order_by"], query["updated_after"]) == ("updated_at", SINCE.isoformat())


async def test_a_project_without_environments_has_no_deployments_asked_for() -> None:
    off = {**API, "environments_access_level": "disabled"}
    gitlab = Recording({"/groups/acme/projects": [off, WEB]})

    assert await _stream(gitlab, Capability.DEPLOYMENTS, projects=["acme/api"]) == []
    assert "/projects/11/deployments" not in gitlab.queries
