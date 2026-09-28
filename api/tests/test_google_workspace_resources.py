"""What the Google Workspace connector reads for the sync engine (LEKA-346).

The same stand-in Google as test_google_workspace_connector.py. What
matters here: My Drive and each shared drive in scope, one at a time; each
file once; its text where one can be had — Google's own formats exported,
Office files read — and a file without text rather than a failed pass when
Drive keeps it; an incremental pass that Drive itself filters by date.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from leka.connectors import Capability, ConnectorError, DiagnosticCode, RawRecord
from leka.connectors.google_workspace import connector as workspace
from leka.connectors.office import WORD
from tests.test_google_workspace_connector import (
    DOC,
    ENGINEERING,
    SHEET,
    Google,
    _connector,
    drive_file,
    reason,
)
from tests.test_office_text import docx

SINCE = datetime(2026, 9, 20, 8, 30, tzinfo=UTC)


async def _stream(
    google: Google, capability: Capability, since: datetime | None = None, **config: object
) -> list[RawRecord]:
    connector = _connector(google, **config)
    return [r async for r in connector.iter_resources(capability, since=since)]


async def test_shared_drives_are_read_whole_those_in_scope_only() -> None:
    every = await _stream(Google(), Capability.DRIVES)
    some = await _stream(Google(), Capability.DRIVES, drives=["0ALegalDrive00"])

    assert [r.external_id for r in every] == ["0AEngineeringDrive", "0ALegalDrive00"]
    assert [r.external_id for r in some] == ["0ALegalDrive00"]


async def test_files_are_read_from_my_drive_then_each_shared_drive_each_once() -> None:
    google = Google()
    google.files[ENGINEERING["id"]].append(drive_file("mine"))  # also in My Drive's listing

    records = await _stream(google, Capability.FILES)

    assert [(r.external_id, r.container) for r in records] == [
        ("mine", "user"),
        ("design", "0AEngineeringDrive"),
    ]
    corpora = [dict(r.url.params) for r in google.requests("/files")]
    assert [c.get("corpora") for c in corpora] == ["user", "drive", "drive"]
    assert corpora[1]["driveId"] == "0AEngineeringDrive"
    assert "trashed = false" in corpora[0]["q"] and "folder" in corpora[0]["q"]
    assert "modifiedTime" not in corpora[0]["q"]


async def test_only_the_drives_in_scope_are_read() -> None:
    google = Google()

    records = await _stream(google, Capability.FILES, drives=["0AEngineeringDrive"])

    assert [r.external_id for r in records] == ["design"]


async def test_an_incremental_pass_asks_drive_for_what_changed_since() -> None:
    google = Google()

    await _stream(google, Capability.FILES, since=SINCE, drives=["user"])

    query = google.requests("/files")[0].url.params["q"]
    assert "modifiedTime > '2026-09-20T08:28:00'" in query  # less two minutes


async def test_google_s_own_formats_are_exported_as_text() -> None:
    google = Google()
    google.files = {"user": [drive_file("notes", DOC), drive_file("budget", SHEET)]}
    google.answers["/files/notes/export"] = httpx.Response(200, content=b"Q4 plan\nShip it")
    google.answers["/files/budget/export"] = httpx.Response(200, content=b"team,cost\napi,42\n")

    records = await _stream(google, Capability.FILES, drives=["user"])

    assert [r.payload["content"] for r in records] == ["Q4 plan\nShip it", "team,cost\napi,42\n"]
    asked = [r.url.params["mimeType"] for r in google.asked if r.url.path.endswith("/export")]
    assert asked == ["text/plain", "text/csv"]


async def test_an_office_file_is_downloaded_and_read() -> None:
    google = Google()
    google.files = {"user": [drive_file("spec", WORD, name="Spec.docx", size="2048")]}
    google.contents["spec"] = docx("Spec", "Every call is a GET.")

    records = await _stream(google, Capability.FILES, drives=["user"])

    assert records[0].payload["content"] == "Spec\nEvery call is a GET."
    assert records[0].payload["content_truncated"] is False
    download = next(r for r in google.asked if r.url.path.endswith("/files/spec"))
    assert download.url.params["alt"] == "media"


@pytest.mark.parametrize(
    "found",
    [
        drive_file("scan", "application/pdf", name="scan.pdf"),
        drive_file("huge", WORD, name="huge.docx", size=str(50 * 1024 * 1024)),
    ],
)
async def test_a_file_whose_text_is_not_read_comes_without_it(found: dict[str, object]) -> None:
    google = Google()
    google.files = {"user": [found]}

    records = await _stream(google, Capability.FILES, drives=["user"])

    assert records[0].payload["content"] is None
    assert not [r for r in google.asked if "/files/" in r.url.path]  # nothing downloaded


async def test_a_file_drive_will_not_hand_over_is_a_file_without_text() -> None:
    google = Google()
    google.files = {"user": [drive_file("big", DOC)]}
    google.answers["/files/big/export"] = reason(403, "exportSizeLimitExceeded")

    records = await _stream(google, Capability.FILES, drives=["user"])

    assert records[0].payload["content"] is None


async def test_a_quota_hit_while_reading_a_text_stops_the_pass() -> None:
    google = Google()
    google.files = {"user": [drive_file("a", DOC), drive_file("b", DOC)]}
    google.answers["/files/a/export"] = httpx.Response(200, content=b"A")
    google.answers["/files/b/export"] = reason(403, "userRateLimitExceeded")
    connector = _connector(google, drives=["user"])
    read: list[RawRecord] = []

    with pytest.raises(ConnectorError) as caught:
        async for item in connector.iter_resources(Capability.FILES):
            read.append(item)

    assert [r.external_id for r in read] == ["a"]
    assert caught.value.diagnostic.code is DiagnosticCode.RATE_LIMITED


async def test_files_are_followed_across_drive_s_page_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace, "FILE_PAGE", 2)
    google = Google()
    google.files = {"user": [drive_file(f"f{n}", "application/pdf") for n in range(5)]}

    records = await _stream(google, Capability.FILES, drives=["user"])

    assert [r.external_id for r in records] == ["f0", "f1", "f2", "f3", "f4"]
    assert [r.url.params.get("pageToken") for r in google.requests("/files")] == [None, "2", "4"]


async def test_google_workspace_reads_only_what_it_declares() -> None:
    with pytest.raises(ValueError, match="does not read"):
        await _stream(Google(), Capability.PAGES)
