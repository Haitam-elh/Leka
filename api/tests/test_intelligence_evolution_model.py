"""Knowledge evolution and Activité, against the database (LEKA-383).

A month of a company, written as its builds would have recorded it:
- payment-api, critical, came to depend on ledger-api, fx-rates and
  tax-service, which appeared one after another, and had three incidents
  this month;
- user-service went from Nadia to Thomas;
- redis-sessions went from every source six days ago while auth-service
  relied on it.

What these protect:
- A real analysis reads the course and finds what it says: the
  dependencies grown, the owner changed, what went while relied on, the
  incidents rising, the architecture moved, the company known less well
  than a month ago — each with the changes that show it, which are the
  model's own.
- Activité reads the period and the one before: the builds, what no source
  shows any more, the incidents, a source failing, what LEKA ran and
  raised, who decided —
  counted by category, day by day, in the reader's zone; the services most
  concerned; the latest first.
- A member reads it; another workspace sees nothing of it.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.api import knowledge as knowledge_api
from leka.connectors.models import (
    Source,
    SourceEvent,
    SourceEventType,
    SourceKind,
    SourceStatus,
)
from leka.db import session_factory, workspace_scope
from leka.intelligence import Finding, QualityPoint, QualityScoreRow
from leka.intelligence.evolution import ANALYZERS as EVOLUTION
from leka.intelligence.job import analyse_workspace
from leka.knowledge import (
    MODEL_VERSION,
    Entity,
    EntityType,
    EntityVersion,
    Lifecycle,
    ModelRun,
    Relationship,
    RelationshipChange,
    RelationshipType,
)
from tests.conftest import FakeIdentity
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)
STATED = {"confidence": 1.0, "origin": "stated", "rule": "stated", "environments": []}


def _ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


async def _company(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    """The company now, and the month it took to get there."""
    ids: dict[str, uuid.UUID] = {}
    runs: dict[float, uuid.UUID] = {}
    with workspace_scope(workspace):
        async with session_factory() as session:
            for days in (30, 20, 14, 12, 8, 6, 3):
                run = ModelRun(
                    workspace_id=workspace,
                    status="succeeded",
                    started_at=_ago(days),
                    finished_at=_ago(days),
                    model_version=MODEL_VERSION,
                    counts={},
                )
                session.add(run)
                await session.flush()
                runs[days] = run.id

            def thing(
                name: str,
                kind: EntityType,
                *,
                appeared: float = 30,
                attributes: dict[str, object] | None = None,
                removed: float | None = None,
            ) -> Entity:
                said = attributes or {}
                row = Entity(
                    workspace_id=workspace,
                    type=kind,
                    key=f"{kind.value}:{name}",
                    name=name,
                    attributes=said,
                    lifecycle=Lifecycle.REMOVED if removed else Lifecycle.ACTIVE,
                    version=2 if removed else 1,
                    provenance={},
                    first_seen_at=_ago(appeared),
                    removed_at=_ago(removed) if removed else None,
                    occurred_at=_ago(appeared) if kind is EntityType.INCIDENT else None,
                )
                session.add(row)
                ids[name] = row.id = uuid.uuid4()
                content = {"name": name, "attributes": said, "lifecycle": "active"}
                session.add(
                    EntityVersion(
                        workspace_id=workspace,
                        entity_id=row.id,
                        version=1,
                        content=content,
                        changed=["created"],
                        schema_version=1,
                        recorded_at=_ago(appeared),
                        run_id=runs.get(appeared),
                    )
                )
                if removed:
                    session.add(
                        EntityVersion(
                            workspace_id=workspace,
                            entity_id=row.id,
                            version=2,
                            content={**content, "lifecycle": "removed"},
                            changed=["lifecycle"],
                            schema_version=1,
                            recorded_at=_ago(removed),
                            run_id=runs[removed],
                        )
                    )
                return row

            service = EntityType.SERVICE
            thing("payment-api", service, attributes={"criticality": "critical"})
            thing("auth-service", service)
            thing("user-service", service)
            thing("redis-sessions", EntityType.INFRA_RESOURCE, removed=6)
            for name, days in (("ledger-api", 20), ("fx-rates", 12), ("tax-service", 3)):
                thing(name, service, appeared=days)
            thing("Nadia Kowalski", EntityType.PERSON)
            thing("Thomas Berger", EntityType.PERSON)
            for n, days in enumerate((2, 9, 16)):
                thing(f"OPS-{n}", EntityType.INCIDENT, appeared=days)
            await session.flush()

            def tie(start: str, kind: RelationshipType, end: str, added: float = 30) -> None:
                session.add(
                    Relationship(
                        workspace_id=workspace,
                        from_entity_id=ids[start],
                        to_entity_id=ids[end],
                        type=kind,
                        first_seen_at=_ago(added),
                        changed_at=_ago(added),
                    )
                )
                moved(start, kind, end, "added", added)

            def moved(
                start: str, kind: RelationshipType, end: str, change: str, days: float
            ) -> None:
                session.add(
                    RelationshipChange(
                        workspace_id=workspace,
                        from_entity_id=ids[start],
                        to_entity_id=ids[end],
                        type=kind.value,
                        change=change,
                        before=STATED if change == "removed" else None,
                        after=STATED if change == "added" else None,
                        recorded_at=_ago(days),
                        run_id=runs.get(days),
                    )
                )

            depends = RelationshipType.DEPENDS_ON
            tie("payment-api", depends, "auth-service")
            for name, days in (("ledger-api", 20), ("fx-rates", 12), ("tax-service", 3)):
                tie("payment-api", depends, name, days)
            moved("Nadia Kowalski", RelationshipType.OWNS, "user-service", "added", 30)
            moved("Nadia Kowalski", RelationshipType.OWNS, "user-service", "removed", 14)
            tie("Thomas Berger", RelationshipType.OWNS, "user-service", 14)
            moved("auth-service", depends, "redis-sessions", "added", 30)
            moved("auth-service", depends, "redis-sessions", "removed", 6)
            for n, days in enumerate((2, 9, 16)):
                tie(f"OPS-{n}", RelationshipType.AFFECTS, "payment-api", days)
            # Its monitoring stopped synchronising yesterday.
            source = Source(
                workspace_id=workspace,
                kind=SourceKind.DATADOG,
                name="acme-eu",
                status=SourceStatus.ERROR,
                config={},
            )
            session.add(source)
            await session.flush()
            session.add(
                SourceEvent(
                    workspace_id=workspace,
                    source_id=source.id,
                    type=SourceEventType.SYNC_FAILED,
                    created_at=_ago(1),
                )
            )
            # What LEKA knew of the company a month ago, and now (LEKA-381).
            measured = uuid.uuid4()
            session.add(
                QualityScoreRow(
                    workspace_id=workspace,
                    key="workspace",
                    scope="workspace",
                    subject_name="workspace",
                    score=0.58,
                    level="low",
                    measured_at=NOW,
                    run_id=measured,
                    since=_ago(2),
                )
            )
            session.add(
                QualityPoint(
                    workspace_id=workspace,
                    key="workspace",
                    scope="workspace",
                    score=0.72,
                    level="medium",
                    measured_at=_ago(40),
                    run_id=measured,
                )
            )
            await session.commit()
    return ids


@pytest.fixture
async def company(acme: dict[str, uuid.UUID]) -> dict[str, uuid.UUID]:
    ids = await _company(acme["acme"])
    await analyse_workspace(acme["acme"], trigger="model", analyzers=EVOLUTION)
    return ids


async def _findings(workspace: uuid.UUID) -> dict[str, Finding]:
    with workspace_scope(workspace):
        async with session_factory() as session:
            rows = await session.execute(select(Finding))
            return {f"{f.code}:{f.subject_name}": f for f in rows.scalars()}


async def test_a_real_analysis_finds_what_the_course_says(
    acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    found = await _findings(workspace)

    assert set(found) == {
        "evolution.dependencies_grew:payment-api",
        "evolution.owner_changed:user-service",
        "evolution.removed_relied:redis-sessions",
        "evolution.incidents_rising:payment-api",
        "evolution.architecture_moved:workspace",
        "evolution.quality_fell:workspace",
    }
    fell = found["evolution.quality_fell:workspace"]
    assert (fell.severity, fell.params["before"], fell.params["after"]) == ("medium", 0.72, 0.58)
    grown = found["evolution.dependencies_grew:payment-api"]
    assert (grown.category, grown.severity, grown.params["added"]) == ("evolution", "medium", 3)
    assert grown.params["names"] == ["fx-rates", "ledger-api", "tax-service"]
    removed = found["evolution.removed_relied:redis-sessions"]
    assert removed.params["names"] == ["auth-service"]
    assert removed.subject_id == company["redis-sessions"]
    moved = found["evolution.architecture_moved:workspace"]
    # What the first build made is no change: three appeared since, one went.
    assert (moved.params["created"], moved.params["removed"]) == (3, 1)
    assert found["evolution.incidents_rising:payment-api"].params["recent"] == 3
    owner = found["evolution.owner_changed:user-service"]
    assert (owner.params["before"], owner.params["after"]) == (
        ["Nadia Kowalski"],
        ["Thomas Berger"],
    )

    # The evidence is the model's own history.
    with workspace_scope(workspace):
        async with session_factory() as session:
            for finding in (grown, removed, owner):
                for said in finding.evidence:
                    table = EntityVersion if said["kind"] == "version" else RelationshipChange
                    assert await session.get(table, uuid.UUID(str(said["id"]))) is not None


async def test_activite_reads_the_period_and_the_one_before(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    company: dict[str, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def queue(workspace_id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr(knowledge_api, "queue_model_build", queue)
    _as(identity, acme, "admin")
    rebuilt = await client.post("/api/v1/knowledge/model/rebuild", json={"reason": "check"})
    assert rebuilt.status_code == 202

    _as(identity, acme, "member")
    response = await client.get(
        "/api/v1/intelligence/activity", params={"days": 7, "timezone": "Europe/Paris"}
    )
    assert response.status_code == 200, response.text
    activity: dict[str, Any] = response.json()

    assert activity["timezone"] == "Europe/Paris"
    assert len(activity["buckets"]) == 8
    kinds = [item["kind"] for item in activity["latest"]]
    assert kinds[0] == "rebuild"  # the latest first
    assert {"model_built", "entity_removed", "incident", "analysis", "finding"} <= set(kinds)
    removed = next(i for i in activity["latest"] if i["kind"] == "entity_removed")
    assert (removed["subject"]["name"], removed["category"]) == ("redis-sessions", "information")
    built = [i for i in activity["latest"] if i["kind"] == "model_built"]
    # The builds of six, three and two days ago: auth-service's tie went
    # with redis-sessions; tax-service came, and its tie; an incident, and
    # what it affects.
    assert sorted(i["count"] for i in built) == [1, 2, 2]
    incident = next(i for i in activity["latest"] if i["kind"] == "incident")
    assert (incident["subject"]["name"], incident["params"]["name"]) == ("payment-api", "OPS-0")
    rebuild = next(i for i in activity["latest"] if i["kind"] == "rebuild")
    assert (rebuild["via"], rebuild["by"]) == ("person", str(acme["admin"]))
    assert rebuild["by_name"].startswith("admin-")

    stats = activity["stats"]
    assert stats["incidents"] == {"value": 1, "previous": 1}
    assert stats["people"] == {"value": 1, "previous": 0}
    assert stats["events"]["value"] == sum(activity["categories"].values())
    # Six findings, and the source that stopped synchronising.
    assert activity["categories"]["alert"] == 7
    failing = next(i for i in activity["latest"] if i["kind"] == "source_event")
    assert (failing["category"], failing["params"]["type"], failing["subject"]["type"]) == (
        "alert",
        "sync_failed",
        "source",
    )
    assert failing["subject"]["name"] == "acme-eu"
    assert (
        sum(sum(b[c] for c in activity["categories"]) for b in activity["buckets"])
        == (stats["events"]["value"])
    )
    [top, *_] = activity["top"]
    assert top["subject"]["name"] == "payment-api"
    assert [p["user_id"] for p in activity["people"]] == [str(acme["admin"])]
    assert activity["people"][0]["role"] == "admin"

    _as(identity, acme, "other_admin")
    elsewhere = (await client.get("/api/v1/intelligence/activity")).json()
    assert elsewhere["latest"] == []
    assert elsewhere["stats"]["events"] == {"value": 0, "previous": 0}
