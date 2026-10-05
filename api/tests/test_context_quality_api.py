"""How good a context is (LEKA-375), against the database.

Acme's company model, as tests/test_context_engine.py builds it: Billing
API, owned by Payments, watched by PagerDuty, described by no page; the
Billing platform application, owned by nobody.

What these protect: a context is judged when it is made and keeps it — its
measures, each factor naming elements of that version, what it lacks, a
page nobody wrote said — and inspected: as kept, whether the context is up
to date, what people said; the versions say it in short; a disagreement
on what decides an answer about what was asked is critical and holds the
level to medium; an ownership question on what nobody owns is a critical
gap that holds it to low, the intention's own gaps beside; a version made
before is judged when read, what the model knew then left unknown; what
people say — an element useful, wrong, something missing — is kept with
what the element was then, refused when it says nothing or names an
element the version does not hold, and counted by what found it.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.test_context_engine import API, _create, _get, _sql, model
from tests.test_knowledge_graph import BILLING
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name


async def _post(client: AsyncClient, path: str, body: Any = None, status: int = 200) -> Any:
    response = await client.post(f"{API}{path}", json=body)
    assert response.status_code == status, response.text
    return response.json()


def _gaps(quality: dict[str, Any]) -> dict[str, str]:
    return {gap["kind"]: gap["severity"] for gap in quality["gaps"]}


async def test_a_context_is_judged_when_made_kept_with_it_and_inspected(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model)
    quality = made["quality"]

    assert (quality["version"], quality["assessed"], quality["level"]) == (1, "assembled", "high")
    assert [m["name"] for m in quality["measures"]] == ["completeness", "confidence", "freshness"]
    assert _gaps(quality) == {"undocumented": "info"}
    [page] = quality["gaps"]
    assert page["refs"] == [str(model[BILLING])]
    knowledge = next(f for f in quality["measures"][0]["factors"] if f["name"] == "knowledge")
    assert knowledge["detail"]["lacking"] == ["Billing API: page"]
    # Every factor, every gap, names elements of this version.
    held = {e["ref_id"] for e in made["elements"]}
    for measure in quality["measures"]:
        for factor in measure["factors"]:
            assert set(factor["refs"]) <= held, factor
    assert quality["support"]["entities"] == sum(
        1 for e in made["elements"] if e["kind"] == "entity"
    )
    assert {y["retriever"] for y in quality["retrieval"]} == {
        run["retriever"] for run in made["retrieval"]
    }

    inspected = await _get(client, f"/{made['context_id']}/quality")
    assert inspected["quality"] == quality
    assert (inspected["version"], inspected["freshness"]["state"]) == (1, "fresh")
    assert inspected["feedback"] == {"useful": 0, "not_useful": 0, "wrong": 0, "missing": 0}
    assert inspected["given"] == []
    [version] = (await _get(client, f"/{made['context_id']}/versions"))["data"]
    assert (version["quality_score"], version["quality_level"]) == (quality["score"], "high")


async def test_a_disagreement_on_what_decides_an_answer_about_what_was_asked_is_critical(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
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
        acme["acme"],
        "UPDATE entities SET provenance = jsonb_set(provenance, '{conflicts}', "
        "CAST(:said AS jsonb)) WHERE id = :id",
        said=json.dumps(conflict),
        id=model[BILLING],
    )

    quality = (await _create(client, model))["quality"]

    [said] = quality["conflicts"]
    assert (said["about"], said["severity"], said["refs"]) == (
        "tier",
        "critical",
        [str(model[BILLING])],
    )
    assert quality["capped"] == "critical_conflict"
    assert quality["score"] <= 0.84
    assert quality["level"] == "medium"
    assert (quality["support"]["conflicts"], quality["support"]["critical"]) == (1, 1)


async def test_an_ownership_question_on_what_nobody_owns_is_a_critical_gap(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    made = await _post(
        client, "/intents", {"text": "Qui est responsable de Billing platform ?"}, 201
    )
    quality = made["quality"]

    gaps = _gaps(quality)
    assert gaps["no_owner"] == "critical"
    assert (quality["level"], quality["capped"]) == ("low", "critical_gap")
    assert quality["score"] <= 0.59
    # The critical first; the intention's own gaps beside LEKA's.
    assert quality["gaps"][0]["kind"] == "no_owner"
    assert {g["origin"] for g in quality["gaps"]} == {"quality", "intent"}
    no_owner = quality["gaps"][0]
    assert no_owner["refs"] == [s["entity_id"] for s in made["intent"]["subjects"]][:1]


async def test_a_version_made_before_is_judged_when_read(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model)
    await _sql(
        acme["acme"],
        "UPDATE context_versions SET quality = NULL WHERE context_id = :id",
        id=uuid.UUID(made["context_id"]),
    )

    read = (await _get(client, f"/{made['context_id']}/assembled"))["quality"]
    assert read["assessed"] == "read"
    knowledge = next(f for f in read["measures"][0]["factors"] if f["name"] == "knowledge")
    assert knowledge["value"] is None
    assert read["score"] is not None
    # The rest is read from what the version holds: the same.
    assert read["measures"][1] == made["quality"]["measures"][1]
    [version] = (await _get(client, f"/{made['context_id']}/versions"))["data"]
    assert version["quality_score"] is None


async def test_what_people_say_is_kept_with_the_element_and_counted_by_what_found_it(
    client: AsyncClient, model: dict[str, uuid.UUID]
) -> None:
    made = await _create(client, model)
    context_id = made["context_id"]
    root, other = made["elements"][0], made["elements"][1]

    useful = await _post(
        client, f"/{context_id}/feedback", {"ref_id": root["ref_id"], "verdict": "useful"}, 201
    )
    assert (useful["version"], useful["label"], useful["verdict"]) == (1, "Billing API", "useful")
    await _post(
        client,
        f"/{context_id}/feedback",
        {"ref_id": other["ref_id"], "verdict": "wrong", "note": "Not ours any more."},
        201,
    )
    await _post(
        client,
        f"/{context_id}/feedback",
        {"verdict": "missing", "note": "The payments runbook."},
        201,
    )

    # Saying nothing, or of what the version does not hold: refused.
    for body, code in (
        ({"verdict": "useful"}, 422),
        ({"verdict": "missing"}, 422),
        ({"verdict": "missing", "note": "x", "ref_id": root["ref_id"]}, 422),
        ({"verdict": "useful", "ref_id": str(uuid.uuid4())}, 404),
        ({"verdict": "useful", "ref_id": root["ref_id"], "version": 9}, 404),
    ):
        response = await client.post(f"{API}/{context_id}/feedback", json=body)
        assert response.status_code == code, (body, response.text)

    inspected = await _get(client, f"/{context_id}/quality")
    assert inspected["feedback"] == {"useful": 1, "not_useful": 0, "wrong": 1, "missing": 1}
    assert [g["verdict"] for g in inspected["given"]] == ["missing", "wrong", "useful"]
    assert inspected["given"][0]["note"] == "The payments runbook."

    counted = await _get(client, "/feedback", days=7)
    assert counted["total"] == {"useful": 1, "not_useful": 0, "wrong": 1, "missing": 1}
    assert counted["by_role"]["root"]["useful"] == 1
    assert counted["by_type"]["service"]["useful"] == 1
    found_by = {m["retriever"] for m in root["reason"]["retrievers"]}
    for retriever in found_by:
        assert counted["by_retriever"][retriever]["useful"] >= 1
