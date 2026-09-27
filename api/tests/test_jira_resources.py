"""What the Jira connector reads for the sync engine (LEKA-346).

The same stand-in Jira as test_jira_connector.py. What matters here: every
project in scope and nothing else, every issue of each, across every page,
and an incremental pass that misses no change — JQL reads dates to the
minute, in the account's time zone.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from tests.test_jira_connector import OPS, PAY, Jira, _connector

# 08:30 UTC is 10:30 in Paris in September.
SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    jira: Jira, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(jira, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def _issue(number: int, project: str = "PAY") -> dict[str, object]:
    return {
        "id": str(20000 + number),
        "key": f"{project}-{number}",
        "fields": {
            "summary": f"Issue {number}",
            "updated": "2026-09-21T14:05:00.000+0200",
            "issuelinks": [{"type": {"name": "Blocks"}}],
        },
    }


def _search(by_project: dict[str, list[dict[str, object]]]) -> object:
    """A /search/jql that answers each project's issues, one page each."""

    def answer(request: httpx.Request) -> httpx.Response:
        jql = request.url.params["jql"]
        project = jql.split('"')[1]
        return httpx.Response(200, json={"issues": by_project.get(project, []), "isLast": True})

    return answer


async def test_projects_are_read_across_every_page() -> None:
    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("startAt") == "50":
            return httpx.Response(200, json={"values": [OPS], "isLast": True})
        following = str(request.url.copy_set_param("startAt", 50))
        return httpx.Response(200, json={"values": [PAY], "nextPage": following})

    records = await _stream(Jira({"/project/search": pages}), Capability.PROJECTS)

    assert [(r.kind, r.external_id, r.container) for r in records] == [
        # Its own key as container: what scope rules match it by (LEKA-351).
        (Capability.PROJECTS, "10000", "PAY"),
        (Capability.PROJECTS, "10001", "OPS"),
    ]
    assert records[0].payload["name"] == "Payments"


async def test_only_the_projects_in_scope_are_read() -> None:
    jira = Jira()

    records = await _stream(jira, Capability.PROJECTS, projects=["OPS"])

    assert [r.external_id for r in records] == ["10001"]
    assert all(q.get_list("keys") == ["OPS"] for q in jira.asked("/project/search"))


async def test_a_wide_scope_is_asked_fifty_keys_at_a_time() -> None:
    jira = Jira()
    keys = [f"P{n}" for n in range(120)]

    await _stream(jira, Capability.PROJECTS, projects=keys)

    asked = [q.get_list("keys") for q in jira.asked("/project/search")]
    assert [len(chunk) for chunk in asked] == [50, 50, 20]
    assert [key for chunk in asked for key in chunk] == keys


async def test_an_initial_pass_reads_every_issue_of_each_project() -> None:
    issues = {"PAY": [_issue(1), _issue(2)], "OPS": [_issue(7, "OPS")]}
    jira = Jira({"/search/jql": _search(issues)})

    records = await _stream(jira, Capability.ISSUES)

    assert [(r.external_id, r.container) for r in records] == [
        ("20001", "PAY"),
        ("20002", "PAY"),
        ("20007", "OPS"),
    ]
    assert records[0].updated_at == datetime(2026, 9, 21, 12, 5, tzinfo=UTC)
    assert records[0].payload["key"] == "PAY-1"
    # Every field: comments, links, parent, sprint go with the issue.
    asked = jira.asked("/search/jql")
    assert [q["jql"] for q in asked] == [
        'project = "PAY" ORDER BY updated ASC',
        'project = "OPS" ORDER BY updated ASC',
    ]
    assert all(q["fields"] == "*all" for q in asked)


async def test_an_incremental_pass_asks_from_a_minute_earlier_in_the_account_s_zone() -> None:
    jira = Jira()

    await _stream(jira, Capability.ISSUES, since=SINCE, projects=["PAY"])

    assert jira.asked("/search/jql")[0]["jql"] == (
        'project = "PAY" AND updated >= "2026/09/20 10:29" ORDER BY updated ASC'
    )


@pytest.mark.parametrize("zone", [None, "Not/AZone", ""])
async def test_an_unknown_zone_widens_the_window_rather_than_miss_a_change(
    zone: str | None,
) -> None:
    me = {"displayName": "Nora", "timeZone": zone}
    jira = Jira({"/myself": me})

    await _stream(jira, Capability.ISSUES, since=SINCE, projects=["PAY"])

    # Fourteen hours before 08:30 UTC, the widest offset there is.
    assert '"2026/09/19 18:30"' in jira.asked("/search/jql")[0]["jql"]


async def test_issues_are_followed_across_page_tokens() -> None:
    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("nextPageToken") == "t2":
            return httpx.Response(200, json={"issues": [_issue(2)], "isLast": True})
        return httpx.Response(200, json={"issues": [_issue(1)], "nextPageToken": "t2"})

    jira = Jira({"/search/jql": pages})

    records = await _stream(jira, Capability.ISSUES, projects=["PAY"])

    assert [r.external_id for r in records] == ["20001", "20002"]
    first, second = jira.asked("/search/jql")
    assert second["jql"] == first["jql"]
    assert second["nextPageToken"] == "t2"


async def test_a_page_token_jira_repeats_ends_the_pass_rather_than_loop() -> None:
    again = httpx.Response(200, json={"issues": [_issue(1)], "nextPageToken": "same"})
    jira = Jira({"/search/jql": lambda request: again})

    with pytest.raises(ConnectorError) as caught:
        await _stream(jira, Capability.ISSUES, projects=["PAY"])

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert len(jira.asked("/search/jql")) == 2


async def test_an_exhausted_quota_mid_stream_keeps_what_was_read() -> None:
    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("nextPageToken"):
            return httpx.Response(429, headers={"retry-after": "60"})
        return httpx.Response(200, json={"issues": [_issue(1)], "nextPageToken": "t2"})

    connector = _connector(Jira({"/search/jql": pages}), projects=["PAY"])
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(Capability.ISSUES):
            read.append(item)

    assert [r.external_id for r in read] == ["20001"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 60


async def test_jira_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Jira(), Capability.COMMITS)
