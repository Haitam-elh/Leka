"""Skills over HTTP (LEKA-396) — LEKA's reads, run end to end on Acme's
company model (test_knowledge_graph): Billing API, owned by Payments;
Checkout depends on it.

What these protect:
- Every skill is listed as a caller gets it: what it does, what it takes and
  gives as JSON schemas, who may run it, where it stands, its versions.
- A skill runs over HTTP and gives what its contract says; what it was
  given that it does not take, a thing it does not know, a skill or version
  that does not exist — refused, said why (422, 404); a permission the
  person's role lacks — 403. Every run kept, refused or not, the workspace's
  own.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from leka.capabilities.skills import REGISTRY
from leka.intentions import SKILLS
from tests.conftest import FakeIdentity, error_code
from tests.test_context_engine import model
from tests.test_knowledge_graph import BILLING, PAYMENTS
from tests.test_skills import echo, toy
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name

API = "/api/v1/skills"


async def _run(client: AsyncClient, key: str, code: int = 200, **body: Any) -> Any:
    response = await client.post(f"{API}/{key}/run", json=body)
    assert response.status_code == code, response.text
    return response.json()


async def test_every_skill_is_listed_with_its_contract(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    _as(identity, acme, "member")
    response = await client.get(API)
    assert response.status_code == 200, response.text
    listed = {s["key"]: s for s in response.json()}
    assert set(listed) >= {s.key for s in SKILLS}
    describe = listed["describe"]
    assert describe["effect"] == "read"
    assert (describe["permission"], describe["usable"]) == ("workspace:read", True)
    assert describe["input_schema"]["required"] == ["id"]
    assert {"name", "responsibility", "ties", "cited"} <= set(
        describe["output_schema"]["properties"]
    )
    assert describe["versions"] == [
        {"version": "1.0.0", "lifecycle": "active", "fingerprint": describe["fingerprint"]}
    ]
    assert listed["sources"]["permission"] == "source:read"
    one = await client.get(f"{API}/happened")
    assert one.json()["title"] == "What happened"
    missing = await client.get(f"{API}/nope")
    assert (missing.status_code, error_code(missing)) == (404, "not_found")


async def test_a_skill_runs_over_http_gives_what_it_promised_and_is_kept(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    billing = f"entity:{model[BILLING]}"
    described = await _run(client, "describe", inputs={"id": billing})
    assert (described["status"], described["caller"], described["mine"]) == (
        "succeeded",
        "api",
        True,
    )
    said = described["output"]
    assert said["name"] == "Billing API"
    assert [o["name"] for o in said["responsibility"]["owners"]] == ["Payments"]
    assert "cited" not in said and described["cited"] >= 1
    # The other reads, on the same model.
    found = await _run(client, "find", inputs={"query": "billing"})
    assert billing in {f["id"] for f in found["output"]["found"]}
    upstream = await _run(client, "dependencies", inputs={"id": billing, "direction": "upstream"})
    assert "Checkout" in {t["name"] for t in upstream["output"]["things"]}
    team = await _run(client, "describe", inputs={"id": f"entity:{model[PAYMENTS]}"})
    assert team["output"]["type"] == "team"
    for key, inputs in (
        ("happened", {"since": "2020-01-01T00:00:00Z"}),
        ("learned", {"since": "2020-01-01"}),
        ("sources", {}),
        ("insights", {"about": billing}),
        ("overview", {}),
    ):
        ran = await _run(client, key, inputs=inputs)
        assert ran["status"] == "succeeded", (key, ran)
    overview = await _run(client, "overview", inputs={})
    assert overview["output"]["things"]["service"] >= 2

    # Refused, said why — and kept.
    wrong = await _run(client, "describe", 422, inputs={})
    assert wrong["error"]["code"] == "validation_failed"
    assert wrong["error"]["details"][0]["field"] == "inputs.id"
    unknown = await _run(client, "describe", 404, inputs={"id": f"entity:{uuid.uuid4()}"})
    assert unknown["error"]["message"] == "LEKA knows no such thing."
    await _run(client, "describe", 404, inputs={"id": billing}, version="2")
    await _run(client, "nope", 404, inputs={})
    runs = await client.get(API + "/runs", params={"key": "describe"})
    assert [(r["status"], r["reason"]) for r in runs.json()] == [
        ("refused", "not_found"),
        ("refused", "unknown"),
        ("refused", "invalid_input"),
        ("succeeded", None),
        ("succeeded", None),
    ]
    kept = runs.json()[-1]
    assert (kept["inputs"], kept["output"]["name"]) == ({"id": billing}, "Billing API")
    # The workspace's own.
    _as(identity, acme, "other_admin")
    elsewhere = await client.get(API + "/runs")
    assert elsewhere.json() == []


async def test_a_skill_takes_its_own_permission(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managing = toy(key="managing", run=echo, permission="source:manage")
    monkeypatch.setitem(REGISTRY._skills, "managing", {"1.0.0": managing})
    _as(identity, acme, "member")
    listed = {s["key"]: s for s in (await client.get(API)).json()}
    assert listed["managing"]["usable"] is False
    refused = await _run(client, "managing", 403, inputs={"word": "hi"})
    assert refused["error"]["message"] == "Running it takes the permission source:manage."
    _as(identity, acme, "admin")
    ran = await _run(client, "managing", inputs={"word": "hi"})
    assert ran["output"] == {"said": "HI"}
    runs = (await client.get(API + "/runs", params={"key": "managing"})).json()
    assert [(r["status"], r["mine"]) for r in runs] == [("succeeded", True), ("refused", False)]
