"""What the Notion connector reads for the sync engine (LEKA-346).

The same stand-in Notion as test_notion_connector.py. What matters here:
everything shared and nothing else, or only what lies beneath a root; each
page with its blocks, in reading order and bounded; an incremental pass
that ends at the last one, with room for Notion's rounded edit times.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from leka.connectors.notion import connector as notion_module
from tests.test_notion_connector import (
    DRAFT,
    NOTES,
    OBJECTS,
    ROADMAP,
    SPEC_ROW,
    SPECS,
    TOP,
    UNSHARED,
    WIKI,
    Notion,
    _connector,
    _text,
    failure,
    in_page,
    page,
    uid,
)


async def _stream(
    notion: Notion, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(notion, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def ids(record: RawRecord) -> list[str]:
    """The ids of a page's blocks, in the order they were read."""
    return [str(b["id"]) for b in cast(list[dict[str, Any]], record.payload["blocks"])]


def block(block_id: str, text: str, *, kind: str = "paragraph", children: bool = False) -> Any:
    return {
        "object": "block",
        "id": block_id,
        "type": kind,
        "has_children": children,
        kind: {"rich_text": _text(text)},
    }


# ── what is read ─────────────────────────────────────────────────────────────


async def test_an_initial_pass_reads_every_shared_page_where_it_lives() -> None:
    records = await _stream(Notion(), Capability.PAGES)

    assert [(r.external_id, r.container) for r in records] == [
        (ROADMAP, WIKI),
        (SPEC_ROW, SPECS),
        (NOTES, None),
        (DRAFT, UNSHARED),
        (WIKI, None),
    ]
    assert records[0].kind is Capability.PAGES
    assert records[0].updated_at == datetime(2026, 9, 25, 10, tzinfo=UTC)
    assert records[0].payload["properties"] == OBJECTS[0]["properties"]


async def test_databases_are_their_own_capability() -> None:
    notion = Notion()

    records = await _stream(notion, Capability.DATABASES)

    assert [(r.kind, r.external_id, r.container) for r in records] == [
        (Capability.DATABASES, SPECS, WIKI)
    ]
    assert notion.searches()[0]["filter"] == {"property": "object", "value": "database"}
    # A database's rows are pages; its own record carries no blocks.
    assert "blocks" not in records[0].payload


async def test_search_is_followed_across_notion_s_cursors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notion_module, "PAGE_SIZE", 2)
    notion = Notion()

    records = await _stream(notion, Capability.PAGES)

    assert len(records) == 5
    assert [body.get("start_cursor") for body in notion.searches()] == [None, "2", "4"]


async def test_a_cursor_notion_repeats_ends_the_pass_rather_than_loop() -> None:
    again = {"object": "list", "results": [], "has_more": True, "next_cursor": "same"}
    notion = Notion(overrides={"POST /search": httpx.Response(200, json=again)})

    with pytest.raises(ConnectorError) as caught:
        await _stream(notion, Capability.PAGES)

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR
    assert len(notion.searches()) == 2


# ── incremental ──────────────────────────────────────────────────────────────


async def test_an_incremental_pass_stops_at_the_first_page_edited_before_the_last() -> None:
    notion = Notion()

    records = await _stream(notion, Capability.PAGES, since=datetime(2026, 9, 24, 12, tzinfo=UTC))

    assert [r.external_id for r in records] == [ROADMAP]
    assert len(notion.searches()) == 1


async def test_an_edit_notion_rounded_down_to_the_minute_is_not_missed() -> None:
    # Edited at 10:00:45 during the last pass, which started at 10:00:30:
    # Notion says 10:00:00.
    records = await _stream(
        Notion(), Capability.PAGES, since=datetime(2026, 9, 25, 10, 0, 30, tzinfo=UTC)
    )

    assert [r.external_id for r in records] == [ROADMAP]


# ── the scope ────────────────────────────────────────────────────────────────


async def test_with_roots_only_what_lies_beneath_them_is_read() -> None:
    notion = Notion()

    records = await _stream(notion, Capability.PAGES, roots=[WIKI])

    assert [r.external_id for r in records] == [ROADMAP, SPEC_ROW, WIKI]
    # Roadmap's parent is the root itself; the row's database was asked
    # once; Notes and Wiki are at the top; Draft's parent is not shared.
    assert [p for p in notion.paths() if not p.startswith("/blocks/")] == [
        f"/databases/{SPECS}",
        f"/pages/{UNSHARED}",
    ]


async def test_a_database_can_be_the_root() -> None:
    records = await _stream(Notion(), Capability.PAGES, roots=[SPECS])

    assert [r.external_id for r in records] == [SPEC_ROW]


