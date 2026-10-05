"""The context engine (LEKA-370): contexts assembled, kept, inspected.

Acme's company model, as the knowledge graph's tests build it — PagerDuty
watching Billing API, a catalogue saying Checkout depends on it, both owned
by Payments, applications, an HR system, a business system — through the
whole pipeline. A member asks for the context of Billing API.

What these protect: a context is created from the model, its first version
whole — the root first, each element with its sources named, the records
that stated it, why it is there; it is listed, inspected, its versions
read; reassembled, it makes a new version only when what the model says
of it changed, and every earlier version reads back as it was made — by
number, or as it stood at a date — with what changed between them; a root
gone fails a version that says why, the last good one still read; an
archived context is read, never reassembled; a budget cuts and says so;
what is refused is refused before anything is kept; another workspace's
context is not found. Ranked (LEKA-372): what entity resolution linked as
probably the same is folded and said, what its sources disagree on is
said, every element says how it was ranked — and a version kept before
says nothing of it, rather than something made up.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from leka.db import session_factory, workspace_scope
from leka.ingestion import ResolutionDecision
from tests.conftest import FakeIdentity, error_code
from tests.test_knowledge_graph import BILLING, CHECKOUT, PAYMENTS, SHOP, _acme
from tests.test_relationships_engine import _build
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/context"


@pytest.fixture
async def model(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids = await _acme(acme["acme"])
    _as(identity, acme, "member")
    return ids


async def _create(client: AsyncClient, model: dict[str, uuid.UUID], **body: Any) -> Any:
    response = await client.post(
        API,
        json={
            "title": "Billing API",
            "purpose": "Why is Billing API slow?",
            "subject": {"type": "entity", "id": str(model[BILLING])},
            "roots": [str(model[BILLING])],
            **body,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _get(client: AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _refresh(client: AsyncClient, context_id: str, reason: str | None = None) -> Any:
    response = await client.post(
        f"{API}/{context_id}/refresh", json={"reason": reason} if reason else None
    )
    assert response.status_code == 200, response.text
    return response.json()


def _labels(assembled: dict[str, Any]) -> list[str]:
    return [element["label"] for element in assembled["elements"]]


async def _sql(workspace: uuid.UUID, statement: str, **params: Any) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(text(statement), params)
            await session.commit()


async def test_a_context_is_created_whole_with_its_provenance_and_inspected(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model)

    assert (made["version"], made["status"], made["contract_version"]) == (1, "assembled", 1)
    assert made["purpose"] == "Why is Billing API slow?"
    assert made["subject"] == {"type": "entity", "id": str(model[BILLING])}
    assert made["request"] == {
        "roots": [str(model[BILLING])],
        "query": None,
        "depth": 1,
        "relationships": [],
        "environment": None,
        "limit": 100,
        "window_days": 14,
        "until": None,
        "retrievers": [],
        "strategy": "hybrid",
        "min_relevance": 0.05,
        "weights": {},
        "sources": [],
    }
    assert made["strategy"] == {"name": "hybrid", "version": 1}
    assert made["model_built_at"] is not None
    assert (made["truncated"], made["dropped"]) == (False, 0)

    # The root first, as the model says it, with every source that shows it.
    root = made["elements"][0]
    assert (root["position"], root["kind"], root["ref_id"]) == (0, "entity", str(model[BILLING]))
    assert root["entity"]["key"] == BILLING
    assert {k: root["reason"][k] for k in ("strategy", "role", "depth", "root", "via")} == {
        "strategy": "hybrid",
        "role": "root",
        "depth": 0,
        "root": str(model[BILLING]),
        "via": None,
    }
    # Its words found it too: "Billing API" is in the purpose.
    assert [m["retriever"] for m in root["reason"]["retrievers"]] == ["search"]
    assert root["relevance"] == 1.0
    assert {s["name"] for s in root["provenance"]["sources"]} >= {"PagerDuty", "Catalogue"}
    assert root["provenance"]["attributes"]
    assert root["text"].startswith('service "Billing API" (service:billing-api)')

    # What surrounds it: reached through a relationship the catalogue stated.
    elements = {e["label"]: e for e in made["elements"]}
    checkout = elements["Checkout"]
    assert (checkout["reason"]["role"], checkout["reason"]["depth"]) == ("reached", 1)
    via = next(e for e in made["elements"] if e["ref_id"] == checkout["reason"]["via"])
    assert via["kind"] == "relationship"
    assert via["relationship"]["type"] == "depends_on"
    assert (via["relationship"]["start"]["key"], via["relationship"]["end"]["key"]) == (
        CHECKOUT,
        BILLING,
    )
    stated = via["provenance"]
    assert stated["origin"] == "stated"
    assert [s["name"] for s in stated["sources"]] == ["Catalogue"]
    assert stated["sources"][0]["record_id"]
    assert via["reason"]["role"] == "tie"
    assert "Payments" in elements
    assert made["summary"]["entities"] == sum(1 for e in made["elements"] if e["kind"] == "entity")
    assert {s["name"] for s in made["sources"]} >= {"PagerDuty", "Catalogue"}

    # Listed, by subject; inspected; its versions; read back as made.
    listed = await _get(client, "", subject_type="entity", subject_id=str(model[BILLING]))
    assert [c["id"] for c in listed["data"]] == [made["context_id"]]
    assert (await _get(client, "", subject_id=str(uuid.uuid4())))["data"] == []
    detail = await _get(client, f"/{made['context_id']}")
    assert (detail["status"], detail["current_version"]) == ("assembled", 1)
    assert detail["latest"]["fingerprint"]
    assert detail["latest"]["element_count"] == len(made["elements"])
    versions = await _get(client, f"/{made['context_id']}/versions")
    assert [v["version"] for v in versions["data"]] == [1]
    assert versions["data"][0]["trigger"] == "created"
    assert await _get(client, f"/{made['context_id']}/assembled") == made


async def test_a_refresh_makes_a_version_only_when_the_model_changed_and_history_stays(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model)
    context_id = made["context_id"]

    # Nothing changed: no version, but it looked.
    same = await _refresh(client, context_id)
    assert same["changed"] is False
    assert same["version"]["version"] == 1
    assert (await _get(client, f"/{context_id}"))["refreshed_at"] is not None

    # Checkout's record goes: the model is built again without it.
    between = datetime.now(UTC)
    await _sql(acme["acme"], "DELETE FROM normalised_records WHERE entity_key = :k", k=CHECKOUT)
    await _build(acme["acme"])

    moved = await _refresh(client, context_id, reason="Checkout was retired")
    assert moved["changed"] is True
    assert moved["version"]["version"] == 2
    assert (moved["version"]["trigger"], moved["version"]["reason"]) == (
        "refreshed",
        "Checkout was retired",
    )
    latest = await _get(client, f"/{context_id}/assembled")
    assert latest["version"] == 2
    assert "Checkout" not in _labels(latest)

    # What it was: version 1, as made — by number, or as it stood then.
    first = await _get(client, f"/{context_id}/assembled", version=1)
    assert first == made
    assert (await _get(client, f"/{context_id}/assembled", at=between.isoformat()))["version"] == 1
    before = (datetime.fromisoformat(made["assembled_at"]) - timedelta(seconds=1)).isoformat()
    assert (
        await client.get(f"{API}/{context_id}/assembled", params={"at": before})
    ).status_code == 404

    changed = await _get(client, f"/{context_id}/diff", **{"from": 1, "to": 2})
    assert (changed["from_version"], changed["to_version"]) == (1, 2)
    gone = {e["label"] for e in changed["removed"]}
    assert "Checkout" in gone
    assert "Checkout → Billing API" in gone
    assert changed["added"] == []
    assert changed["unchanged"] + len(changed["changed"]) == len(latest["elements"])

    versions = await _get(client, f"/{context_id}/versions")
    assert [v["version"] for v in versions["data"]] == [2, 1]


async def test_a_root_gone_fails_a_version_and_the_last_good_one_still_reads(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model, roots=[str(model[PAYMENTS])])
    context_id = made["context_id"]
    await _sql(acme["acme"], "DELETE FROM entities WHERE id = :id", id=model[PAYMENTS])

    failed = await _refresh(client, context_id)
    assert failed["changed"] is True
    assert (failed["version"]["version"], failed["version"]["status"]) == (2, "failed")
    assert failed["version"]["error"] == "A root of this context is no longer in the company model."
    assert failed["version"]["element_count"] == 0
    assert (await _get(client, f"/{context_id}"))["status"] == "failed"

    # The last version that held something is still what is read.
    assert (await _get(client, f"/{context_id}/assembled"))["version"] == 1
    empty = await _get(client, f"/{context_id}/assembled", version=2)
    assert (empty["status"], empty["elements"]) == ("failed", [])

    # Failing again is no news.
    again = await _refresh(client, context_id)
    assert (again["changed"], again["version"]["version"]) == (False, 2)


async def test_an_archived_context_is_read_never_reassembled(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model)
    context_id = made["context_id"]

    archived = await client.post(f"{API}/{context_id}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"
    assert archived.json()["archived_at"] is not None

    refused = await client.post(f"{API}/{context_id}/refresh")
    assert refused.status_code == 409
    assert error_code(refused) == "conflict"
    assert await _get(client, f"/{context_id}/assembled") == made
    again = await client.post(f"{API}/{context_id}/archive")
    assert again.json()["archived_at"] == archived.json()["archived_at"]
    assert [c["id"] for c in (await _get(client, "", status="archived"))["data"]] == [context_id]


async def test_a_budget_cuts_and_says_so(client: AsyncClient, model: dict[str, uuid.UUID]) -> None:
    made = await _create(client, model, limit=2)

    assert len(made["elements"]) == 2
    assert made["elements"][0]["ref_id"] == str(model[BILLING])
    assert made["truncated"] is True
    assert made["dropped"] > 0


async def test_what_is_refused_keeps_nothing(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    unknown = await client.post(API, json={"title": "Nothing", "roots": [str(uuid.uuid4())]})
    assert unknown.status_code == 404
    assert error_code(unknown) == "not_found"
    wrongs: list[dict[str, Any]] = [
        {"roots": []},
        {"roots": [str(model[BILLING])], "depth": 4},
        {"roots": [str(model[BILLING])], "limit": 501},
        {"roots": [str(model[BILLING])], "relationships": ["knows_nothing_of"]},
        {"roots": [str(model[BILLING])], "subject": {"type": "a guess"}},
    ]
    for wrong in wrongs:
        response = await client.post(API, json={"title": "Wrong", **wrong})
        assert response.status_code == 422, wrong
    assert (await _get(client, ""))["data"] == []

    made = await _create(client, model)
    context_id = made["context_id"]
    both = await client.get(
        f"{API}/{context_id}/assembled", params={"version": 1, "at": datetime.now(UTC).isoformat()}
    )
    assert both.status_code == 400
    missing = await client.get(f"{API}/{context_id}/diff", params={"from": 1, "to": 7})
    assert missing.status_code == 404
    assert (
        await client.get(f"{API}/{context_id}/assembled", params={"version": 3})
    ).status_code == 404


async def test_another_workspace_s_context_is_not_found(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    model: dict[str, uuid.UUID],
) -> None:
    made = await _create(client, model)
    context_id = made["context_id"]

    _as(identity, acme, "other_admin")  # Globex's
    for path in ("", "/versions", "/assembled", "/diff?from=1&to=1"):
        assert (await client.get(f"{API}/{context_id}{path}")).status_code == 404, path
    for action in ("refresh", "archive"):
        assert (await client.post(f"{API}/{context_id}/{action}")).status_code == 404, action
    assert (await _get(client, ""))["data"] == []
    # Nor can Acme's entities be the roots of Globex's context.
    borrowed = await client.post(API, json={"title": "Theirs", "roots": [str(model[BILLING])]})
    assert borrowed.status_code == 404


async def test_a_context_is_ranked_its_duplicates_folded_its_conflicts_said(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    # Entity resolution found Checkout and the Shop application probably the
    # same thing, and kept them apart; the sources of Billing API disagree
    # on its tier.
    with workspace_scope(workspace):
        async with session_factory() as session:
            session.add(
                ResolutionDecision(
                    workspace_id=workspace,
                    entity_id=model[SHOP],
                    other_entity_id=model[CHECKOUT],
                    kind="link",
                    rule="same_name",
                    confidence=0.8,
                    keys=[],
                    evidence="Shop ~ Checkout",
                )
            )
            await session.commit()
    conflict = [
        {
            "attribute": "tier",
            "chosen": 1,
            "values": [
                {"value": 1, "source_id": str(uuid.uuid4())},
                {"value": 2, "source_id": str(uuid.uuid4())},
            ],
        }
    ]
    await _sql(
        workspace,
        "UPDATE entities SET provenance = jsonb_set(provenance, '{conflicts}', "
        "CAST(:said AS jsonb)) WHERE id = :id",
        said=json.dumps(conflict),
        id=model[BILLING],
    )

    made = await _create(client, model, depth=2)
    ranking = made["ranking"]
    assert (ranking["version"], ranking["min_relevance"], ranking["trust_share"]) == (1, 0.05, 0.4)
    assert ranking["left_out"]["duplicate"] == 1
    (folded,) = [item for item in ranking["left"] if item["reason"] == "duplicate"]
    assert (folded["ref_id"], folded["duplicate_of"]) == (str(model[SHOP]), str(model[CHECKOUT]))
    elements = {e["label"]: e for e in made["elements"]}
    assert "Shop" not in elements
    assert [d["ref_id"] for d in elements["Checkout"]["ranking"]["duplicates"]] == [
        str(model[SHOP])
    ]

    # The disagreement said, on the context and on the thing.
    (said,) = made["conflicts"]
    assert (said["kind"], said["subject"], said["about"], said["chosen"]) == (
        "attribute",
        str(model[BILLING]),
        "tier",
        1,
    )
    assert [v["by"] for v in said["values"]] == [["a deleted source"], ["a deleted source"]]
    root = made["elements"][0]
    assert root["ranking"]["conflicts"] == [said["id"]]
    assert root["text"].endswith(" — disputed: tier: 1 by a source, 2 by a source")

    # Every element says how it was ranked: the entities in order, from 1.
    entities = [e for e in made["elements"] if e["kind"] == "entity"]
    assert [e["ranking"]["rank"] for e in entities] == list(range(1, len(entities) + 1))
    for element in made["elements"]:
        signals = {s["name"]: s for s in element["ranking"]["signals"]}
        assert {s["axis"] for s in signals.values()} == {"topic", "trust"}
        assert all(s["said"] for s in signals.values())
    assert {"confidence", "freshness", "sources", "corroboration"} <= {
        s["name"] for s in root["ranking"]["signals"]
    }

    # The versions say it in short.
    versions = await _get(client, f"/{made['context_id']}/versions")
    assert versions["data"][0]["left_out"]["duplicate"] == 1
    assert versions["data"][0]["conflicts"] == 1

    # A version kept before LEKA-372 says nothing of a ranking it never had.
    await _sql(workspace, "UPDATE context_versions SET ranking = NULL")
    await _sql(workspace, "UPDATE context_elements SET ranking = NULL")
    before = await _get(client, f"/{made['context_id']}/assembled")
    assert (before["ranking"], before["conflicts"]) == (None, [])
    assert {e["ranking"] for e in before["elements"]} == {None}
    versions = await _get(client, f"/{made['context_id']}/versions")
    assert (versions["data"][0]["left_out"], versions["data"][0]["conflicts"]) == ({}, 0)
