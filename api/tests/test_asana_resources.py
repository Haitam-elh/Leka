"""What the Asana connector reads for the sync engine (LEKA-346).

The same stand-in Asana as test_asana_connector.py. What matters here:
the projects in scope and nothing else, each task once, across Asana's
offsets, and an incremental pass that Asana itself filters by date.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from tests.test_asana_connector import Asana, _connector, page

SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    asana: Asana, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(asana, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def _task(gid: str, *projects: str) -> dict[str, Any]:
    return {
        "gid": gid,
        "name": f"Task {gid}",
        "modified_at": "2026-09-21T12:05:00.000Z",
        "memberships": [{"project": {"gid": p}} for p in projects],
    }


def _tasks_by_project(tasks: dict[str, list[Any]]) -> Any:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page(tasks.get(request.url.params["project"], [])))

    return answer


async def test_every_project_of_every_workspace_is_read_whole() -> None:
    records = await _stream(Asana(), Capability.PROJECTS)

    assert [(r.external_id, r.container) for r in records] == [
        ("1001", "100"),
        ("1002", "100"),
        ("2001", "200"),
    ]
    assert records[0].updated_at == datetime(2026, 9, 25, 9, tzinfo=UTC)


async def test_only_the_projects_in_scope_are_read() -> None:
    asana = Asana()

    records = await _stream(asana, Capability.PROJECTS, projects=["2001", "1001"])

    assert [r.external_id for r in records] == ["2001", "1001"]
    assert asana.params("/projects") == []  # asked one by one, not listed


async def test_a_project_in_scope_gone_since_is_left_for_the_sweep() -> None:
    records = await _stream(Asana(), Capability.PROJECTS, projects=["1001", "9999"])

    assert [r.external_id for r in records] == ["1001"]


async def test_tasks_are_read_project_by_project_each_once() -> None:
    tasks = _tasks_by_project(
        {
            "1001": [_task("1"), _task("2", "1001", "2001")],
            "2001": [
                _task("2", "1001", "2001"),
                _task("3"),
            ],
        }
    )
    asana = Asana({"/tasks": tasks})

    records = await _stream(asana, Capability.ISSUES)

    assert [(r.external_id, r.container) for r in records] == [
        ("1", "1001"),
        ("2", "1001"),
        ("3", "2001"),
    ]
    assert records[0].updated_at == datetime(2026, 9, 21, 12, 5, tzinfo=UTC)
    assert all("modified_since" not in p for p in asana.params("/tasks"))
    assert "memberships.project.name" in asana.params("/tasks")[0]["opt_fields"]


async def test_an_incremental_pass_asks_asana_for_what_changed_since() -> None:
    asana = Asana()

    await _stream(asana, Capability.ISSUES, since=SINCE, projects=["1001"])

    assert asana.params("/tasks")[0]["modified_since"] == "2026-09-20T08:30:00+00:00"


async def test_tasks_are_followed_across_asana_s_offsets() -> None:
    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("offset") == "o2":
            return httpx.Response(200, json=page([_task("2")]))
        return httpx.Response(200, json=page([_task("1")], offset="o2"))

    asana = Asana({"/tasks": pages})

    records = await _stream(asana, Capability.ISSUES, projects=["1001"])

    assert [r.external_id for r in records] == ["1", "2"]
    second = asana.params("/tasks")[1]
    assert (second["offset"], second["project"], second["limit"]) == ("o2", "1001", "100")


async def test_an_exhausted_quota_mid_stream_keeps_what_was_read() -> None:
    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("offset"):
            return httpx.Response(429, headers={"retry-after": "60"}, json={"errors": []})
        return httpx.Response(200, json=page([_task("1")], offset="o2"))

    connector = _connector(Asana({"/tasks": pages}), projects=["1001"])
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(Capability.ISSUES):
            read.append(item)

    assert [r.external_id for r in read] == ["1"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 60


async def test_asana_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Asana(), Capability.PAGES)
