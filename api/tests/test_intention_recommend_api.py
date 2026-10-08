"""What LEKA recommends, end to end (LEKA-389): from an intention's real
analysis on Acme's model to the result its decision interface reads.

What these protect: the recommendations are in the analysis result, apart
from its findings, each traceable — the findings and causes it follows
from, the evidence they rest on, all in the same result — and none is
invented: what is known (Billing API's owner) proposes no owner.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient

from tests.test_context_engine import model
from tests.test_intention_analysis_api import _analysed, _ask, _get, queued
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

_ = (model, queued)  # fixtures, requested by name


def _traceable(result: dict[str, Any]) -> None:
    ids = {f["id"] for f in result["findings"]} | {c["id"] for c in result["causes"]}
    evidence = {e["id"] for e in result["evidence"]}
    for recommendation in result["recommendations"]:
        assert set(recommendation["basis"]) <= ids, recommendation["code"]
        assert set(recommendation["evidence"]) <= evidence, recommendation["code"]
        assert recommendation["code"].startswith("recommend.")


async def test_a_wide_reach_tells_its_people_said_as_a_recommendation(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Qu'est-ce qui dépend de Billing API ?")
    await _analysed(acme, intention)
    result = (await _get(client, f"/{intention['id']}/analysis"))["result"]
    found = {r["code"]: r for r in result["recommendations"]}
    assert "recommend.notify" in found
    notify = found["recommend.notify"]
    # Billing API is part of Billing platform; Checkout, of Shop.
    assert notify["params"]["applications"] == ["Billing platform", "Shop"]
    assert (notify["changes_systems"], notify["action"]) == (False, "other")
    assert notify["why"]["code"] == "recommend.why.impact"
    # Apart from what it found.
    assert not any(f["code"].startswith("recommend.") for f in result["findings"])
    _traceable(result)


async def test_what_is_known_proposes_nothing_about_it(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    await _analysed(acme, intention)
    result = (await _get(client, f"/{intention['id']}/analysis"))["result"]
    codes = {r["code"] for r in result["recommendations"]}
    assert "recommend.assign_owner" not in codes
    assert "recommend.settle_owner" not in codes
    _traceable(result)
