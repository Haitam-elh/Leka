"""The model's course, end to end (LEKA-383): what changed, what it was,
what it held — and the operations that change it, through real builds.

The workspace of tests/test_company_model_job.py: GitHub, Jira and
PagerDuty, resolved, enriched and built for real. Its course is moved by
what moves a model: a validated fact closes the pull request (a version),
an owner refuted takes acme/billing-api's inherited owner away (a
relationship change).

What these protect:
- Each build that changes the model writes what it holds; a model built
  again with nothing new writes nothing — it is not built.
- What changed is read over time: each version against the one before,
  narrowed to a thing, a kind, a kind of change; day by day, in the
  reader's zone, with the period before.
- An entity's whole course, and what it was at a moment: its version then,
  its relationships rewound.
- A version restored goes through a real build, over what the facts and
  the sources say, its operation in the provenance — and undone, the model
  is as it was. What restores nothing, or is its own version, is refused.
- A rebuild asked is built though nothing new came, and says what it did;
  where nothing was ever enriched, it says that.
- A workspace's first snapshot rebuilds the weeks before from its history;
  what the history does not reach is not invented.
- The sweep queues the rebuilds asked and forgets old snapshots — never the
  latest.
- A member reads and does not change the course; another workspace sees
  nothing.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.api import knowledge as knowledge_api
from leka.db import session_factory, workspace_scope
from leka.knowledge import (
    Assertion,
    AssertionRepository,
    EntityVersion,
    ModelOperation,
    ModelSnapshot,
)
from leka.knowledge import job as model_job
from leka.knowledge.job import build_workspace, sweep_models
from tests.conftest import FakeIdentity
from tests.test_company_model_job import _built, _capture, _entities, _runs
from tests.test_enrichment_job import PR, REPO, TEAM
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/knowledge"


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    asked: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID) -> bool:
        asked.append(workspace_id)
        return True

    monkeypatch.setattr(knowledge_api, "queue_model_build", queue)
    return asked


async def _fact(workspace: uuid.UUID, **fields: object) -> None:
    """A fact validated, as À valider writes one (LEKA-380)."""
    said: dict[str, Any] = {
        "id": uuid.uuid4(),
        "kind": "attribute",
        "rule": "enrichment.test",
        "confidence": 0.9,
        "overrides": True,
        "provenance": {"candidate_id": str(uuid.uuid4()), "decided_via": "person"},
        **fields,
    }
    with workspace_scope(workspace):
        async with session_factory() as session:
            await AssertionRepository(session, workspace).put(Assertion(**said))
            await session.commit()


async def _closed(workspace: uuid.UUID, ids: dict[str, uuid.UUID]) -> None:
    """The pull request closed by a validated fact; acme/billing-api's
    inherited owner refuted — then built."""
    await _fact(workspace, entity_id=ids[PR], attribute="state", value="closed")
    await _fact(
        workspace,
        kind="absence",
        from_id=ids[REPO],
        to_id=ids[TEAM],
        type="owned_by",
        overrides=False,
    )
    await build_workspace(workspace)


async def _snapshots(workspace: uuid.UUID) -> list[ModelSnapshot]:
    with workspace_scope(workspace):
        async with session_factory() as session:
            rows = await session.execute(select(ModelSnapshot).order_by(ModelSnapshot.built_at))
            return list(rows.scalars())


async def _sql(workspace: uuid.UUID, statement: str, **values: object) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(text(statement), {"w": workspace, **values})
            await session.commit()


async def _get(client: AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _post(client: AsyncClient, path: str, body: dict[str, Any], code: int = 200) -> Any:
    response = await client.post(f"{API}{path}", json=body)
    assert response.status_code == code, response.text
    return response.json()


# ── snapshots ────────────────────────────────────────────────────────────────


async def test_each_build_that_changes_the_model_writes_what_it_holds(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _built(workspace)

    [first] = await _snapshots(workspace)
    [run] = await _runs(workspace)
    model = await _entities(workspace)
    assert (first.run_id, first.reconstructed) == (run.id, False)
    assert first.counts["types"]["pull_request"] == 1  # type: ignore[index]
    assert sum(first.counts["types"].values()) == len(model)  # type: ignore[attr-defined]
    assert first.counts["relationships"]["owned_by"] >= 1  # type: ignore[index]
    # acme/billing-api: inherited from Payments, said by GitHub alone.
    assert first.measures["repository"] == {
        "total": 1,
        "owned": 1,
        "documented": 0,
        "corroborated": 0,
        "connected": 1,
    }

    # Nothing new: not built, nothing written.
    assert (await build_workspace(workspace))["status"] == "nothing"
    assert len(await _snapshots(workspace)) == 1

    await _closed(workspace, ids)
    later = (await _snapshots(workspace))[-1]
    assert later.measures["repository"]["owned"] == 0  # type: ignore[index]
    assert len(await _snapshots(workspace)) == 2


# ── what changed, over time ──────────────────────────────────────────────────


async def test_what_changed_is_read_over_time(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    ids = await _built(workspace)
    await _closed(workspace, ids)
    model = await _entities(workspace)
    _as(identity, acme, "member")

    latest = (await _get(client, "/evolution"))["data"]
    closed = next(c for c in latest if c["entity_id"] == str(ids[PR]) and c["version"] == 2)
    assert latest.index(closed) < len(model)  # the latest first
    assert (closed["change"], closed["name"], closed["entity"]["name"]) == (
        "changed",
        "Fix doubled refunds",
        "Fix doubled refunds",
    )
    assert closed["fields"] == [
        {"field": "attributes.state", "before": "merged", "after": "closed"}
    ]

    created = await _get(client, "/evolution", change="created", limit=100)
    assert len(created["data"]) == len(model)
    assert all(c["fields"] == [] and c["version"] == 1 for c in created["data"])
    of_pr = await _get(client, "/evolution", entity_id=str(ids[PR]))
    assert [c["version"] for c in of_pr["data"]] == [2, 1]
    changed = await _get(client, "/evolution", type="pull_request", change="changed")
    assert [c["entity_id"] for c in changed["data"]] == [str(ids[PR])]
    assert (await _get(client, "/evolution", change="removed"))["data"] == []

    summary = await _get(client, "/evolution/summary", timezone="Europe/Paris")
    assert summary["timezone"] == "Europe/Paris"
    assert len(summary["buckets"]) in (7, 8)
    totals = summary["totals"]
    assert (totals["created"], totals["changed"], totals["relationships_removed"]) == (
        len(model),
        1,
        1,
    )
    assert totals["relationships_added"] >= 1
    assert summary["previous"]["created"] == 0
    today = summary["buckets"][-1]
    assert today["changed"] == 1

    response = await client.get(
        f"{API}/evolution/summary",
        params={"since": "2026-10-07T00:00:00Z", "until": "2026-10-01T00:00:00Z"},
    )
    assert response.status_code == 422


async def test_an_entity_s_course_and_what_it_was_at_a_moment(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    ids = await _built(workspace)
    between = datetime.now(UTC)
    await _closed(workspace, ids)
    _as(identity, acme, "member")

    history = await _get(client, f"/entities/{ids[PR]}/history")
    assert [v["version"] for v in history["versions"]] == [2, 1]
    assert [v["change"] for v in history["versions"]] == ["changed", "created"]
    assert history["operations"] == []
    assert history["horizon"] is None
    repository = await _get(client, f"/entities/{ids[REPO]}/history")
    went = [c for c in repository["relationships"] if c["change"] == "removed"]
    assert [(c["type"], c["to_entity"]["id"]) for c in went] == [("owned_by", str(ids[TEAM]))]

    then = await _get(client, f"/entities/{ids[REPO]}/at", moment=between.isoformat())
    assert (then["existed"], then["complete"], then["version"]["version"]) == (True, True, 1)
    owners = [r for r in then["relationships"] if r["type"] == "owned_by"]
    assert [(o["direction"], o["other"]["id"], o["origin"]) for o in owners] == [
        ("outgoing", str(ids[TEAM]), "inferred")
    ]
    now = await _get(client, f"/entities/{ids[REPO]}/at", moment=datetime.now(UTC).isoformat())
    assert not [r for r in now["relationships"] if r["type"] == "owned_by"]

    pr_then = await _get(client, f"/entities/{ids[PR]}/at", moment=between.isoformat())
    assert pr_then["content"]["attributes"]["state"] == "merged"
    before = await _get(
        client, f"/entities/{ids[PR]}/at", moment=(between - timedelta(days=1)).isoformat()
    )
    assert (before["existed"], before["version"], before["relationships"]) == (False, None, [])

    missing = await client.get(f"{API}/entities/{uuid.uuid4()}/history")
    assert missing.status_code == 404


# ── restoring a version ──────────────────────────────────────────────────────


async def test_a_version_restored_goes_through_a_real_build_and_is_undone(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _built(workspace)
    await _closed(workspace, ids)
    _as(identity, acme, "admin")

    operation = await _post(
        client,
        f"/entities/{ids[PR]}/restore",
        {"version": 1, "reason": "Closed by mistake"},
        code=202,
    )
    assert (operation["kind"], operation["status"], operation["version"]) == (
        "restore",
        "applied",
        1,
    )
    assert operation["detail"]["attributes"] == {"state": {"before": "closed", "after": "merged"}}
    assert operation["detail"]["from_version"] == 2
    assert (operation["reason"], operation["entity"]["id"]) == ("Closed by mistake", str(ids[PR]))
    assert builds == [workspace]

    await build_workspace(workspace)
    pr = (await _entities(workspace))[PR]
    assert (pr.attributes["state"], pr.version) == ("merged", 3)
    said = pr.provenance["attributes"]["state"]  # type: ignore[index]
    assert (said["origin"], said["rule"], said["operation_id"], said["replaced"]) == (
        "accepted",
        "restore",
        operation["id"],
        "closed",
    )
    listed = await _get(client, "/operations", kind="restore")
    assert [o["id"] for o in listed] == [operation["id"]]

    undone = await _post(client, f"/operations/{operation['id']}/undo", {"reason": "Not a mistake"})
    assert (undone["status"], undone["detail"]["undo_reason"]) == ("undone", "Not a mistake")
    assert undone["undone_at"] is not None
    await build_workspace(workspace)
    pr = (await _entities(workspace))[PR]
    assert (pr.attributes["state"], pr.version) == ("closed", 4)
    assert "operation_id" not in pr.provenance["attributes"]["state"]  # type: ignore[index]

    refused = [
        (f"/operations/{operation['id']}/undo", {}, 409),
        (f"/entities/{ids[PR]}/restore", {"version": 4}, 409),
        (f"/entities/{ids[PR]}/restore", {"version": 2}, 409),
        (f"/entities/{ids[PR]}/restore", {"version": 99}, 404),
        (f"/entities/{uuid.uuid4()}/restore", {"version": 1}, 404),
        (f"/operations/{uuid.uuid4()}/undo", {}, 404),
    ]
    for path, body, code in refused:
        response = await client.post(f"{API}{path}", json=body)
        assert response.status_code == code, (path, response.text)


# ── rebuilding ───────────────────────────────────────────────────────────────


async def test_a_rebuild_asked_is_built_and_says_what_it_did(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
) -> None:
    workspace = acme["acme"]
    await _built(workspace)
    model = await _entities(workspace)
    _as(identity, acme, "admin")

    asked = await _post(client, "/model/rebuild", {"reason": "Registry fixed"}, code=202)
    assert (asked["kind"], asked["status"], asked["run_id"]) == ("rebuild", "queued", None)
    again = await _post(client, "/model/rebuild", {}, code=202)
    assert again["id"] == asked["id"]

    counts = await build_workspace(workspace)
    assert counts["unchanged"] == len(model)
    [done] = await _get(client, "/operations", kind="rebuild")
    runs = await _runs(workspace)
    assert (done["status"], done["run_id"], done["reason"]) == (
        "done",
        str(runs[-1].id),
        "Registry fixed",
    )
    assert done["detail"]["counts"]["unchanged"] == len(model)
    assert done["detail"]["counts"]["created"] == 0
    # Asked, it is written down even though nothing changed.
    assert len(await _snapshots(workspace)) == 2
    assert (await build_workspace(workspace))["status"] == "nothing"

    # Where nothing was ever enriched, there is nothing to build from.
    _as(identity, acme, "other_admin")
    await _post(client, "/model/rebuild", {}, code=202)
    await build_workspace(acme["globex"])
    [failed] = await _get(client, "/operations")
    assert (failed["status"], failed["detail"]) == ("failed", {"error": "nothing_enriched"})


async def test_a_rebuild_whose_build_fails_says_why(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = acme["acme"]
    await _built(workspace)
    _as(identity, acme, "admin")
    asked = await _post(client, "/model/rebuild", {}, code=202)

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(model_job, "build", broken)
    with pytest.raises(RuntimeError):
        await build_workspace(workspace)

    [failed] = await _get(client, "/operations", kind="rebuild")
    runs = await _runs(workspace)
    assert (failed["id"], failed["status"], failed["detail"]) == (
        asked["id"],
        "failed",
        {"error": "RuntimeError"},
    )
    assert failed["run_id"] == str(runs[-1].id)
    assert runs[-1].status == "failed"


# ── the history's own snapshots ──────────────────────────────────────────────


async def test_the_first_snapshot_rebuilds_the_weeks_before_from_the_history(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
) -> None:
    workspace = acme["acme"]
    await _built(workspace)
    # The model's history began twenty days ago; no snapshot was written.
    for table in ("entity_versions", "relationship_changes"):
        await _sql(
            workspace,
            f"UPDATE {table} SET recorded_at = recorded_at - interval '20 days' "  # noqa: S608
            "WHERE workspace_id = :w",
        )
    await _sql(workspace, "DELETE FROM model_snapshots WHERE workspace_id = :w")
    _as(identity, acme, "admin")
    await _post(client, "/model/rebuild", {}, code=202)
    await build_workspace(workspace)

    taken = await _snapshots(workspace)
    assert [s.reconstructed for s in taken] == [True, True, False]
    now = taken[-1].built_at
    assert [round((now - s.built_at) / timedelta(days=1)) for s in taken] == [14, 7, 0]
    assert taken[0].counts == taken[-1].counts
    assert taken[0].measures["repository"]["corroborated"] is None  # type: ignore[index]

    listed = await _get(client, "/snapshots")
    assert [s["reconstructed"] for s in listed] == [True, True, False]
    ten_days = (now - timedelta(days=10)).isoformat()
    kept = await _get(client, "/snapshots/at", moment=ten_days)
    assert (kept["id"], kept["reconstructed"]) == (str(taken[0].id), True)
    assert kept["types"] == taken[0].counts["types"]
    far = await client.get(
        f"{API}/snapshots/at", params={"moment": (now - timedelta(days=30)).isoformat()}
    )
    assert far.status_code == 404

    # None kept: rebuilt on the spot, not written.
    await _sql(workspace, "DELETE FROM model_snapshots WHERE workspace_id = :w")
    rebuilt = await _get(client, "/snapshots/at", moment=ten_days)
    assert (rebuilt["id"], rebuilt["reconstructed"]) == (None, True)
    assert rebuilt["types"] == kept["types"]
    assert await _snapshots(workspace) == []


# ── the sweep ────────────────────────────────────────────────────────────────


async def test_the_sweep_queues_the_rebuilds_asked_and_forgets_old_snapshots(
    monkeypatch: pytest.MonkeyPatch, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _built(workspace)
    old = datetime.now(UTC) - timedelta(days=500)
    with workspace_scope(workspace):
        async with session_factory() as session:
            session.add(ModelSnapshot(workspace_id=workspace, built_at=old, counts={}, measures={}))
            session.add(
                ModelOperation(workspace_id=workspace, kind="rebuild", status="queued", detail={})
            )
            await session.commit()
    queued = _capture(monkeypatch)

    result = await sweep_models()

    assert str(workspace) in [q["args"][0] for q in queued]
    assert result["queued"] >= 1
    [kept] = await _snapshots(workspace)
    assert kept.built_at > old


# ── who may ─────────────────────────────────────────────────────────────────


async def test_a_member_reads_and_does_not_change_the_course_another_workspace_sees_nothing(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
) -> None:
    workspace = acme["acme"]
    ids = await _built(workspace)
    await _closed(workspace, ids)

    _as(identity, acme, "member")
    assert (await _get(client, "/snapshots"))[0]["reconstructed"] is False
    for path, body in (
        (f"/entities/{ids[PR]}/restore", {"version": 1}),
        ("/model/rebuild", {}),
        (f"/operations/{uuid.uuid4()}/undo", {}),
    ):
        assert (await client.post(f"{API}{path}", json=body)).status_code == 403

    _as(identity, acme, "other_admin")
    for path in (f"/entities/{ids[PR]}/history", f"/entities/{ids[PR]}/at"):
        response = await client.get(
            f"{API}{path}", params={"moment": datetime.now(UTC).isoformat()}
        )
        assert response.status_code == 404
    assert (await _get(client, "/evolution"))["data"] == []
    assert await _get(client, "/snapshots") == []
    restore = await client.post(f"{API}/entities/{ids[PR]}/restore", json={"version": 1})
    assert restore.status_code == 404
    assert builds == []
    with workspace_scope(workspace):
        async with session_factory() as session:
            versions = await session.execute(
                select(EntityVersion).where(EntityVersion.entity_id == ids[PR])
            )
            assert len(list(versions.scalars())) == 2
