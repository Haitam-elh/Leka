"""« Demander une compétence » (LEKA-501): an agent or a skill someone wishes
LEKA had, kept for LEKA's team.

What these protect: a suggestion kept with who asked, where it stands, read
again by the workspace — never another's; never an intention, nothing run;
the same one still open refused (409), a sixth in a day from the same person
refused (429), an empty one refused (422); LEKA's team lists it and moves it
on the server.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from leka.capabilities import CapabilitySuggestion
from leka.capabilities import suggestions as module
from leka.db import session_factory, system_scope
from leka.intentions import Intention
from tests.conftest import FakeIdentity
from tests.test_workspace_api import _create_workspace, people  # noqa: F401

pytestmark = pytest.mark.integration

SUGGESTIONS = "/api/v1/capability-suggestions"


def _body(name: str = "Agent FinOps", **over: object) -> dict[str, object]:
    return {
        "name": name,
        "problem": "Nos factures cloud montent sans que l'on sache pourquoi.",
        "use_case": "Chaque lundi, dire quel service a coûté plus que la semaine d'avant.",
        **over,
    }


async def _count(model: type) -> int:
    with system_scope():
        async with session_factory() as session:
            return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_a_suggestion_kept_read_again_never_an_intention(
    client: AsyncClient,
    identity: FakeIdentity,
    people: dict[str, uuid.UUID],  # noqa: F811
) -> None:
    await _create_workspace(client, identity, people["owner"], "Acme Corp")
    intentions = await _count(Intention)

    sent = await client.post(SUGGESTIONS, json=_body(systems="  AWS, GCP ", context="   "))
    assert sent.status_code == 201, sent.text
    said = sent.json()
    assert said["status"] == "received"
    assert said["systems"] == "AWS, GCP"
    assert said["context"] is None

    listed = (await client.get(SUGGESTIONS)).json()
    assert [s["id"] for s in listed] == [said["id"]]
    assert await _count(Intention) == intentions

    # Another workspace reads none of it.
    await _create_workspace(client, identity, people["outsider"], "Globex")
    assert (await client.get(SUGGESTIONS)).json() == []


async def test_refused_empty_twice_or_too_often(
    client: AsyncClient,
    identity: FakeIdentity,
    people: dict[str, uuid.UUID],  # noqa: F811
) -> None:
    await _create_workspace(client, identity, people["owner"], "Acme Corp")

    assert (await client.post(SUGGESTIONS, json=_body(problem="court"))).status_code == 422
    assert (await client.post(SUGGESTIONS, json={**_body(), "other": 1})).status_code == 422

    assert (await client.post(SUGGESTIONS, json=_body())).status_code == 201
    again = await client.post(SUGGESTIONS, json=_body("  agent   finops "))
    assert again.status_code == 409

    for n in range(module.SUGGESTIONS_A_DAY - 1):
        assert (await client.post(SUGGESTIONS, json=_body(f"Agent {n}"))).status_code == 201
    flood = await client.post(SUGGESTIONS, json=_body("Agent de trop"))
    assert flood.status_code == 429
    assert await _count(CapabilitySuggestion) == module.SUGGESTIONS_A_DAY


async def test_leka_team_lists_and_moves_them_on_the_server(
    client: AsyncClient,
    identity: FakeIdentity,
    people: dict[str, uuid.UUID],  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _create_workspace(client, identity, people["owner"], "Acme Corp")
    said = (await client.post(SUGGESTIONS, json=_body())).json()

    assert await module._list("received") == 0
    line = json.loads(capsys.readouterr().out.splitlines()[0])
    assert line["id"] == said["id"]
    assert line["workspace_id"]

    assert await module._set_status(uuid.UUID(said["id"]), "planned") == 0
    assert (await client.get(SUGGESTIONS)).json()[0]["status"] == "planned"
    # No longer open once declined: suggested again, kept.
    await module._set_status(uuid.UUID(said["id"]), "declined")
    assert (await client.post(SUGGESTIONS, json=_body())).status_code == 201
