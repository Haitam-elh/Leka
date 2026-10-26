"""The architect on a Confluence space, on LEKA (2026-10-25): « Arborescence »
and the dossier.

Acme's Confluence synced two spaces — ARCHI, four pages three deep, and
OTHER; the model is a scripted Gemini.

What these protect:
- « Arborescence »: each space a source synced, its pages parent and child,
  how many, how deep — never their text; another workspace's, a 404.
- The architect asked on a space: its synced pages, read by the core's
  steps (leka.architect) — each shown with where it sits —, its dossier
  delivered in Markdown, PDF, Word and JSON, each section citing its pages
  by their Confluence link; held to its source, said in the audit trail's
  journal; on a page, that page and what is under it only.
- A space nothing synced: refused, said why — no model asked.
"""

# ruff: noqa: F811 — fixtures imported to be requested by name.
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text

from leka.capabilities import sync_catalogue
from leka.db import session_factory, workspace_scope
from leka.ingestion.models import ExtractedRecordRow, ExtractionStatus, SourceRecord
from leka.platform import LocalObjectStore
from tests.conftest import FakeIdentity
from tests.test_agent_runs_api import (
    ARCHITECT,
    Script,
    _detail,
    _run,
    gemini,
    leka_gemini,
    queued,
    store,
)
from tests.test_resolution_job import _source
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401

_ = (leka_gemini, queued, store)  # fixtures, requested by name
API = "/api/v1"
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
SITE = "https://acme.atlassian.net/wiki/spaces"
PAGES = [
    ("ARCHI", "100", "Accueil", None, "Le SI de facturation de bout en bout."),
    ("ARCHI", "101", "Applications", "100", "Billing API appelle Ledger pour chaque facture."),
    ("ARCHI", "102", "Billing API", "101", "Composant applicatif. Expose /invoices."),
    ("ARCHI", "103", "Infrastructure", "100", "Billing API tourne sur Kubernetes."),
    ("OTHER", "200", "Ailleurs", None, "Une autre équipe."),
]


async def _confluence(acme: dict[str, uuid.UUID]) -> uuid.UUID:
    """A Confluence source of Acme's, as a sync and extraction left it."""
    source = await _source(acme["acme"], "Confluence de l'organisation")
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            await session.execute(
                text("UPDATE sources SET kind = 'confluence', status = 'active' WHERE id = :s"),
                {"s": source},
            )

            async def keep(
                kind: str, external_id: str, container: str | None, result: dict[str, Any]
            ) -> None:
                checksum = hashlib.sha256(f"{kind}{external_id}".encode()).hexdigest()
                record = SourceRecord(
                    workspace_id=acme["acme"],
                    id=uuid.uuid4(),
                    source_id=source,
                    kind=kind,
                    external_id=external_id,
                    container=container,
                    checksum=checksum,
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                )
                session.add(record)
                # No relationship between the two rows: the record first.
                await session.flush()
                session.add(
                    ExtractedRecordRow(
                        workspace_id=acme["acme"],
                        id=uuid.uuid4(),
                        source_id=source,
                        source_record_id=record.id,
                        kind=kind,
                        status=ExtractionStatus.EXTRACTED,
                        extractor=f"confluence.{kind}",
                        extractor_version=1,
                        checksum=checksum,
                        result=result,
                        extracted_at=NOW,
                    )
                )

            for key, name in (("ARCHI", "Architecture"), ("OTHER", "Autre")):
                await keep("spaces", f"s-{key}", key, {"title": name, "metadata": {"key": key}})
            for space, pid, title, parent, body in PAGES:
                await keep(
                    "pages",
                    pid,
                    space,
                    {
                        "title": title,
                        "url": f"{SITE}/{space}/pages/{pid}",
                        "updated_at": "2026-10-20T10:00:00+00:00",
                        "content": [{"role": "body", "format": "text", "text": body}],
                        "references": (
                            [{"role": "parent", "kind": "document", "external_id": parent}]
                            if parent
                            else []
                        ),
                    },
                )
            await session.commit()
    return source


def _dossier(ids: list[str]) -> str:
    """What the model answers: a dossier citing these pages."""
    return json.dumps(
        {
            "title": "Dossier d'architecture — Facturation",
            "sections": [
                {"key": "synthese", "summary": "La facturation.", "pages": [ids[0]]},
                {"key": "application", "summary": "Billing API et Ledger.", "pages": ids[1:]},
                {"key": "technologie", "summary": "Kubernetes.", "pages": ids[-1:]},
            ],
            "elements": [
                {
                    "id": "b",
                    "layer": "application",
                    "type": "Composant applicatif",
                    "name": "Billing API",
                    "pages": ids[1:],
                },
                {
                    "id": "l",
                    "layer": "application",
                    "type": "Composant applicatif",
                    "name": "Ledger",
                    "pages": ids[1:2],
                },
            ],
            "relations": [
                {
                    "source": "b",
                    "target": "l",
                    "type": "Flux",
                    "label": "factures",
                    "pages": ids[1:2],
                }
            ],
            "points": ["Qui exploite Ledger ?"],
        }
    )


