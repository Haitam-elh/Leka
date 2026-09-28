"""What the Monday connector reads for the sync engine (LEKA-346).

The same stand-in Monday as test_monday_connector.py. What matters here:
the boards in scope and nothing else — boards only — every item across
Monday's cursors, and an incremental pass that keeps only the items
updated since the last one, since Monday cannot filter by it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from tests.test_monday_connector import Monday, _connector, data, refused

SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    monday: Monday, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(monday, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def _item(number: int, updated: str = "2026-09-21T12:05:00Z") -> dict[str, Any]:
    return {
        "id": str(number),
        "name": f"Item {number}",
        "updated_at": updated,
        "column_values": [{"id": "status", "text": "Done"}],
    }


async def test_every_board_is_read_whole_boards_only() -> None:
    records = await _stream(Monday(), Capability.PROJECTS)

    assert [(r.external_id, r.container) for r in records] == [("111", "7"), ("222", None)]
    assert records[0].updated_at == datetime(2026, 9, 25, 9, tzinfo=UTC)


async def test_only_the_boards_in_scope_are_read() -> None:
    monday = Monday()

    records = await _stream(monday, Capability.PROJECTS, boards=["222"])

    assert [r.external_id for r in records] == ["222"]
    assert monday.variables("Boards") == []


async def test_every_item_of_each_board_is_read_with_its_columns() -> None:
    monday = Monday()
    monday.items = {"111": [_item(1), _item(2)], "222": [_item(3)]}

    records = await _stream(monday, Capability.ISSUES)

    assert [(r.external_id, r.container) for r in records] == [
        ("1", "111"),
        ("2", "111"),
        ("3", "222"),
    ]
    assert records[0].payload["column_values"] == [{"id": "status", "text": "Done"}]
    assert records[0].updated_at == datetime(2026, 9, 21, 12, 5, tzinfo=UTC)


async def test_items_are_followed_across_monday_s_cursors() -> None:
    first = data({"boards": [{"items_page": {"cursor": "c2", "items": [_item(1)]}}]})

    def following(variables: dict[str, Any]) -> httpx.Response:
        assert variables["cursor"] == "c2"
        return data({"next_items_page": {"cursor": None, "items": [_item(2)]}})

    monday = Monday({"Items": first, "NextItems": following})

    records = await _stream(monday, Capability.ISSUES, boards=["111"])

    assert [r.external_id for r in records] == ["1", "2"]


async def test_a_cursor_monday_repeats_ends_the_pass_rather_than_loop() -> None:
    first = data({"boards": [{"items_page": {"cursor": "same", "items": [_item(1)]}}]})
    again = data({"next_items_page": {"cursor": "same", "items": [_item(2)]}})
    monday = Monday({"Items": first, "NextItems": again})

    with pytest.raises(ConnectorError) as caught:
        await _stream(monday, Capability.ISSUES, boards=["111"])

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR


async def test_an_incremental_pass_keeps_the_items_updated_since() -> None:
    monday = Monday()
    monday.items = {
        "111": [
            _item(1, "2026-09-10T00:00:00Z"),
            _item(2, "2026-09-20T08:29:00Z"),  # within the margin: kept
            _item(3),
        ]
    }

    records = await _stream(monday, Capability.ISSUES, since=SINCE, boards=["111"])

    assert [r.external_id for r in records] == ["2", "3"]


async def test_an_exhausted_budget_mid_stream_keeps_what_was_read() -> None:
    first = data({"boards": [{"items_page": {"cursor": "c2", "items": [_item(1)]}}]})
    busy = refused("COMPLEXITY_BUDGET_EXHAUSTED", status=429, retry_in_seconds=30)
    connector = _connector(Monday({"Items": first, "NextItems": busy}), boards=["111"])
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(Capability.ISSUES):
            read.append(item)

    assert [r.external_id for r in read] == ["1"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 30


async def test_monday_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Monday(), Capability.PAGES)