async def test_an_ancestor_is_asked_once_per_pass() -> None:
    rows = [
        page(uid(20 + n), f"Row {n}", "2026-09-24T10:00:00.000Z", in_page(UNSHARED))
        for n in range(3)
    ]
    notion = Notion(objects=rows)

    records = await _stream(notion, Capability.PAGES, roots=[WIKI])

    assert records == []
    assert [p for p in notion.paths() if not p.startswith("/blocks/")] == [f"/pages/{UNSHARED}"]


async def test_a_page_inside_a_block_climbs_through_it() -> None:
    column = uid(30)
    inside = page(
        uid(31),
        "In a column",
        "2026-09-26T10:00:00.000Z",
        {
            "type": "block_id",
            "block_id": column,
        },
    )
    notion = Notion(objects=[inside, *OBJECTS], block_parents={column: in_page(WIKI)})

    records = await _stream(notion, Capability.PAGES, roots=[WIKI])

    assert records[0].external_id == uid(31)
    assert f"/blocks/{column}" in notion.paths()


async def test_a_page_beneath_no_root_is_not_read_even_if_shared() -> None:
    records = await _stream(Notion(), Capability.PAGES, roots=[NOTES])

    assert [r.external_id for r in records] == [NOTES]


# ── a page's content ─────────────────────────────────────────────────────────


async def test_a_page_comes_with_its_blocks_nested_ones_after_their_parent() -> None:
    blocks = {
        NOTES: [
            block("b1", "Intro"),
            block("b2", "A list", kind="bulleted_list_item", children=True),
            block("b3", "Sub page", kind="child_page", children=True),
            block("b4", "End"),
        ],
        "b2": [block("b2.1", "First item")],
        "b3": [block("never", "read through its parent")],
    }
    notion = Notion(objects=[page(NOTES, "Notes", "2026-09-22T10:00:00.000Z", TOP)], blocks=blocks)

    records = await _stream(notion, Capability.PAGES)

    assert ids(records[0]) == ["b1", "b2", "b2.1", "b3", "b4"]
    assert records[0].payload["blocks_truncated"] is False
    assert "/blocks/b3/children" not in notion.paths()


async def test_blocks_are_followed_across_cursors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notion_module, "PAGE_SIZE", 2)
    blocks = {NOTES: [block(f"b{n}", str(n)) for n in range(5)]}
    notion = Notion(objects=[page(NOTES, "Notes", "2026-09-22T10:00:00.000Z", TOP)], blocks=blocks)

    records = await _stream(notion, Capability.PAGES)

    assert len(ids(records[0])) == 5
    assert notion.paths().count(f"/blocks/{NOTES}/children") == 3


async def test_blocks_deeper_than_the_limit_are_left_out_and_said_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notion_module, "MAX_DEPTH", 2)
    blocks = {
        NOTES: [block("l1", "1", children=True)],
        "l1": [block("l2", "2", children=True)],
        "l2": [block("l3", "3")],
    }
    notion = Notion(objects=[page(NOTES, "Notes", "2026-09-22T10:00:00.000Z", TOP)], blocks=blocks)

    records = await _stream(notion, Capability.PAGES)

    assert ids(records[0]) == ["l1", "l2"]
    assert records[0].payload["blocks_truncated"] is True


async def test_a_page_longer_than_the_limit_is_cut_and_said_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notion_module, "MAX_BLOCKS", 3)
    blocks = {
        NOTES: [block("a", "a", children=True), block("b", "b"), block("c", "c")],
        "a": [block("a1", "a1"), block("a2", "a2")],
    }
    notion = Notion(objects=[page(NOTES, "Notes", "2026-09-22T10:00:00.000Z", TOP)], blocks=blocks)

    records = await _stream(notion, Capability.PAGES)

    assert ids(records[0]) == ["a", "a1", "a2"]
    assert records[0].payload["blocks_truncated"] is True


async def test_an_archived_page_is_listed_without_reading_its_content() -> None:
    archived = page(NOTES, "Notes", "2026-09-22T10:00:00.000Z", TOP, archived=True)
    notion = Notion(objects=[archived])

    records = await _stream(notion, Capability.PAGES)

    assert records[0].payload["archived"] is True
    assert "blocks" not in records[0].payload
    assert notion.paths() == []


# ── failures ─────────────────────────────────────────────────────────────────


async def test_an_exhausted_quota_mid_stream_keeps_what_was_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notion_module, "PAGE_SIZE", 2)

    def search(request: httpx.Request) -> httpx.Response:
        if b"start_cursor" in request.content:
            return failure(429, "rate_limited", headers={"retry-after": "30"})
        return httpx.Response(
            200,
            json={"object": "list", "results": OBJECTS[:1], "has_more": True, "next_cursor": "1"},
        )

    connector = _connector(Notion(overrides={"POST /search": search}))
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(Capability.PAGES):
            read.append(item)

    assert [r.external_id for r in read] == [ROADMAP]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 30


async def test_notion_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Notion(), Capability.ISSUES)
