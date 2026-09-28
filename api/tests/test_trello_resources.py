"""What the Trello connector reads for the sync engine (LEKA-346).

The same stand-in Trello as test_trello_connector.py. What matters here:
the boards in scope and nothing else, every card — archived ones too —
across pages that go back in time, and an incremental pass that keeps only
the cards active since the last one, since Trello cannot filter by it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from leka.connectors.trello import connector as trello_module
from tests.test_trello_connector import ARCHIVE, ROADMAP, Trello, _connector

SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    trello: Trello, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(trello, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def _card(number: int, active: str = "2026-09-21T12:05:00.000Z") -> dict[str, Any]:
    return {
        "id": f"6000000000000000000000{number:02d}",
        "name": f"Card {number}",
        "dateLastActivity": active,
        "closed": number % 2 == 0,
    }


async def test_every_board_is_read_whole_with_its_lists() -> None:
    trello = Trello()

    records = await _stream(trello, Capability.PROJECTS)

    assert [(r.external_id, r.container) for r in records] == [
        (ROADMAP["id"], "org-1"),
        (ARCHIVE["id"], "org-1"),
    ]
    assert records[0].payload["lists"] == [{"id": "l-1", "name": "Doing"}]
    assert records[0].updated_at == datetime(2026, 9, 25, 9, tzinfo=UTC)
    assert trello.params(f"/1/boards/{ROADMAP['id']}")[0]["lists"] == "all"


async def test_only_the_boards_in_scope_are_read_by_id_or_short_link() -> None:
    records = await _stream(Trello(), Capability.PROJECTS, boards=["ZzYy9876"])

    assert [r.external_id for r in records] == [ARCHIVE["id"]]


async def test_every_card_is_read_archived_ones_too() -> None:
    trello = Trello()
    trello.cards[ROADMAP["id"]] = [_card(1), _card(2)]

    records = await _stream(trello, Capability.ISSUES, boards=["AbCd1234"])

    assert [(r.external_id, r.container) for r in records] == [
        (_card(2)["id"], ROADMAP["id"]),
        (_card(1)["id"], ROADMAP["id"]),
    ]
    assert records[0].payload["closed"] is True
    assert records[0].updated_at == datetime(2026, 9, 21, 12, 5, tzinfo=UTC)


async def test_cards_are_followed_back_in_time_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(trello_module, "PAGE_SIZE", 2)
    trello = Trello()
    trello.cards[ROADMAP["id"]] = [_card(n) for n in range(1, 6)]

    records = await _stream(trello, Capability.ISSUES, boards=["AbCd1234"])

    assert [r.payload["name"] for r in records] == [f"Card {n}" for n in (5, 4, 3, 2, 1)]
    befores = [p.get("before") for p in trello.params(f"/1/boards/{ROADMAP['id']}/cards/all")]
    assert befores == [None, _card(4)["id"], _card(2)["id"]]


async def test_a_page_trello_repeats_ends_the_pass_rather_than_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(trello_module, "PAGE_SIZE", 2)
    same = httpx.Response(200, json=[_card(1), _card(2)])
    trello = Trello({f"/1/boards/{ROADMAP['id']}/cards/all": same})

    with pytest.raises(ConnectorError) as caught:
        await _stream(trello, Capability.ISSUES, boards=["AbCd1234"])

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR


async def test_an_incremental_pass_keeps_the_cards_active_since() -> None:
    trello = Trello()
    trello.cards[ROADMAP["id"]] = [
        _card(1, "2026-09-10T00:00:00.000Z"),
        _card(3, "2026-09-20T08:29:00.000Z"),  # within the margin: kept
        _card(5),
    ]

    records = await _stream(trello, Capability.ISSUES, since=SINCE, boards=["AbCd1234"])

    assert [r.payload["name"] for r in records] == ["Card 5", "Card 3"]


async def test_trello_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Trello(), Capability.PAGES)
