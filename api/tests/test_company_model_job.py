"""The company model, the job and the API (LEKA-361), against the database.

The workspace of tests/test_enrichment_job.py — GitHub, Jira and PagerDuty
as normalisation leaves them — resolved and enriched, then built. What
these protect: the model is made of that processed data, one entity per
resolved one, its id kept, with the sources it came from and what it
relates to; a new enrichment versions what changed, removes what is gone —
kept, with its history — and leaves the rest at its version; nothing new is
nothing built; a failed build changes nothing; a new model version builds
again without inventing versions; enrichment tells the model by an event,
routed to the build; the hourly sweep queues what is behind and forgets old
history, never the last success; and members read the model — never
another workspace's.

The build's rules are tests/test_company_model.py's.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.background import Event
from leka.background.routes import ROUTES
from leka.db import session_factory, workspace_scope
from leka.ingestion.enrichment.job import ENRICHED, enrich_workspace
from leka.ingestion.resolution.job import resolve_workspace
from leka.knowledge import ENTITY_KINDS, Entity, EntityType, EntityVersion, ModelRun, Relationship
from leka.knowledge import job as model_job
from leka.knowledge.job import MODEL_JOB, build_workspace, sweep_models
from leka.knowledge.registry import MODEL_VERSION
from tests.conftest import FakeIdentity
from tests.test_enrichment_job import (
    ISSUE,
    NOW,
    PR,
    REPO,
    SARA,
    SERVICE,
    TEAM,
    _normalised,
    _ready,
    _resolved,
    relationship,
)
from tests.test_resolution_job import entity
from tests.test_sources_api import FAKE_KEY, _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/knowledge"


async def _built(workspace_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Normalised, resolved, enriched and built: the model, by key."""
    await _ready(workspace_id)
    await enrich_workspace(workspace_id, now=NOW)
    await build_workspace(workspace_id)
    return await _resolved(workspace_id)


async def _entities(workspace_id: uuid.UUID) -> dict[str, Entity]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(Entity))
            return {row.key: row for row in rows.scalars()}


async def _edges(workspace_id: uuid.UUID) -> set[tuple[uuid.UUID, str, uuid.UUID, str, str]]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(Relationship))
            return {
                (r.from_entity_id, r.type.value, r.to_entity_id, r.origin, r.rule)
                for r in rows.scalars()
            }


async def _versions(workspace_id: uuid.UUID, entity_id: uuid.UUID) -> list[EntityVersion]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(
                select(EntityVersion)
                .where(EntityVersion.entity_id == entity_id)
                .order_by(EntityVersion.version)
            )
            return list(rows.scalars())


async def _runs(workspace_id: uuid.UUID) -> list[ModelRun]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(ModelRun).order_by(ModelRun.started_at))
            return list(rows.scalars())


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    queued: list[dict[str, Any]] = []

    async def capture(job: str, *args: object, **kwargs: Any) -> object:
        queued.append({"job": job, "args": args, **kwargs})
        return object()

    monkeypatch.setattr(model_job, "enqueue_job", capture)
    return queued


# ── the job ──────────────────────────────────────────────────────────────────


async def test_the_model_is_made_of_the_processed_data(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    tools = await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)

    counts = await build_workspace(workspace)

    ids = await _resolved(workspace)
    model = await _entities(workspace)
    # One entity per resolved one — the branch-less, modelled kinds — its id kept.
    assert {key: model[key].id for key in (PR, REPO, ISSUE, SERVICE, TEAM, SARA)} == {
        key: ids[key] for key in (PR, REPO, ISSUE, SERVICE, TEAM, SARA)
    }
    assert {model[key].type.value for key in model} >= {
        "pull_request",
        "repository",
        "issue",
        "service",
        "team",
        "person",
    }
    pr = model[PR]
    assert (pr.lifecycle.value, pr.version, pr.schema_version, pr.removed_at) == (
        "active",
        1,
        ENTITY_KINDS[EntityType.PULL_REQUEST].version,
        None,
    )
    assert pr.attributes["state"] == "merged"
    assert pr.attributes["category"] == "bug"  # enrichment's, where the source said nothing
    assert pr.provenance["attributes"]["state"] == {"origin": "source"}  # type: ignore[index]
    assert pr.provenance["attributes"]["category"]["origin"] == "enrichment"  # type: ignore[index]
    assert {s["source_id"] for s in pr.provenance["sources"]} == {str(tools["github"])}  # type: ignore[attr-defined]
    # Sara is seen by GitHub and Jira: both are where she comes from.
    assert {s["source_id"] for s in model[SARA].provenance["sources"]} == {  # type: ignore[attr-defined]
        str(tools["github"]),
        str(tools["jira"]),
    }

    edges = await _edges(workspace)
    assert (ids[PR], "resolves", ids[ISSUE], "stated", "stated") in edges
    assert (ids[PR], "authored_by", ids[SARA], "stated", "stated") in edges
    assert (ids[REPO], "owned_by", ids[TEAM], "inferred", "inherited") in edges

    [created] = await _versions(workspace, ids[PR])
    assert (created.version, created.changed, created.content["name"]) == (
        1,
        ["created"],
        "Fix doubled refunds",
    )
    [run] = await _runs(workspace)
    assert (run.status, run.model_version, run.error) == ("succeeded", MODEL_VERSION, None)
    assert run.counts == counts
    assert counts["created"] == len(model)
    assert created.run_id == run.id


