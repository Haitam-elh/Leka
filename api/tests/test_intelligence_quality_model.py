"""Knowledge quality, end to end (LEKA-381): what the model holds, the
scores kept and their history, the findings, the API.

The small company of test_intelligence_gaps_model, written as a build
writes it, and a few things of it known less well: orphan-worker — tied to
nothing, owned by no one — last shown by a source forty days ago, its
records judged 0.2, its merges uncertain; payment-api's SLA disputed by its
sources, one of its relationships broken by the last build.

What these protect: the model gives each thing's quality signals, counting
what it should; a run keeps a score for each thing and each area — the
workspace, its columns, teams and applications — and a point of history
only when one moves; what is no longer measured is forgotten as it stands,
its history kept, and history past a year pruned; the weak thing is a
finding, with what lowers it; the API serves the summary, the scores by
scope, level and area, one with its factors and history — to a member,
never to another workspace; and in code, what builds on LEKA reads them
(QualityService.of).
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from leka.db import session_factory, system_scope, workspace_scope
from leka.intelligence import (
    ANALYZERS,
    QualityPoint,
    QualityRepository,
    QualityScoreRow,
    QualityService,
)
from leka.intelligence.job import analyse_workspace
from leka.intelligence.repository import IntelligenceSweeper
from leka.knowledge import (
    Entity,
    GraphRepository,
    GraphService,
    Lifecycle,
    RelationshipIssue,
)
from tests.conftest import FakeIdentity
from tests.test_intelligence_gaps_model import _company
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/intelligence"
NOW = datetime.now(UTC).replace(microsecond=0)


async def _weaken(workspace: uuid.UUID, ids: dict[str, uuid.UUID]) -> None:
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                update(Entity)
                .where(Entity.id == ids["orphan-worker"])
                .values(last_seen_at=NOW - timedelta(days=40), quality=0.2, confidence=0.4)
            )
            payment = await session.get(Entity, ids["payment-api"])
            assert payment is not None
            payment.quality = 0.95
            payment.attributes = {**payment.attributes, "sla": "99.9"}
            payment.provenance = {
                **payment.provenance,
                "attributes": {
                    "criticality": {"origin": "source"},
                    "sla": {"origin": "source", "disputed": True},
                    "description": {"origin": "enrichment", "rule": "r", "confidence": 0.7},
                },
                "conflicts": [
                    {
                        "attribute": "sla",
                        "chosen": "99.9",
                        "values": [
                            {"value": "99.9", "source_id": str(ids["GitHub"])},
                            {"value": "99.95", "source_id": str(ids["AWS"])},
                        ],
                    }
                ],
            }
            session.add(
                RelationshipIssue(
                    workspace_id=workspace,
                    from_entity_id=ids["nadia"],
                    to_entity_id=ids["payment-api"],
                    type="owns",
                    issue="multiple",
                    severity="error",
                    origin="stated",
                    rule="stated",
                    confidence=1.0,
                )
            )
            await session.commit()


@pytest.fixture
async def company(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids = await _company(acme["acme"])
    await _weaken(acme["acme"], ids)
    _as(identity, acme, "member")
    return ids


async def _get(client: AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _analysed(workspace: uuid.UUID, now: datetime | None = None) -> dict[str, object]:
    return await analyse_workspace(workspace, trigger="model", analyzers=ANALYZERS, now=now)


async def _rows(workspace: uuid.UUID) -> dict[str, QualityScoreRow]:
    with workspace_scope(workspace):
        async with session_factory() as session:
            return await QualityRepository(session, workspace).current()


async def _points(workspace: uuid.UUID, key: str) -> list[QualityPoint]:
    with workspace_scope(workspace):
        async with session_factory() as session:
            found = await session.execute(
                select(QualityPoint)
                .where(QualityPoint.workspace_id == workspace, QualityPoint.key == key)
                .order_by(QualityPoint.measured_at)
            )
            return list(found.scalars())


async def test_the_model_gives_each_things_quality_signals(
    company: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            graph = GraphService(GraphRepository(session, acme["acme"]))
            found = await graph.standing([company["payment-api"], company["orphan-worker"]])
    payment, orphan = found[company["payment-api"]], found[company["orphan-worker"]]
    assert payment.quality == 0.95
    assert payment.source_ids == (company["GitHub"],)
    assert payment.origins == {"source": 2, "enrichment": 1}
    assert payment.disputed == ("sla",)
    assert payment.issues == (1, 0)
    assert (orphan.confidence, orphan.quality) == (0.4, 0.2)
    assert orphan.last_seen_at == NOW - timedelta(days=40)
    assert orphan.issues == (0, 0)


async def test_a_run_keeps_each_score_and_its_history_only_when_it_moves(
    company: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _analysed(workspace)
    rows = await _rows(workspace)
    orphan = rows[f"entity:{company['orphan-worker']}"]
    payment = rows[f"entity:{company['payment-api']}"]
    assert orphan.level == "low"
    # What costs it most first, across dimensions: unseen for forty days,
    # then tied to nothing, owned by no one.
    assert [lack["code"] for lack in orphan.missing][:3] == ["unseen", "isolated", "no_owner"]
    assert {"isolated", "no_owner", "undocumented"} <= {lack["code"] for lack in orphan.missing}
    assert orphan.provenance["analyzer"] == "quality"
    assert orphan.provenance["sources"] == ["github"]
    # The SLA disputed, a relationship broken: 1 - .35 - .25.
    assert payment.consistency == pytest.approx(0.4)
    assert payment.level == "medium"
    assert {
        "workspace",
        "column:services",
        "column:data",
        f"application:{company['checkout']}",
    } <= set(rows)
    assert f"application:{company['checkout']}" in payment.areas
    # Dormant: asked one question by the gaps, not measured.
    assert f"entity:{company['ledger']}" not in rows
    assert len(await _points(workspace, orphan.key)) == 1

    # Nothing moved: no point.
    await _analysed(workspace)
    assert len(await _points(workspace, orphan.key)) == 1

    # Its records better, a source showing it today: it moves, and its level.
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                update(Entity)
                .where(Entity.id == company["orphan-worker"])
                .values(last_seen_at=NOW, quality=0.9, confidence=1.0)
            )
            await session.commit()
    later = NOW + timedelta(minutes=5)
    await _analysed(workspace, now=later)
    moved = (await _rows(workspace))[orphan.key]
    assert moved.score > orphan.score
    assert moved.level == "medium"
    assert moved.since == later
    points = await _points(workspace, orphan.key)
    assert [p.level for p in points] == ["low", "medium"]


async def test_what_is_no_longer_measured_is_forgotten_its_history_kept(
    company: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _analysed(workspace)
    key = f"entity:{company['orphan-worker']}"
    with workspace_scope(workspace):
        async with session_factory() as session:
            await session.execute(
                update(Entity)
                .where(Entity.id == company["orphan-worker"])
                .values(lifecycle=Lifecycle.REMOVED, removed_at=NOW)
            )
            await session.commit()
    result = await _analysed(workspace)
    assert int(result["unmeasured"]) >= 1  # type: ignore[call-overload]
    assert key not in await _rows(workspace)
    assert len(await _points(workspace, key)) == 1

    with system_scope():
        async with session_factory() as session:
            pruned = await IntelligenceSweeper(session).prune_quality(
                before=NOW + timedelta(days=1)
            )
            await session.commit()
    assert pruned >= 1
    assert await _points(workspace, key) == []


async def test_the_weak_thing_is_a_finding_with_what_lowers_it(
    client: AsyncClient, company: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    await _analysed(acme["acme"])
    found = await _get(client, "/findings", category="quality", status="open")
    weak = [f for f in found["data"] if f["code"] == "quality.low"]
    assert [f["subject"]["name"] for f in weak] == ["orphan-worker"]
    assert weak[0]["severity"] == "medium"
    assert weak[0]["params"]["missing"] == ["unseen", "isolated", "no_owner"]
    detail = await _get(client, f"/findings/{weak[0]['id']}")
    assert detail["provenance"]["analyzer"] == "quality"
    assert {e["name"] for e in detail["evidence"]} == set(weak[0]["params"]["missing"])


async def test_the_api_serves_quality_to_a_member_only(
    client: AsyncClient,
    identity: FakeIdentity,
    company: dict[str, uuid.UUID],
    acme: dict[str, uuid.UUID],
) -> None:
    empty = await _get(client, "/quality")
    assert empty["workspace"] is None
    assert empty["levels"] == {"high": 0, "medium": 0, "low": 0}

    await _analysed(acme["acme"])
    summary = await _get(client, "/quality")
    assert summary["workspace"]["scope"] == "workspace"
    assert summary["workspace"]["subject"]["type"] == "workspace"
    assert summary["levels"]["low"] == 1
    assert summary["weakest"][0]["subject"]["name"] == "orphan-worker"
    assert {c["subject"]["name"] for c in summary["columns"]} >= {"services", "data"}
    assert [a["subject"]["name"] for a in summary["applications"]] == ["checkout"]
    assert len(summary["trend"]) == 1
    assert summary["change"] is None

    weakest = await _get(client, "/quality/scores", scope="entity", sort="score", order="asc")
    assert weakest["data"][0]["subject"]["name"] == "orphan-worker"
    held = await _get(client, "/quality/scores", area=f"application:{company['checkout']}")
    assert {s["subject"]["name"] for s in held["data"]} == {"payment-api", "checkout"}
    low = await _get(client, "/quality/scores", level="low")
    assert [s["subject"]["name"] for s in low["data"]] == ["orphan-worker"]

    key = f"entity:{company['orphan-worker']}"
    one = await _get(client, f"/quality/scores/{key}")
    assert set(one["factors"]) == {"completeness", "freshness", "consistency", "confidence"}
    assert one["factors"]["freshness"]["seen"] == 0.0
    # The conflicts were read (LEKA-382): consistency rests on them.
    assert one["provenance"]["conflicts"] is True
    payment = await _get(client, f"/quality/scores/entity:{company['payment-api']}")
    assert {lack["code"] for lack in payment["missing"]} >= {"disputed", "relationship_error"}
    assert [p["level"] for p in one["history"]] == ["low"]
    assert (await client.get(f"{API}/quality/scores/entity:{uuid.uuid4()}")).status_code == 404

    _as(identity, acme, "other_admin")
    assert (await client.get(f"{API}/quality/scores/{key}")).status_code == 404
    assert (await _get(client, "/quality/scores"))["data"] == []
    assert (await _get(client, "/quality"))["workspace"] is None


async def test_what_builds_on_leka_reads_the_scores(
    company: dict[str, uuid.UUID], acme: dict[str, uuid.UUID]
) -> None:
    await _analysed(acme["acme"])
    with workspace_scope(acme["acme"]):
        async with session_factory() as session:
            found = await QualityService(QualityRepository(session, acme["acme"])).of(
                [company["payment-api"], company["orphan-worker"], uuid.uuid4()]
            )
    assert set(found) == {company["payment-api"], company["orphan-worker"]}
    assert found[company["orphan-worker"]].level == "low"
