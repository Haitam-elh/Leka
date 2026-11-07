"""Environments & integrations, for LEKA's team (LEKA-555): every
organisation's sources, how their reads went, what they found; one
environment whole; its map, every relationship as certain as its data
makes it.

What these say comes from LEKA CORE's own records — the sources and their
reads (leka.connectors, leka.ingestion), the company model (leka.knowledge)
— never a figure of their own:

- a relationship is CONFIRMED when a source's records state it, or a person
  accepted it (LEKA-380); SUPPOSED when an enrichment rule inferred it —
  never shown as certain; a service or an application tied to nothing has
  UNKNOWN relationships: what it relies on is not known;
- the map holds only the relationships the model holds — stated by the
  data, or inferred from it — each with the sources that state it, the rule
  that inferred it, its confidence, and what says it, scanned for secrets;
- a source is VERIFIED when it is active, healthy and was read at least
  once; its errors are its diagnostics, cleaned of secrets when written and
  scanned again here;
- never a credential nor a source's settings: neither is read.

Read inside `system_scope()` like every admin read; demonstration
organisations left out of the figures across LEKA.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from leka.admin.reads import diagnostic_of, organisations_query, source_rows
from leka.admin.schemas import (
    ConnectorUse,
    EnvironmentChange,
    EnvironmentDetail,
    EnvironmentEntity,
    EnvironmentMap,
    EnvironmentRelations,
    EnvironmentRow,
    EnvironmentsOverview,
    EnvironmentState,
    MapLink,
    MapNode,
    MapSource,
    OrganisationRef,
    SourceRef,
    SyncRunRow,
)
from leka.connectors import HealthStatus, Source, SourceStatus, SyncStatus, manifests
from leka.core.sensitive import guarded
from leka.ingestion import SyncRun, SyncRunOutcome
from leka.knowledge import (
    Entity,
    EntityType,
    GraphRepository,
    GraphService,
    Lifecycle,
    ModelRun,
    Relationship,
    RelationshipChange,
    RelationshipIssue,
)
from leka.platform import Workspace

# Sources are read every hour (leka.ingestion.sync): three reads missed, what
# a source said then is not what is there now — the Digital Twin's rule.
STALE_AFTER = timedelta(hours=3)
FAILED = (SyncRunOutcome.FAILED, SyncRunOutcome.ABANDONED)
SERVICES = (EntityType.SERVICE, EntityType.APPLICATION)
SHOWN = (EntityType.SERVICE, EntityType.APPLICATION, EntityType.DATABASE)
CONFIRMED = ("stated", "accepted")
LATEST = 20
SERVICES_SHOWN = 100


def _real(column: Any) -> Any:
    return column.not_in(select(Workspace.id).where(Workspace.demo.is_(True)))


def certainty_of(origin: str) -> str:
    """Confirmed: stated by a source's records, or accepted by a person;
    supposed: inferred by a rule."""
    return "confirmed" if origin in CONFIRMED else "supposed"


def _failing(source: Source) -> bool:
    return (
        source.status == SourceStatus.ERROR
        or source.health_status == HealthStatus.UNHEALTHY
        or source.sync_status == SyncStatus.FAILED
    )


def _stale(source: Source, now: datetime) -> bool:
    return source.status == SourceStatus.ACTIVE and (
        source.last_synced_at is None or source.last_synced_at < now - STALE_AFTER
    )


def state_of(sources: Iterable[Source], now: datetime) -> EnvironmentState:
    """The worst of its sources, disabled ones aside: one failing, one
    degraded, one not read for three hours; none connected."""
    live = [s for s in sources if s.status != SourceStatus.DISABLED]
    if not live:
        return "none"
    if any(_failing(s) for s in live):
        return "error"
    if any(
        s.status == SourceStatus.DEGRADED or s.health_status == HealthStatus.DEGRADED for s in live
    ):
        return "degraded"
    if any(_stale(s, now) for s in live):
        return "stale"
    return "ok"


def _verified(source: Source) -> bool:
    return (
        source.status == SourceStatus.ACTIVE
        and source.health_status == HealthStatus.HEALTHY
        and source.last_synced_at is not None
    )


# ── Across LEKA ──────────────────────────────────────────────────────────────


async def overview(session: AsyncSession, *, now: datetime) -> EnvironmentsOverview:
    sources = (await session.scalars(select(Source).where(_real(Source.workspace_id)))).all()
    live = [s for s in sources if s.status != SourceStatus.DISABLED]
    by_workspace: dict[uuid.UUID, list[Source]] = defaultdict(list)
    for source in live:
        by_workspace[source.workspace_id].append(source)

    services = await session.scalar(
        select(func.count()).where(
            Entity.type.in_(SERVICES),
            Entity.lifecycle != Lifecycle.REMOVED,
            _real(Entity.workspace_id),
        )
    )
    syncs = dict(
        (
            await session.execute(
                select(SyncRun.status, func.count())
                .where(SyncRun.started_at >= now - timedelta(hours=24), _real(SyncRun.workspace_id))
                .group_by(SyncRun.status)
            )
        )
        .tuples()
        .all()
    )

    used: dict[str, list[Source]] = defaultdict(list)
    for source in live:
        used[str(source.kind)].append(source)

    def use(key: str, name: str, category: str, receives: bool) -> ConnectorUse:
        connected = used.get(key, [])
        seen = [s.last_synced_at for s in connected if s.last_synced_at]
        return ConnectorUse(
            key=key,
            name=name,
            category=category,
            receives=receives,
            sources=len(connected),
            organisations=len({s.workspace_id for s in connected}),
            in_error=sum(1 for s in connected if _failing(s)),
            last_synced_at=max(seen, default=None),
        )

    connectors = [use(str(m.key), m.display_name, str(m.category), m.receives) for m in manifests()]
    seen_at = [s.last_synced_at for s in live if s.last_synced_at]
    return EnvironmentsOverview(
        organisations=len(by_workspace),
        organisations_in_error=sum(
            1 for held in by_workspace.values() if any(_failing(s) for s in held)
        ),
        sources=len(live),
        active=sum(1 for s in live if s.status == SourceStatus.ACTIVE),
        in_error=sum(1 for s in live if _failing(s)),
        degraded=sum(
            1
            for s in live
            if not _failing(s)
            and (s.status == SourceStatus.DEGRADED or s.health_status == HealthStatus.DEGRADED)
        ),
        stale=sum(1 for s in live if _stale(s, now)),
        disabled=len(sources) - len(live),
        services=int(services or 0),
        syncs=sum(int(n) for n in syncs.values()),
        syncs_failed=sum(int(syncs.get(outcome, 0)) for outcome in FAILED),
        last_synced_at=max(seen_at, default=None),
        connectors=sorted(connectors, key=lambda c: (-c.sources, c.name.lower())),
    )


def environments_query(
    *, q: str | None = None, connected: bool = False, in_error: bool = False
) -> Select[tuple[Workspace]]:
    """The organisations (demonstrations left out): those with a source
    connected, those with one failing."""
    statement = organisations_query(q=q)
    live = and_(Source.workspace_id == Workspace.id, Source.status != SourceStatus.DISABLED)
    if connected:
        statement = statement.where(exists(select(Source.id).where(live)))
    if in_error:
        statement = statement.where(
            exists(
                select(Source.id).where(
                    live,
                    or_(
                        Source.status == SourceStatus.ERROR,
                        Source.health_status == HealthStatus.UNHEALTHY,
                        Source.sync_status == SyncStatus.FAILED,
                    ),
                )
            )
        )
    return statement


async def _counts(
    session: AsyncSession, column: Any, ids: Sequence[uuid.UUID], *where: Any
) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(column, func.count()).where(column.in_(ids), *where).group_by(column)
        )
    ).tuples()
    return {workspace: int(n) for workspace, n in rows}


async def environment_rows(
    session: AsyncSession, workspaces: Sequence[Workspace], *, now: datetime
) -> list[EnvironmentRow]:
    ids = [w.id for w in workspaces]
    held: dict[uuid.UUID, list[Source]] = defaultdict(list)
    if ids:
        for source in (
            await session.scalars(select(Source).where(Source.workspace_id.in_(ids)))
        ).all():
            held[source.workspace_id].append(source)
    services = await _counts(
        session,
        Entity.workspace_id,
        ids,
        Entity.type.in_(SERVICES),
        Entity.lifecycle != Lifecycle.REMOVED,
    )
    entities = await _counts(
        session, Entity.workspace_id, ids, Entity.lifecycle != Lifecycle.REMOVED
    )
    relationships = await _counts(session, Relationship.workspace_id, ids)
    failed = await _counts(
        session,
        SyncRun.workspace_id,
        ids,
        SyncRun.status.in_(FAILED),
        SyncRun.started_at >= now - timedelta(days=7),
    )
    rows = []
    for workspace in workspaces:
        sources = held.get(workspace.id, [])
        live = [s for s in sources if s.status != SourceStatus.DISABLED]
        seen = [s.last_synced_at for s in live if s.last_synced_at]
        rows.append(
            EnvironmentRow(
                organisation=OrganisationRef(id=workspace.id, name=workspace.name),
                state=state_of(sources, now),
                sources=len(live),
                in_error=sum(1 for s in live if _failing(s)),
                kinds=sorted({str(s.kind) for s in live}),
                last_synced_at=max(seen, default=None),
                services=services.get(workspace.id, 0),
                entities=entities.get(workspace.id, 0),
                relationships=relationships.get(workspace.id, 0),
                failed_syncs=failed.get(workspace.id, 0),
            )
        )
    return rows


# ── One environment ──────────────────────────────────────────────────────────


def sync_runs_query(
    *, organisation_id: uuid.UUID, source_id: uuid.UUID | None = None, status: str | None = None
) -> Select[tuple[SyncRun]]:
    statement = select(SyncRun).where(SyncRun.workspace_id == organisation_id)
    if source_id:
        statement = statement.where(SyncRun.source_id == source_id)
    if status == "failed":
        statement = statement.where(SyncRun.status.in_(FAILED))
    elif status:
        statement = statement.where(SyncRun.status == status)
    return statement


async def sync_run_rows(session: AsyncSession, runs: Sequence[SyncRun]) -> list[SyncRunRow]:
    ids = {r.source_id for r in runs}
    sources = (
        {s.id: s for s in (await session.scalars(select(Source).where(Source.id.in_(ids)))).all()}
        if ids
        else {}
    )

    def ref(source_id: uuid.UUID) -> SourceRef:
        source = sources.get(source_id)
        return SourceRef(
            id=source_id,
            kind=str(source.kind) if source else "",
            name=source.name if source else "",
        )

    return [
        SyncRunRow(
            id=r.id,
            source=ref(r.source_id),
            trigger=str(r.trigger),
            status=str(r.status),
            capability=r.capability,
            started_at=r.started_at,
            finished_at=r.finished_at,
            records=r.records,
            error=diagnostic_of(r.error),
        )
        for r in runs
    ]


def _environment_of(attributes: dict[str, object]) -> str | None:
    said = attributes.get("environment")
    return str(said) if isinstance(said, str) and said else None


def _sources_of(provenance: dict[str, object], sources: dict[str, Source]) -> list[SourceRef]:
    said = provenance.get("sources")
    found: dict[str, SourceRef] = {}
    for item in said if isinstance(said, list) else []:
        if not isinstance(item, dict):
            continue
        source = sources.get(str(item.get("source_id")))
        if source is not None:
            found[str(source.id)] = SourceRef(id=source.id, kind=str(source.kind), name=source.name)
    return list(found.values())


async def environment_detail(
    session: AsyncSession, workspace_id: uuid.UUID, *, now: datetime
) -> EnvironmentDetail | None:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return None
    sources = (
        await session.scalars(
            select(Source).where(Source.workspace_id == workspace_id).order_by(Source.created_at)
        )
    ).all()
    by_id = {str(s.id): s for s in sources}
    runs = (
        await session.scalars(
            sync_runs_query(organisation_id=workspace_id)
            .order_by(SyncRun.started_at.desc())
            .limit(LATEST)
        )
    ).all()
    failed = await session.scalar(
        select(func.count()).where(
            SyncRun.workspace_id == workspace_id,
            SyncRun.status.in_(FAILED),
            SyncRun.started_at >= now - timedelta(days=7),
        )
    )
    built = await session.scalar(
        select(func.max(ModelRun.finished_at)).where(
            ModelRun.workspace_id == workspace_id, ModelRun.status == "succeeded"
        )
    )
    live = Entity.lifecycle != Lifecycle.REMOVED
    by_type = {
        str(kind): int(n)
        for kind, n in (
            await session.execute(
                select(Entity.type, func.count())
                .where(Entity.workspace_id == workspace_id, live)
                .group_by(Entity.type)
            )
        ).tuples()
    }
    shown = (
        await session.scalars(
            select(Entity)
            .where(Entity.workspace_id == workspace_id, Entity.type.in_(SHOWN), live)
            .order_by(Entity.last_seen_at.desc().nulls_last(), Entity.name)
            .limit(SERVICES_SHOWN)
        )
    ).all()
    origins = Counter(
        {
            str(origin): int(n)
            for origin, n in (
                await session.execute(
                    select(Relationship.origin, func.count())
                    .where(Relationship.workspace_id == workspace_id)
                    .group_by(Relationship.origin)
                )
            ).tuples()
        }
    )
    tied = select(Relationship.id).where(
        Relationship.workspace_id == workspace_id,
        or_(Relationship.from_entity_id == Entity.id, Relationship.to_entity_id == Entity.id),
    )
    unknown = await session.scalar(
        select(func.count()).where(
            Entity.workspace_id == workspace_id,
            Entity.type.in_(SERVICES),
            live,
            ~exists(tied),
        )
    )
    issues = await session.scalar(
        select(func.count()).where(RelationshipIssue.workspace_id == workspace_id)
    )
    start, end = aliased(Entity), aliased(Entity)
    changes = (
        await session.execute(
            select(RelationshipChange, start.name, end.name)
            .join(
                start,
                and_(
                    start.workspace_id == RelationshipChange.workspace_id,
                    start.id == RelationshipChange.from_entity_id,
                ),
            )
            .join(
                end,
                and_(
                    end.workspace_id == RelationshipChange.workspace_id,
                    end.id == RelationshipChange.to_entity_id,
                ),
            )
            .where(RelationshipChange.workspace_id == workspace_id)
            .order_by(RelationshipChange.recorded_at.desc())
            .limit(LATEST)
        )
    ).tuples()

    def after_certainty(change: RelationshipChange) -> Any:
        after = change.after or {}
        origin = after.get("origin")
        return certainty_of(str(origin)) if change.change != "removed" and origin else None

    return EnvironmentDetail(
        organisation=OrganisationRef(id=workspace.id, name=workspace.name),
        state=state_of(sources, now),
        built_at=built,
        sources=await source_rows(session, sources),
        syncs=await sync_run_rows(session, runs),
        failed_syncs=int(failed or 0),
        entities=dict(sorted(by_type.items(), key=lambda item: -item[1])),
        services=[
            EnvironmentEntity(
                id=e.id,
                type=str(e.type),
                name=e.name,
                lifecycle=str(e.lifecycle),
                environment=_environment_of(e.attributes),
                confidence=e.confidence,
                last_seen_at=e.last_seen_at,
                sources=_sources_of(e.provenance, by_id),
            )
            for e in shown
        ],
        relations=EnvironmentRelations(
            confirmed=sum(origins[o] for o in CONFIRMED),
            supposed=sum(n for o, n in origins.items() if o not in CONFIRMED),
            unknown=int(unknown or 0),
            issues=int(issues or 0),
        ),
        history=[
            EnvironmentChange(
                from_name=from_name,
                to_name=to_name,
                type=change.type,
                change=change.change,
                certainty=after_certainty(change),
                recorded_at=change.recorded_at,
            )
            for change, from_name, to_name in changes
        ],
    )


async def environment_map(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    now: datetime,
    environment: str | None = None,
) -> EnvironmentMap | None:
    """Its architecture as its customer's map draws it (leka.knowledge,
    every card), its links each said confirmed or supposed, what says them
    scanned for secrets; where it was read from, and how fresh."""
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return None
    drawn = await GraphService(GraphRepository(session, workspace_id)).architecture(
        now=now, environment=environment, detailed=True
    )
    ids = {card.id for card in drawn.cards}
    links = [
        MapLink(
            from_id=link.from_id,
            to_id=link.to_id,
            role=link.role,
            certainty="confirmed" if link.origin in CONFIRMED else "supposed",
            origin=link.origin,
            rule=link.rule,
            confidence=round(link.confidence, 2),
            sources=list(link.sources),
            evidence=guarded(link.evidence) if link.evidence else None,
        )
        # Only between what is drawn: a relationship the data holds, both ends shown.
        for link in drawn.links
        if link.from_id in ids and link.to_id in ids
    ]
    linked = {link.from_id for link in links} | {link.to_id for link in links}
    nodes = [
        MapNode(
            id=card.id,
            column=card.column,
            group=card.group,
            kind=card.kind,
            type=card.type,
            name=card.name,
            status=card.status,
            deduced=card.deduced,
            environment=card.environment,
            sources=list(card.sources),
            linked=card.id in linked,
        )
        for card in drawn.cards
    ]
    sources = {
        s.id: s
        for s in (
            await session.scalars(select(Source).where(Source.workspace_id == workspace_id))
        ).all()
    }
    read = [
        MapSource(
            id=said.source_id,
            kind=said.kind,
            name=said.name,
            status=said.status,
            last_synced_at=said.last_synced_at,
            entities=said.entities,
            verified=_verified(sources[said.source_id]) if said.source_id in sources else False,
        )
        for said in drawn.sources
    ]
    return EnvironmentMap(
        organisation=OrganisationRef(id=workspace.id, name=workspace.name),
        built_at=drawn.built_at,
        environment=drawn.environment,
        environments=list(drawn.environments),
        nodes=nodes,
        links=links,
        confirmed=sum(1 for link in links if link.certainty == "confirmed"),
        supposed=sum(1 for link in links if link.certainty == "supposed"),
        unknown=sum(1 for node in nodes if not node.linked),
        sources=read,
        unverified=sum(1 for said in read if not said.verified),
    )


__all__ = [
    "certainty_of",
    "environment_detail",
    "environment_map",
    "environment_rows",
    "environments_query",
    "overview",
    "state_of",
    "sync_run_rows",
    "sync_runs_query",
]
