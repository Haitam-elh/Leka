"""The demonstration, from opening it to a first answer (LEKA-449).

A person with no tool connected opens the demonstration: a workspace of
their own, marked so, with Nova Retail's four sources — GitHub, Jira,
Datadog, Confluence — which their connectors replay from
leka/connectors/demo/world.py. Each goes the whole way with the real
stages, run by hand where the job loop would queue them, and a question
asked in it is answered from what they hold.

What these protect:
- One demonstration per person, entered when opened; opened again, the
  same; started afresh, the one before erased.
- Its sources read with no request leaving LEKA: the network refuses.
- The company model holds Nova Retail as its tools say it — its services,
  the deployment of yesterday, the incident open since — and a question
  about it is answered, citing what says so.
- What would reach a real system is refused in it, whoever asks: a source
  added, an invitation, a payment.
- Nothing of it is anyone else's, nothing of anyone else's in it.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.connectors import Source
from leka.connectors import network as connectors_network
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion import sync as sync_module
from leka.ingestion.enrichment import job as enrichment_job
from leka.ingestion.enrichment.job import enrich_workspace
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.normalisation.job import normalise_source
from leka.ingestion.parsing.job import parse_source
from leka.ingestion.resolution.job import resolve_workspace
from leka.ingestion.sync import sync_source
from leka.ingestion.validation.job import validate_source
from leka.intentions.processing import analyse_intention
from leka.knowledge import Entity
from leka.knowledge.job import build_workspace
from leka.platform import LocalObjectStore, Workspace
from leka.platform import service as platform_service
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """No network at all: a request leaving LEKA fails the test. A local
    store; the jobs run by hand, not queued."""

    def nowhere(*args: object, **kwargs: object) -> None:
        msg = "a demonstration reached the network"
        raise AssertionError(msg)

    monkeypatch.setattr(connectors_network.PublicTransport, "__init__", nowhere)
    from leka.platform import storage

    monkeypatch.setattr(storage, "_store", LocalObjectStore(tmp_path))

    async def queued(job: str, *args: object, **kwargs: object) -> object:
        return object()

    for module in (sync_module, pipeline_module, enrichment_job):
        monkeypatch.setattr(module, "enqueue_job", queued)
    monkeypatch.setattr(platform_service, "enqueue", queued)
    yield


@pytest.fixture
async def demos(acme: dict[str, uuid.UUID]) -> AsyncIterator[dict[str, uuid.UUID]]:
    """Acme's people; their demonstrations erased afterwards."""
    yield acme
    with system_scope():
        async with session_factory() as session:
            await session.execute(
                text(
                    "DELETE FROM workspaces WHERE demo AND id IN (SELECT workspace_id "
                    "FROM memberships WHERE user_id IN (:a, :m))"
                ),
                {"a": acme["admin"], "m": acme["member"]},
            )
            await session.commit()


async def _open(client: AsyncClient, *, fresh: bool = False) -> dict[str, Any]:
    response = await client.post(f"{API}/demo", params={"fresh": "true"} if fresh else None)
    assert response.status_code == 200, response.text
    opened: dict[str, Any] = response.json()
    return opened


async def _read(workspace: uuid.UUID) -> list[Source]:
    """Its sources, each from its pass to validated records; then the model."""
    with workspace_scope(workspace):
        async with session_factory() as session:
            sources = list((await session.scalars(select(Source))).all())
    for source in sources:
        assert (await sync_source(workspace, source.id, full=True)).status == "succeeded"
        for stage in (extract_source, parse_source, normalise_source, validate_source):
            await stage(workspace, source.id)
    await resolve_workspace(workspace)
    await enrich_workspace(workspace)
    await build_workspace(workspace)
    return sources


async def _names(workspace: uuid.UUID) -> dict[str, set[str]]:
    with workspace_scope(workspace):
        async with session_factory() as session:
            rows = (await session.execute(select(Entity.type, Entity.name))).tuples().all()
    found: dict[str, set[str]] = {}
    for kind, name in rows:
        found.setdefault(str(kind), set()).add(name)
    return found


