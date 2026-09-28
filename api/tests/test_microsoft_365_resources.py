"""What the Microsoft 365 connector reads for the sync engine (LEKA-346).

The same stand-in Microsoft as test_microsoft_365_connector.py. What
matters here: the drives in scope and nothing else; files through Graph's
delta, from a time on an incremental pass; folders, deleted items and
packages left out; each file once; its text from the link Graph gives —
followed to SharePoint only, without LEKA's token.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from leka.connectors.office import WORD
from tests.test_microsoft_365_connector import (
    DOCS,
    HANDBOOK,
    NORA_DRIVE,
    Microsoft,
    _connector,
    graph_error,
)
from tests.test_office_text import docx

SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    microsoft: Microsoft, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(microsoft, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


def item(item_id: str, **more: Any) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": f"{item_id}.bin",
        "file": {"mimeType": "application/octet-stream"},
        "size": 100,
        "lastModifiedDateTime": "2026-09-21T12:05:00Z",
        **more,
    }


async def test_every_drive_is_read_whole_libraries_and_onedrives() -> None:
    records = await _stream(Microsoft(), Capability.DRIVES)

    assert [r.external_id for r in records] == [DOCS, HANDBOOK, NORA_DRIVE]


async def test_only_the_drives_in_scope_are_read() -> None:
    microsoft = Microsoft()

    records = await _stream(microsoft, Capability.DRIVES, drives=[NORA_DRIVE])

    assert [r.external_id for r in records] == [NORA_DRIVE]
    assert not microsoft.requests("/sites")


async def test_files_come_through_delta_folders_and_deleted_ones_left_out() -> None:
    microsoft = Microsoft()
    microsoft.items[DOCS] = [
        {"id": "root", "root": {}, "folder": {}},
        item("folder-1", folder={"childCount": 2}),
        item("gone", deleted={"state": "deleted"}),
        item("notebook", package={"type": "oneNote"}),
        item("report"),
        item("report"),  # delta may give an item twice
    ]

    records = await _stream(microsoft, Capability.FILES, drives=[DOCS])

    assert [(r.external_id, r.container) for r in records] == [("report", DOCS)]
    assert records[0].updated_at == datetime(2026, 9, 21, 12, 5, tzinfo=UTC)
    params = microsoft.requests(f"/drives/{DOCS}/root/delta")[0].url.params
    assert "token" not in params


async def test_an_incremental_pass_asks_delta_from_a_time() -> None:
    microsoft = Microsoft()

    await _stream(microsoft, Capability.FILES, since=SINCE, drives=[DOCS])

    params = microsoft.requests(f"/drives/{DOCS}/root/delta")[0].url.params
    assert params["token"] == "2026-09-20T08:28:00Z"  # less two minutes


async def test_delta_is_followed_across_its_next_links() -> None:
    first = {
        "value": [item("a")],
        "@odata.nextLink": f"https://graph.microsoft.com/v1.0/drives/{DOCS}/root/delta?token=p2",
    }

    def pages(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("token") == "p2":
            return httpx.Response(200, json={"value": [item("b")], "@odata.deltaLink": "x"})
        return httpx.Response(200, json=first)

    microsoft = Microsoft({f"/drives/{DOCS}/root/delta": pages})

    records = await _stream(microsoft, Capability.FILES, drives=[DOCS])

    assert [r.external_id for r in records] == ["a", "b"]


async def test_a_next_link_to_another_host_is_refused() -> None:
    elsewhere = {"value": [item("a")], "@odata.nextLink": "https://evil.test/steal"}
    microsoft = Microsoft({f"/drives/{DOCS}/root/delta": elsewhere})

    with pytest.raises(ConnectorError) as caught:
        await _stream(microsoft, Capability.FILES, drives=[DOCS])

    assert caught.value.diagnostic.code is DiagnosticCode.PROVIDER_ERROR


async def test_a_word_file_is_read_from_sharepoint_without_leka_s_token() -> None:
    microsoft = Microsoft()
    microsoft.items[DOCS] = [item("spec", name="Spec.docx", file={"mimeType": WORD})]
    microsoft.downloads["spec"] = docx("Spec", "Every call is a GET.")

    records = await _stream(microsoft, Capability.FILES, drives=[DOCS])

    assert records[0].payload["content"] == "Spec\nEvery call is a GET."
    # The stand-in SharePoint fails on an Authorization header: none was sent.
    assert any(r.url.host == "acme.sharepoint.com" for r in microsoft.asked)


async def test_a_link_off_sharepoint_is_never_followed() -> None:
    microsoft = Microsoft()
    microsoft.items[DOCS] = [item("spec", name="Spec.docx")]
    elsewhere = httpx.Response(302, headers={"location": "https://evil.test/x?UniqueId=spec"})
    microsoft.answers[f"/drives/{DOCS}/items/spec/content"] = elsewhere

    records = await _stream(microsoft, Capability.FILES, drives=[DOCS])

    assert records[0].payload["content"] is None
    assert all(r.url.host != "evil.test" for r in microsoft.asked)


async def test_content_graph_gives_itself_is_read_too() -> None:
    microsoft = Microsoft()
    microsoft.items[DOCS] = [item("notes", name="notes.md")]
    microsoft.answers[f"/drives/{DOCS}/items/notes/content"] = httpx.Response(
        200, content=b"# Notes"
    )

    records = await _stream(microsoft, Capability.FILES, drives=[DOCS])

    assert records[0].payload["content"] == "# Notes"


@pytest.mark.parametrize(
    "found",
    [item("photo", name="photo.png"), item("big", name="big.docx", size=50 * 1024 * 1024)],
)
async def test_a_file_whose_text_is_not_read_comes_without_it(found: dict[str, Any]) -> None:
    microsoft = Microsoft()
    microsoft.items[DOCS] = [found]

    records = await _stream(microsoft, Capability.FILES, drives=[DOCS])

    assert records[0].payload["content"] is None
    assert not [r for r in microsoft.asked if r.url.path.endswith("/content")]


async def test_a_file_graph_will_not_hand_over_is_a_file_without_text() -> None:
    microsoft = Microsoft()
    microsoft.items[DOCS] = [item("locked", name="locked.docx")]
    microsoft.answers[f"/drives/{DOCS}/items/locked/content"] = graph_error(403, "accessDenied")

    records = await _stream(microsoft, Capability.FILES, drives=[DOCS])

    assert records[0].payload["content"] is None


async def test_microsoft_365_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Microsoft(), Capability.PAGES)
