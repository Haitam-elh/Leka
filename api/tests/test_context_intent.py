"""Intent context assembly, end to end (LEKA-373): an intention, in its
asker's words, makes the context it needs.

Acme's operations, as test_context_retrieval builds them — GitHub's
billing-api and its deployments, PagerDuty's Billing API with its incident
Q1 and a change, Jira, a catalogue's Billing platform and Checkout, a
business system's Invoicing, a Confluence page about recovering payments —
with its sources read, active and able to read what happens, what ships,
who works on what and what is written. The week before 29 September is
asked.

What these protect: five representative intentions — why is invoicing
slow, what changed on Billing API, how is Checkout tied to invoicing, who
answers for Billing API, where is the recovery procedure — each read as
its kind, about what it names, its context holding the evidence, nothing
critical missing; the plan alone, read from the words — « depuis hier » —
the structured request it makes, nothing kept; the context traceable to
the intention it is for and the sources it reads — those not asked for
left out; what is missing, said: nothing named, a thing asked for not in
the model, no source able to read it, nothing happened in the period; an
intention with nothing to start from refused.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.context.intent import PROFILES
from leka.context.schemas import IntentKind
from leka.db import session_factory, workspace_scope
from tests.test_context_engine import _sql
from tests.test_context_retrieval import company  # noqa: F401 — fixture
from tests.test_operations_landscape import (
    BILLING,
    CHECKOUT,
    FLAG,
    INCIDENT,
    INVOICING,
    PLATFORM,
    RELEASE,
)
from tests.test_sources_api import acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/context"
WEEK = {"since": "2026-09-22T00:00:00Z", "until": "2026-09-29T00:00:00Z"}
SARA = "person:github.com:sara"
READS = ["incidents", "changes", "deployments", "repositories", "teams", "people", "pages"]


@pytest.fixture
async def readable(acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID]) -> dict[str, Any]:
    """Acme's sources read: active, able to read what an intention needs —
    and their ids by name."""
    await _sql(
        acme["acme"],
        "UPDATE sources SET status = 'active', capabilities = CAST(:can AS jsonb)",
        can=json.dumps(READS),
    )
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            rows = await session.execute(text("SELECT name, id FROM sources"))
            return dict(rows.tuples().all())


async def _intend(client: AsyncClient, said: str, **body: Any) -> Any:
    response = await client.post(f"{API}/intents", json={"text": said, **WEEK, **body})
    assert response.status_code == 201, response.text
    return response.json()


def _gaps(made: Any, severity: str | None = None) -> list[str]:
    return [g["kind"] for g in made["intent"]["gaps"] if severity in (None, g["severity"])]


CASES: list[tuple[str, str, IntentKind, list[str], list[str]]] = [
    (
        "why slow",
        "Pourquoi la facturation est lente ?",
        "diagnose",
        [INVOICING],
        [BILLING, INCIDENT, RELEASE, FLAG],
    ),
    (
        "what changed",
        "Qu'est-ce qui a changé sur Billing API ?",
        "change",
        [BILLING],
        [RELEASE, FLAG, INCIDENT],
    ),
    (
        "how tied",
        "Comment Checkout est-il relié à la facturation ?",
        "dependency",
        [CHECKOUT, INVOICING],
        [BILLING, PLATFORM],
    ),
    ("who answers", "Qui est responsable de Billing API ?", "ownership", [BILLING], [SARA]),
    ("where written", "Où est la procédure de reprise des paiements ?", "knowledge", [], ["PAGE"]),
]


@pytest.mark.parametrize(
    ("name", "said", "kind", "about", "evidence"), CASES, ids=[case[0] for case in CASES]
)
async def test_a_representative_intention_assembles_a_usable_context(
    client: AsyncClient,
    company: dict[str, uuid.UUID],
    readable: dict[str, Any],
    name: str,
    said: str,
    kind: IntentKind,
    about: list[str],
    evidence: list[str],
) -> None:
    made = await _intend(client, said)
    plan = made["intent"]
    assert plan["kind"] == kind
    named = [s["entity_id"] for s in plan["subjects"] if s["how"] == "named"]
    assert named == [str(company[key]) for key in about]
    # Its kind's request: its weights, its roots first in its context.
    assert plan["request"]["weights"] == dict(PROFILES[kind].weights)
    assert plan["request"]["roots"][: len(about)] == named
    held = {e["ref_id"] for e in made["elements"] if e["kind"] == "entity"}
    assert {str(company[key]) for key in evidence} <= held, name
    assert _gaps(made, "critical") == [], name
    assert made["subject"] == {"type": "request", "id": None}


async def test_the_plan_alone_reads_the_words_and_keeps_nothing(
    client: AsyncClient, company: dict[str, uuid.UUID], readable: dict[str, Any]
) -> None:
    response = await client.post(
        f"{API}/intents/plan", json={"text": "Pourquoi Billing API est lent depuis hier en prod ?"}
    )
    assert response.status_code == 200, response.text
    plan = response.json()
    assert (plan["kind"], plan["kind_said"]) == ("diagnose", ["pourquoi", "lent"])
    assert [(s["name"], s["how"], s["said"], s["confidence"]) for s in plan["subjects"]] == [
        ("Billing API", "named", "Billing API", 1.0)
    ]
    assert (plan["period"]["origin"], plan["period"]["said"]) == ("text", "hier")
    request = plan["request"]
    assert request["roots"] == [str(company[BILLING])]
    assert (request["depth"], request["window_days"], request["strategy"]) == (2, 2, "hybrid")
    assert request["until"] == plan["period"]["until"]
    assert {c["kind"]: c["origin"] for c in plan["constraints"]} == {
        "period": "text",
        "environment": "text",
        "retrievers": "kind",
    }
    # « en prod »: the production the model knows (v1.4.0 was deployed to it).
    assert plan["environment"] == "production"
    assert request["environment"] == "production"
    # Nothing kept.
    assert (await client.get(API)).json()["data"] == []


async def test_a_context_is_traceable_to_its_intention_and_the_sources_it_reads(
    client: AsyncClient, company: dict[str, uuid.UUID], readable: dict[str, Any]
) -> None:
    pagerduty = readable["PagerDuty"]
    made = await _intend(
        client,
        "Pourquoi Billing API est lent ?",
        intention_id="intention-42",
        services=[str(company[CHECKOUT])],
        sources=[str(pagerduty)],
    )
    assert made["subject"] == {"type": "intention", "id": "intention-42"}
    plan = made["intent"]
    assert [(s["name"], s["how"]) for s in plan["subjects"]][:2] == [
        ("Checkout", "asked"),
        ("Billing API", "named"),
    ]
    assert {c["kind"]: c["origin"] for c in plan["constraints"]} == {
        "period": "asked",
        "services": "asked",
        "sources": "asked",
        "retrievers": "kind",
    }
    assert plan["request"]["sources"] == [str(pagerduty)]
    # Only what PagerDuty says, but the roots; the rest left out, said why.
    roots = set(plan["request"]["roots"])
    for element in made["elements"]:
        if element["kind"] == "entity" and element["ref_id"] not in roots:
            assert str(pagerduty) in {s["source_id"] for s in element["provenance"]["sources"]}
    assert made["ranking"]["left_out"]["out_of_scope"] > 0
    # Each retriever said what it counted for.
    weights = {run["retriever"]: run["weight"] for run in made["retrieval"]}
    assert weights["timeline"] == pytest.approx(0.8 * 1.5)
    # Kept with the context, and read back.
    detail = await client.get(f"{API}/{made['context_id']}")
    assert detail.json()["intent"]["intention_id"] == "intention-42"


async def test_what_is_missing_is_said_never_ignored(
    client: AsyncClient,
    acme: dict[str, uuid.UUID],
    company: dict[str, uuid.UUID],
    readable: dict[str, Any],
) -> None:
    # Nothing in the model is named; something asked for is not in it.
    unnamed = await _intend(
        client, "Pourquoi le service Zorglub est lent ?", services=[str(uuid.uuid4())]
    )
    assert _gaps(unnamed, "critical") == ["no_subject", "unknown_service"]
    gap = unnamed["intent"]["gaps"][0]
    assert "zorglub" in gap["detail"]["tried"]

    # The sources read cannot read what happens.
    await _sql(
        acme["acme"],
        "UPDATE sources SET capabilities = CAST(:can AS jsonb) WHERE id = :id",
        can=json.dumps(["pages"]),
        id=readable["Confluence"],
    )
    blind = await _intend(
        client, "Pourquoi Billing API est lent ?", sources=[str(readable["Confluence"])]
    )
    (needs,) = [g for g in blind["intent"]["gaps"] if g["kind"] == "no_source_for"]
    assert needs["severity"] == "critical"
    assert "incidents" in needs["detail"]["needs"]

    # Nothing happened in the period asked, when what happened is the question.
    quiet = await _intend(
        client,
        "Qu'est-ce qui a changé sur Billing API ?",
        since="2025-12-01T00:00:00Z",
        until="2026-01-01T00:00:00Z",
    )
    assert "nothing_happened" in _gaps(quiet, "critical")

    # Nothing to start from: refused, nothing kept.
    before = len((await client.get(API)).json()["data"])
    refused = await client.post(f"{API}/intents", json={"text": "Pourquoi ?"})
    assert refused.status_code == 422, refused.text
    assert len((await client.get(API)).json()["data"]) == before
