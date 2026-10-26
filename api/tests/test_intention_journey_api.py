"""An intention's journey, end to end (LEKA-443): the state every screen
reads, its versions, stopping and resuming, retries that never do anything
twice, nothing left running.

Acme's company model (test_knowledge_graph), as test_intention_analysis_api
reads it.

What these protect:
- The list and the page say the same state for the same intention, at each
  step:
  - queued, it is ready;
  - answered, its result is available;
  - asked again, it is version 2. The analysis of version 1 is kept, said
    not current, and never shown as its result.
- The same words asked again while it is analysed: nothing done twice, no
  new version.
- The same request sent twice with its Idempotency-Key: one intention.
- « Arrêter l'analyse » while it runs:
  - the intention is ready, said stopped;
  - the analysis running is said stopped, and what it found is kept;
  - the result moves nothing;
  - resumed, it is analysed again, and the stopped analysis is never taken
    for done;
  - stopped twice, the same.
- An analysis that raises is said failed, never left running. The intention
  says why, keeps the error's type for diagnosis, and is analysed again on
  request.
- An analysis left running past its deadline (a worker that died) is said
  interrupted by the sweep, and its intention can be analysed again.
- A question answered while a capability failed is said partial, on the
  list as on its page.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.db import session_factory, workspace_scope
from leka.intentions import IntentionAnalysis, processing
from leka.intentions.analysis import Capability, Material, Output
from leka.intentions.capabilities import CAPABILITIES
from leka.intentions.journey import ANALYSIS_DEADLINE
from leka.intentions.processing import analyse_intention, analyse_pending, interrupt_overdue
from tests.test_context_engine import model
from tests.test_intention_analysis_api import queued  # noqa: F401 — a fixture
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

_ = model  # a fixture, requested by name
API = "/api/v1/intentions"
ASKED = "Qui est responsable de Billing API ?"


async def _ask(client: AsyncClient, words: str = ASKED, **headers: str) -> dict[str, Any]:
    response = await client.post(API, json={"text": words}, headers=headers)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()["intention"]
    return created


async def _get(client: AsyncClient, path: str) -> Any:
    response = await client.get(f"{API}{path}")
    assert response.status_code == 200, response.text
    return response.json()


async def _seen(client: AsyncClient, intention_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Its journey as its page says it, and as the list says it."""
    page = (await _get(client, f"/{intention_id}"))["journey"]
    listed = next(i for i in (await _get(client, ""))["data"] if i["id"] == intention_id)
    return page, listed["journey"]


async def _same(client: AsyncClient, intention_id: str) -> dict[str, Any]:
    page, listed = await _seen(client, intention_id)
    assert page == listed
    return page


async def _analysed(acme: dict[str, uuid.UUID], intention_id: str, **kwargs: Any) -> Any:
    return await analyse_intention(
        acme["acme"], uuid.UUID(intention_id), trigger="created", **kwargs
    )


