"""Data enrichment, the job and the API (LEKA-359), against the database.

A workspace whose GitHub, Jira and PagerDuty sources sit in
`normalised_records` as normalisation leaves them, resolved by entity
resolution. What these protect: enrichment reads what the last successful
resolution run made, and what the sources stated — never a quarantined
record's, never another workspace's; what it makes is replaced whole,
names the run that made it and the records it came from; it runs when
resolution made something new or its rules changed, and not otherwise; a
failed run changes nothing, an enricher that fails costs only its output;
the last enrichment stays readable while resolution runs again; and members
read what was added — never another workspace's.

The rules themselves are tests/test_enrichment.py's.
"""

# ruff: noqa: F811 — the fixtures of test_sources_api are imported to be requested by name.
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from leka.db import session_factory, workspace_scope
from leka.ingestion import (
    EnrichedRelationship,
    EnrichmentRun,
    EntityEnrichment,
    ResolutionRun,
    ResolvedEntity,
)
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion.enrichment import engine
from leka.ingestion.enrichment import job as enrichment_job
from leka.ingestion.enrichment.job import ENRICH_JOB, enrich_workspace
from leka.ingestion.lifecycle import sweep_processing
from leka.ingestion.resolution.job import resolve_workspace
from tests.conftest import FakeIdentity
from tests.test_resolution_job import _source, entity
from tests.test_sources_api import FAKE_KEY, _as, acme, fake_connector  # noqa: F401 — fixtures

pytestmark = pytest.mark.integration

API = "/api/v1/ingestion/enrichment"
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)

PR = "github.com/acme/billing-api#41"
REPO = "github.com/acme/billing-api"
ISSUE = "acme.atlassian.net/PAY-42"
SERVICE = "service:billing"
TEAM = "team:payments"
SARA = "person:email:sara@acme.io"


def relationship(
    kind: str, from_key: str, to_key: str, source_id: uuid.UUID, *, evidence: str = "references"
) -> dict[str, Any]:
    return {
        "type": kind,
        "from_key": from_key,
        "to_key": to_key,
        "source_id": str(source_id),
        "confidence": 1.0,
        "evidence": evidence,
    }


async def _normalised(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    own: dict[str, Any],
    *named: dict[str, Any],
    relationships: tuple[dict[str, Any], ...] = (),
    at: datetime = NOW,
    external_id: str | None = None,
) -> uuid.UUID:
    """A record as normalisation leaves it — its row, the rows it came from,
    and what it states — and the row's id. Its source's id for it is its
    entity's key, unless another record names the same entity."""
    external_id = external_id or own["key"]
    checksum = hashlib.sha256(external_id.encode() + source_id.bytes).hexdigest()
    result = json.dumps(
        {"entity": own, "related": list(named), "relationships": list(relationships)}
    )
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            values = {"w": workspace_id, "s": source_id, "c": checksum, "at": at}
            record = await session.scalar(
                text(
                    "INSERT INTO source_records (workspace_id, source_id, kind, external_id, "
                    "checksum, first_seen_at, last_seen_at) VALUES (:w, :s, 'records', :e, :c, "
                    ":at, :at) RETURNING id"
                ),
                {**values, "e": external_id},
            )
            extracted = await session.scalar(
                text(
                    "INSERT INTO extracted_records (workspace_id, source_id, source_record_id, "
                    "kind, status, checksum, result, extracted_at) VALUES (:w, :s, :r, "
                    "'records', 'extracted', :c, '{}', :at) RETURNING id"
                ),
                {**values, "r": record},
            )
            parsed = await session.scalar(
                text(
                    "INSERT INTO parsed_records (workspace_id, source_id, extracted_record_id, "
                    "kind, status, checksum, parser_version, result, parsed_at) VALUES (:w, :s, "
                    ":x, 'records', 'parsed', :c, 1, '{}', :at) RETURNING id"
                ),
                {**values, "x": extracted},
            )
            row = await session.scalar(
                text(
                    "INSERT INTO normalised_records (workspace_id, source_id, parsed_record_id, "
                    "kind, status, checksum, parser_version, normaliser_version, entity_type, "
                    "entity_key, result, normalised_at) VALUES (:w, :s, :p, 'records', "
                    "'normalised', :c, 1, 1, :t, :k, CAST(:j AS jsonb), :at) RETURNING id"
                ),
                {**values, "p": parsed, "t": own["type"], "k": own["key"], "j": result},
            )
            await session.commit()
            return uuid.UUID(str(row))


