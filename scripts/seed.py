"""Recreate the "Acme Corp" demo workspace.

    api/.venv/bin/python scripts/seed.py

This is what lets the frontend be built before a single real connector
exists. It is deliberately a *plausible* company rather than lorem ipsum:
a screen looks right or wrong depending on whether "payment-api depends on
postgres-prod" reads like something a real engineer would see.

Idempotent — it deletes the acme workspace and rebuilds it. Every table
cascades from workspaces, so one DELETE is the whole cleanup.

NOTE ON ARCHITECTURE RULE 4. This script writes through the ORM directly
rather than through repositories, because the repositories are still
skeletons. That is acceptable here: scripts/ is developer tooling, not
application code, and it never runs in production. When
knowledge/repository.py grows real upsert methods, this script should call
them — it will then also be testing them.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from leka.connectors import Source, SourceKind, SourceStatus
from leka.db import session_factory, system_scope
from leka.knowledge import Entity, EntityType, Relationship, RelationshipType
from leka.platform import Workspace

WORKSPACE_SLUG = "acme"
WORKSPACE_NAME = "Acme Corp"

NOW = datetime.now(UTC)

# Twelve connected sources: a real company has several of each kind, which
# is why (workspace_id, kind, name) is the unique key and not (workspace,
# kind).
SOURCES: tuple[tuple[SourceKind, str, SourceStatus], ...] = (
    (SourceKind.GITHUB, "acme/backend", SourceStatus.ACTIVE),
    (SourceKind.GITHUB, "acme/frontend", SourceStatus.ACTIVE),
    (SourceKind.GITHUB, "acme/infrastructure", SourceStatus.ACTIVE),
    (SourceKind.JIRA, "ACME board", SourceStatus.ACTIVE),
    (SourceKind.JIRA, "OPS board", SourceStatus.ACTIVE),
    (SourceKind.CONFLUENCE, "Engineering space", SourceStatus.ACTIVE),
    (SourceKind.CONFLUENCE, "Runbooks space", SourceStatus.ERROR),
    (SourceKind.AWS, "production account", SourceStatus.ACTIVE),
    (SourceKind.AWS, "staging account", SourceStatus.ACTIVE),
    (SourceKind.DATADOG, "acme-eu", SourceStatus.ACTIVE),
    (SourceKind.SLACK, "#incidents", SourceStatus.ACTIVE),
    (SourceKind.SLACK, "#platform", SourceStatus.PENDING),
)


async def _reset(session: Any) -> None:
    """Remove the demo workspace. Everything else cascades from it."""
    await session.execute(delete(Workspace).where(Workspace.slug == WORKSPACE_SLUG))
    await session.commit()


async def seed() -> None:
    """Build the demo workspace, declaring that this crosses tenants.

    system_scope() is required, not decorative: this script creates a
    workspace and then reads the whole database to report what it wrote.
    Without it the scope guard in leka.db refuses the reads — which is the
    point. A request never legitimately does this; a seed script always does.
    """
    with system_scope():
        await _build_demo_workspace()


async def _build_demo_workspace() -> None:
    async with session_factory() as session:
        await _reset(session)

        workspace = Workspace(name=WORKSPACE_NAME, slug=WORKSPACE_SLUG)
        session.add(workspace)
        await session.flush()

        sources: dict[str, Source] = {}
        for kind, name, status in SOURCES:
            source = Source(
                workspace_id=workspace.id,
                kind=kind,
                name=name,
                status=status,
                config={"demo": True},
                last_synced_at=(
                    NOW - timedelta(minutes=7) if status is SourceStatus.ACTIVE else None
                ),
            )
            session.add(source)
            sources[f"{kind.value}:{name}"] = source
        await session.flush()

        github = sources["github:acme/backend"]
        infra = sources["github:acme/infrastructure"]
        aws = sources["aws:production account"]
        datadog = sources["datadog:acme-eu"]
        jira = sources["jira:OPS board"]

        def entity(
            source: Source,
            type_: EntityType,
            external_id: str,
            name: str,
            attributes: dict[str, object],
            confidence: float = 1.0,
            last_seen: datetime | None = None,
        ) -> Entity:
            row = Entity(
                workspace_id=workspace.id,
                type=type_,
                external_id=external_id,
                source_id=source.id,
                name=name,
                attributes=attributes,
                confidence=confidence,
                last_seen_at=last_seen or NOW,
            )
            session.add(row)
            return row

        # ── Services ────────────────────────────────────────────────────────
        payment = entity(
            github,
            EntityType.SERVICE,
            "svc-payment-api",
            "payment-api",
            {
                "version": "2.8.4",
                "language": "python",
                "runtime": "ecs-fargate",
                "sla": "99.95",
                "team": "payments",
            },
        )
        auth = entity(
            github,
            EntityType.SERVICE,
            "svc-auth-service",
            "auth-service",
            {
                "version": "1.4.0",
                "language": "go",
                "runtime": "ecs-fargate",
                "sla": "99.99",
                "team": "platform",
            },
        )
        users = entity(
            github,
            EntityType.SERVICE,
            "svc-user-service",
            "user-service",
            {
                "version": "3.1.2",
                "language": "python",
                "runtime": "ecs-fargate",
                "sla": "99.9",
                "team": "platform",
            },
        )

        # ── Infrastructure ──────────────────────────────────────────────────
        database = entity(
            aws,
            EntityType.DATABASE,
            "arn:aws:rds:eu-west-1:acme:db:postgres-prod",
            "postgres-prod",
            {
                "engine": "postgresql",
                "version": "16.4",
                "instance": "db.r6g.xlarge",
                "multi_az": True,
                "region": "eu-west-1",
            },
        )
        cluster = entity(
            infra,
            EntityType.INFRA_RESOURCE,
            "arn:aws:ecs:eu-west-1:acme:cluster/prod",
            "ecs-prod-cluster",
            {"provider": "aws", "region": "eu-west-1", "services": 14},
        )

        # ── People ──────────────────────────────────────────────────────────
        nadia = entity(
            github,
            EntityType.PERSON,
            "gh:nadia-k",
            "Nadia Kowalski",
            {"email": "nadia.kowalski@acme.example", "team": "payments", "role": "tech lead"},
        )
        thomas = entity(
            github,
            EntityType.PERSON,
            "gh:t-berger",
            "Thomas Berger",
            {"email": "thomas.berger@acme.example", "team": "platform", "role": "sre"},
        )
        mei = entity(
            github,
            EntityType.PERSON,
            "gh:mei-tanaka",
            "Mei Tanaka",
            {"email": "mei.tanaka@acme.example", "team": "payments", "role": "engineer"},
        )

        # ── The deployment, and the incident that followed it ───────────────
        deployment = entity(
            github,
            EntityType.DEPLOYMENT,
            "deploy-2026-09-18-1432",
            "payment-api v2.8.4",
            {
                "commit": "4f2a1c9",
                "released_at": (NOW - timedelta(hours=26)).isoformat(),
                "released_by": "mei-tanaka",
                "changes": "connection pool tuning",
            },
            last_seen=NOW - timedelta(hours=26),
        )
        incident = entity(
            jira,
            EntityType.INCIDENT,
            "OPS-1841",
            "payment-api p99 latency above 2s",
            {
                "severity": "sev2",
                "status": "resolved",
                "opened_at": (NOW - timedelta(hours=25)).isoformat(),
                "resolved_at": (NOW - timedelta(hours=21)).isoformat(),
                "p99_before_ms": 180,
                "p99_peak_ms": 2140,
            },
            last_seen=NOW - timedelta(hours=21),
        )
        monitor = entity(
            datadog,
            EntityType.INFRA_RESOURCE,
            "dd-monitor-77213",
            "payment-api latency p99",
            {"threshold_ms": 500, "triggered_at": (NOW - timedelta(hours=25)).isoformat()},
            last_seen=NOW - timedelta(hours=21),
        )
        runbook = entity(
            sources["confluence:Runbooks space"],
            EntityType.DOCUMENT,
            "conf-88421",
            "Payment API runbook",
            {"updated_at": (NOW - timedelta(days=243)).isoformat(), "author": "nadia-k"},
            confidence=0.6,
            last_seen=NOW - timedelta(days=12),
        )

        repository = entity(
            github,
            EntityType.REPOSITORY,
            "gh:acme/backend",
            "acme/backend",
            {"default_branch": "main", "language": "python", "private": True},
        )
        await session.flush()

        def edge(
            source: Source,
            from_entity: Entity,
            to_entity: Entity,
            type_: RelationshipType,
            confidence: float = 1.0,
        ) -> None:
            session.add(
                Relationship(
                    workspace_id=workspace.id,
                    from_entity_id=from_entity.id,
                    to_entity_id=to_entity.id,
                    type=type_,
                    confidence=confidence,
                    source_id=source.id,
                )
            )

        edge(aws, payment, database, RelationshipType.DEPENDS_ON)
        edge(aws, users, database, RelationshipType.DEPENDS_ON)
        edge(github, payment, auth, RelationshipType.DEPENDS_ON)
        edge(github, payment, users, RelationshipType.DEPENDS_ON)
        # Observed in traffic, documented nowhere — the kind of edge LEKA
        # exists to surface, and the reason confidence is a column.
        edge(datadog, auth, database, RelationshipType.DEPENDS_ON, confidence=0.72)

        edge(infra, payment, cluster, RelationshipType.DEPLOYED_TO)
        edge(infra, auth, cluster, RelationshipType.DEPLOYED_TO)
        edge(infra, users, cluster, RelationshipType.DEPLOYED_TO)

        edge(github, nadia, payment, RelationshipType.OWNS)
        edge(github, thomas, auth, RelationshipType.OWNS)
        edge(github, thomas, users, RelationshipType.OWNS)
        edge(github, mei, repository, RelationshipType.MEMBER_OF)

        edge(jira, incident, deployment, RelationshipType.CAUSED_BY, confidence=0.83)
        edge(datadog, incident, monitor, RelationshipType.MENTIONS)
        edge(jira, incident, payment, RelationshipType.MENTIONS)
        edge(sources["confluence:Runbooks space"], runbook, payment, RelationshipType.MENTIONS)

        await session.commit()

        counts = {
            "sources": len(SOURCES),
            "entities": len((await session.execute(select(Entity))).scalars().all()),
            "relationships": len((await session.execute(select(Relationship))).scalars().all()),
        }

    print(f"Seeded workspace {WORKSPACE_NAME!r} ({WORKSPACE_SLUG})")
    for label, count in counts.items():
        print(f"  {count:3} {label}")
    print("\nThe story it tells: payment-api v2.8.4 shipped 26h ago, p99 went")
    print("from 180ms to 2.1s, and auth-service turns out to share the database.")


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except KeyboardInterrupt:
        sys.exit(130)
