"""What the Guru connector reads for the sync engine (LEKA-346).

The same stand-in Guru as test_guru_connector.py. What matters here: the
collections in scope and nothing else, every card across Guru's
"next-page" links, and an incremental pass that stops at the first card
modified before the last one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from leka.connectors.guru import connector as guru_module
from tests.test_guru_connector import Guru, _connector, card

SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    guru: Guru, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(guru, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


async def test_every_collection_is_read_whole() -> None:
    records = await _stream(Guru(), Capability.SPACES)

    assert [r.external_id for r in records] == ["c-onboard", "c-sales"]


async def test_only_the_collections_in_scope_are_read() -> None:
    records = await _stream(Guru(), Capability.SPACES, collections=["C-Sales"])

    assert [r.external_id for r in records] == ["c-sales"]


async def test_every_card_is_read_most_recently_modified_first() -> None:
    guru = Guru()

    records = await _stream(guru, Capability.PAGES)

    assert [(r.external_id, r.container) for r in records] == [
        ("card-1", "c-onboard"),
        ("card-2", "c-sales"),
    ]
    assert records[0].payload["content"] == "<p>Card 1</p>"
    assert records[0].updated_at == datetime(2026, 9, 21, 12, 5, tzinfo=UTC)
    first = guru.params("/search/query")[0]
    assert (first["sortField"], first["sortOrder"]) == ("lastModified", "desc")


async def test_only_the_cards_of_the_collections_in_scope_are_read() -> None:
    records = await _stream(Guru(), Capability.PAGES, collections=["c-sales"])

    assert [r.external_id for r in records] == ["card-2"]


async def test_cards_are_followed_across_guru_s_next_page_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guru_module, "PAGE_SIZE", 2)
    guru = Guru()
    guru.cards = [card(n) for n in range(1, 6)]

    records = await _stream(guru, Capability.PAGES)

    assert [r.external_id for r in records] == [f"card-{n}" for n in range(1, 6)]
    assert [p.get("token") for p in guru.params("/search/query")] == [None, "2", "4"]


async def test_a_link_to_another_host_is_refused() -> None:
    elsewhere = httpx.Response(
        200, json=[card(1)], headers={"link": '<https://evil.test/steal>; rel="next-page"'}
    )

    with pytest.raises(ConnectorError) as caught:
        await _stream(Guru({"/search/query": elsewhere}), Capability.PAGES)

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR


async def test_an_incremental_pass_stops_at_the_first_card_modified_before() -> None:
    guru = Guru()
    guru.cards = [
        card(1),
        card(2, modified="2026-09-20T08:29:00.000+0000"),  # within the margin: kept
        card(3, modified="2026-09-10T00:00:00.000+0000"),
        card(4),  # never reached: the order says it is older
    ]

    records = await _stream(guru, Capability.PAGES, since=SINCE)

    assert [r.external_id for r in records] == ["card-1", "card-2"]


async def test_guru_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Guru(), Capability.ISSUES)
