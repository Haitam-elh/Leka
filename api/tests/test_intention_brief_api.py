"""An intention's brief and what it takes, through the API (LEKA-439).

What these protect:
- before asking, `POST /intentions/brief` says what LEKA understood — each
  part of what it must know, its questions, what follows — what it would
  read, and what it takes here: the capabilities, the credits; nothing is
  kept;
- asked incomplete, an intention waits with questions about what it lacks;
  answered (`POST …/answers`), the answer is kept, read with its words —
  which are kept as asked — and it is analysed; « je ne sais pas » about
  what an action acts on blocks it, never guessed;
- answers given when asking are kept and read with it;
- `GET …/feasibility`: its credits spent, the cheapest plan that is enough,
  asked first;
- another workspace sees none of it.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from leka.metering import credits as metering_credits
from leka.metering.schemas import CreditsRead
from tests.conftest import FakeIdentity
from tests.test_context_engine import model
from tests.test_intention_analysis_api import API, _ask, _get, queued  # noqa: F401
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name


async def _brief(client: AsyncClient, words: str, **more: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/brief", json={"text": words, **more})
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


async def test_before_asking_it_says_what_it_understood_reads_and_takes(
    client: AsyncClient, model: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    preview = await _brief(client, "Qui est responsable de Billing API ?")
    brief = preview["brief"]
    assert brief["decision"] == "analyse"
    assert brief["questions"] == []
    assert [s["slot"] for s in brief["slots"]] == [
        "goal",
        "target",
        "scope",
        "expected",
        "constraints",
    ]
    goal = brief["slots"][0]
    assert (goal["state"], goal["value"]) == ("known", "find_owner")
    assert brief["slots"][1]["values"] == ["Billing API"]
    assert isinstance(preview["sources"], list)
    feasible = preview["feasibility"]
    assert feasible["verdict"] == "ready"
    assert feasible["credits"]["plan"] == "free"
    used = [n for n in feasible["needed"] if n["selected"]]
    assert used and all(n["offer"] in ("included", "beta") for n in used)
    # Nothing kept.
    assert (await client.get(API)).json()["data"] == []


async def test_incomplete_it_asks_what_it_lacks_then_reads_the_answer_with_it(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    words = "Redémarre ça en production"
    intention = await _ask(client, words)
    assert intention["status"] == "needs_clarification"
    brief = intention["brief"]
    assert brief["decision"] == "clarify"
    assert brief["acting"] is True
    [question] = [q for q in brief["questions"] if q["blocking"]]
    assert (question["kind"], question["slot"], question["free"]) == (
        "action_without_target",
        "target",
        True,
    )

    response = await client.post(
        f"{API}/{intention['id']}/answers",
        json={"answers": [{"question": "action_without_target", "value": "Billing API"}]},
    )
    assert response.status_code == 200, response.text
    after = response.json()["intention"]
    assert after["status"] == "analysing"
    # Its words kept as asked; the answer kept beside them, and read.
    assert after["text"] == words
    assert after["answers"] == [
        {"question": "action_without_target", "value": "Billing API", "unknown": False}
    ]
    assert after["brief"]["decision"] in ("analyse", "continue")
    assert "Billing API" in after["brief"]["slots"][1]["values"]
    assert queued[-1] == (uuid.UUID(intention["id"]), "asked_again")
    history = await _get(client, f"/{intention['id']}/history")
    assert history[-1]["detail"]["answers"] == ["action_without_target"]


async def test_an_action_on_what_its_asker_does_not_know_is_blocked(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Redémarre ça en production")
    response = await client.post(
        f"{API}/{intention['id']}/answers",
        json={"answers": [{"question": "action_without_target", "unknown": True}]},
    )
    assert response.status_code == 200, response.text
    after = response.json()["intention"]
    # Never acted on a guess: it waits, said why.
    assert after["status"] == "needs_clarification"
    assert after["brief"]["decision"] == "block"
    assert after["brief"]["slots"][1]["state"] == "unknown"
    assert not [q for q in queued if q[0] == uuid.UUID(intention["id"])]


async def test_answers_given_when_asking_are_kept_and_read(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    answers = [{"question": "missing_environment", "value": "production"}]
    preview = await _brief(client, "Redémarre Billing API", answers=answers)
    assert preview["understanding"]["environment"] == "production"
    response = await client.post(API, json={"text": "Redémarre Billing API", "answers": answers})
    assert response.status_code == 201, response.text
    intention = response.json()["intention"]
    assert intention["answers"] == [
        {"question": "missing_environment", "value": "production", "unknown": False}
    ]
    assert intention["understanding"]["environment"] == "production"
    # The scope its asker chose is theirs: the answer is not written into it.
    assert intention["scope"] == {}


async def test_its_credits_spent_the_cheapest_plan_that_is_enough_asked_first(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intention = await _ask(client, "Qui est responsable de Billing API ?")
    now = datetime.now(UTC)

    async def spent(*args: Any, **kwargs: Any) -> CreditsRead:
        return CreditsRead(
            plan="free",
            plan_since=None,
            monthly=200,
            packs=0,
            allowance=200,
            used=200,
            remaining=0,
            percent=100,
            period_start=now - timedelta(days=3),
            period_end=now + timedelta(days=20),
            state="exhausted",
            warn_at=[80],
            enforced=True,
            credit_usd=0.01,
        )

    monkeypatch.setattr(metering_credits, "credits_now", spent)
    feasible = await _get(client, f"/{intention['id']}/feasibility")
    assert feasible["verdict"] == "over_quota"
    [step] = feasible["path"]
    assert (step["kind"], step["detail"]["plan"], step["consent"]) == (
        "change_plan",
        "starter",
        True,
    )


async def test_another_workspace_sees_none_of_it(
    client: AsyncClient,
    identity: FakeIdentity,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client, "Redémarre ça en production")
    _as(identity, acme, "other_admin")
    await _get(client, f"/{intention['id']}/feasibility", code=404)
    response = await client.post(
        f"{API}/{intention['id']}/answers",
        json={"answers": [{"question": "action_without_target", "value": "Billing API"}]},
    )
    assert response.status_code == 404
