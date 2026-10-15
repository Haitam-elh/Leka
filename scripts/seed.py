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
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from leka.billing import AgentEntitlement
from leka.connectors import Source, SourceKind, SourceStatus
from leka.core.security import hash_password
from leka.db import session_factory, system_scope
from leka.governance import set_plan
from leka.identity import User as Account
from leka.ingestion import (
    RESOLVER_VERSION,
    EnrichedRelationship,
    ResolutionDecision,
    ResolvedEntity,
    ResolvedKey,
)
from leka.intelligence.job import analyse_workspace
from leka.knowledge import (
    MODEL_VERSION,
    AssertionRepository,
    Entity,
    EntityType,
    EntityVersion,
    EvolutionRepository,
    EvolutionService,
    Lifecycle,
    ModelRun,
    Relationship,
    RelationshipChange,
    RelationshipType,
    search_fields,
)
from leka.knowledge.build import changes, content_of
from leka.platform import Membership, Role, Workspace

WORKSPACE_SLUG = "acme"
WORKSPACE_NAME = "Acme Corp"

# The demo login. Local only — see the note where the account is created.
DEMO_EMAIL = "nora@acme.example"
DEMO_PASSWORD = "leka-demo-password"  # noqa: S105

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
    (SourceKind.SLACK, "#platform", SourceStatus.DRAFT),
)


# ── The month that led here (LEKA-383) ─────────────────────────────────────
# The model's history, as its builds would have recorded it: what appeared
# when, what each thing said before, the ties that came and went. Days ago.
FIRST_BUILD = 30.0
# When each thing first appeared — the rest, at the first build.
APPEARED: dict[str, float] = {
    "gh:mei-tanaka": 20,
    "gh-team:acme/platform": 14,
    "gh:acme/user-service": 3,
    "deploy-2026-09-18-1432": 26 / 24,
    "OPS-1841": 25 / 24,
    "dd-monitor-77213": 25 / 24,
}
# What a thing said before — from when — and since when it says what it says.
BEFORE: dict[str, tuple[list[tuple[float, dict[str, object]]], float]] = {
    # payment-api shipped 2.8.2, 2.8.3, then 2.8.4 — the deployment.
    "svc-payment-api": (
        [
            (FIRST_BUILD, {"version": "2.8.1"}),
            (16, {"version": "2.8.2"}),
            (8, {"version": "2.8.3"}),
        ],
        26 / 24,
    ),
    # user-service moved from Payments to Platform.
    "svc-user-service": ([(FIRST_BUILD, {"team": "payments"})], 14),
}
# When a tie appeared, when not with its ends.
TIED: dict[tuple[str, str, str], float] = {
    ("svc-payment-api", "depends_on", "svc-user-service"): 10,
    # Observed in traffic five days ago (Datadog).
    ("svc-auth-service", "depends_on", "arn:aws:rds:eu-west-1:acme:db:postgres-prod"): 5,
    ("gh:t-berger", "owns", "svc-user-service"): 14,
}
REDIS = "arn:aws:elasticache:eu-west-1:acme:cluster/redis-sessions"
# Ties that went: from, kind, to, appeared, went.
WENT: tuple[tuple[str, str, str, float, float], ...] = (
    ("gh:nadia-k", "owns", "svc-user-service", FIRST_BUILD, 14),
    ("svc-auth-service", "depends_on", REDIS, FIRST_BUILD, 6),
)
# What no source shows any more, and since when.
REMOVED: dict[str, float] = {REDIS: 6}


