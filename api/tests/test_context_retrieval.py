"""Context retrieval, end to end (LEKA-371): representative requests find
their evidence; a retriever that fails degrades the context, never stops it.

Acme's operations, as the knowledge graph's operations tests build them —
GitHub's billing-api repository and its deployments, PagerDuty's Billing
API with its incident Q1 and a change, Jira's change and incident, a
catalogue's Billing platform and Checkout, a business system's Invoicing
— and a Confluence page whose body only says what it is about: a recovery
procedure for payments. Through the whole pipeline: the page's text as
extraction reads it, normalisation, resolution, enrichment, the model.

What these protect: a request in the asker's words, French, with no root,
finds what it is about and what happened around it in its window; a
request between two roots finds what is on the way; the records' own text
finds the page its title does not name; each thing found says by which
retrievers, at what rank, how relevant; the retrievers asked, and only
them; a retriever that errs, or takes too long, is undone alone — the
context is made from the others, the version says which failed and why,
and the log says so; every retriever failing makes a failed version that
says why, and the next refresh recovers; a request with nothing to start
from is refused.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import sys
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.connectors import Capability, SourceKind
from leka.context import retrieval
from leka.context.strategies import EVERY_ONE_FAILED
from leka.db import session_factory, workspace_scope
from leka.ingestion import ContentRepository
from leka.knowledge import GraphService
from tests.conftest import FakeIdentity
from tests.test_application_landscape import _record, _store
from tests.test_extraction import _extract
from tests.test_operations_landscape import (
    BILLING,
    CHECKOUT,
    FLAG,
    INCIDENT,
    INVOICING,
    PLATFORM,
    RELEASE,
    SITE,
    _operations,
)
from tests.test_relationships_engine import _build
from tests.test_resolution_job import _source
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/context"
# The window of Acme's operations: the week before 29 September.
UNTIL = "2026-09-29T00:00:00Z"
PAGE_BODY = (
    "<p>Procédure de reprise des paiements : quand les factures ne partent plus, "
    "relancer le worker puis vérifier la file d'envoi.</p>"
)


def _page() -> dict[str, Any]:
    return {
        "id": "1001",
        "title": "Notes d'astreinte ENG-7",
        "spaceId": "98304",
        "authorId": "u-sara",
        "version": {"number": 2, "createdAt": "2026-09-20T10:00:00Z", "authorId": "u-sara"},
        "body": {"storage": {"value": PAGE_BODY}},
        "web_url": f"https://{SITE}/wiki/spaces/ENG/pages/1001/Notes",
    }


async def _company(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    """Acme's operations, and a Confluence page whose text is extracted as
    the pipeline extracts it: the model's ids, by key — the page's as PAGE."""
    await _operations(workspace)
    confluence = await _source(workspace, "Confluence")
    page = _record(
        SourceKind.CONFLUENCE, Capability.PAGES, _page(), external_id="1001", container="ENG"
    )
    await _store(workspace, confluence, page, external_id="1001")
    read = _extract(
        SourceKind.CONFLUENCE, Capability.PAGES, _page(), external_id="1001", container="ENG"
    )
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE extracted_records x SET result = CAST(:result AS jsonb) "
                    "FROM source_records s WHERE s.id = x.source_record_id "
                    "AND s.source_id = :source AND s.external_id = '1001'"
                ),
                {"result": read.model_dump_json(), "source": confluence},
            )
            await session.commit()
    ids = await _build(workspace)
    ids["PAGE"] = ids[page.entity.key]
    return ids


@pytest.fixture
async def company(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids = await _company(acme["acme"])
    _as(identity, acme, "member")
    return ids


async def _ask(client: AsyncClient, purpose: str, **body: Any) -> Any:
    response = await client.post(
        API,
        json={"title": purpose[:60], "purpose": purpose, "until": UNTIL, "window_days": 7, **body},
    )
    assert response.status_code == 201, response.text
    return response.json()


# What representative requests are about — the evidence they must find.
SARA = "person:github.com:sara"
CASES: list[tuple[str, str, dict[str, Any], list[str]]] = [
    (
        "why slow",
        "Pourquoi la facturation est lente ?",
        {},
        [BILLING, INCIDENT, RELEASE, FLAG],
    ),
    (
        "what changed",
        "Qu'est-ce qui a changé avant l'incident « Invoices fail to send » ?",
        {},
        [INCIDENT, FLAG, RELEASE, BILLING],
    ),
    ("where documented", "Où est la procédure de reprise des paiements ?", {}, ["PAGE"]),
    (
        "how tied",
        "Comment Checkout est-il relié à la facturation ?",
        {"roots": [CHECKOUT, INVOICING]},
        [BILLING, PLATFORM],
    ),
    ("who deployed", "Qui a déployé Billing API ?", {"depth": 2}, [RELEASE, SARA]),
]


def _body(company: dict[str, uuid.UUID], extra: dict[str, Any]) -> dict[str, Any]:
    roots = [str(company[key]) for key in extra.get("roots", [])]
    return {**extra, "roots": roots}


def _expected(company: dict[str, uuid.UUID], keys: list[str]) -> set[uuid.UUID]:
    return {company[key] for key in keys}


@pytest.mark.parametrize(("name", "purpose", "extra", "expected"), CASES, ids=[c[0] for c in CASES])
async def test_a_representative_request_finds_its_evidence(
    client: AsyncClient,
    company: dict[str, uuid.UUID],
    name: str,
    purpose: str,
    extra: dict[str, Any],
    expected: list[str],
) -> None:
    made = await _ask(client, purpose, **_body(company, extra))

    found = {uuid.UUID(e["ref_id"]): e for e in made["elements"] if e["kind"] == "entity"}
    assert _expected(company, expected) <= found.keys(), name
    for entity_id in _expected(company, expected):
        element = found[entity_id]
        assert element["reason"]["retrievers"] or element["reason"]["role"] == "root"
        assert 0 < element["relevance"] <= 1
    assert {run["status"] for run in made["retrieval"]} <= {"ok", "skipped"}
    assert made["strategy"] == {"name": "hybrid", "version": 1}


async def test_what_is_found_keeps_its_sources_its_relevance_and_how(
    client: AsyncClient, company: dict[str, uuid.UUID]
) -> None:
    made = await _ask(client, "Pourquoi la facturation est lente ?")

    incident = next(e for e in made["elements"] if e["ref_id"] == str(company[INCIDENT]))
    assert [s["name"] for s in incident["provenance"]["sources"]] == ["PagerDuty"]
    found_by = {m["retriever"]: m for m in incident["reason"]["retrievers"]}
    assert set(found_by) == {"graph", "timeline", "search"}
    # Its latest moment in the window: resolved at 13:00, opened at noon.
    assert found_by["timeline"]["detail"] == "incident_resolved 2026-09-28T13:00:00+00:00"
    assert found_by["graph"]["detail"] == "1"
    assert all(m["rank"] >= 1 and m["score"] > 0 for m in found_by.values())
    # Found by three: more relevant than what one found.
    page = next(e for e in made["elements"] if e["ref_id"] == str(company["PAGE"]))
    assert [m["retriever"] for m in page["reason"]["retrievers"]] == ["content"]
    assert page["reason"]["role"] == "found"
    assert incident["relevance"] > page["relevance"]
    assert made["summary"]["by_retriever"]["timeline"] == 4

    # What each retriever did: kept with the version.
    report = {run["retriever"]: run for run in made["retrieval"]}
    assert report["timeline"]["detail"] == ("2026-09-22T00:00:00+00:00/2026-09-29T00:00:00+00:00")
    assert report["paths"]["status"] == "skipped"
    assert report["search"]["ms"] >= 0
    versions = (await client.get(f"{API}/{made['context_id']}/versions")).json()["data"]
    assert versions[0]["retrieval"] == made["retrieval"]


async def test_the_retrievers_asked_and_only_them(
    client: AsyncClient, company: dict[str, uuid.UUID]
) -> None:
    made = await _ask(
        client, "Ce qui s'est passé", roots=[str(company[BILLING])], retrievers=["timeline"]
    )

    assert [run["retriever"] for run in made["retrieval"]] == ["timeline"]
    found = {uuid.UUID(e["ref_id"]) for e in made["elements"] if e["kind"] == "entity"}
    assert {company[INCIDENT], company[FLAG]} <= found
    assert company[PLATFORM] not in found


async def test_a_failing_retriever_is_undone_alone_and_seen(
    client: AsyncClient,
    company: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def broken(self: ContentRepository, tsquery: str, *, limit: int) -> Any:
        # An error in the database: the transaction would be lost but for
        # the savepoint.
        await self._session.execute(text("SELECT * FROM no_such_table"))

    monkeypatch.setattr(ContentRepository, "matching", broken)
    capsys.readouterr()
    made = await _ask(client, "Pourquoi la facturation est lente ?")

    assert made["status"] == "assembled"
    report = {run["retriever"]: run for run in made["retrieval"]}
    assert report["content"]["status"] == "failed"
    assert report["content"]["error"] == "ProgrammingError: the retriever failed."
    assert {report[name]["status"] for name in ("search", "graph", "timeline")} == {"ok"}
    found = {uuid.UUID(e["ref_id"]) for e in made["elements"] if e["kind"] == "entity"}
    assert {company[BILLING], company[INCIDENT]} <= found
    assert company["PAGE"] not in found
    assert "context_retriever_failed" in capsys.readouterr().out


async def test_a_slow_retriever_times_out_and_the_others_go_on(
    client: AsyncClient, company: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow(self: ContentRepository, tsquery: str, *, limit: int) -> Any:
        await self._session.execute(text("SELECT pg_sleep(5)"))

    monkeypatch.setattr(ContentRepository, "matching", slow)
    monkeypatch.setattr(retrieval, "TIMEOUT_MS", 200)
    made = await _ask(client, "Pourquoi la facturation est lente ?")

    report = {run["retriever"]: run for run in made["retrieval"]}
    assert report["content"]["status"] == "timeout"
    assert report["content"]["error"] == "Took longer than 200 ms."
    assert report["content"]["ms"] < 5000
    assert report["timeline"]["status"] == "ok"


async def test_every_retriever_failing_fails_the_version_and_a_refresh_recovers(
    client: AsyncClient, company: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("down")

    with monkeypatch.context() as patched:
        patched.setattr(GraphService, "matching", down)
        patched.setattr(ContentRepository, "matching", down)
        made = await _ask(client, "Pourquoi la facturation est lente ?")
        assert (made["status"], made["error"], made["elements"]) == (
            "failed",
            EVERY_ONE_FAILED,
            [],
        )
        # Nothing found: nothing to walk from, nothing to read the time of.
        assert [(r["retriever"], r["status"]) for r in made["retrieval"]] == [
            ("search", "failed"),
            ("content", "failed"),
            ("graph", "skipped"),
            ("timeline", "skipped"),
            ("paths", "skipped"),
        ]

    again = await client.post(f"{API}/{made['context_id']}/refresh")
    assert again.status_code == 200, again.text
    assert (again.json()["changed"], again.json()["version"]["status"]) == (True, "assembled")


async def test_a_request_with_nothing_to_start_from_is_refused(
    client: AsyncClient, company: dict[str, uuid.UUID]
) -> None:
    for body in (
        {"title": "Rien", "purpose": "Pourquoi ?"},
        {"title": "Rien", "strategy": "neighbourhood", "purpose": "Billing"},
        {
            "title": "Rien",
            "roots": [str(company[BILLING])],
            "strategy": "neighbourhood",
            "retrievers": ["search"],
        },
    ):
        assert (await client.post(API, json=body)).status_code == 422, body


# ── how well it retrieves ────────────────────────────────────────────────────

CONFIGURATIONS: list[tuple[str, list[str]]] = [
    ("hybrid", []),
    ("search", ["search"]),
    ("content", ["content"]),
    ("graph", ["graph"]),
    ("timeline", ["timeline"]),
    ("paths", ["paths"]),
]


async def test_retrieval_quality_on_the_test_cases(
    client: AsyncClient, company: dict[str, uuid.UUID]
) -> None:
    """Each configuration on each case: how much of the evidence it finds
    (recall, within the budget) and how high the first of it comes (the
    reciprocal rank, among what is not a root). The hybrid must find all
    of it, and more than any retriever alone."""
    measured: dict[str, tuple[float, float]] = {}
    for configuration, retrievers in CONFIGURATIONS:
        recalls: list[float] = []
        ranks: list[float] = []
        for _, purpose, extra, expected in CASES:
            made = await _ask(client, purpose, retrievers=retrievers, **_body(company, extra))
            wanted = _expected(company, expected)
            roots = {uuid.UUID(r) for r in made["request"]["roots"]}
            found = [
                uuid.UUID(e["ref_id"])
                for e in made["elements"]
                if e["kind"] == "entity" and uuid.UUID(e["ref_id"]) not in roots
            ]
            recalls.append(len(wanted & set(found)) / len(wanted))
            first = next((at for at, i in enumerate(found, start=1) if i in wanted), None)
            ranks.append(1 / first if first else 0.0)
        measured[configuration] = (sum(recalls) / len(recalls), sum(ranks) / len(ranks))

    # The table docs/context.md § 10 quotes: read with `pytest -s`.
    table = ["| retrievers | recall | MRR |", "|---|---:|---:|"]
    table += [f"| {name} | {recall:.2f} | {mrr:.2f} |" for name, (recall, mrr) in measured.items()]
    sys.stdout.write("\n" + "\n".join(table) + "\n")
    hybrid_recall, hybrid_mrr = measured["hybrid"]
    assert hybrid_recall == 1.0
    assert hybrid_mrr >= 0.5
    assert all(hybrid_recall > recall for name, (recall, _) in measured.items() if name != "hybrid")
