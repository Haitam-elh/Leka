"""What the ClickUp connector reads for the sync engine (LEKA-346).

The same stand-in ClickUp as test_clickup_connector.py. What matters here:
the Spaces in scope and nothing else, every List — in a Folder or not —
every Task across ClickUp's numbered pages, and an incremental pass that
ClickUp itself filters by date.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from leka.connectors.clickup import connector as clickup_module
from tests.test_clickup_connector import ClickUp, _connector, ecode

SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    clickup: ClickUp, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(clickup, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def _task(number: int, list_id: str = "l-1") -> dict[str, Any]:
    return {
        "id": f"t{number}",
        "name": f"Task {number}",
        "date_updated": "1790000000000",
        "list": {"id": list_id},
    }


async def test_every_list_of_every_space_is_read_in_folders_or_not() -> None:
    records = await _stream(ClickUp(), Capability.PROJECTS)

    assert [(r.external_id, r.container) for r in records] == [
        ("l-1", "901"),
        ("l-2", "901"),
        ("l-3", "902"),
    ]
    assert records[0].payload["folder"] == {"id": "f-1", "name": "Q4"}


async def test_only_the_spaces_in_scope_are_read() -> None:
    clickup = ClickUp()

    records = await _stream(clickup, Capability.PROJECTS, spaces=["902"])

    assert [r.external_id for r in records] == ["l-3"]
    assert not clickup.requests("/space/901/folder")


async def test_tasks_are_read_closed_ones_and_subtasks_included() -> None:
    clickup = ClickUp({"/team/9001/task": {"tasks": [_task(1), _task(2, "l-3")]}})

    records = await _stream(clickup, Capability.ISSUES, spaces=["901", "902"])

    assert [(r.external_id, r.container) for r in records] == [("t1", "l-1"), ("t2", "l-3")]
    assert records[0].updated_at == datetime.fromtimestamp(1_790_000_000, tz=UTC)
    params = clickup.requests("/team/9001/task")[0].url.params
    assert (params["include_closed"], params["subtasks"]) == ("true", "true")
    assert params.get_list("space_ids[]") == ["901", "902"]
    assert "date_updated_gt" not in params


async def test_an_incremental_pass_asks_clickup_for_what_changed_since() -> None:
    clickup = ClickUp()

    await _stream(clickup, Capability.ISSUES, since=SINCE)

    params = clickup.requests("/team/9001/task")[0].url.params
    assert params["date_updated_gt"] == str(int(SINCE.timestamp() * 1000))


async def test_tasks_are_followed_across_numbered_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clickup_module, "PAGE_SIZE", 2)

    def pages(request: httpx.Request) -> httpx.Response:
        number = int(request.url.params["page"])
        tasks = [_task(2 * number + 1), _task(2 * number + 2)] if number < 2 else [_task(9)]
        return httpx.Response(200, json={"tasks": tasks})

    clickup = ClickUp({"/team/9001/task": pages})

    records = await _stream(clickup, Capability.ISSUES)

    assert [r.external_id for r in records] == ["t1", "t2", "t3", "t4", "t9"]
    asked = [r.url.params["page"] for r in clickup.requests("/team/9001/task")]
    assert asked == ["0", "1", "2"]


async def test_a_clickup_that_never_ends_ends_the_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clickup_module, "PAGE_SIZE", 1)
    monkeypatch.setattr(clickup_module, "MAX_PAGES", 3)
    clickup = ClickUp({"/team/9001/task": {"tasks": [_task(1)]}})

    with pytest.raises(ConnectorError) as caught:
        await _stream(clickup, Capability.ISSUES)

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR


async def test_an_exhausted_quota_mid_stream_keeps_what_was_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(clickup_module, "PAGE_SIZE", 1)

    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params["page"] != "0":
            return httpx.Response(429, headers={"retry-after": "60"}, json={})
        return httpx.Response(200, json={"tasks": [_task(1)]})

    connector = _connector(ClickUp({"/team/9001/task": pages}))
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(Capability.ISSUES):
            read.append(item)

    assert [r.external_id for r in read] == ["t1"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 60


async def test_a_workspace_not_authorised_for_the_token_is_said_so() -> None:
    clickup = ClickUp({"/team/9001/task": ecode(401, "OAUTH_027")})

    with pytest.raises(ConnectorError) as caught:
        await _stream(clickup, Capability.ISSUES)

    assert caught.value.diagnostic.code is DiagnosticCode.PERMISSION_DENIED


async def test_clickup_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(ClickUp(), Capability.PAGES)
