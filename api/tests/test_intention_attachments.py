"""Files attached to an intention — the paperclip of the home's bar.

What these protect:
- A file LEKA reads is uploaded, kept in object storage — its size and
  checksum measured by the store, its name kept tidy — and its id answered.
- Refused, nothing kept, with the code the screen says: a type LEKA does not
  read (415), bytes that are not what they say (415), too large (413),
  empty (422).
- Asked with its ids, the intention is linked to its files; its page lists
  them; whoever reads the intention reads their bytes.
- An id that is not a file of this person's, waiting: the intention is
  refused (422) and nothing is kept — never said attached.
- Removed before asking: gone, bytes and all. Once attached, or someone
  else's: not removable.
- Another workspace never reads them.
- Uploaded and never asked with: purged after a day; attached ones kept.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from leka.api import intentions as intentions_api
from leka.db import session_factory, system_scope, workspace_scope
from leka.intentions import Intention, IntentionAttachment
from leka.intentions import attachments as attachments_module
from leka.intentions.attachments import purge
from leka.platform import storage
from leka.platform.storage import LocalObjectStore
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import leka_gemini  # noqa: F401 — a fixture
from tests.test_context_engine import model
from tests.test_intention_analysis_api import queued  # noqa: F401 — a fixture
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/intentions"
ASKED = "Qui est responsable de Billing API ?"
NOTES = "Relevé des lenteurs de paiement — été 2026\n".encode() * 40
PDF = b"%PDF-1.7\n" + b"0" * 2048


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalObjectStore:
    kept = LocalObjectStore(tmp_path)
    monkeypatch.setattr(storage, "_store", kept)
    return kept


async def _upload(
    client: AsyncClient,
    body: bytes,
    *,
    name: str = "notes.txt",
    content_type: str = "text/plain",
) -> httpx.Response:
    return await client.post(
        f"{API}/attachments",
        content=body,
        headers={"Content-Type": content_type, "X-File-Name": quote(name)},
    )


async def _uploaded(client: AsyncClient, body: bytes = NOTES, **kwargs: Any) -> dict[str, Any]:
    response = await _upload(client, body, **kwargs)
    assert response.status_code == 201, response.text
    kept: dict[str, Any] = response.json()
    return kept


def _refusal(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["details"][0]["message"]


async def _rows(workspace_id: uuid.UUID) -> list[IntentionAttachment]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            return list((await session.scalars(select(IntentionAttachment))).all())


async def _kept_keys(store: LocalObjectStore, workspace_id: uuid.UUID) -> list[str]:
    return [key async for key in store.iter_prefix(f"{workspace_id}/intention-attachments/")]


async def test_a_file_is_kept_measured_and_answered_with_its_id(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    store: LocalObjectStore,
) -> None:
    kept = await _uploaded(
        client, name="../relevé été.txt", content_type="text/plain; charset=utf-8"
    )
    # Its name without a path; its type without parameters; its size measured.
    assert (kept["name"], kept["content_type"], kept["size_bytes"]) == (
        "relevé été.txt",
        "text/plain",
        len(NOTES),
    )
    [row] = await _rows(acme["acme"])
    assert str(row.id) == kept["id"]
    assert row.intention_id is None
    assert row.storage_key.startswith(f"{acme['acme']}/intention-attachments/")
    assert len(row.checksum_sha256) == 64
    assert await store.exists(row.storage_key)
    pdf = await _uploaded(client, PDF, name="audit.pdf", content_type="application/pdf")
    assert pdf["content_type"] == "application/pdf"


async def test_refused_files_are_said_why_and_nothing_is_kept(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    store: LocalObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _refusal(
        await _upload(client, b"GIF89a....", name="a.gif", content_type="image/gif")
    ) == (
        415,
        "file_type_refused",
    )
    # Says it is a PDF; its bytes are text.
    assert _refusal(
        await _upload(client, b"hello", name="fake.pdf", content_type="application/pdf")
    ) == (415, "file_content_mismatch")
    # A text with a NUL in it is not text.
    assert _refusal(await _upload(client, b"a\x00b", name="bin.txt")) == (
        415,
        "file_content_mismatch",
    )
    assert _refusal(await _upload(client, b"", name="empty.txt")) == (422, "file_empty")
    # Too large: said before the bytes come when the length says it, else as
    # they come — the store keeping nothing either way.
    monkeypatch.setattr(attachments_module, "MAX_BYTES", 1000)
    assert _refusal(await _upload(client, NOTES)) == (413, "file_too_large")
    monkeypatch.setattr(intentions_api, "MAX_BYTES", 1000)
    assert _refusal(await _upload(client, NOTES)) == (413, "file_too_large")
    assert await _rows(acme["acme"]) == []
    assert await _kept_keys(store, acme["acme"]) == []


async def test_asked_with_its_files_the_intention_is_linked_to_them_and_they_are_read(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    store: LocalObjectStore,
) -> None:
    notes = await _uploaded(client, name="notes.txt")
    audit = await _uploaded(client, PDF, name="audit.pdf", content_type="application/pdf")
    response = await client.post(
        API, json={"text": ASKED, "attachments": [notes["id"], audit["id"]]}
    )
    assert response.status_code == 201, response.text
    intention = response.json()["intention"]
    assert [a["name"] for a in intention["attachments"]] == ["notes.txt", "audit.pdf"]
    # Its page says them too.
    page = (await client.get(f"{API}/{intention['id']}")).json()
    assert [a["id"] for a in page["attachments"]] == [notes["id"], audit["id"]]
    created = next(
        e
        for e in (await client.get(f"{API}/{intention['id']}/history")).json()
        if e["kind"] == "created"
    )
    assert created["detail"]["attachments"] == ["notes.txt", "audit.pdf"]
    # Whoever reads it reads their bytes.
    read = await client.get(f"{API}/{intention['id']}/attachments/{audit['id']}")
    assert read.status_code == 200
    assert read.content == PDF
    assert read.headers["content-type"] == "application/pdf"
    assert "audit.pdf" in read.headers["content-disposition"]
    assert read.headers["x-content-type-options"] == "nosniff"
    # Not a file of this intention: 404.
    other = await client.get(f"{API}/{intention['id']}/attachments/{uuid.uuid4()}")
    assert other.status_code == 404


async def test_an_unknown_file_refuses_the_intention_and_nothing_is_kept(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    store: LocalObjectStore,
) -> None:
    async def intentions() -> int:
        with workspace_scope(acme["acme"]):
            async with session_factory() as session:
                return int(await session.scalar(select(func.count()).select_from(Intention)) or 0)

    before = await intentions()
    refused = await client.post(API, json={"text": ASKED, "attachments": [str(uuid.uuid4())]})
    assert _refusal(refused) == (422, "attachment_unknown")
    # Someone else's file: not this person's to attach.
    _as(identity, acme, "admin")
    theirs = await _uploaded(client, name="admin.txt")
    _as(identity, acme, "member")
    mine = await _uploaded(client, name="mine.txt")
    refused = await client.post(
        API, json={"text": ASKED, "attachments": [mine["id"], theirs["id"]]}
    )
    assert _refusal(refused) == (422, "attachment_unknown")
    assert await intentions() == before
    # Nothing was said attached: both still waiting.
    assert {r.intention_id for r in await _rows(acme["acme"])} == {None}


async def test_removed_before_asking_and_not_once_attached_or_someone_elses(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    store: LocalObjectStore,
) -> None:
    waiting = await _uploaded(client)
    [row] = await _rows(acme["acme"])
    removed = await client.delete(f"{API}/attachments/{waiting['id']}")
    assert removed.status_code == 204
    assert await _rows(acme["acme"]) == []
    assert not await store.exists(row.storage_key)
    assert (await client.delete(f"{API}/attachments/{waiting['id']}")).status_code == 404

    attached = await _uploaded(client)
    created = await client.post(API, json={"text": ASKED, "attachments": [attached["id"]]})
    assert created.status_code == 201, created.text
    assert (await client.delete(f"{API}/attachments/{attached['id']}")).status_code == 404

    other = await _uploaded(client, name="other.txt")
    _as(identity, acme, "admin")
    assert (await client.delete(f"{API}/attachments/{other['id']}")).status_code == 404


async def test_another_workspace_never_reads_them(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    store: LocalObjectStore,
) -> None:
    kept = await _uploaded(client)
    created = await client.post(API, json={"text": ASKED, "attachments": [kept["id"]]})
    intention = created.json()["intention"]
    _as(identity, acme, "other_admin")
    read = await client.get(f"{API}/{intention['id']}/attachments/{kept['id']}")
    assert read.status_code == 404
    assert (await client.delete(f"{API}/attachments/{kept['id']}")).status_code == 404


async def test_files_never_asked_with_are_purged_after_a_day(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    store: LocalObjectStore,
) -> None:
    abandoned = await _uploaded(client, name="abandoned.txt")
    attached = await _uploaded(client, name="attached.txt")
    recent = await _uploaded(client, name="recent.txt")
    created = await client.post(API, json={"text": ASKED, "attachments": [attached["id"]]})
    assert created.status_code == 201, created.text
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text("UPDATE intention_attachments SET created_at = :at WHERE id = ANY(:ids)"),
                {
                    "at": datetime.now(UTC) - timedelta(days=2),
                    "ids": [uuid.UUID(abandoned["id"]), uuid.UUID(attached["id"])],
                },
            )
            await session.commit()
    [gone] = [r for r in await _rows(acme["acme"]) if str(r.id) == abandoned["id"]]
    assert await purge() == 1
    assert {r.name for r in await _rows(acme["acme"])} == {"attached.txt", "recent.txt"}
    assert not await store.exists(gone.storage_key)
    _ = recent


def _pdf_saying(*lines: str) -> bytes:
    import io

    from reportlab.pdfgen import canvas

    out = io.BytesIO()
    page = canvas.Canvas(out)
    for number, line in enumerate(lines):
        page.drawString(72, 760 - 20 * number, line)
    page.showPage()
    page.save()
    return out.getvalue()


async def test_its_files_are_read_once_and_given_to_the_agent_that_works_for_it(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    store: LocalObjectStore,
    leka_gemini: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 2026-10-28, Haitam: « que le LLM et LEKA lisent bien le fichier ».
    # Before, a file joined to an intention was kept and shown, read by no
    # model.
    import json

    from leka.capabilities import execute_run, sync_catalogue
    from leka.capabilities import runs as runs_module
    from tests.test_agent_runs_api import gemini

    async def nothing(*_: Any) -> bool:
        return True

    monkeypatch.setattr(runs_module, "queue_redraw", nothing)
    incident = await _uploaded(
        client,
        _pdf_saying("Rapport d'incident", "Le paiement échoue avec l'erreur E-4021."),
        name="incident.pdf",
        content_type="application/pdf",
    )
    notes = await _uploaded(client, name="notes.txt")
    asked = await client.post(
        API, json={"text": ASKED, "attachments": [incident["id"], notes["id"]]}
    )
    assert asked.status_code == 201, asked.text
    intention = asked.json()["intention"]
    await sync_catalogue()
    script = leka_gemini(gemini("# Diagnostic\n\nL'erreur E-4021 vient du paiement."))
    started = await client.post(
        "/api/v1/agent-runs",
        json={
            "key": "debug-assistant",
            "inputs": {"symptome": "Le paiement échoue"},
            "intention_id": intention["id"],
        },
    )
    assert started.status_code == 202, started.text
    run_id = uuid.UUID(started.json()["id"])
    assert (await execute_run(acme["acme"], run_id))["status"] == "succeeded"
    material = json.loads(script.asked[0]["contents"][-1]["parts"][0]["text"])
    pdf, text = material["attachments"]
    assert (pdf["id"], pdf["name"], pdf["read"]) == ("attachment:1", "incident.pdf", "pdf")
    assert "E-4021" in pdf["text"]
    assert text["read"] == "text" and "Relevé des lenteurs de paiement" in text["text"]
    assert "read by LEKA" in material["attachments_note"]
    # Read once, kept with the file for every model after.
    kept = {row.name: (row.read_as, row.text or "") for row in await _rows(acme["acme"])}
    assert kept["incident.pdf"][0] == "pdf" and "E-4021" in kept["incident.pdf"][1]
    # The run says it was given them.
    run = (await client.get(f"/api/v1/agent-runs/{run_id}")).json()
    [given] = [e["detail"] for e in run["events"] if e["kind"] == "attachments"]
    assert given["files"] == [
        {"name": "incident.pdf", "read": "pdf"},
        {"name": "notes.txt", "read": "text"},
    ]


def test_an_analysis_is_given_the_files_its_question_came_with() -> None:
    from leka.capabilities import ContextItem, ContextPack
    from leka.intentions.attachments import with_attached
    from leka.intentions.writing import with_files

    attached = [{"id": "attachment:1", "name": "incident.pdf", "read": "pdf", "text": "E-4021"}]
    said = with_files({"question": "Pourquoi ?"}, attached)
    assert said["attachments"] == attached and "attachment:N" in said["attachments_note"]
    assert with_files({"question": "Pourquoi ?"}, []) == {"question": "Pourquoi ?"}
    pack = with_attached(
        ContextPack((ContextItem("entity:1", "service", "Billing API"),)), attached
    )
    # Its files first, by their id: what the analysis may cite.
    assert [item.id for item in pack.items] == ["attachment:1", "entity:1"]