async def test_one_demonstration_per_person_entered_when_opened_and_made_afresh(
    client: AsyncClient, identity: FakeIdentity, demos: dict[str, uuid.UUID]
) -> None:
    _as(identity, demos, "admin")
    opened = await _open(client)
    demo = uuid.UUID(opened["workspace"]["id"])
    assert opened["created"] is True
    assert opened["workspace"]["demo"] is True
    # Entered: the session is in it, its sources there, all four.
    assert identity.active_workspace == demo
    current = (await client.get(f"{API}/workspaces/current")).json()
    assert current["workspace"]["demo"] is True
    sources = (await client.get(f"{API}/sources")).json()["data"]
    assert sorted(s["type"] for s in sources) == ["confluence", "datadog", "github", "jira"]
    # Opened again: the same one.
    assert (await _open(client))["workspace"]["id"] == str(demo)
    # Afresh: a new one, the one before gone.
    again = await _open(client, fresh=True)
    assert again["created"] is True and again["workspace"]["id"] != str(demo)
    with system_scope():
        async with session_factory() as session:
            assert await session.get(Workspace, demo) is None


async def test_nova_retail_is_read_with_no_request_leaving_and_a_question_answered(
    client: AsyncClient, identity: FakeIdentity, demos: dict[str, uuid.UUID]
) -> None:
    _as(identity, demos, "admin")
    demo = uuid.UUID((await _open(client))["workspace"]["id"])
    identity.active_workspace = demo
    await _read(demo)

    names = await _names(demo)
    # One each, its code, its catalogue and its monitors saying the same
    # service — named « nova-checkout-api » or « Nova Checkout API », as the
    # tool read first says it.
    services = sorted("-".join(n.lower().split()) for n in names["service"])
    for slug in ("nova-checkout-api", "nova-catalog-api", "nova-storefront"):
        assert services.count(slug) == 1, names
    assert any("Paiements refusés" in n for n in names.get("incident", set())), names
    assert names.get("deployment"), names

    response = await client.post(
        f"{API}/intentions", json={"text": "Qui est responsable de nova-checkout-api ?"}
    )
    assert response.status_code == 201, response.text
    intention = response.json()["intention"]
    await analyse_intention(demo, uuid.UUID(intention["id"]), trigger="created")
    analysis = (await client.get(f"{API}/intentions/{intention['id']}/analysis")).json()
    result = analysis["result"]
    assert analysis["status"] in ("complete", "partial"), analysis["status"]
    assert result["evidence"], result
    # Its team, as GitHub, the catalogue and the documentation say it.
    assert any("Paiements" in str(n.get("params")) for n in result["summary"]), result["summary"]
    consulted = {s["name"] for s in result["explanation"]["consulted"]}
    assert consulted & {"GitHub Nova", "Jira Nova", "Datadog Nova", "Confluence Nova"}


async def test_what_would_reach_a_real_system_is_refused_in_it(
    client: AsyncClient, identity: FakeIdentity, demos: dict[str, uuid.UUID]
) -> None:
    _as(identity, demos, "admin")
    await _open(client)
    for method, path, body in (
        ("post", "/sources", {"type": "github", "display_name": "Mine", "credentials": {}}),
        ("post", "/members/invite", {"email": "someone@acme.example", "role": "member"}),
        ("post", "/billing/checkout", {"plan": "growth", "interval": "month"}),
    ):
        response = await getattr(client, method)(f"{API}{path}", json=body)
        assert response.status_code == 403, (path, response.text)
        assert "demonstration" in response.text, (path, response.text)


async def test_nothing_of_it_is_anyone_else_s_nor_theirs_in_it(
    client: AsyncClient, identity: FakeIdentity, demos: dict[str, uuid.UUID]
) -> None:
    _as(identity, demos, "admin")
    demo = uuid.UUID((await _open(client))["workspace"]["id"])
    await _read(demo)
    # Acme, the person's real workspace, holds none of Nova Retail.
    assert not (await _names(demos["acme"])).get("service")
    _as(identity, demos, "admin")
    assert not [
        s for s in (await client.get(f"{API}/sources")).json()["data"] if "Nova" in s["name"]
    ]
    # Another member of Acme has no demonstration of theirs, and cannot enter this one.
    _as(identity, demos, "member")
    refused = await client.post(f"{API}/workspaces/{demo}/switch")
    assert refused.status_code == 403