async def test_its_tree_as_synced_never_its_text(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    source = await _confluence(acme)
    _as(identity, acme, "member")
    found = await client.get(f"{API}/sources/{source}/tree")
    assert found.status_code == 200, found.text
    spaces = {s["key"]: s for s in found.json()["spaces"]}
    archi = spaces["ARCHI"]
    assert (archi["name"], archi["pages"], archi["depth"]) == ("Architecture", 4, 3)
    [home] = archi["nodes"]
    assert home["title"] == "Accueil" and home["url"] == f"{SITE}/ARCHI/pages/100"
    assert [c["title"] for c in home["children"]] == ["Applications", "Infrastructure"]
    assert [c["title"] for c in home["children"][0]["children"]] == ["Billing API"]
    assert spaces["OTHER"]["pages"] == 1
    assert "Kubernetes" not in found.text
    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/sources/{source}/tree")).status_code == 404


async def test_the_architect_on_a_space_its_dossier_its_evidence(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    queued: list[uuid.UUID],
    store: LocalObjectStore,
) -> None:
    await sync_catalogue()
    await _confluence(acme)
    script = leka_gemini(gemini(_dossier(["100", "102", "103"])))
    _as(identity, acme, "admin")
    asked = {"parcours": "Facturation", "perimetre": "Espace ARCHI", "espace": "ARCHI"}
    started = await client.post(f"{API}/agent-runs", json={"key": ARCHITECT, "inputs": asked})
    assert started.status_code == 202, started.text
    run = started.json()
    assert await _run(acme, run["id"]) == {"status": "succeeded"}

    # The core's steps: every page of the space, each where it sits.
    shown = json.dumps(script.asked[0], ensure_ascii=False)
    assert "[102] Accueil › Applications › Billing API" in shown  # noqa: RUF001
    assert "Sujet à documenter en priorité : Facturation" in shown
    assert "Une autre équipe" not in shown

    done = await _detail(client, run["id"])
    assert done["status"] == "succeeded"
    kinds = [e["kind"] for e in done["events"]]
    assert "dossier_pages" in kinds and "dossier" in kinds
    files = {f["format"]: f for f in done["deliverables"]}
    assert set(files) == {"md", "pdf", "docx", "json"}
    assert files["pdf"]["name"] == "Dossier d'architecture - Architecture.pdf"
    said = await client.get(f"{API}/agent-runs/{run['id']}/deliverables/md")
    assert said.status_code == 200
    assert said.headers["content-type"].startswith("text/markdown")
    assert "## 3. Couche application" in said.text
    assert f"[Billing API]({SITE}/ARCHI/pages/102)" in said.text
    assert "1. Qui exploite Ledger ?" in said.text
    drawn = await client.get(f"{API}/agent-runs/{run['id']}/deliverables/pdf")
    assert drawn.content.startswith(b"%PDF")
    word = await client.get(f"{API}/agent-runs/{run['id']}/deliverables/docx")
    assert word.content.startswith(b"PK")
    # Said in the journal: on which space, held to which source.
    journal = (await client.get(f"{API}/agent-runs/journal")).json()
    entry = next(j for j in journal if j["id"] == run["id"])
    assert (entry["scope"], entry["sources"]) == ("ARCHI", ["Confluence de l'organisation"])


async def test_on_a_page_that_page_and_what_is_under_it_only(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    queued: list[uuid.UUID],
    store: LocalObjectStore,
) -> None:
    await sync_catalogue()
    await _confluence(acme)
    script = leka_gemini(gemini(_dossier(["101", "102"])))
    _as(identity, acme, "admin")
    asked = {
        "parcours": "Applications",
        "perimetre": "Espace ARCHI",
        "espace": "ARCHI",
        "page_racine": "101",
    }
    run = (await client.post(f"{API}/agent-runs", json={"key": ARCHITECT, "inputs": asked})).json()
    assert await _run(acme, run["id"]) == {"status": "succeeded"}
    shown = json.dumps(script.asked[0], ensure_ascii=False)
    assert "[101]" in shown and "[102]" in shown
    assert "[100]" not in shown and "[103]" not in shown
    assert "à partir de la page « Applications »" in shown


async def test_a_space_nothing_synced_refused_no_model_asked(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    leka_gemini: Callable[..., Script],
    queued: list[uuid.UUID],
    store: LocalObjectStore,
) -> None:
    await sync_catalogue()
    await _confluence(acme)
    script = leka_gemini()
    _as(identity, acme, "admin")
    asked = {"parcours": "X", "perimetre": "Y", "espace": "NOPE"}
    run = (await client.post(f"{API}/agent-runs", json={"key": ARCHITECT, "inputs": asked})).json()
    assert await _run(acme, run["id"]) == {"status": "failed", "error": "unavailable"}
    done = await _detail(client, run["id"])
    assert done["error"] == "unavailable"
    assert script.asked == []
