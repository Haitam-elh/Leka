"""The Bitbucket connector against a Bitbucket that is not there (LEKA-345).

httpx.MockTransport stands in for api.bitbucket.org: no network. Bitbucket
pages in the body ({"values": [...], "next": url}), which this fake does
too, and records what it was asked — so a test can say what was fetched.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from leka.connectors import Capability, ConnectorError, DiagnosticCode, HealthStatus, RawRecord
from leka.connectors.bitbucket import BitbucketConfig, BitbucketConnector, BitbucketCredentials

TOKEN = "ATCTT3xFfGN0Abcdefghij0123456789_secretpart"
SINCE = datetime(2026, 9, 20, tzinfo=UTC)

API = {
    "uuid": "{r-api}",
    "full_name": "acme/api",
    "description": "The API",
    "is_private": True,
    "updated_on": "2026-09-25T09:00:00.000000+00:00",
    "mainbranch": {"name": "main"},
    "has_issues": True,
}
WEB = {"uuid": "{r-web}", "full_name": "acme/web", "is_private": False, "mainbranch": None}


class Bitbucket:
    """A healthy Bitbucket, unless a path is overridden. A tuple is pages."""

    def __init__(self, overrides: dict[str, object] | None = None) -> None:
        self.answers: dict[str, object] = {
            "/workspaces/acme": {"slug": "acme"},
            "/user": {"username": "nora"},
            "/repositories/acme": [API, WEB],
            "/repositories/acme/api": API,
            **(overrides or {}),
        }
        self.queries: dict[str, list[httpx.QueryParams]] = {}
        self.authorization: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "LEKA reads"
        self.authorization = request.headers["authorization"]
        path = request.url.path.removeprefix("/2.0")
        self.queries.setdefault(path, []).append(request.url.params)
        answer = self.answers.get(path)
        if isinstance(answer, httpx.Response):
            return answer
        if isinstance(answer, tuple):
            page = int(request.url.params.get("page", "1"))
            body: dict[str, object] = {"values": answer[page - 1]}
            if page < len(answer):
                body["next"] = str(request.url.copy_set_param("page", page + 1))
            return httpx.Response(200, json=body)
        if isinstance(answer, list):
            return httpx.Response(200, json={"values": answer})
        if answer is not None:
            return httpx.Response(200, json=answer)
        if path.startswith("/repositories/acme/") and path.count("/") > 3:  # a listing
            return httpx.Response(200, json={"values": []})
        return httpx.Response(404, json={"type": "error", "error": {"message": "Not found"}})


def _connector(
    bitbucket: Bitbucket, config: dict[str, object] | None = None, email: str | None = None
) -> BitbucketConnector:
    return BitbucketConnector(
        BitbucketConfig.model_validate({"workspace": "acme", **(config or {})}),
        BitbucketCredentials(token=SecretStr(TOKEN), email=email),
        transport=httpx.MockTransport(bitbucket),
    )


async def _stream(
    bitbucket: Bitbucket, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(bitbucket, config)
    return [r async for r in connector.iter_resources(capability, since=since)]


# ── connection ───────────────────────────────────────────────────────────────


async def test_a_working_token_reports_the_workspace_and_what_it_can_read() -> None:
    bitbucket = Bitbucket()

    result = await _connector(bitbucket).test_connection()

    assert result.account == "nora"
    assert result.metadata["workspace"] == "acme"
    assert result.metadata["repositories_visible"] == 2
    assert set(result.capabilities) == set(BitbucketConnector.manifest.capabilities)
    assert Capability.RELEASES not in result.capabilities  # Bitbucket has none
    assert result.warnings == []
    assert bitbucket.authorization == f"Bearer {TOKEN}"


async def test_an_api_token_goes_with_its_email_and_an_access_token_needs_no_user() -> None:
    bitbucket = Bitbucket({"/user": httpx.Response(401, json={})})

    result = await _connector(bitbucket, email="nora@acme.example").test_connection()

    expected = base64.b64encode(f"nora@acme.example:{TOKEN}".encode()).decode()
    assert bitbucket.authorization == f"Basic {expected}"
    assert result.account == "acme"  # no user: the workspace names it


async def test_a_token_that_can_write_is_accepted_with_a_warning() -> None:
    scoped = httpx.Response(
        200, json={"slug": "acme"}, headers={"x-oauth-scopes": "repository, pullrequest:write"}
    )
    result = await _connector(Bitbucket({"/workspaces/acme": scoped})).test_connection()

    assert len(result.warnings) == 1
    assert "pullrequest:write" in result.warnings[0]


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (httpx.Response(401, json={}), "AUTH_INVALID"),
        (
            httpx.Response(
                403, text="Your credentials lack one or more required privilege scopes."
            ),
            "INSUFFICIENT_SCOPE",
        ),
        (httpx.Response(403, json={"error": {"message": "Forbidden"}}), "PERMISSION_DENIED"),
        (httpx.Response(404, json={}), "NOT_FOUND"),
        (httpx.Response(429, text="Rate limit", headers={"retry-after": "20"}), "RATE_LIMITED"),
        (httpx.Response(500, text="Oops"), "PROVIDER_ERROR"),
    ],
)
async def test_each_refusal_has_its_diagnostic(answer: httpx.Response, code: str) -> None:
    with pytest.raises(ConnectorError) as caught:
        await _connector(Bitbucket({"/workspaces/acme": answer})).test_connection()

    assert caught.value.diagnostic.code == DiagnosticCode(code)
    assert TOKEN not in repr(caught.value.diagnostic)


async def test_an_echoed_atlassian_token_is_removed_from_the_detail() -> None:
    other = "ATATT3xFfGF0SomeoneElse0123456789"
    echo = httpx.Response(401, text=f"refused {TOKEN} and {other}")
    with pytest.raises(ConnectorError) as caught:
        await _connector(Bitbucket({"/workspaces/acme": echo})).test_connection()

    detail = caught.value.diagnostic.detail or ""
    assert TOKEN not in detail
    assert other not in detail


async def test_health_says_when_the_quota_is_nearly_spent() -> None:
    near = httpx.Response(200, json={"slug": "acme"}, headers={"x-ratelimit-nearlimit": "true"})

    assert (await _connector(Bitbucket()).check_health()).status is HealthStatus.HEALTHY
    degraded = await _connector(Bitbucket({"/workspaces/acme": near})).check_health()
    assert degraded.status is HealthStatus.DEGRADED


def test_the_token_never_shows_in_a_repr() -> None:
    credentials = BitbucketCredentials(token=SecretStr(TOKEN), email="nora@acme.example")

    assert TOKEN not in repr(credentials)
    assert next(iter(credentials.model_dump())) == "token"  # the hint is the token's


# ── scope ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [
        {"workspace": "acme", "repositories": ["api"]},
        {"workspace": "acme", "repositories": ["globex/api"]},
        {"workspace": "acme", "repositories": []},
        {"workspace": "acme/x"},
    ],
    ids=["not-a-full-name", "another-workspace", "empty", "not-a-slug"],
)
def test_a_scope_that_cannot_be_read_is_refused(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BitbucketConfig.model_validate(config)


async def test_the_connection_test_probes_a_repository_in_scope() -> None:
    bitbucket = Bitbucket()

    await _connector(bitbucket, {"repositories": ["acme/api"]}).test_connection()

    assert "/repositories/acme/api" in bitbucket.queries
    assert "/repositories/acme/api/commits/main" in bitbucket.queries


async def test_the_scope_is_chosen_from_every_repository_across_pages() -> None:
    listing = await _connector(Bitbucket({"/repositories/acme": ([API], [WEB])})).list_scope()

    assert [option.key for option in listing.options] == ["acme/api", "acme/web"]
    assert (listing.options[0].private, listing.options[1].private) == (True, False)
    assert listing.options[0].updated_at == datetime(2026, 9, 25, 9, tzinfo=UTC)


# ── synchronisation ──────────────────────────────────────────────────────────


async def test_repositories_in_scope_are_known_by_their_uuid() -> None:
    records = await _stream(Bitbucket(), Capability.REPOSITORIES, repositories=["ACME/web"])

    assert [r.external_id for r in records] == ["{r-web}"]


async def test_commits_of_the_main_branch_end_after_a_page_older_than_the_last_pass() -> None:
    new = {"hash": "abc", "date": "2026-09-22T08:00:00+00:00"}
    old = {"hash": "def", "date": "2026-09-01T08:00:00+00:00"}
    bitbucket = Bitbucket({"/repositories/acme/api/commits/main": ([new, old], [old], [new])})

    records = await _stream(bitbucket, Capability.COMMITS, since=SINCE)

    assert [(r.external_id, r.container) for r in records] == [("{r-api}:abc", "acme/api")]
    # Page 2 holds nothing newer: page 3 is never asked for.
    assert len(bitbucket.queries["/repositories/acme/api/commits/main"]) == 2
    # acme/web has no main branch: an empty repository, not asked.
    assert not any("acme/web/commits" in path for path in bitbucket.queries)


async def test_an_older_commit_ahead_of_a_newer_one_does_not_hide_it() -> None:
    """A rebase, or an old branch merged in, puts an older date first."""
    older = {"hash": "aaa", "date": "2026-09-01T08:00:00+00:00"}
    newer = {"hash": "bbb", "date": "2026-09-22T08:00:00+00:00"}
    bitbucket = Bitbucket({"/repositories/acme/api/commits/main": [older, newer]})

    records = await _stream(bitbucket, Capability.COMMITS, since=SINCE)

    assert [r.external_id for r in records] == ["{r-api}:bbb"]


async def test_a_newer_commit_on_a_later_page_is_still_read() -> None:
    older = {"hash": "aaa", "date": "2026-09-01T08:00:00+00:00"}
    newer = {"hash": "bbb", "date": "2026-09-22T08:00:00+00:00"}
    undated = {"hash": "ccc"}
    pages = ([newer, older], [older, newer, undated], [older])
    bitbucket = Bitbucket({"/repositories/acme/api/commits/main": pages})

    records = await _stream(bitbucket, Capability.COMMITS, since=SINCE)

    # Undated is kept: nothing says it is old.
    assert [r.external_id for r in records] == ["{r-api}:bbb", "{r-api}:bbb", "{r-api}:ccc"]


async def test_pull_requests_of_every_state_newest_first() -> None:
    pull = {"id": 7, "updated_on": "2026-09-23T00:00:00+00:00"}
    bitbucket = Bitbucket({"/repositories/acme/api/pullrequests": [pull]})

    records = await _stream(bitbucket, Capability.PULL_REQUESTS, since=SINCE)

    assert [r.external_id for r in records] == ["{r-api}:7"]
    query = bitbucket.queries["/repositories/acme/api/pullrequests"][0]
    assert query.get_list("state") == ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"]
    assert (query["sort"], query["pagelen"]) == ("-updated_on", "50")


async def test_issues_only_where_the_tracker_is_on() -> None:
    issue = {"id": 3, "updated_on": "2026-09-23T00:00:00+00:00"}
    no_tracker = {**API, "has_issues": False}
    bitbucket = Bitbucket(
        {
            "/repositories/acme": [no_tracker, {**WEB, "has_issues": True}],
            "/repositories/acme/web/issues": [issue],
        }
    )

    records = await _stream(bitbucket, Capability.ISSUES)

    assert [(r.external_id, r.container) for r in records] == [("{r-web}:3", "acme/web")]
    assert "/repositories/acme/api/issues" not in bitbucket.queries


async def test_branches_are_known_by_their_repository_and_name() -> None:
    bitbucket = Bitbucket({"/repositories/acme/api/refs/branches": [{"name": "main"}]})

    records = await _stream(bitbucket, Capability.BRANCHES, repositories=["acme/api"])

    assert [r.external_id for r in records] == ["{r-api}:main"]