async def test_a_new_enrichment_versions_what_changed_and_removes_what_is_gone(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _built(workspace)
    github = (await _entities(workspace))[PR].provenance["sources"][0]["source_id"]  # type: ignore[index]

    # PagerDuty's record goes; a new pull request comes.
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM normalised_records WHERE entity_key = :k"), {"k": SERVICE}
            )
            await session.commit()
    new = "github.com/acme/billing-api#42"
    await _normalised(
        workspace,
        uuid.UUID(github),
        entity(new, "Add refund export", type="pull_request"),
        relationships=(relationship("part_of", new, REPO, uuid.UUID(github)),),
        at=NOW + timedelta(hours=1),
    )
    await resolve_workspace(workspace)
    await enrich_workspace(workspace, now=NOW)
    await build_workspace(workspace)

    model = await _entities(workspace)
    service = model[SERVICE]
    assert service.id == ids[SERVICE]  # kept, never deleted
    assert (service.lifecycle.value, service.version) == ("removed", 2)
    assert service.removed_at is not None
    assert [(v.version, v.changed) for v in await _versions(workspace, ids[SERVICE])] == [
        (1, ["created"]),
        (2, ["lifecycle"]),
    ]
    assert model[new].version == 1
    assert model[ISSUE].version == 1  # nothing changed: no version
    assert not [e for e in await _edges(workspace) if ids[SERVICE] in (e[0], e[2])]
    assert [r.status for r in await _runs(workspace)] == ["succeeded", "succeeded"]


