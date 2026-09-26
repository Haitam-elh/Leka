"""What the Linear connector reads for the sync engine (LEKA-346).

The same stand-in Linear as test_linear_connector.py. What matters here:
every team in scope and nothing else, each project once, every issue —
archived ones too — across Linear's cursors, and an incremental pass that
Linear itself filters by date.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from tests.test_linear_connector import ENG, OPS, Linear, _connector, connection, refused

SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    linear: Linear, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(linear, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def _issue(number: int, team: str = "ENG") -> dict[str, Any]:
    return {
        "id": f"issue-{number}",
        "identifier": f"{team}-{number}",
        "title": f"Issue {number}",
        "updatedAt": "2026-09-21T12:05:00.000Z",
        "relations": {"nodes": [{"type": "blocks", "relatedIssue": {"identifier": "OPS-1"}}]},
    }


def _by_team(key: str, nodes: dict[str, list[Any]]) -> Any:
    """An answer giving each team its own nodes, one page each."""

    def answer(variables: dict[str, Any]) -> httpx.Response:
        found = nodes.get(variables["team"], [])
        return httpx.Response(200, json={"data": {"team": {key: connection(found)}}})

    return answer


async def test_teams_are_read_across_linear_s_cursors() -> None:
    def pages(variables: dict[str, Any]) -> httpx.Response:
        if variables["after"] == "c2":
            return httpx.Response(200, json={"data": {"teams": connection([OPS])}})
        return httpx.Response(200, json={"data": {"teams": connection([ENG], end="c2")}})

    projects = _by_team("projects", {"team-ops": [{"id": "p-1", "name": "Launch"}]})
    linear = Linear({"Teams": pages, "TeamProjects": projects})

    records = await _stream(linear, Capability.PROJECTS)

    assert [(r.external_id, r.container) for r in records] == [("p-1", "OPS")]
    assert [v["after"] for v in linear.variables("Teams")] == [None, "c2"]


async def test_a_project_shared_by_two_teams_is_read_once() -> None:
    launch = {"id": "p-1", "name": "Launch", "updatedAt": "2026-09-22T10:00:00.000Z"}
    shared = _by_team("projects", {"team-eng": [launch], "team-ops": [launch]})

    records = await _stream(Linear({"TeamProjects": shared}), Capability.PROJECTS)

    assert [(r.kind, r.external_id, r.container) for r in records] == [
        (Capability.PROJECTS, "p-1", "ENG")
    ]
    assert records[0].updated_at == datetime(2026, 9, 22, 10, tzinfo=UTC)


async def test_only_the_teams_in_scope_are_read() -> None:
    issues = _by_team("issues", {"team-eng": [_issue(1)], "team-ops": [_issue(2, "OPS")]})
    linear = Linear({"TeamIssues": issues})

    records = await _stream(linear, Capability.ISSUES, teams=["OPS"])

    assert [r.container for r in records] == ["OPS"]
    assert linear.variables("Teams")[0]["filter"] == {"key": {"in": ["OPS"]}}


async def test_an_initial_pass_reads_every_issue_of_each_team_archived_included() -> None:
    issues = _by_team(
        "issues", {"team-eng": [_issue(1), _issue(2)], "team-ops": [_issue(7, "OPS")]}
    )
    linear = Linear({"TeamIssues": issues})

    records = await _stream(linear, Capability.ISSUES)

    assert [(r.external_id, r.container) for r in records] == [
        ("issue-1", "ENG"),
        ("issue-2", "ENG"),
        ("issue-7", "OPS"),
    ]
    assert records[0].updated_at == datetime(2026, 9, 21, 12, 5, tzinfo=UTC)
    assert records[0].payload["relations"] == _issue(1)["relations"]
    assert all(v["filter"] is None for v in linear.variables("TeamIssues"))


async def test_an_incremental_pass_asks_linear_for_what_changed_since() -> None:
    linear = Linear()

    await _stream(linear, Capability.ISSUES, since=SINCE, teams=["ENG"])

    assert linear.variables("TeamIssues")[0]["filter"] == {
        "updatedAt": {"gte": "2026-09-20T08:30:00+00:00"}
    }


async def test_issues_are_followed_across_cursors() -> None:
    def pages(variables: dict[str, Any]) -> httpx.Response:
        if variables["after"] == "c2":
            return httpx.Response(200, json={"data": {"team": {"issues": connection([_issue(2)])}}})
        first = connection([_issue(1)], end="c2")
        return httpx.Response(200, json={"data": {"team": {"issues": first}}})

    records = await _stream(Linear({"TeamIssues": pages}), Capability.ISSUES, teams=["ENG"])

    assert [r.external_id for r in records] == ["issue-1", "issue-2"]


async def test_a_cursor_linear_repeats_ends_the_pass_rather_than_loop() -> None:
    again = {"data": {"team": {"issues": connection([_issue(1)], end="same")}}}
    linear = Linear({"TeamIssues": again})

    with pytest.raises(ConnectorError) as caught:
        await _stream(linear, Capability.ISSUES, teams=["ENG"])

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert len(linear.variables("TeamIssues")) == 2


async def test_an_exhausted_quota_mid_stream_keeps_what_was_read() -> None:
    def pages(variables: dict[str, Any]) -> httpx.Response:
        if variables["after"]:
            return refused("RATELIMITED", headers={"retry-after": "60"})
        first = connection([_issue(1)], end="c2")
        return httpx.Response(200, json={"data": {"team": {"issues": first}}})

    connector = _connector(Linear({"TeamIssues": pages}), teams=["ENG"])
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(Capability.ISSUES):
            read.append(item)

    assert [r.external_id for r in read] == ["issue-1"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 60


async def test_linear_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Linear(), Capability.PAGES)