async def _quarantine(workspace_id: uuid.UUID, source_id: uuid.UUID, row_id: uuid.UUID) -> None:
    """Validation's verdict on a record: quarantined (LEKA-358)."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO validated_records (workspace_id, source_id, "
                    "normalised_record_id, kind, status, issues, quality, completeness, "
                    "consistency, freshness, confidence, normalised_at, validator_version, "
                    "validated_at) VALUES (:w, :s, :r, 'records', 'quarantined', '[]', 0, 0, 0, "
                    "0, 0, :at, 1, :at)"
                ),
                {"w": workspace_id, "s": source_id, "r": row_id, "at": NOW},
            )
            await session.commit()


async def _tools(workspace_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """GitHub, Jira and PagerDuty, and what each normalised — with what
    each states."""
    github, jira, pagerduty = [
        await _source(workspace_id, name) for name in ("GitHub", "Jira", "PagerDuty")
    ]
    ids = {"github": github, "jira": jira, "pagerduty": pagerduty}
    await _normalised(
        workspace_id,
        github,
        entity(REPO, "acme/billing-api", type="repository", updated_at="2026-09-28T10:00:00Z"),
    )
    ids["pr"] = await _normalised(
        workspace_id,
        github,
        entity(
            PR,
            "Fix doubled refunds",
            type="pull_request",
            state="merged",
            created_at="2026-09-27T10:00:00Z",
            merged_at="2026-09-28T10:00:00Z",
            updated_at="2026-09-28T10:00:00Z",
        ),
        entity("person:github.com:sara", "sara"),
        relationships=(
            relationship("part_of", PR, REPO, github, evidence="container"),
            relationship("authored_by", PR, "person:github.com:sara", github),
            relationship("resolves", PR, "ticket:PAY-42", github, evidence="parsing"),
        ),
    )
    await _normalised(
        workspace_id,
        jira,
        entity(ISSUE, "Refunds are doubled", type="issue", aliases=("ticket:PAY-42",)),
        entity(SARA, "Sara Martin", aliases=("person:github.com:sara",)),
        relationships=(relationship("assigned_to", ISSUE, SARA, jira),),
    )
    await _normalised(
        workspace_id,
        pagerduty,
        entity(SERVICE, "Billing", type="service"),
        entity(TEAM, "payments", type="team"),
        relationships=(relationship("owned_by", SERVICE, TEAM, pagerduty),),
    )
    return ids


async def _resolved(workspace_id: uuid.UUID) -> dict[str, uuid.UUID]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(ResolvedEntity.key, ResolvedEntity.id))
            return dict(rows.tuples().all())


async def _edges(workspace_id: uuid.UUID) -> list[EnrichedRelationship]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(EnrichedRelationship))
            return list(rows.scalars())


async def _facts(workspace_id: uuid.UUID) -> list[EntityEnrichment]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(EntityEnrichment))
            return list(rows.scalars())


async def _runs(workspace_id: uuid.UUID) -> list[EnrichmentRun]:
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            rows = await session.execute(select(EnrichmentRun).order_by(EnrichmentRun.started_at))
            return list(rows.scalars())


async def _ready(workspace_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """The tools normalised and resolved: what enrichment reads."""
    tools = await _tools(workspace_id)
    await resolve_workspace(workspace_id)
    return tools


def _find(
    edges: list[EnrichedRelationship], ids: dict[str, uuid.UUID], a: str, kind: str, b: str
) -> EnrichedRelationship | None:
    return next(
        (e for e in edges if (e.from_entity_id, e.type, e.to_entity_id) == (ids[a], kind, ids[b])),
        None,
    )


# ── the job ──────────────────────────────────────────────────────────────────


async def test_a_workspace_is_enriched_from_its_last_resolution(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    tools = await _ready(workspace)
    # Another workspace's records are none of this one's.
    elsewhere = await _source(acme["globex"], "GitHub")
    await _normalised(
        acme["globex"],
        elsewhere,
        entity("github.com/globex/x#1", "Fix", type="pull_request"),
        relationships=(
            relationship("resolves", "github.com/globex/x#1", "ticket:PAY-42", elsewhere),
        ),
    )

    counts = await enrich_workspace(workspace, now=NOW)

    ids = await _resolved(workspace)
    edges = await _edges(workspace)
    resolves = _find(edges, ids, PR, "resolves", ISSUE)
    assert resolves is not None
    assert (resolves.origin, resolves.cross_source, resolves.sources) == ("stated", True, 1)
    assert resolves.provenance == [
        {"source_id": str(tools["github"]), "record_id": str(tools["pr"]), "evidence": "parsing"}
    ]
    # Sara's login, in the pull request, is her.
    assert _find(edges, ids, PR, "authored_by", SARA) is not None
    # The repository is the service's — and so the team's, inherited.
    assert _find(edges, ids, REPO, "part_of", SERVICE).rule == "same_name"  # type: ignore[union-attr]
    assert _find(edges, ids, REPO, "owned_by", TEAM).rule == "inherited"  # type: ignore[union-attr]
    facts = {(f.entity_id, f.attribute): f for f in await _facts(workspace)}
    category = facts[(ids[PR], "category")]
    assert (category.value, category.rule, category.inputs) == ("bug", "title_words", [PR])
    assert facts[(ids[PR], "cycle_time_hours")].value == 24.0

    [run] = await _runs(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            resolution = await session.scalar(select(ResolutionRun.id))
    assert (run.status, run.resolution_run_id, run.failures) == ("succeeded", resolution, [])
    assert run.counts == counts
    assert isinstance(crossing := counts["cross_source"], int)
    assert crossing >= 1
    assert {e.run_id for e in edges} == {run.id}
    assert await _edges(acme["globex"]) == []


async def test_nothing_new_is_nothing_to_run(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)

    assert await enrich_workspace(workspace, now=NOW) == {"status": "nothing"}
    assert len(await _runs(workspace)) == 1


async def test_nothing_resolved_is_nothing_to_enrich(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    await _tools(workspace)

    assert await enrich_workspace(workspace, now=NOW) == {"status": "nothing"}
    assert await _runs(workspace) == []


async def test_a_new_resolution_is_enriched_again_the_ids_kept(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    tools = await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)
    before = await _resolved(workspace)

    await _normalised(
        workspace,
        tools["github"],
        entity("github.com/acme/billing-api#42", "Add refund export", type="pull_request"),
        relationships=(
            relationship("part_of", "github.com/acme/billing-api#42", REPO, tools["github"]),
        ),
        at=NOW + timedelta(hours=1),
    )
    await resolve_workspace(workspace)
    await enrich_workspace(workspace, now=NOW)

    ids = await _resolved(workspace)
    assert {key: ids[key] for key in before} == before
    edges = await _edges(workspace)
    assert _find(edges, ids, "github.com/acme/billing-api#42", "part_of", REPO) is not None
    runs = await _runs(workspace)
    assert [r.status for r in runs] == ["succeeded", "succeeded"]
    assert runs[0].resolution_run_id != runs[1].resolution_run_id


async def test_new_rules_enrich_everything_again(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)
    monkeypatch.setattr(enrichment_job, "ENRICHER_VERSION", engine.ENRICHER_VERSION + 1)

    await enrich_workspace(workspace, now=NOW)

    assert [r.enricher_version for r in await _runs(workspace)] == [
        engine.ENRICHER_VERSION,
        engine.ENRICHER_VERSION + 1,
    ]


async def test_a_failed_run_changes_nothing_and_says_why(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)
    before = {(e.from_entity_id, e.type, e.to_entity_id) for e in await _edges(workspace)}
    facts = len(await _facts(workspace))

    def broken(snapshot: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(enrichment_job, "enrich", broken)
    monkeypatch.setattr(enrichment_job, "ENRICHER_VERSION", engine.ENRICHER_VERSION + 1)

    with pytest.raises(RuntimeError):
        await enrich_workspace(workspace, now=NOW)

    assert {(e.from_entity_id, e.type, e.to_entity_id) for e in await _edges(workspace)} == before
    assert len(await _facts(workspace)) == facts
    last = (await _runs(workspace))[-1]
    assert (last.status, last.error) == ("failed", "RuntimeError")


async def test_an_enricher_that_fails_is_said_and_costs_only_its_output(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    await _ready(workspace)

    def broken(graph: engine.Graph) -> engine.Made:
        raise KeyError("no such thing")

    enrichers = (engine.ENRICHERS[0], ("ownership", broken), *engine.ENRICHERS[3:])
    monkeypatch.setattr(
        enrichment_job, "enrich", lambda snapshot: engine.enrich(snapshot, enrichers)
    )

    counts = await enrich_workspace(workspace, now=NOW)

    [run] = await _runs(workspace)
    assert (run.status, run.failures) == (
        "succeeded",
        [{"enricher": "ownership", "error": "KeyError"}],
    )
    assert counts["failed"] == 1
    ids = await _resolved(workspace)
    edges = await _edges(workspace)
    assert _find(edges, ids, PR, "resolves", ISSUE) is not None
    assert not [e for e in edges if e.rule == "inherited"]


async def test_a_quarantined_record_states_nothing(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    tools = await _tools(workspace)
    await _quarantine(workspace, tools["github"], tools["pr"])
    await resolve_workspace(workspace)

    await enrich_workspace(workspace, now=NOW)

    ids = await _resolved(workspace)
    assert PR not in ids
    assert not [e for e in await _edges(workspace) if e.type == "resolves"]


async def test_a_run_left_running_is_abandoned_by_the_next(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    await _ready(workspace)
    with workspace_scope(workspace):
        async with session_factory() as session:
            session.add(
                EnrichmentRun(
                    workspace_id=workspace,
                    status="running",
                    started_at=NOW - timedelta(hours=3),
                    enricher_version=engine.ENRICHER_VERSION,
                )
            )
            await session.commit()

    await enrich_workspace(workspace, now=NOW)

    assert [r.status for r in await _runs(workspace)] == ["abandoned", "succeeded"]


async def test_a_run_that_sees_resolution_run_again_reads_again(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    await _ready(workspace)
    read = enrichment_job._snapshot
    calls = 0

    async def meanwhile(repository: Any, now: datetime) -> engine.Snapshot:
        nonlocal calls
        calls += 1
        snapshot = await read(repository, now)
        if calls == 1:  # resolution succeeds again while the first run reads
            with workspace_scope(workspace):
                async with session_factory() as session:
                    session.add(
                        ResolutionRun(
                            workspace_id=workspace,
                            status="succeeded",
                            started_at=datetime.now(UTC),
                            resolver_version=1,
                        )
                    )
                    await session.commit()
        return snapshot

    monkeypatch.setattr(enrichment_job, "_snapshot", meanwhile)

    await enrich_workspace(workspace, now=NOW)

    runs = await _runs(workspace)
    assert [r.status for r in runs] == ["abandoned", "succeeded"]
    assert runs[0].resolution_run_id != runs[1].resolution_run_id


async def test_the_last_enrichment_stays_readable_while_resolution_runs_again(
    acme: dict[str, uuid.UUID],
) -> None:
    workspace = acme["acme"]
    tools = await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)
    edges = len(await _edges(workspace))

    await _normalised(
        workspace,
        tools["jira"],
        entity("acme.atlassian.net/PAY-43", "Another", type="issue"),
        at=NOW + timedelta(hours=1),
    )
    await resolve_workspace(workspace)

    assert len(await _edges(workspace)) == edges  # resolution does not take it along


async def test_resolution_queues_the_enrichment_and_advance_catches_up(
    acme: dict[str, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = acme["acme"]
    await _tools(workspace)
    queued: list[dict[str, Any]] = []

    async def capture(job: str, *args: object, **kwargs: Any) -> object:
        queued.append({"job": job, "args": args, **kwargs})
        return object()

    monkeypatch.setattr(enrichment_job, "enqueue_job", capture)

    await resolve_workspace(workspace)

    [call] = queued
    assert (call["job"], call["args"], call["concurrency_key"]) == (
        ENRICH_JOB,
        (str(workspace),),
        f"enrich:{workspace}",
    )
    await enrich_workspace(workspace, now=NOW)
    with workspace_scope(workspace):
        async with session_factory() as session:
            assert not await enrichment_job.enrich_if_pending(session, workspace)
            # New rules, nothing to resolve: a pass's end queues the enrichment.
            monkeypatch.setattr(enrichment_job, "ENRICHER_VERSION", engine.ENRICHER_VERSION + 1)
            assert not await pipeline_module.resolve_if_pending(session, workspace)
    assert [c["job"] for c in queued] == [ENRICH_JOB, ENRICH_JOB]


async def test_the_history_of_runs_is_kept_ninety_days(acme: dict[str, uuid.UUID]) -> None:
    workspace = acme["acme"]
    await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)

    result = await sweep_processing(now=datetime.now(UTC) + timedelta(days=91))

    assert result["enrichment_runs"] >= 1
    assert await _runs(workspace) == []
    edges = await _edges(workspace)
    assert edges != []  # what the runs made is not history
    assert {e.run_id for e in edges} == {None}


# ── the API ──────────────────────────────────────────────────────────────────


async def test_members_read_what_enrichment_added(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    tools = await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)
    ids = await _resolved(workspace)
    _as(identity, acme, "member")

    status = (await client.get(API)).json()
    issue = (await client.get(f"{API}/entities/{ids[ISSUE]}")).json()
    pr = (await client.get(f"{API}/entities/{ids[PR]}")).json()
    crossing = (await client.get(f"{API}/relationships", params={"cross_source": "true"})).json()
    inferred = (
        await client.get(f"{API}/relationships", params={"origin": "inferred", "limit": 100})
    ).json()["data"]
    around = (
        await client.get(f"{API}/relationships", params={"entity_id": str(ids[ISSUE])})
    ).json()

    assert status["pending"] is False
    assert status["last_run"]["status"] == "succeeded"
    assert status["last_run"]["failures"] == []
    assert status["counts"]["cross_source"] >= 1
    assert status["relationships"]["resolves:stated"] == 1
    assert status["attributes"]["category"] >= 1

    [resolves] = [r for r in issue["incoming"] if r["type"] == "resolves"]
    assert resolves["from_entity"]["key"] == PR
    assert resolves["cross_source"] is True
    assert resolves["provenance"][0]["record_id"] == str(tools["pr"])
    assert issue["incoming_total"] == len(issue["incoming"])
    assert issue["attributes"] == {}  # what the sources say, untouched
    enriched = {a["attribute"]: a for a in pr["enriched"]}
    assert (enriched["category"]["value"], enriched["category"]["confidence"]) == ("bug", 0.6)
    assert enriched["category"]["inputs"] == [PR]
    assert "category" not in pr["attributes"]
    assert {(r["type"], r["to_entity"]["key"]) for r in pr["outgoing"]} >= {
        ("resolves", ISSUE),
        ("part_of", REPO),
        ("authored_by", SARA),
    }
    assert {(r["from_entity"]["key"], r["to_entity"]["key"]) for r in crossing["data"]} >= {
        (PR, ISSUE)
    }
    assert all(r["cross_source"] for r in crossing["data"])
    assert {r["rule"] for r in inferred} >= {"same_name", "inherited"}
    assert all(r["origin"] == "inferred" for r in inferred)
    confidences = [r["confidence"] for r in inferred]
    assert confidences == sorted(confidences, reverse=True)
    assert {(r["from_entity"]["key"], r["type"]) for r in around["data"]} >= {
        (PR, "resolves"),
        (ISSUE, "assigned_to"),
    }


async def test_another_workspace_s_entity_is_not_found(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _ready(workspace)
    await enrich_workspace(workspace, now=NOW)
    ids = await _resolved(workspace)
    _as(identity, acme, "other_admin")  # Globex's

    missing = await client.get(f"{API}/entities/{ids[PR]}")
    listed = (await client.get(f"{API}/relationships")).json()
    status = (await client.get(API)).json()

    assert missing.status_code == 404
    assert listed["data"] == []
    assert (status["pending"], status["last_run"], status["counts"]["relationships"]) == (
        False,
        None,
        0,
    )


# ── the "Mon environnement" screens (mockups 10 and 11) ─────────────────────


async def _live(workspace_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """The tools, plus what moved in the last hours: an incident open on
    the billing service, and the cloud instance it runs on."""
    tools = await _tools(workspace_id)
    now = datetime.now(UTC)
    hour, hours = ((now - timedelta(hours=n)).strftime("%Y-%m-%dT%H:%M:%SZ") for n in (1, 2))
    aws = await _source(workspace_id, "AWS")
    await _normalised(
        workspace_id,
        tools["pagerduty"],
        entity(
            "incident:pagerduty:Q1",
            "Billing API 500s",
            type="incident",
            state="open",
            created_at=hour,
            updated_at=hour,
        ),
        relationships=(
            relationship("affects", "incident:pagerduty:Q1", SERVICE, tools["pagerduty"]),
        ),
        at=now,
    )
    instance = "aws:arn:aws:ec2:eu-central-1:111:instance/i-1"
    await _normalised(
        workspace_id,
        aws,
        entity(
            instance,
            "billing-api-1",
            type="infra_resource",
            state="running",
            environment="production",
            updated_at=hours,
        ),
        relationships=(relationship("part_of", instance, SERVICE, aws, evidence="tags"),),
        at=now,
    )
    await resolve_workspace(workspace_id)
    await enrich_workspace(workspace_id, now=now)
    return tools


async def test_members_see_their_environment_as_the_mockup_lays_it_out(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _live(workspace)
    ids = await _resolved(workspace)
    _as(identity, acme, "member")

    screen = (await client.get(f"{API}/environment")).json()

    nodes = {n["id"]: n for n in screen["nodes"]}
    service = nodes[str(ids[SERVICE])]
    # PagerDuty watches it, and an incident is open on it.
    assert (service["layer"], service["status"]) == ("services", "incident")
    assert service["team"]["key"] == TEAM
    assert nodes[str(ids[REPO])]["layer"] == "applications"
    [cloud] = [n for n in screen["nodes"] if n["type"] == "provider"]
    assert (cloud["name"], cloud["detail"], cloud["count"], cloud["status"]) == (
        "aws",
        "eu-central-1",
        1,
        "operational",
    )
    assert {(e["from_id"], e["to_id"]) for e in screen["edges"]} >= {
        (str(ids[REPO]), str(ids[SERVICE])),
        (cloud["id"], str(ids[SERVICE])),
    }
    assert screen["layers"] == {"applications": 1, "services": 1, "infrastructure": 1}
    assert screen["environments"] == []  # the instance is boxed with its provider
    assert (screen["services"], screen["services_operational"]) == (1, 0)
    assert (screen["incidents_open"], screen["services_impacted"]) == (1, 1)
    assert screen["updated_at"] is not None
    [incident] = [p for p in screen["attention"] if p["kind"] == "open_incident"]
    assert (incident["level"], incident["detail"]) == ("high", "Billing")
    latest = screen["events"][0]
    assert (latest["entity"]["key"], latest["kind"]) == ("incident:pagerduty:Q1", "incident")
    assert latest["where"]["key"] == SERVICE
    assert latest["source_kinds"] == ["slack"]  # the test's sources are all one kind


async def test_an_entity_s_sheet_says_its_state_team_incidents_and_dependencies(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _live(workspace)
    ids = await _resolved(workspace)
    _as(identity, acme, "member")

    sheet = (await client.get(f"{API}/environment/{ids[SERVICE]}")).json()

    assert sheet["entity"]["key"] == SERVICE
    assert sheet["status"] == "incident"
    assert (sheet["team"]["entity"]["key"], sheet["team"]["origin"]) == (TEAM, "stated")
    [incident] = sheet["incidents"]
    assert (incident["entity"]["key"], incident["kind"]) == ("incident:pagerduty:Q1", "incident")
    assert {(d["entity"]["key"], d["type"], d["direction"]) for d in sheet["dependencies"]} >= {
        (REPO, "part_of", "in"),
        ("aws:arn:aws:ec2:eu-central-1:111:instance/i-1", "part_of", "in"),
    }
    repository = next(d for d in sheet["dependencies"] if d["entity"]["key"] == REPO)
    assert (repository["origin"], repository["cross_source"]) == ("inferred", True)
    # What moved around it: its incident, and its repository's pull request.
    assert {e["entity"]["key"] for e in sheet["events"]} >= {"incident:pagerduty:Q1", PR}
    assert [p["kind"] for p in sheet["attention"]] == ["open_incident"]

    repository_sheet = (await client.get(f"{API}/environment/{ids[REPO]}")).json()
    assert repository_sheet["status"] is None  # a repository has no state of its own
    assert repository_sheet["owner"] is None  # one pull request maintains nothing
    assert repository_sheet["team"]["origin"] == "inferred"


async def test_an_entity_s_activity_is_everything_that_moved_around_it(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _live(workspace)
    ids = await _resolved(workspace)
    _as(identity, acme, "member")

    # Long enough to hold the test's moment, whatever today is.
    response = await client.get(f"{API}/environment/{ids[SERVICE]}/activity", params={"days": 180})
    assert response.status_code == 200
    activity = response.json()
    assert activity["days"] == 180 and len(activity["by_day"]) == 180
    keys = {e["entity"]["key"]: e for e in activity["events"]}
    # Its incident, and its repository's pull request — each as its source says it.
    assert {"incident:pagerduty:Q1", PR} <= set(keys)
    assert keys["incident:pagerduty:Q1"]["kind"] == "incident"
    assert (activity["incidents"], activity["incidents_open"]) == (1, 1)
    assert activity["changes"] >= 1
    assert sum(d["changes"] + d["incidents"] for d in activity["by_day"]) == (
        activity["changes"] + activity["incidents"]
    )
    assert activity["last_activity"] == activity["events"][0]["at"]
    assert set(activity["previous"]) == {"changes", "deployments", "incidents", "work"}
    assert activity["log_sources"] == []  # the test's sources are all one kind
    assert isinstance(activity["mentions"], list)

    assert (
        await client.get(f"{API}/environment/{ids[SERVICE]}/activity", params={"days": 0})
    ).status_code == 422
    _as(identity, acme, "other_admin")
    missing = await client.get(f"{API}/environment/{ids[SERVICE]}/activity")
    assert missing.status_code == 404


async def test_an_empty_workspace_has_an_empty_environment_and_no_one_else_s(
    client: AsyncClient, identity: FakeIdentity, acme: dict[str, uuid.UUID]
) -> None:
    workspace = acme["acme"]
    await _live(workspace)
    ids = await _resolved(workspace)
    _as(identity, acme, "other_admin")  # Globex's

    screen = (await client.get(f"{API}/environment")).json()
    missing = await client.get(f"{API}/environment/{ids[SERVICE]}")

    assert (screen["nodes"], screen["edges"], screen["events"], screen["attention"]) == (
        [],
        [],
        [],
        [],
    )
    assert (screen["updated_at"], screen["services"], screen["layers"]) == (None, 0, {})
    assert missing.status_code == 404
