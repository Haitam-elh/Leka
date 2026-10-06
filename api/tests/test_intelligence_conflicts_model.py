"""Knowledge conflicts, end to end (LEKA-382): found, weighed, settled,
applied — and undone.

TWO COMPANIES.

The first is written into the model as a build writes it. payment-api's
sources disagree twice:
- its SLA: 99.95 to GitHub, 99.9 to Datadog, both a day ago;
- its region: eu-west-1 to GitHub, two hundred days ago, eu-west-3 to AWS,
  yesterday.

Its owner is said twice too: GitHub states Payments, and Jira infers that
Platform owns it. A ticket's disagreement is no conflict; nor is a removed
thing's.

The second is the pipeline's own (tests/test_company_model_job.py), built
for real, so that a decision goes through a real build. On it, two
conflicts are written as a run would:
- the pull request's state;
- acme/billing-api's owner.

What these protect:
- Each disagreement is found and weighed, and the best side recommended:
  the cloud on the region (clearly), the stated owner over the inferred
  one, and the SLA by its families until the workspace's rule makes it
  Datadog's.
- A person keeps a side — remembering its source, if they say so — or
  dismisses it, or reopens it. Each decision's facts are written or
  withdrawn with it, and each is kept in the history.
- A decision stands from one run to the next, until a value no one decided
  on appears.
- A conflict no longer disagreed on is gone and cannot be decided.
- A member reads and does not decide; another workspace sees nothing.
- Through a real build: the value kept is the model's, no longer disputed,
  with the decision in its provenance. The owner refuted is left out.
  Reopened, the model is as its sources say.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from leka.api import intelligence as intelligence_api
from leka.connectors.models import Source, SourceKind, SourceStatus
from leka.db import session_factory, workspace_scope
from leka.intelligence import ANALYZERS, KnowledgeConflict
from leka.intelligence.job import analyse_workspace
from leka.knowledge import (
    Entity,
    EntityType,
    Lifecycle,
    ModelAssertion,
    Relationship,
    RelationshipType,
)
from leka.knowledge.job import build_workspace
from tests.conftest import FakeIdentity
from tests.test_company_model_job import _built, _entities
from tests.test_enrichment_job import PR, REPO, SARA, TEAM
from tests.test_sources_api import _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/intelligence"
NOW = datetime.now(UTC).replace(microsecond=0)


def _said(value: object, source: uuid.UUID, days: float) -> dict[str, object]:
    return {
        "value": value,
        "source_id": str(source),
        "observed_at": (NOW - timedelta(days=days)).isoformat(),
    }


def _side(value: str, edges: list[dict[str, str]] | None = None) -> dict[str, object]:
    """A side as a run writes it."""
    return {
        "value": value,
        "ref_id": None,
        "origin": None,
        "sources": [],
        "authority": 0.5,
        "freshness": 0.5,
        "corroboration": 0.0,
        "score": 0.4,
        "edges": edges or [],
    }


async def _company(workspace: uuid.UUID) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    with workspace_scope(workspace):
        async with session_factory() as session:
            for kind, name in (
                (SourceKind.GITHUB, "acme/backend"),
                (SourceKind.DATADOG, "acme-eu"),
                (SourceKind.JIRA, "OPS"),
                (SourceKind.AWS, "production"),
            ):
                source = Source(
                    workspace_id=workspace,
                    kind=kind,
                    name=name,
                    status=SourceStatus.ACTIVE,
                    config={},
                    last_synced_at=NOW,
                )
                session.add(source)
                ids[name] = source.id = uuid.uuid4()
            await session.flush()
            github, datadog, aws = ids["acme/backend"], ids["acme-eu"], ids["production"]

            def thing(
                name: str,
                type_: EntityType,
                *,
                conflicts: list[dict[str, object]] | None = None,
                lifecycle: Lifecycle = Lifecycle.ACTIVE,
                **attributes: object,
            ) -> None:
                row = Entity(
                    workspace_id=workspace,
                    type=type_,
                    key=f"{type_.value}:{name}",
                    name=name,
                    attributes=attributes,
                    provenance={
                        "sources": [{"source_id": str(github), "key": name, "kind": "id"}],
                        "conflicts": conflicts or [],
                    },
                    lifecycle=lifecycle,
                    removed_at=NOW if lifecycle is Lifecycle.REMOVED else None,
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                )
                session.add(row)
                ids[name] = row.id = uuid.uuid4()

            thing(
                "payment-api",
                EntityType.SERVICE,
                sla="99.95",
                region="eu-west-1",
                conflicts=[
                    {
                        "attribute": "sla",
                        "chosen": "99.95",
                        "values": [_said("99.95", github, 1), _said("99.9", datadog, 1)],
                    },
                    {
                        "attribute": "region",
                        "chosen": "eu-west-1",
                        "values": [_said("eu-west-1", github, 200), _said("eu-west-3", aws, 1)],
                    },
                ],
            )
            thing(
                "PAY-42",
                EntityType.ISSUE,
                conflicts=[
                    {
                        "attribute": "status",
                        "chosen": "open",
                        "values": [_said("open", github, 1), _said("closed", datadog, 1)],
                    }
                ],
            )
            thing(
                "legacy-api",
                EntityType.SERVICE,
                lifecycle=Lifecycle.REMOVED,
                conflicts=[
                    {
                        "attribute": "sla",
                        "chosen": "99",
                        "values": [_said("99", github, 1), _said("98", datadog, 1)],
                    }
                ],
            )
            thing("Payments", EntityType.TEAM)
            thing("Platform", EntityType.TEAM)
            await session.flush()
            for start, tie, end, origin, said in (
                ("payment-api", RelationshipType.OWNED_BY, "Payments", "stated", github),
                ("Platform", RelationshipType.OWNS, "payment-api", "inferred", ids["OPS"]),
            ):
                session.add(
                    Relationship(
                        workspace_id=workspace,
                        from_entity_id=ids[start],
                        to_entity_id=ids[end],
                        type=tie,
                        confidence=1.0 if origin == "stated" else 0.7,
                        origin=origin,
                        rule="stated" if origin == "stated" else "component",
                        provenance=[{"source_id": str(said)}],
                        changed_at=NOW - timedelta(days=2),
                    )
                )
            await session.commit()
    return ids


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    asked: list[uuid.UUID] = []

    async def queue(workspace_id: uuid.UUID) -> bool:
        asked.append(workspace_id)
        return True

    monkeypatch.setattr(intelligence_api, "queue_model_build", queue)
    return asked


@pytest.fixture
async def company(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    ids = await _company(acme["acme"])
    await analyse_workspace(acme["acme"], trigger="model", analyzers=ANALYZERS)
    _as(identity, acme, "admin")
    return ids


async def _get(client: AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _conflicts(workspace: uuid.UUID) -> dict[str, KnowledgeConflict]:
    with workspace_scope(workspace):
        async with session_factory() as session:
            rows = await session.execute(select(KnowledgeConflict))
            return {c.about: c for c in rows.scalars()}


async def _facts(workspace: uuid.UUID) -> list[ModelAssertion]:
    with workspace_scope(workspace):
        async with session_factory() as session:
            return list((await session.execute(select(ModelAssertion))).scalars())


async def _post(client: AsyncClient, path: str, body: dict[str, Any] | None = None) -> Any:
    response = await client.post(f"{API}{path}", json=body if body is not None else {})
    assert response.status_code in (200, 201), response.text
    return response.json()


# ── found, weighed, recommended ────────────────────────────────────────────


async def test_each_disagreement_is_found_weighed_and_recommended(
    client: AsyncClient, acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID]
) -> None:
    found = await _conflicts(acme["acme"])
    # A ticket's disagreement is no conflict, nor a removed thing's.
    assert set(found) == {"sla", "region", "owner"}
    assert all(c.status == "open" for c in found.values())

    region = found["region"]
    assert [side["value"] for side in region.sides] == ["eu-west-1", "eu-west-3"]
    assert region.recommendation["side"] == 1
    assert region.recommendation["strength"] == "clear"
    assert region.recommendation["reasons"] == ["authority", "fresher"]
    assert region.chosen == "eu-west-1"

    owner = found["owner"]
    assert owner.kind == "relationship"
    assert [side["value"] for side in owner.sides] == ["Payments", "Platform"]
    assert owner.recommendation["side"] == 0
    assert owner.sides[1]["edges"] == [
        {"from": str(company["Platform"]), "to": str(company["payment-api"]), "type": "owns"}
    ]

    summary = await _get(client, "/conflicts/summary")
    assert summary == {"open": 3, "resolved": 0, "dismissed": 0, "gone": 0}
    listed = (await _get(client, "/conflicts", status="open"))["data"]
    assert {c["about"] for c in listed} == {"sla", "region", "owner"}
    detail = await _get(client, f"/conflicts/{region.id}")
    assert detail["sides"][1]["sources"][0]["name"] == "production"
    assert detail["sides"][1]["sources"][0]["authority"] == 1.0
    assert detail["statement"].startswith("payment-api's sources disagree on region")
    assert detail["provenance"]["analyzer"] == "conflicts"


async def test_the_workspace_s_rule_makes_the_recommendation(
    client: AsyncClient, acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID]
) -> None:
    sla = (await _conflicts(acme["acme"]))["sla"]
    assert sla.recommendation["side"] == 0  # GitHub, by its family

    rule = await _post(
        client,
        "/authority-rules",
        {"about": "sla", "source_id": str(company["acme-eu"]), "stance": "prefer"},
    )
    assert (rule["source_name"], rule["source_kind"]) == ("acme-eu", "datadog")
    await analyse_workspace(acme["acme"], trigger="request", analyzers=ANALYZERS)
    ruled = (await _conflicts(acme["acme"]))["sla"]
    assert (ruled.recommendation["side"], ruled.recommendation["strength"]) == (1, "rule")

    assert [r["about"] for r in await _get(client, "/authority-rules")] == ["sla"]
    deleted = await client.delete(f"{API}/authority-rules/{rule['id']}")
    assert deleted.status_code == 204
    assert await _get(client, "/authority-rules") == []
    unknown = await client.post(
        f"{API}/authority-rules",
        json={"about": "sla", "source_id": str(uuid.uuid4()), "stance": "prefer"},
    )
    assert unknown.status_code == 404


# ── settled ────────────────────────────────────────────────────────────────


async def test_a_person_keeps_a_side_and_the_decision_is_the_model_s(
    client: AsyncClient,
    acme: dict[str, uuid.UUID],
    company: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
) -> None:
    workspace = acme["acme"]
    found = await _conflicts(workspace)

    kept = await _post(
        client,
        f"/conflicts/{found['region'].id}/resolve",
        {"side": 1, "reason": "AWS runs it", "remember": True},
    )
    assert kept["status"] == "resolved"
    assert kept["resolution"]["value"] == "eu-west-3"
    assert kept["resolution"]["by"] == str(acme["admin"])
    assert [h["status"] for h in kept["history"]] == ["resolved"]
    assert builds == [workspace]
    # Remembered: AWS is preferred on regions from now on.
    [rule] = await _get(client, "/authority-rules")
    assert (rule["about"], rule["source_name"], rule["stance"]) == (
        "region",
        "production",
        "prefer",
    )

    await _post(client, f"/conflicts/{found['owner'].id}/resolve", {"side": 0})
    facts = {(f.kind, f.attribute, f.relationship_type): f for f in await _facts(workspace)}
    region = facts[("attribute", "region", None)]
    assert (region.value, region.overrides, region.entity_id) == (
        "eu-west-3",
        True,
        company["payment-api"],
    )
    assert region.provenance["conflict_id"] == str(found["region"].id)
    refuted = facts[("absence", None, "owns")]
    assert (refuted.from_entity_id, refuted.to_entity_id) == (
        company["Platform"],
        company["payment-api"],
    )

    # The next run: the decisions stand, the SLA still waits.
    await analyse_workspace(workspace, trigger="request", analyzers=ANALYZERS)
    after = await _conflicts(workspace)
    assert (after["region"].status, after["owner"].status, after["sla"].status) == (
        "resolved",
        "resolved",
        "open",
    )


async def test_dismissed_reopened_and_never_decided_twice_in_silence(
    client: AsyncClient,
    acme: dict[str, uuid.UUID],
    company: dict[str, uuid.UUID],
    builds: list[uuid.UUID],
) -> None:
    workspace = acme["acme"]
    sla = (await _conflicts(workspace))["sla"]

    dismissed = await _post(
        client, f"/conflicts/{sla.id}/dismiss", {"reason": "Two SLOs, both true"}
    )
    assert dismissed["status"] == "dismissed"
    assert (await client.post(f"{API}/conflicts/{sla.id}/dismiss", json={})).status_code == 200
    reopened = await _post(client, f"/conflicts/{sla.id}/reopen")
    assert reopened["status"] == "open"
    assert [h["status"] for h in reopened["history"]] == ["dismissed", "dismissed", "reopened"]
    assert (await client.post(f"{API}/conflicts/{sla.id}/reopen")).status_code == 409

    # Kept 99.95 — then Jira says 99.5: no one decided on that, open again.
    await _post(client, f"/conflicts/{sla.id}/resolve", {"side": 0})
    with workspace_scope(workspace):
        async with session_factory() as session:
            entity = await session.get(Entity, company["payment-api"])
            assert entity is not None
            conflicts = list(entity.provenance["conflicts"])  # type: ignore[call-overload]
            conflicts[0] = {
                **conflicts[0],
                "values": [*conflicts[0]["values"], _said("99.5", company["OPS"], 0)],
            }
            entity.provenance = {**entity.provenance, "conflicts": conflicts}
            await session.commit()
    await analyse_workspace(workspace, trigger="request", analyzers=ANALYZERS)
    again = (await _conflicts(workspace))["sla"]
    assert again.status == "open"
    assert again.history[-1]["reason"] == "a value no one decided on"
    # The decision stands meanwhile: its fact is still the model's.
    assert any(f.attribute == "sla" for f in await _facts(workspace))


async def test_a_conflict_no_longer_disagreed_on_is_gone(
    client: AsyncClient, acme: dict[str, uuid.UUID], company: dict[str, uuid.UUID], builds: Any
) -> None:
    workspace = acme["acme"]
    with workspace_scope(workspace):
        async with session_factory() as session:
            entity = await session.get(Entity, company["payment-api"])
            assert entity is not None
            entity.provenance = {**entity.provenance, "conflicts": []}
            await session.commit()
    await analyse_workspace(workspace, trigger="request", analyzers=ANALYZERS)
    gone = (await _conflicts(workspace))["sla"]
    assert gone.status == "gone"
    refused = await client.post(f"{API}/conflicts/{gone.id}/resolve", json={"side": 0})
    assert refused.status_code == 409


async def test_a_member_reads_and_another_workspace_sees_nothing(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    company: dict[str, uuid.UUID],
) -> None:
    sla = (await _conflicts(acme["acme"]))["sla"]
    _as(identity, acme, "member")
    assert (await client.get(f"{API}/conflicts/{sla.id}")).status_code == 200
    refused = await client.post(f"{API}/conflicts/{sla.id}/resolve", json={"side": 0})
    assert refused.status_code == 403

    _as(identity, acme, "other_admin")
    assert (await _get(client, "/conflicts"))["data"] == []
    assert (await client.get(f"{API}/conflicts/{sla.id}")).status_code == 404
    assert (
        await client.post(f"{API}/conflicts/{sla.id}/resolve", json={"side": 0})
    ).status_code == 404


# ── through a real build — and undone ─────────────────────────────────────


async def test_a_decision_goes_through_a_real_build_and_is_undone(
    client: AsyncClient,
    identity: FakeIdentity,
    acme: dict[str, uuid.UUID],
    builds: Any,
) -> None:
    workspace = acme["acme"]
    ids = await _built(workspace)
    run = uuid.uuid4()
    with workspace_scope(workspace):
        async with session_factory() as session:
            for key, kind, subject, about, sides in (
                (
                    "test.state",
                    "attribute",
                    PR,
                    "state",
                    [_side("merged"), _side("closed")],
                ),
                (
                    "test.owner",
                    "relationship",
                    REPO,
                    "owner",
                    [
                        _side(
                            "payments",
                            [{"from": str(ids[REPO]), "to": str(ids[TEAM]), "type": "owned_by"}],
                        ),
                        _side("Sara Martin"),
                    ],
                ),
            ):
                session.add(
                    KnowledgeConflict(
                        workspace_id=workspace,
                        key=key,
                        kind=kind,
                        subject_id=ids[subject],
                        subject_name=subject,
                        about=about,
                        sides=sides,
                        recommendation={},
                        statement="A test's conflict.",
                        status="open",
                        first_seen_at=NOW,
                        last_seen_at=NOW,
                        first_run_id=run,
                        last_run_id=run,
                    )
                )
            await session.commit()
    _as(identity, acme, "admin")
    conflicts = await _conflicts(workspace)
    await _post(client, f"/conflicts/{conflicts['state'].id}/resolve", {"side": 1})
    await _post(client, f"/conflicts/{conflicts['owner'].id}/resolve", {"side": 1})

    counts = await build_workspace(workspace)
    assert counts["relationships_refuted"] == 1
    model = await _entities(workspace)
    pr = model[PR]
    assert pr.attributes["state"] == "closed"
    said = pr.provenance["attributes"]["state"]  # type: ignore[index]
    assert (said["origin"], said["conflict_id"], said["replaced"]) == (
        "accepted",
        str(conflicts["state"].id),
        "merged",
    )

    async def owned() -> bool:
        with workspace_scope(workspace):
            async with session_factory() as session:
                found = await session.execute(
                    select(Relationship).where(
                        Relationship.from_entity_id == ids[REPO],
                        Relationship.to_entity_id == ids[TEAM],
                        Relationship.type == RelationshipType.OWNED_BY,
                    )
                )
                return found.scalar_one_or_none() is not None

    assert not await owned()
    assert ids[SARA]  # the side kept names no tie of its own

    for about in ("state", "owner"):
        await _post(client, f"/conflicts/{conflicts[about].id}/reopen")
    await build_workspace(workspace)
    assert (await _entities(workspace))[PR].attributes["state"] == "merged"
    assert await owned()