async def test_a_question_left_waits_for_its_answer_said_unclear(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    # 2026-10-24: every move says its readiness — a question left was said
    # « ce sur quoi elle agit doit être précisé ».
    intention = await _ask(client, "Redémarre le service")
    assert intention["status"] == "needs_clarification"
    said = await _same(client, intention["id"])
    assert (said["state"], said["reason"], said["next"]) == (
        "needs_clarification",
        "unclear",
        "answer",
    )


async def test_the_list_and_its_page_say_the_same_state_and_versions_are_kept_apart(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client)
    assert intention["version"] == 1
    said = await _same(client, intention["id"])
    assert (said["state"], said["reason"], said["next"]) == ("ready", "queued", "wait")
    assert said["step"]["at"] == "analysis"

    await _analysed(acme, intention["id"])
    said = await _same(client, intention["id"])
    # Answered, then decided: its agents, or by hand (2026-10-14).
    assert (said["state"], said["next"]) == ("decision_required", "choose")
    assert (said["step"]["at"], said["step"]["done"], said["step"]["last"]) == (
        "decision",
        False,
        4,
    )
    assert {"ask_again", "launch_agents", "by_hand"} <= set(said["controls"])

    # Changed after its analysis finished: version 2, the earlier analysis
    # kept but never its result.
    asked = await client.post(
        f"{API}/{intention['id']}/ask", json={"text": "Qui maintient Billing API ?"}
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["intention"]["version"] == 2
    said = await _same(client, intention["id"])
    assert (said["state"], said["reason"]) == ("ready", "queued")
    analyses = await _get(client, f"/{intention['id']}/analyses")
    assert [(a["number"], a["intention_version"], a["current"]) for a in analyses] == [
        (1, 1, False)
    ]
    moved = [e for e in await _get(client, f"/{intention['id']}/history") if e["kind"] == "moved"]
    assert moved[-1]["name"] == "asked_again"
    assert moved[-1]["detail"]["intention_version"] == 2

    await _analysed(acme, intention["id"])
    analyses = await _get(client, f"/{intention['id']}/analyses")
    assert [(a["number"], a["intention_version"], a["current"]) for a in analyses] == [
        (2, 2, True),
        (1, 1, False),
    ]
    assert (await _same(client, intention["id"]))["state"] == "decision_required"
    # Its story says which version each moment belongs to.
    story = await _get(client, f"/{intention['id']}/timeline")
    versions = {(i["kind"], i["detail"].get("number")): i["version"] for i in story}
    assert versions[("created", None)] == 1
    assert versions[("asked_again", None)] == 2
    assert versions[("analysis_complete", 1)] == 1
    assert versions[("analysis_complete", 2)] == 2


async def test_the_same_words_asked_again_while_analysed_do_nothing_twice(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client)
    for _ in range(2):
        again = await client.post(f"{API}/{intention['id']}/ask", json={"text": ASKED})
        assert again.status_code == 200, again.text
        assert again.json()["intention"]["version"] == 1
    names = [e["name"] for e in await _get(client, f"/{intention['id']}/history")]
    assert "asked_again" not in names


async def test_the_same_request_sent_twice_is_one_intention(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    key = str(uuid.uuid4())
    first = await _ask(client, **{"Idempotency-Key": key})
    second = await _ask(client, **{"Idempotency-Key": key})
    assert second["id"] == first["id"]
    # Its analysis queued once: the second is the first's answer.
    assert [t for i, t in queued if str(i) == first["id"]] == ["created"]
    other = await _ask(client, **{"Idempotency-Key": str(uuid.uuid4())})
    assert other["id"] != first["id"]
    ids = [i["id"] for i in (await _get(client, ""))["data"]]
    assert ids.count(first["id"]) == 1


async def test_stopped_while_it_runs_it_is_ready_what_it_found_kept_and_resumed(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client)
    started, release = threading.Event(), threading.Event()

    def _held(material: Material) -> Output:
        started.set()
        release.wait(timeout=10)
        return Output()

    held = [
        *CAPABILITIES,
        Capability("held", 1, ".", goals=frozenset({"find_owner"}), run=_held, budget=15.0),
    ]
    running = asyncio.create_task(_analysed(acme, intention["id"], capabilities=held))
    await asyncio.to_thread(started.wait, 10)
    said = await _same(client, intention["id"])
    assert said["state"] == "analysing"
    assert "stop" in said["controls"]

    stopped = await client.post(f"{API}/{intention['id']}/stop")
    assert stopped.status_code == 200, stopped.text
    assert (stopped.json()["journey"]["state"], stopped.json()["journey"]["reason"]) == (
        "ready",
        "stopped",
    )
    assert set(stopped.json()["journey"]["controls"]) == {"resume", "ask_again", "cancel"}
    # Stopped twice: the same.
    twice = await client.post(f"{API}/{intention['id']}/stop")
    assert twice.status_code == 200, twice.text
    release.set()
    outcome = await running
    assert outcome["superseded"] is True

    # What it found kept, said stopped — never its result; nothing moved.
    [analysis] = await _get(client, f"/{intention['id']}/analyses")
    assert (analysis["status"], analysis["current"]) == ("stopped", False)
    assert analysis["result"] is not None
    said = await _same(client, intention["id"])
    assert (said["state"], said["reason"]) == ("ready", "stopped")
    names = [e["name"] for e in await _get(client, f"/{intention['id']}/history")]
    assert names.count("stopped") == 1

    # Resumed: analysing again; the stopped analysis is never taken for done.
    resumed = await client.post(f"{API}/{intention['id']}/analyse")
    assert resumed.status_code == 202, resumed.text
    assert (await _same(client, intention["id"]))["state"] == "ready"
    swept = await analyse_pending()
    assert swept["analysed"] >= 1
    analyses = await _get(client, f"/{intention['id']}/analyses")
    assert [(a["status"], a["current"]) for a in analyses] == [
        ("complete", True),
        ("stopped", False),
    ]
    assert (await _same(client, intention["id"]))["state"] == "decision_required"


async def test_an_analysis_that_raises_is_failed_never_left_running(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intention = await _ask(client)

    async def _broken(*args: object, **kwargs: object) -> object:
        msg = "the explanation broke"
        raise KeyError(msg)

    monkeypatch.setattr(processing, "_explained", _broken)
    outcome = await _analysed(acme, intention["id"])
    assert outcome == {"status": "failed", "analysis": outcome["analysis"], "error": "crashed"}

    [analysis] = await _get(client, f"/{intention['id']}/analyses")
    assert (analysis["status"], analysis["error"], analysis["detail"]["crashed"]) == (
        "failed",
        "crashed",
        "KeyError",
    )
    said = await _same(client, intention["id"])
    assert (said["state"], said["reason"], said["technical"], said["next"]) == (
        "analysis_failed",
        "crashed",
        "crashed",
        "analyse_again",
    )
    monkeypatch.undo()
    again = await client.post(f"{API}/{intention['id']}/analyse")
    assert again.status_code == 202, again.text
    assert (await _same(client, intention["id"]))["state"] == "ready"


async def test_an_analysis_left_running_past_its_deadline_is_said_interrupted(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client)
    long_ago = datetime.now(UTC) + timedelta(seconds=1)
    # A worker that died: its analysis recorded running, never finished.
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            session.add(
                IntentionAnalysis(
                    workspace_id=acme["acme"],
                    id=uuid.uuid4(),
                    intention_id=uuid.UUID(intention["id"]),
                    number=1,
                    trigger="created",
                    status="running",
                    intention_version=1,
                    started_at=long_ago,
                    selection=[],
                    steps=[],
                    detail={},
                )
            )
            await session.commit()
    said = await _same(client, intention["id"])
    assert said["state"] == "analysing"

    # Not yet past its deadline: nothing.
    assert await interrupt_overdue(now=long_ago + timedelta(minutes=1)) == 0
    assert await interrupt_overdue(now=long_ago + ANALYSIS_DEADLINE + timedelta(seconds=1)) == 1
    said = await _same(client, intention["id"])
    assert (said["state"], said["reason"]) == ("analysis_failed", "interrupted")
    assert "analyse_again" in said["controls"]
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            row = await session.scalar(
                select(IntentionAnalysis).where(
                    IntentionAnalysis.intention_id == uuid.UUID(intention["id"])
                )
            )
            assert row is not None
            assert (row.status, row.error) == ("failed", "interrupted")
    # Idempotent.
    assert await interrupt_overdue(now=long_ago + ANALYSIS_DEADLINE * 2) == 0


def _boom(material: Material) -> Output:
    msg = "the source did not answer"
    raise RuntimeError(msg)


async def test_a_question_answered_while_a_capability_failed_is_said_partial_everywhere(
    client: AsyncClient,
    model: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
    queued: list[tuple[uuid.UUID, str]],
) -> None:
    intention = await _ask(client)
    broken = [
        *CAPABILITIES,
        Capability("boom", 1, ".", goals=frozenset({"find_owner"}), run=_boom),
    ]
    await _analysed(acme, intention["id"], capabilities=broken)
    said = await _same(client, intention["id"])
    # Partial, said at its decision (2026-10-14: every request is decided).
    assert (said["state"], said["reason"]) == ("decision_required", "partial")
    [analysis] = await _get(client, f"/{intention['id']}/analyses")
    assert (analysis["status"], analysis["current"]) == ("partial", True)