async def test_nothing_new_is_nothing_to_build(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    await _built(workspace)

    assert await build_workspace(workspace) == {"status": "nothing"}
    assert len(await _runs(workspace)) == 1


async def test_nothing_enriched_is_nothing_to_build(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    await _ready(workspace)

    assert await build_workspace(workspace) == {"status": "nothing"}
    assert await _runs(workspace) == []


async def test_a_failed_build_changes_nothing_and_says_why(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    await _built(workspace)
    before = {key: (e.id, e.version) for key, e in (await _entities(workspace)).items()}

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(model_job, "build", broken)
    monkeypatch.setattr(model_job, "MODEL_VERSION", MODEL_VERSION + 1)

    with pytest.raises(RuntimeError):
        await build_workspace(workspace)

    assert {key: (e.id, e.version) for key, e in (await _entities(workspace)).items()} == before
    last = (await _runs(workspace))[-1]
    assert (last.status, last.error) == ("failed", "RuntimeError")


async def test_a_new_model_version_builds_again_without_inventing_versions(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    ids = await _built(workspace)
    monkeypatch.setattr(model_job, "MODEL_VERSION", MODEL_VERSION + 1)

    counts = await build_workspace(workspace)

    assert [r.model_version for r in await _runs(workspace)] == [MODEL_VERSION, MODEL_VERSION + 1]
    assert counts["created"] == counts["changed"] == 0
    assert len(await _versions(workspace, ids[PR])) == 1


async def test_a_run_left_running_is_abandoned_by_the_next(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)
    with workspace_scope(workspace):
        async with session_factory() as session:
            session.add(
                ModelRun(
                    workspace_id=workspace,
                    status="running",
                    started_at=datetime.now(UTC) - timedelta(hours=3),
                    model_version=MODEL_VERSION,
                )
            )
            await session.commit()

    await build_workspace(workspace)

    assert [r.status for r in await _runs(workspace)] == ["abandoned", "succeeded"]


# ── how it is started ────────────────────────────────────────────────────────


async def test_enrichment_tells_the_model_and_the_route_queues_the_build(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)
    with workspace_scope(workspace):
        async with session_factory() as session:
            [event] = (await session.execute(select(Event).where(Event.type == ENRICHED))).scalars()
    assert [route.job for route in ROUTES[ENRICHED]] == [
        "leka.knowledge.job.run_model_build_for_event"
    ]
    queued = _capture(monkeypatch)

    assert await model_job._queue_for_event(event.id) == "queued"

    [call] = queued
    assert (call["job"], call["args"], call["concurrency_key"]) == (
        MODEL_JOB,
        (str(workspace),),
        f"model:{workspace}",
    )


async def test_the_sweep_queues_what_is_behind_and_forgets_old_history(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)
    queued = _capture(monkeypatch)

    # Enriched, never built — as every workspace the day this ships.
    await sweep_models()
    assert [c["args"] for c in queued if c["for_workspace_id"] == workspace] == [(str(workspace),)]

    queued.clear()
    await build_workspace(workspace)
    await sweep_models()
    assert not [c for c in queued if c["for_workspace_id"] == workspace]

    with workspace_scope(workspace):
        async with session_factory() as session:
            session.add(
                ModelRun(
                    workspace_id=workspace,
                    status="running",
                    started_at=datetime.now(UTC) - timedelta(hours=4),
                    model_version=MODEL_VERSION,
                )
            )
            await session.commit()
    result = await sweep_models(now=datetime.now(UTC) + timedelta(days=91))

    assert result["abandoned"] >= 1
    assert result["pruned"] >= 1
    # The last success stays: it says what the model was made from.
    assert [r.status for r in await _runs(workspace)] == ["succeeded"]
    assert await _entities(workspace) != {}


# ── the API ──────────────────────────────────────────────────────────────────


async def test_members_read_the_company_model(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    ids = await _built(workspace)
    _as(identity, acme, "member")

    status = (await client.get(f"{API}/model")).json()
    registry = (await client.get(f"{API}/registry")).json()
    prs = (await client.get(f"{API}/entities", params={"type": "pull_request"})).json()
    named = (await client.get(f"{API}/entities", params={"q": "refunds"})).json()
    pr = (await client.get(f"{API}/entities/{ids[PR]}")).json()
    history = (await client.get(f"{API}/entities/{ids[PR]}/versions")).json()
    around = (await client.get(f"{API}/entities/{ids[ISSUE]}/neighbourhood")).json()
    further = (await client.get(f"{API}/entities/{ids[ISSUE]}/neighbourhood?depth=2")).json()

    assert status["pending"] is False
    assert status["last_run"]["status"] == "succeeded"
    assert status["types"]["pull_request"] == 1
    assert status["relationships"]["resolves"] == 1
    kinds = {kind["type"]: kind for kind in registry["entities"]}
    assert set(kinds) >= {"service", "team", "pull_request"}
    assert "topics" in kinds["repository"]["attributes"]
    assert {r["type"] for r in registry["relationships"]} >= {"resolves", "owned_by"}

    assert [e["key"] for e in prs["data"]] == [PR]
    assert {e["key"] for e in named["data"]} >= {PR, ISSUE}
    assert (pr["lifecycle"], pr["version"], pr["versions"]) == ("active", 1, 1)
    assert pr["provenance"]["attributes"]["category"]["origin"] == "enrichment"
    links = {
        (link["direction"], link["type"], link["other"]["key"]) for link in pr["relationships"]
    }
    assert links >= {("out", "resolves", ISSUE), ("out", "part_of", REPO)}
    assert pr["relationships_total"] == len(pr["relationships"])
    assert [(v["version"], v["changed"]) for v in history] == [(1, ["created"])]
    assert around["root"]["id"] == str(ids[ISSUE])
    assert {e["key"] for e in around["entities"]} == {PR, SARA}
    assert {(r["from_entity_id"], r["type"]) for r in around["relationships"]} >= {
        (str(ids[PR]), "resolves"),
        (str(ids[ISSUE]), "assigned_to"),
    }
    # Two steps: the repository, through the pull request that resolves it.
    assert REPO in {e["key"] for e in further["entities"]}


async def test_the_removed_are_read_only_when_asked(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    ids = await _built(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM normalised_records WHERE entity_key = :k"), {"k": SERVICE}
            )
            await session.commit()
    await resolve_workspace(workspace)
    await enrich_workspace(workspace, now=NOW)
    await build_workspace(workspace)
    _as(identity, acme, "member")

    current = (await client.get(f"{API}/entities", params={"limit": 100})).json()["data"]
    removed = (await client.get(f"{API}/entities", params={"lifecycle": "removed"})).json()
    gone = (await client.get(f"{API}/entities/{ids[SERVICE]}")).json()

    assert SERVICE not in {e["key"] for e in current}
    # The team went with the record that named it.
    assert {e["key"] for e in removed["data"]} == {SERVICE, TEAM}
    assert (gone["lifecycle"], gone["versions"]) == ("removed", 2)


async def test_another_workspace_s_entity_is_not_found(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    ids = await _built(acme["acme"])
    _as(identity, acme, "other_admin")  # Globex's

    for path in ("", "/versions", "/neighbourhood"):
        response = await client.get(f"{API}/entities/{ids[PR]}{path}")
        assert response.status_code == 404, path
    listed = (await client.get(f"{API}/entities")).json()
    assert listed["data"] == []
    assert (await client.get(f"{API}/model")).json()["types"] == {}
