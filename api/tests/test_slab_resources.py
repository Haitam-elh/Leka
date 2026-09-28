"""What the Slab connector reads for the sync engine (LEKA-346).

The same stand-in Slab as test_slab_connector.py. What matters here: the
topics in scope and nothing else, each post with its content, asked one by
one, and an incremental pass that asks only for the posts updated since.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from tests.test_slab_connector import Slab, _connector, data, post, refused

SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    slab: Slab, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(slab, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


async def test_every_topic_is_read_whole() -> None:
    records = await _stream(Slab(), Capability.SPACES)

    assert [r.external_id for r in records] == ["t-eng", "t-people"]


async def test_only_the_topics_in_scope_are_read() -> None:
    records = await _stream(Slab(), Capability.SPACES, topics=["t-people"])

    assert [r.external_id for r in records] == ["t-people"]


async def test_every_post_is_read_with_its_content() -> None:
    slab = Slab()

    records = await _stream(slab, Capability.PAGES)

    assert [(r.external_id, r.container) for r in records] == [("p1", None), ("p2", None)]
    assert records[0].payload["content"] == '[{"insert": "Body of Post 1\\n"}]'
    assert records[0].updated_at == datetime(2026, 9, 21, 12, 5, tzinfo=UTC)
    assert slab.variables("Post") == [{"id": "p1"}, {"id": "p2"}]


async def test_only_the_posts_of_the_topics_in_scope_are_read() -> None:
    slab = Slab()

    records = await _stream(slab, Capability.PAGES, topics=["t-people"])

    assert [(r.external_id, r.container) for r in records] == [("p2", "t-people")]
    assert slab.variables("Post") == [{"id": "p2"}]


async def test_an_incremental_pass_asks_only_for_the_posts_updated_since() -> None:
    slab = Slab()
    slab.posts = [post(1, "2026-09-10T00:00:00Z"), post(2, "2026-09-20T08:29:00Z"), post(3)]

    records = await _stream(slab, Capability.PAGES, since=SINCE)

    assert [r.external_id for r in records] == ["p2", "p3"]
    assert slab.variables("Post") == [{"id": "p2"}, {"id": "p3"}]


async def test_a_post_gone_since_the_listing_is_left_for_the_sweep() -> None:
    slab = Slab({"Posts": data({"organization": {"posts": [post(1), post(9)]}})})

    records = await _stream(slab, Capability.PAGES)

    assert [r.external_id for r in records] == ["p1"]


async def test_a_throttled_pass_keeps_what_was_read() -> None:
    slab = Slab()

    def second_refused(variables: dict[str, Any]) -> httpx.Response:
        if variables["id"] == "p2":
            return refused("Rate limit exceeded")
        return slab._post(variables)

    slab.answers["Post"] = second_refused
    connector = _connector(slab)
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(Capability.PAGES):
            read.append(item)

    assert [r.external_id for r in read] == ["p1"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED


async def test_slab_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Slab(), Capability.ISSUES)
