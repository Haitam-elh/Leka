"""A GitHub source for a new workspace, read through the real chain (LEKA-445).

There is no GitHub in the e2e suite and no worker. This plays both: a
connector registered as GitHub, in this process only, answers a repository,
a pull request and a commit; a source of that kind is made in the workspace
of the account given, tested and switched on as the wizard would; then the
pass and every stage run here, as the job loop would run them, to the
company model. The API, in its own process, reads what they wrote.

    python connect_github.py <email>
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import text

import leka.schema  # noqa: F401 — every table, so the foreign keys resolve
from leka.connectors import (
    Capability,
    ConnectionTestResult,
    Connector,
    ConnectorCategory,
    ConnectorManifest,
    HealthResult,
    HealthStatus,
    RawRecord,
    SourceKind,
    SourceService,
    register_connector,
    unregister_connector,
)
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion import pipeline, sync
from leka.ingestion.enrichment import job as enrichment
from leka.ingestion.enrichment.job import enrich_workspace
from leka.ingestion.extraction.job import extract_source
from leka.ingestion.normalisation.job import normalise_source
from leka.ingestion.parsing.job import parse_source
from leka.ingestion.resolution.job import resolve_workspace
from leka.ingestion.validation.job import validate_source
from leka.knowledge.job import build_workspace

REPO = "globex/billing"
RECORDS: dict[Capability, list[tuple[str, str | None, dict[str, Any]]]] = {
    Capability.REPOSITORIES: [
        (
            "R_globex1",
            None,
            {
                "node_id": "R_globex1",
                "full_name": REPO,
                "description": "Invoices and payments",
                "language": "Python",
                "private": True,
                "default_branch": "main",
                "html_url": f"https://github.com/{REPO}",
                "owner": {"login": "globex"},
            },
        )
    ],
    Capability.PULL_REQUESTS: [
        (
            "PR_globex7",
            REPO,
            {
                "node_id": "PR_globex7",
                "number": 7,
                "title": "Send the invoice once",
                "body": "- idempotency key",
                "state": "closed",
                "draft": False,
                "merged_at": "2026-10-01T10:00:00Z",
                "closed_at": "2026-10-01T10:00:00Z",
                "created_at": "2026-09-30T08:00:00Z",
                "updated_at": "2026-10-01T10:00:01Z",
                "html_url": f"https://github.com/{REPO}/pull/7",
                "user": {"login": "sara", "id": 1},
                "assignees": [{"login": "sara"}],
                "requested_reviewers": [],
                "labels": [],
                "head": {"ref": "fix/invoice-once"},
                "base": {"ref": "main"},
            },
        )
    ],
    Capability.COMMITS: [
        (
            "C_globex1",
            REPO,
            {
                "node_id": "C_globex1",
                "sha": "1a2b",
                "html_url": f"https://github.com/{REPO}/commit/1a2b",
                "commit": {
                    "message": "fix(invoices): send each invoice once",
                    "author": {"name": "Sara K.", "email": "sara@globex.example",
                               "date": "2026-10-01T09:00:00Z"},
                    "committer": {"name": "Sara K.", "email": "sara@globex.example",
                                  "date": "2026-10-01T09:00:00Z"},
                },
                "author": {"login": "sara"},
                "parents": [{"sha": "0"}],
            },
        )
    ],
}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr


class GitHubStandIn(Connector[Config, Credentials]):
    manifest = ConnectorManifest(
        key=SourceKind.GITHUB,
        display_name="GitHub",
        category=ConnectorCategory.CODE,
        auth_type="token",
        config_schema=Config,
        credentials_schema=Credentials,
        capabilities=frozenset(RECORDS),
    )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(account="globex", capabilities=sorted(RECORDS))

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


async def _not_queued(*args: object, **kwargs: object) -> object:
    return object()  # run here, one after the other, not by a worker


async def main(email: str) -> None:
    unregister_connector(SourceKind.GITHUB)
    register_connector(GitHubStandIn)
    for module in (sync, pipeline, enrichment):
        module.enqueue_job = _not_queued  # type: ignore[attr-defined]
    with system_scope():
        async with session_factory() as session:
            workspace = (
                await session.execute(
                    text(
                        "SELECT m.workspace_id FROM memberships m JOIN users u ON u.id = m.user_id"
                        " WHERE u.email = :e"
                    ),
                    {"e": email},
                )
            ).scalar_one()
    with workspace_scope(workspace):
        async with session_factory() as session:
            service = SourceService(session, workspace, actor_user_id=None)
            source = await service.create(SourceKind.GITHUB, REPO, {}, {"token": "t" * 24})
            await service.test(source)
            await service.activate(source)
            await session.commit()
    report = await sync.sync_source(workspace, source.id, full=True)
    assert report.status == "succeeded", report
    for stage in (extract_source, parse_source, normalise_source, validate_source):
        await stage(workspace, source.id)
    await resolve_workspace(workspace)
    await enrich_workspace(workspace)
    print(await build_workspace(workspace))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
