"""End to end (LEKA-360): GitHub's own payloads, from a pass to candidates.

A connector registered as GitHub for the test hands over what GitHub's REST
API returns — a repository, an issue, the pull request that fixes it, a
commit — and the real pipeline takes them through: the pass stores and
indexes them, then extraction, parsing and normalisation run with the real
strategies and rules, each queued by the one before. What comes out must
join up: the pull request resolves the issue by its canonical key, the
commit's author is a person by email with their login as an alias, every
stage's run is recorded, and the source is processed through. Then the
workspace's stages: resolution makes one person of the address and the
login, and enrichment (LEKA-359) joins the entities — the pull request to
the issue it resolves and to Sara — and measures them.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import select, text

from leka.connectors import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
    HealthStatus,
    RawRecord,
    Source,
    SourceKind,
    SourceService,
    get_connector,
    register_connector,
    unregister_connector,
)
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import (
    EnrichedRelationship,
    EnrichmentRun,
    EntityEnrichment,
    NormalisedRecordRow,
    ProcessingRun,
    ProcessingRunStatus,
    ResolvedEntity,
)
from leka.ingestion import pipeline as pipeline_module
from leka.ingestion import sync as sync_module
from leka.ingestion.enrichment import job as enrichment_job
from leka.ingestion.enrichment.job import enrich_workspace
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.normalisation import NormalisedRecord
from leka.ingestion.normalisation.job import NORMALISE_JOB, normalise_source
from leka.ingestion.parsing.job import PARSE_JOB, parse_source
from leka.ingestion.resolution.job import resolve_workspace
from leka.ingestion.sync import sync_source
from leka.ingestion.validation.job import VALIDATE_JOB, validate_source
from leka.platform import LocalObjectStore
from tests.test_extraction import GITHUB_PR

pytestmark = pytest.mark.integration

REPO = "acme/payments"
RECORDS: dict[Capability, list[tuple[str, str | None, dict[str, Any]]]] = {
    Capability.REPOSITORIES: [
        (
            "R_kgDO1",
            None,
            {
                "node_id": "R_kgDO1",
                "full_name": REPO,
                "description": "The payments service",
                "language": "Python",
                "topics": ["payments"],
                "private": True,
                "default_branch": "main",
                "html_url": f"https://github.com/{REPO}",
                "owner": {"login": "acme"},
            },
        )
    ],
    Capability.ISSUES: [
        (
            "I_kwDO41",
            REPO,
            {
                "node_id": "I_kwDO41",
                "number": 41,
                "title": "Webhook lost under load",
                "body": "Seen by @omar in production.",
                "state": "open",
                "labels": [{"name": "bug"}],
                "user": {"login": "omar"},
                "html_url": f"https://github.com/{REPO}/issues/41",
                "created_at": "2026-09-17T08:00:00Z",
                "updated_at": "2026-09-17T08:00:00Z",
            },
        )
    ],
    Capability.PULL_REQUESTS: [("PR_kwDOA", REPO, GITHUB_PR)],  # "Fixes #41."
    Capability.COMMITS: [
        (
            "C_kwDO9f",
            REPO,
            {
                "node_id": "C_kwDO9f",
                "sha": "9f2c",
                "html_url": f"https://github.com/{REPO}/commit/9f2c",
                "commit": {
                    "message": "fix(webhooks): retry with an idempotency key",
                    "author": {
                        "name": "Sara K.",
                        "email": "sara@acme.io",
                        "date": "2026-09-19T09:00:00Z",
                    },
                    "committer": {
                        "name": "Sara K.",
                        "email": "sara@acme.io",
                        "date": "2026-09-19T09:00:00Z",
                    },
                },
                "author": {"login": "sara"},
                "parents": [{"sha": "a"}],
            },
        )
    ],
}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr


class GitHubAsItAnswers(Connector[Config, Credentials]):
    manifest = ConnectorManifest(
        key=SourceKind.GITHUB,
        display_name="GitHub (as it answers)",
        category=ConnectorCategory.CODE,
        auth_type="token",
        config_schema=Config,
        credentials_schema=Credentials,
        capabilities=frozenset(RECORDS),
    )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(account="acme", capabilities=sorted(RECORDS))

    async def check_health(self) -> HealthResult:
        return HealthResult(status=HealthStatus.HEALTHY, checked_at=datetime.now(UTC))

    async def iter_resources(
        self, capability: Capability, *, since: datetime | None = None
    ) -> AsyncIterator[RawRecord]:
        for external_id, container, payload in RECORDS.get(capability, []):
            yield RawRecord(
                kind=capability,
                external_id=external_id,
                container=container,
                payload=payload,
                fetched_at=datetime.now(UTC),
            )


queued: list[str] = []


@pytest.fixture(autouse=True)
def github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """GitHub, as it answers, in place of the real connector; a local store;
    the jobs captured, not queued."""
    real = get_connector(SourceKind.GITHUB)
    unregister_connector(SourceKind.GITHUB)
    register_connector(GitHubAsItAnswers)
    from leka.platform import storage

    monkeypatch.setattr(storage, "_store", LocalObjectStore(tmp_path))
    queued.clear()

    async def capture(job: str, *args: object, **kwargs: object) -> object:
        queued.append(job)
        return object()

    monkeypatch.setattr(sync_module, "enqueue_job", capture)
    monkeypatch.setattr(pipeline_module, "enqueue_job", capture)
    monkeypatch.setattr(enrichment_job, "enqueue_job", capture)
    yield
    unregister_connector(SourceKind.GITHUB)
    register_connector(real)


@pytest.fixture
async def source() -> AsyncIterator[Source]:
    with system_scope():
        async with session_factory() as session:
            workspace_id: uuid.UUID = (
                await session.execute(
                    text("INSERT INTO workspaces (name, slug) VALUES ('E2E', :s) RETURNING id"),
                    {"s": f"e2e-{uuid.uuid4().hex[:10]}"},
                )
            ).scalar_one()
            await session.commit()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            service = SourceService(session, workspace_id, actor_user_id=None)
            created = await service.create(SourceKind.GITHUB, "Acme", {}, {"token": "t" * 24})
            await service.test(created)
            await service.activate(created)
            await session.commit()
            yield created
    with system_scope():
        async with session_factory() as session:
            await session.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace_id})
            await session.commit()


async def test_github_payloads_come_out_as_joined_up_candidates(source: Source) -> None:
    report = await sync_source(source.workspace_id, source.id, full=True)
    assert report.status == "succeeded"

    extracted = await extract_source(source.workspace_id, source.id)
    assert queued[-1] == PARSE_JOB
    parsed = await parse_source(source.workspace_id, source.id)
    assert queued[-1] == NORMALISE_JOB
    normalised = await normalise_source(source.workspace_id, source.id)
    assert queued[-1] == VALIDATE_JOB  # LEKA-358: what normalisation made is checked next
    validated = await validate_source(source.workspace_id, source.id)

    assert (extracted["extracted"], parsed["parsed"], normalised["normalised"]) == (4, 4, 4)
    assert extracted["failed"] == parsed["failed"] == normalised["failed"] == 0
    # GitHub as it answers: nothing to quarantine.
    assert (validated["valid"] + validated["warning"], validated["quarantined"]) == (4, 0)

    with workspace_scope(source.workspace_id):
        async with session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(NormalisedRecordRow).where(
                            NormalisedRecordRow.source_id == source.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            runs = (
                await session.execute(
                    select(ProcessingRun.stage, ProcessingRun.status).where(
                        ProcessingRun.source_id == source.id
                    )
                )
            ).all()
            through = await pipeline_module.advance(
                session, source.workspace_id, source, after=None
            )

    # Read back through the contract: what the graph will be handed.
    by_key = {row.entity_key: NormalisedRecord.model_validate(row.result) for row in rows}
    assert set(by_key) == {
        "github.com/acme/payments",
        "github.com/acme/payments#41",
        "github.com/acme/payments#42",
        "github.com/acme/payments@9f2c",
    }
    pr = by_key["github.com/acme/payments#42"]
    edges = {(e.type, e.to_key) for e in pr.relationships}
    assert (
        "resolves",
        "github.com/acme/payments#41",
    ) in edges  # "Fixes #41." → the issue's own key
    assert ("part_of", "github.com/acme/payments") in edges
    commit = by_key["github.com/acme/payments@9f2c"]
    (person,) = commit.related
    assert (person.key, person.aliases) == ("person:email:sara@acme.io", ["person:github.com:sara"])
    assert commit.entity.attributes["change_type"] == "fix"
    assert sorted((stage.value, status) for stage, status in runs) == [
        ("extraction", ProcessingRunStatus.SUCCEEDED),
        ("normalisation", ProcessingRunStatus.SUCCEEDED),
        ("parsing", ProcessingRunStatus.SUCCEEDED),
        ("validation", ProcessingRunStatus.SUCCEEDED),
    ]
    assert through is None  # processed through: nothing left to queue


async def test_github_payloads_are_resolved_then_enriched(source: Source) -> None:
    workspace = source.workspace_id
    await sync_source(workspace, source.id, full=True)
    for stage in (extract_source, parse_source, normalise_source, validate_source):
        await stage(workspace, source.id)

    await resolve_workspace(workspace)
    assert queued[-1] == enrichment_job.ENRICH_JOB  # a resolution that succeeds queues it
    counts = await enrich_workspace(workspace, now=datetime(2026, 9, 30, tzinfo=UTC))

    with workspace_scope(workspace):
        async with session_factory() as session:
            found = await session.execute(select(ResolvedEntity.key, ResolvedEntity.id))
            ids = dict(found.tuples().all())
            edges = {
                (e.from_entity_id, e.type, e.to_entity_id): e
                for e in (await session.execute(select(EnrichedRelationship))).scalars()
            }
            facts = {
                (f.entity_id, f.attribute): f.value
                for f in (await session.execute(select(EntityEnrichment))).scalars()
            }
            [run] = (await session.execute(select(EnrichmentRun))).scalars().all()

    pr, issue = ids["github.com/acme/payments#42"], ids["github.com/acme/payments#41"]
    repository, sara = ids["github.com/acme/payments"], ids["person:email:sara@acme.io"]
    assert edges[(pr, "resolves", issue)].origin == "stated"  # "Fixes #41."
    # By her login in the pull request, by her address in the commit: one Sara.
    assert (pr, "authored_by", sara) in edges
    assert edges[(repository, "maintained_by", sara)].rule == "most_active"
    # Real dates, from the records — resolution keeps none.
    assert facts[(pr, "cycle_time_hours")] == 50.0
    assert facts[(repository, "last_activity_at")] == "2026-09-20T10:00:01Z"
    assert facts[(repository, "lifecycle")] == "active"
    assert (run.status, run.failures) == ("succeeded", [])
    assert counts["failed"] == 0