async def _reset(session: Any) -> None:
    """Remove the demo workspace and its account.

    Everything else cascades from the workspace; the account is separate
    because a person is not owned by a tenant.
    """
    await session.execute(delete(Workspace).where(Workspace.slug == WORKSPACE_SLUG))
    await session.execute(delete(Account).where(Account.email == DEMO_EMAIL))
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

        # A French company, as the demo has always been (docs/languages.md).
        workspace = Workspace(name=WORKSPACE_NAME, slug=WORKSPACE_SLUG, default_language="fr")
        session.add(workspace)
        await session.flush()

        # A sign-in-able account, already verified. Without one the demo data
        # exists and nobody can look at it: since LEKA-330 every screen is
        # behind authentication, and a seed you cannot open is half a seed.
        #
        # The password is in this file and in docs/setup.md. That is fine and
        # deliberate — this account only ever exists in a developer's local
        # database, next to a workspace called Acme Corp.
        account = Account(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            email_verified_at=NOW,
            # Chosen, as registering keeps the language the form was shown in.
            language="fr",
        )
        session.add(account)
        await session.flush()
        session.add(Membership(workspace_id=workspace.id, user_id=account.id, role=Role.OWNER))
        # LEKA's own demo: every agent, as its team's workspaces (2026-10-14).
        session.add(
            AgentEntitlement(
                workspace_id=workspace.id,
                key="*",
                kind="all",
                origin="grant",
                status="active",
                by_whom="seed",
                reason="LEKA's demo workspace: every agent",
                started_at=NOW,
            )
        )
        await session.flush()
        # Twelve sources: more than Free allows (LEKA-463).
        await set_plan(session, workspace.id, "business", by="seed", reason="the demo company")

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
            occurred_at: datetime | None = None,
        ) -> Entity:
            # The company model (LEKA-361) is built from what resolution
            # made; the demo writes it directly, saying where each thing
            # was "seen" — and what search reads of it (LEKA-369) — as a
            # build would.
            search_name, search_text = search_fields(external_id, name, attributes)
            row = Entity(
                workspace_id=workspace.id,
                type=type_,
                key=external_id,
                name=name,
                attributes=attributes,
                confidence=confidence,
                provenance={
                    "sources": [{"source_id": str(source.id), "key": external_id, "kind": "id"}],
                    "attributes": {attribute: {"origin": "source"} for attribute in attributes},
                    "dropped": [],
                },
                first_seen_at=last_seen or NOW,
                last_seen_at=last_seen or NOW,
                occurred_at=occurred_at,
                search_name=search_name,
                search_text=search_text,
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
        # Datadog watches it too, and its SLO says 99.9, not 99.95: resolution
        # chose GitHub's and kept both (LEKA-372: a context says so).
        payment.provenance = {
            **payment.provenance,
            "sources": [
                *payment.provenance["sources"],
                {"source_id": str(datadog.id), "key": "service:payment-api", "kind": "key"},
            ],
            "conflicts": [
                {
                    "attribute": "sla",
                    "chosen": "99.95",
                    "values": [
                        {"value": "99.95", "source_id": str(github.id)},
                        {"value": "99.9", "source_id": str(datadog.id)},
                    ],
                }
            ],
        }
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
        # Jira's account for Nadia: resolution could not be sure it is her —
        # an address of her own — so it linked them, kept apart (below).
        nadia_jira = entity(
            jira,
            EntityType.PERSON,
            "jira:nadia.k",
            "Nadia K.",
            {"email": "nadia.k@acme.example", "team": "payments"},
            confidence=0.9,
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
                "state": "succeeded",
                "environment": "production",
            },
            last_seen=NOW - timedelta(hours=26),
            occurred_at=NOW - timedelta(hours=26),
        )
        incident = entity(
            jira,
            EntityType.INCIDENT,
            "OPS-1841",
            "payment-api p99 latency above 2s",
            {
                # As normalisation writes an incident (LEKA-367): its state,
                # its dates — what an incident's analysis reads (LEKA-341).
                "severity": "sev2",
                "state": "closed",
                "created_at": (NOW - timedelta(hours=25)).isoformat(),
                "resolved_at": (NOW - timedelta(hours=21)).isoformat(),
                "duration_minutes": 240,
                "p99_before_ms": 180,
                "p99_peak_ms": 2140,
            },
            last_seen=NOW - timedelta(hours=21),
            occurred_at=NOW - timedelta(hours=25),
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
            # As enrichment says it (LEKA-366): unchanged for eight months,
            # stale — the only document describing payment-api (LEKA-379).
            {
                "updated_at": (NOW - timedelta(days=243)).isoformat(),
                "last_activity_at": (NOW - timedelta(days=243)).isoformat(),
                "freshness": "stale",
                "author": "nadia-k",
            },
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
        # What LEKA's enrichment proposes, and waits for someone to validate
        # (LEKA-380): user-service's own repository, which nothing ties to
        # it; the Platform team, whose two members maintain postgres-prod —
        # the database no one is named to own.
        user_repository = entity(
            github,
            EntityType.REPOSITORY,
            "gh:acme/user-service",
            "acme/user-service",
            {
                "default_branch": "main",
                "language": "go",
                "private": True,
                "description": "User accounts, sign-up and profiles",
            },
        )
        platform = entity(
            github, EntityType.TEAM, "gh-team:acme/platform", "Platform", {"slug": "platform"}
        )
        # auth-service's session cache: the production account stopped
        # showing it six days ago — removed from the model, its history kept
        # (LEKA-383: auth-service relied on it).
        redis = entity(
            aws,
            EntityType.INFRA_RESOURCE,
            REDIS,
            "redis-sessions",
            {
                "provider": "aws",
                "region": "eu-west-1",
                "engine": "redis",
                "resource_class": "cache",
            },
            last_seen=NOW - timedelta(days=REMOVED[REDIS]),
        )
        redis.lifecycle = Lifecycle.REMOVED
        redis.removed_at = redis.lifecycle_changed_at = NOW - timedelta(days=REMOVED[REDIS])
        await session.flush()

        edges: list[Relationship] = []

        def edge(
            source: Source,
            from_entity: Entity,
            to_entity: Entity,
            type_: RelationshipType,
            confidence: float = 1.0,
        ) -> None:
            tie = Relationship(
                workspace_id=workspace.id,
                from_entity_id=from_entity.id,
                to_entity_id=to_entity.id,
                type=type_,
                confidence=confidence,
                origin="stated",
                rule="stated",
                provenance=[{"source_id": str(source.id)}],
            )
            session.add(tie)
            edges.append(tie)

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
        edge(jira, nadia_jira, payment, RelationshipType.OWNS)
        edge(github, thomas, auth, RelationshipType.OWNS)
        edge(github, thomas, users, RelationshipType.OWNS)
        edge(github, mei, repository, RelationshipType.MEMBER_OF)
        edge(github, thomas, platform, RelationshipType.MEMBER_OF)
        edge(github, mei, platform, RelationshipType.MEMBER_OF)
        edge(infra, database, thomas, RelationshipType.MAINTAINED_BY)
        edge(infra, database, mei, RelationshipType.MAINTAINED_BY)
        edge(github, user_repository, mei, RelationshipType.MAINTAINED_BY)

        edge(jira, incident, deployment, RelationshipType.CAUSED_BY, confidence=0.83)
        edge(jira, incident, payment, RelationshipType.AFFECTS)
        edge(github, deployment, payment, RelationshipType.PART_OF)
        edge(datadog, incident, monitor, RelationshipType.MENTIONS)
        edge(jira, incident, payment, RelationshipType.MENTIONS)
        edge(sources["confluence:Runbooks space"], runbook, payment, RelationshipType.DESCRIBES)

        # What the model is built from: the same things as resolution made
        # them, under the same ids — a build keeps resolution's. An entity's
        # sheet reads them (LEKA-359): without them, every sheet of the demo
        # says it found nothing.
        built = await session.execute(select(Entity).where(Entity.workspace_id == workspace.id))
        modelled = list(built.scalars())
        await _history(session, workspace.id, modelled, edges)
        for thing in modelled:
            if thing.lifecycle is Lifecycle.REMOVED:
                continue  # no source shows it: nothing resolved it
            session.add(
                ResolvedEntity(
                    id=thing.id,
                    workspace_id=workspace.id,
                    type=thing.type.value,
                    key=thing.key,
                    name=thing.name,
                    names=[thing.name],
                    attributes=dict(thing.attributes),
                    confidence=thing.confidence,
                    sources=len(thing.provenance.get("sources", [])) or 1,
                    resolver_version=RESOLVER_VERSION,
                    resolved_at=NOW,
                )
            )
        await session.flush()
        # The ties, as enrichment keeps them (LEKA-442): what the map draws,
        # what an incident is on — the Digital Twin's links.
        kept = {thing.id for thing in modelled if thing.lifecycle is not Lifecycle.REMOVED}
        for tie in edges:
            if tie.from_entity_id not in kept or tie.to_entity_id not in kept:
                continue
            session.add(
                EnrichedRelationship(
                    workspace_id=workspace.id,
                    from_entity_id=tie.from_entity_id,
                    to_entity_id=tie.to_entity_id,
                    type=tie.type.value,
                    origin="stated",
                    rule="stated",
                    confidence=tie.confidence,
                    cross_source=False,
                    sources=1,
                    evidence="Stated by its source.",
                    provenance=list(tie.provenance),
                    enriched_at=NOW,
                )
            )
        # Which source shows what, as resolution keeps it (LEKA-442): what the
        # Digital Twin's states and their provenance are read from.
        for thing in modelled:
            if thing.lifecycle is Lifecycle.REMOVED:
                continue
            for seen in thing.provenance.get("sources", []):
                session.add(
                    ResolvedKey(
                        workspace_id=workspace.id,
                        entity_id=thing.id,
                        source_id=uuid.UUID(seen["source_id"]),
                        key=seen["key"],
                        kind=seen["kind"] if seen["kind"] in ("key", "alias", "derived") else "key",
                        name=thing.name,
                        records=1,
                        first_seen_at=thing.first_seen_at,
                        last_seen_at=thing.last_seen_at,
                    )
                )
        # Built, as far as the model knows: what it holds was written as a
        # build writes it (LEKA-373 says a model never built is missing).
        session.add(
            ModelRun(
                workspace_id=workspace.id,
                status="succeeded",
                started_at=NOW,
                finished_at=NOW,
                model_version=MODEL_VERSION,
                counts={},
            )
        )
        await session.flush()
        session.add(
            ResolutionDecision(
                workspace_id=workspace.id,
                entity_id=nadia_jira.id,
                other_entity_id=nadia.id,
                kind="link",
                rule="similar_name",
                confidence=0.78,
                keys=["jira:nadia.k", "gh:nadia-k"],
                evidence="Nadia K. ~ Nadia Kowalski: same team, a name that begins hers.",
            )
        )

        await session.commit()
        # What the model held, week by week, rebuilt from that history — and
        # now (LEKA-383).
        await EvolutionService(
            EvolutionRepository(session, workspace.id), AssertionRepository(session, workspace.id)
        ).record(now=NOW, run_id=None)
        await session.commit()

        counts = {
            "sources": len(SOURCES),
            "entities": len((await session.execute(select(Entity))).scalars().all()),
            "relationships": len((await session.execute(select(Relationship))).scalars().all()),
        }

    # What LEKA concludes from it (LEKA-377): the analyses, run as the job
    # runs them — "Insights LEKA" shows what they found, nothing written by
    # hand.
    analysed = await analyse_workspace(workspace.id, trigger="schedule")
    counts["open findings"] = int(str(analysed.get("opened", 0)))

    print(f"Seeded workspace {WORKSPACE_NAME!r} ({WORKSPACE_SLUG})")
    for label, count in counts.items():
        print(f"  {count:3} {label}")
    print(f"\nSign in at /login with {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print("\nThe story it tells: payment-api v2.8.4 shipped 26h ago, p99 went")
    print("from 180ms to 2.1s, and auth-service turns out to share the database.")


async def _history(
    session: Any, workspace_id: Any, things: list[Entity], edges: list[Relationship]
) -> None:
    """The month that led to the model as it is, written as its builds
    recorded it (LEKA-383): one build a day something changed — each
    version, each tie that came or went. Nothing here contradicts what the
    model holds now; it is how it got there."""
    by_key = {thing.key: thing for thing in things}
    days = {
        FIRST_BUILD,
        *APPEARED.values(),
        *(d for said, since in BEFORE.values() for d in (since, *(day for day, _ in said))),
        *TIED.values(),
        *(d for *_, appeared, went in WENT for d in (appeared, went)),
        *REMOVED.values(),
    }
    runs: dict[float, Any] = {}
    for day in sorted(days, reverse=True):
        at = NOW - timedelta(days=day)
        run = ModelRun(
            workspace_id=workspace_id,
            status="succeeded",
            started_at=at,
            finished_at=at,
            model_version=MODEL_VERSION,
            counts={},
        )
        session.add(run)
        runs[day] = run
    await session.flush()

    def recorded(day: float) -> dict[str, Any]:
        return {"recorded_at": NOW - timedelta(days=day), "run_id": runs[day].id}

    for thing in things:
        now = dict(thing.attributes)
        said, since = BEFORE.get(thing.key, ([], APPEARED.get(thing.key, FIRST_BUILD)))
        course = [(day, {**now, **before}) for day, before in said]
        course.append((since, now))
        if not said:
            course = [(APPEARED.get(thing.key, FIRST_BUILD), now)]
        contents = [
            (day, content_of(thing.name, attributes, "active")) for day, attributes in course
        ]
        if thing.key in REMOVED:
            contents.append((REMOVED[thing.key], content_of(thing.name, now, "removed")))
        previous: dict[str, object] | None = None
        for number, (day, content) in enumerate(contents, start=1):
            session.add(
                EntityVersion(
                    workspace_id=workspace_id,
                    entity_id=thing.id,
                    version=number,
                    content=content,
                    changed=["created"] if previous is None else changes(previous, content),
                    schema_version=1,
                    **recorded(day),
                )
            )
            previous = content
        thing.version = len(contents)
        thing.first_seen_at = NOW - timedelta(days=contents[0][0])

    def state(tie: Relationship | None, confidence: float = 1.0) -> dict[str, object]:
        return {
            "confidence": tie.confidence if tie else confidence,
            "origin": "stated",
            "rule": "stated",
            "environments": [],
        }

    keys = {thing.id: thing.key for thing in things}
    for tie in edges:
        ends = (keys[tie.from_entity_id], tie.type.value, keys[tie.to_entity_id])
        day = TIED.get(
            ends,
            min(APPEARED.get(ends[0], FIRST_BUILD), APPEARED.get(ends[2], FIRST_BUILD)),
        )
        tie.first_seen_at = tie.changed_at = NOW - timedelta(days=day)
        session.add(
            RelationshipChange(
                workspace_id=workspace_id,
                from_entity_id=tie.from_entity_id,
                to_entity_id=tie.to_entity_id,
                type=tie.type.value,
                change="added",
                before=None,
                after=state(tie),
                **recorded(day),
            )
        )
    for start, kind, end, appeared, went in WENT:
        for change, day in (("added", appeared), ("removed", went)):
            session.add(
                RelationshipChange(
                    workspace_id=workspace_id,
                    from_entity_id=by_key[start].id,
                    to_entity_id=by_key[end].id,
                    type=kind,
                    change=change,
                    before=state(None) if change == "removed" else None,
                    after=state(None) if change == "added" else None,
                    **recorded(day),
                )
            )
    await session.flush()


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except KeyboardInterrupt:
        sys.exit(130)
