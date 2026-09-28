"""What the Confluence connector reads for the sync engine (LEKA-346).

The same stand-in Confluence as test_confluence_connector.py. What matters
here: every space in scope and nothing else, every current page of each
with its body, across Confluence's relative page links, and an incremental
pass that stops where the last one did.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from tests.test_confluence_connector import ENG, OPS, Confluence, _connector

SINCE = datetime(2026, 9, 20, tzinfo=UTC)
ENG_PAGES = "/api/v2/spaces/98304/pages"


async def _stream(
    confluence: Confluence,
    capability: Capability,
    since: datetime | None = None,
    **config: object,
) -> list[RawRecord]:
    connector = _connector(confluence, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def _page(number: int, changed: str) -> dict[str, object]:
    return {
        "id": str(1000 + number),
        "title": f"Runbook {number}",
        "spaceId": "98304",
        "parentId": "999",
        "version": {"number": 3, "createdAt": changed},
        "body": {"storage": {"value": "<p>Restart the pods</p>", "representation": "storage"}},
    }


async def test_spaces_are_read_across_relative_page_links() -> None:
    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "c2":
            return httpx.Response(200, json={"results": [OPS], "_links": {}})
        following = "/wiki/api/v2/spaces?cursor=c2&limit=50"
        return httpx.Response(200, json={"results": [ENG], "_links": {"next": following}})

    records = await _stream(Confluence({"/api/v2/spaces": pages}), Capability.SPACES)

    assert [(r.kind, r.external_id, r.container) for r in records] == [
        (Capability.SPACES, "98304", None),
        (Capability.SPACES, "98305", None),
    ]


async def test_only_the_spaces_in_scope_are_read() -> None:
    confluence = Confluence()

    records = await _stream(confluence, Capability.SPACES, spaces=["OPS"])

    assert [r.external_id for r in records] == ["98305"]
    assert [q["keys"] for q in confluence.asked("/api/v2/spaces")] == ["OPS"]


async def test_a_wide_scope_is_asked_fifty_keys_at_a_time() -> None:
    confluence = Confluence()
    keys = [f"S{n}" for n in range(120)]

    await _stream(confluence, Capability.SPACES, spaces=keys)

    asked = [q["keys"].split(",") for q in confluence.asked("/api/v2/spaces")]
    assert [len(chunk) for chunk in asked] == [50, 50, 20]
    assert [key for chunk in asked for key in chunk] == keys


async def test_an_initial_pass_reads_every_current_page_with_its_body() -> None:
    confluence = Confluence(
        {ENG_PAGES: {"results": [_page(1, "2026-09-25T10:00:00.000Z")], "_links": {}}}
    )

    records = await _stream(confluence, Capability.PAGES)

    assert [(r.kind, r.external_id, r.container) for r in records] == [
        (Capability.PAGES, "1001", "ENG"),
    ]
    assert records[0].updated_at == datetime(2026, 9, 25, 10, tzinfo=UTC)
    assert records[0].payload["body"] == {
        "storage": {"value": "<p>Restart the pods</p>", "representation": "storage"}
    }
    query = confluence.asked(ENG_PAGES)[0]
    assert (query["body-format"], query["sort"], query["status"], query["limit"]) == (
        "storage",
        "-modified-date",
        "current",
        "50",
    )
    # Both spaces were visited; OPS simply has no page.
    assert confluence.asked("/api/v2/spaces/98305/pages") != []


async def test_an_incremental_pass_stops_at_the_first_page_changed_before_it() -> None:
    newest = _page(1, "2026-09-25T10:00:00.000Z")
    older = _page(2, "2026-09-01T10:00:00.000Z")
    listing = {"results": [newest, older], "_links": {"next": f"/wiki{ENG_PAGES}?cursor=c2"}}
    confluence = Confluence({ENG_PAGES: listing})

    records = await _stream(confluence, Capability.PAGES, since=SINCE, spaces=["ENG"])

    assert [r.external_id for r in records] == ["1001"]
    # Nothing older is wanted, so the next page is never asked for.
    assert len(confluence.asked(ENG_PAGES)) == 1


async def test_pages_are_followed_across_relative_page_links() -> None:
    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "c2":
            return httpx.Response(
                200, json={"results": [_page(2, "2026-09-24T10:00:00Z")], "_links": {}}
            )
        following = f"/wiki{ENG_PAGES}?cursor=c2&limit=50&body-format=storage"
        first = [_page(1, "2026-09-25T10:00:00Z")]
        return httpx.Response(200, json={"results": first, "_links": {"next": following}})

    records = await _stream(Confluence({ENG_PAGES: pages}), Capability.PAGES, spaces=["ENG"])

    assert [r.external_id for r in records] == ["1001", "1002"]


async def test_an_exhausted_quota_mid_stream_keeps_what_was_read() -> None:
    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor"):
            return httpx.Response(429, headers={"retry-after": "60"})
        following = f"/wiki{ENG_PAGES}?cursor=c2"
        first = [_page(1, "2026-09-25T10:00:00Z")]
        return httpx.Response(200, json={"results": first, "_links": {"next": following}})

    connector = _connector(Confluence({ENG_PAGES: pages}), spaces=["ENG"])
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(Capability.PAGES):
            read.append(item)

    assert [r.external_id for r in read] == ["1001"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED
    assert caught.value.diagnostic.retry_after == 60


async def test_confluence_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Confluence(), Capability.ISSUES)


async def test_pages_and_spaces_carry_the_link_to_open_them() -> None:
    """Confluence gives a path; the record keeps the whole link, on the site."""
    linked = {**_page(1, "2026-09-25T10:00:00.000Z"), "_links": {"webui": "/spaces/ENG/pages/1001"}}
    confluence = Confluence({ENG_PAGES: {"results": [linked], "_links": {}}})

    pages = await _stream(confluence, Capability.PAGES)

    assert pages[0].payload["web_url"] == "https://acme.atlassian.net/wiki/spaces/ENG/pages/1001"
    assert "web_url" not in (await _stream(Confluence(), Capability.SPACES))[0].payload
