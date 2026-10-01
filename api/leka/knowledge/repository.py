"""Database access for the knowledge module.

The only place in this module where a query is written (architecture rule 4),
and the only place a graph traversal is expressed.

Every repository is scoped to one workspace: rule 2 and rule 3 mean there is
no legitimate query here that is not.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Select, delete, exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.db import WorkspaceScopedRepository
from leka.knowledge.build import Built, Current
from leka.knowledge.models import (
    Entity,
    EntityType,
    EntityVersion,
    Lifecycle,
    ModelRun,
    Relationship,
    RelationshipType,
)

CHUNK = 1_000


@dataclass(frozen=True)
class LandscapeFilters:
    """What a list of services or applications is narrowed to (LEKA-362)."""

    lifecycle: Lifecycle | None = None
    criticality: str | None = None
    stage: str | None = None
    environment: str | None = None
    application_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    q: str | None = None


# What the infrastructure is made of (LEKA-363), and what resources are in.
RESOURCE_TYPES = (EntityType.INFRA_RESOURCE, EntityType.DATABASE)
SCOPE_TYPES = (EntityType.CLOUD_ACCOUNT, EntityType.RESOURCE_GROUP)


@dataclass(frozen=True)
class InfrastructureFilters:
    """What a list of resources is narrowed to (LEKA-363): by what they are,
    where they are, whose they are."""

    lifecycle: Lifecycle | None = None
    resource_class: str | None = None
    resource_kind: str | None = None
    provider: str | None = None
    # An account, a subscription, a project — or a resource group.
    account_id: uuid.UUID | None = None
    region: str | None = None
    environment: str | None = None
    state: str | None = None
    exposure: str | None = None
    criticality: str | None = None
    service_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    q: str | None = None


@dataclass(frozen=True)
class Holding:
    """How many resources of a class, in a region, an account holds."""

    holder: uuid.UUID
    resource_class: str | None
    region: str | None
    count: int


class ModelRepository(WorkspaceScopedRepository):
    """The company model's builds: where they stand, what the last left, and
    writing the next."""

    async def latest_run(self, *, succeeded: bool = False) -> ModelRun | None:
        statement = self.select(ModelRun)
        if succeeded:
            statement = statement.where(ModelRun.status == "succeeded")
        found = await self._session.execute(statement.order_by(ModelRun.started_at.desc()).limit(1))
        return found.scalar_one_or_none()

    async def pending(self, basis: uuid.UUID | None, version: int) -> bool:
        """Whether building now would read anything the last success did not:
        a newer enrichment run, or a new model. Nothing enriched: nothing."""
        if basis is None:
            return False
        last = await self.latest_run(succeeded=True)
        return last is None or last.enrichment_run_id != basis or last.model_version != version

    async def start(self, basis: uuid.UUID | None, version: int, *, at: datetime) -> ModelRun:
        """A new run; one still `running` is a dead worker's, closed first."""
        await self._session.execute(
            update(ModelRun)
            .where(ModelRun.workspace_id == self.workspace_id, ModelRun.status == "running")
            .values(status="abandoned", finished_at=at, updated_at=func.now())
        )
        run = ModelRun(
            status="running", started_at=at, enrichment_run_id=basis, model_version=version
        )
        self.add(run)
        await self.flush()
        return run

    async def current(self) -> dict[uuid.UUID, Current]:
        """The model as the last build left it."""
        rows = await self.list(self.select(Entity))
        return {
            row.id: Current(
                id=row.id,
                name=row.name,
                attributes=dict(row.attributes),
                lifecycle=row.lifecycle.value,
                version=row.version,
                content_hash=row.content_hash,
                first_seen_at=row.first_seen_at,
                lifecycle_changed_at=row.lifecycle_changed_at,
                provenance=dict(row.provenance),
                key=row.key,
                type=row.type.value,
                schema_version=row.schema_version,
                confidence=row.confidence,
                quality=row.quality,
                last_seen_at=row.last_seen_at,
            )
            for row in rows
        }

    async def write(self, built: Built, *, run_id: uuid.UUID) -> None:
        """The build's rows, in the caller's transaction: entities upserted —
        their ids kept — versions recorded, relationships replaced."""
        for start in range(0, len(built.entities), CHUNK):
            chunk = [
                {"workspace_id": self.workspace_id, **row}
                for row in built.entities[start : start + CHUNK]
            ]
            statement = insert(Entity).values(chunk)
            columns = [c for c in chunk[0] if c not in ("id", "workspace_id")]
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Entity.id],
                    set_={
                        **{c: getattr(statement.excluded, c) for c in columns},
                        "updated_at": func.now(),
                    },
                    # Never another workspace's row, whatever the id says.
                    where=Entity.workspace_id == self.workspace_id,
                )
            )
        await self._insert(
            EntityVersion, [{**version, "run_id": run_id} for version in built.versions]
        )
        await self._session.execute(
            delete(Relationship).where(Relationship.workspace_id == self.workspace_id)
        )
        await self._insert(Relationship, built.relationships)

    async def _insert(self, model: type[Any], rows: list[dict[str, object]]) -> None:
        for start in range(0, len(rows), CHUNK):
            await self._session.execute(
                insert(model).values(
                    [
                        {"workspace_id": self.workspace_id, **row}
                        for row in rows[start : start + CHUNK]
                    ]
                )
            )


class ModelSweeper:
    """The builds of every workspace, for the hourly sweep (job.py). Not
    workspace-scoped, like leka.ingestion's SyncScheduleRepository: it runs
    under system_scope, declared by its caller."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _last_successes(self) -> Select[tuple[uuid.UUID, uuid.UUID | None, int, uuid.UUID]]:
        return (
            select(
                ModelRun.workspace_id,
                ModelRun.enrichment_run_id,
                ModelRun.model_version,
                ModelRun.id,
            )
            .where(ModelRun.status == "succeeded")
            .distinct(ModelRun.workspace_id)
            .order_by(ModelRun.workspace_id, ModelRun.started_at.desc())
        )

    async def built(self) -> dict[uuid.UUID, tuple[uuid.UUID | None, int]]:
        """workspace → what its last successful build read: (enrichment
        run, model version)."""
        rows = await self._session.execute(self._last_successes())
        return {workspace: (basis, version) for workspace, basis, version, _ in rows.all()}

    async def abandon_stuck(self, *, before: datetime, at: datetime) -> int:
        """Runs still `running` that started before `before`: their worker died."""
        result = await self._session.execute(
            update(ModelRun)
            .where(ModelRun.status == "running", ModelRun.started_at < before)
            .values(status="abandoned", finished_at=at, updated_at=func.now())
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def prune(self, *, before: datetime) -> int:
        """Finished runs started before `before` — never a workspace's last
        success, which says what its model was made from."""
        last = self._last_successes().subquery()
        result = await self._session.execute(
            delete(ModelRun).where(
                ModelRun.status != "running",
                ModelRun.started_at < before,
                ModelRun.id.not_in(select(last.c.id)),
            )
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)


class EntityRepository(WorkspaceScopedRepository):
    """Reads the company model: its entities, their history, their
    neighbourhood."""

    def entities(self) -> Select[tuple[Entity]]:
        return self.select(Entity)

    async def versions_of(self, entity_id: uuid.UUID) -> Sequence[EntityVersion]:
        return await self.list(
            self.select(EntityVersion)
            .where(EntityVersion.entity_id == entity_id)
            .order_by(EntityVersion.version.desc())
        )

    async def edges_of(
        self, entity_id: uuid.UUID, *, limit: int
    ) -> tuple[Sequence[Relationship], int]:
        """An entity's relationships both ways, the surest first — and how
        many there are."""
        touching = or_(
            Relationship.from_entity_id == entity_id, Relationship.to_entity_id == entity_id
        )
        total = await self._session.scalar(
            select(func.count()).where(Relationship.workspace_id == self.workspace_id, touching)
        )
        edges = await self.list(
            self.select(Relationship)
            .where(touching)
            .order_by(Relationship.type, Relationship.confidence.desc(), Relationship.id)
            .limit(limit)
        )
        return edges, int(total or 0)

    async def by_ids(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Entity]:
        if not ids:
            return {}
        found = await self.list(self.select(Entity).where(Entity.id.in_(set(ids))))
        return {entity.id: entity for entity in found}

    async def neighbourhood(
        self, entity_id: uuid.UUID, *, depth: int, limit: int
    ) -> tuple[list[Entity], list[Relationship]]:
        """What surrounds an entity, `depth` steps away in either direction —
        removed things left out. A recursive query, bounded by depth and by
        `limit` entities (docs/adr/001-postgresql.md)."""
        walk = text(
            """
            WITH RECURSIVE reach(id, depth) AS (
                SELECT CAST(:root AS uuid), 0
                UNION
                SELECT CASE WHEN r.from_entity_id = reach.id
                            THEN r.to_entity_id ELSE r.from_entity_id END,
                       reach.depth + 1
                FROM reach
                JOIN relationships r
                  ON r.workspace_id = :workspace
                 AND (r.from_entity_id = reach.id OR r.to_entity_id = reach.id)
                WHERE reach.depth < :depth
            )
            SELECT reach.id FROM reach
            JOIN entities e ON e.id = reach.id AND e.workspace_id = :workspace
            WHERE e.lifecycle <> 'removed' OR reach.id = CAST(:root AS uuid)
            GROUP BY reach.id
            ORDER BY min(reach.depth)
            LIMIT :limit
            """
        )
        rows = await self._session.execute(
            walk,
            {"root": entity_id, "workspace": self.workspace_id, "depth": depth, "limit": limit},
        )
        ids = [row[0] for row in rows.all()]
        entities = list((await self.by_ids(ids)).values())
        edges = await self.list(
            self.select(Relationship).where(
                Relationship.from_entity_id.in_(ids), Relationship.to_entity_id.in_(ids)
            )
        )
        return entities, list(edges)

    # ── the landscape: applications and services (LEKA-362) ─────────────────

    def landscape(self, kind: EntityType, filters: LandscapeFilters) -> Select[tuple[Entity]]:
        """The services — or the applications — of the workspace, for a
        page: every lifecycle but removed unless asked, and only those that
        are as critical, at that stage, run there, belong to that
        application or that team."""
        statement = self.select(Entity).where(Entity.type == kind)
        f = filters
        if f.lifecycle is None:
            statement = statement.where(Entity.lifecycle != Lifecycle.REMOVED)
        else:
            statement = statement.where(Entity.lifecycle == f.lifecycle)
        if f.criticality:
            statement = statement.where(Entity.attributes["criticality"].astext == f.criticality)
        if f.stage:
            statement = statement.where(Entity.attributes["stage"].astext == f.stage)
        if f.environment:
            statement = statement.where(
                Entity.attributes.contains({"environments": [f.environment]})
            )
        if f.q:
            statement = statement.where(Entity.name.ilike(f"%{f.q}%"))
        for other, relation in (
            (f.application_id, RelationshipType.PART_OF),
            (f.team_id, RelationshipType.OWNED_BY),
        ):
            if other is not None:
                statement = statement.where(
                    exists().where(
                        Relationship.workspace_id == self.workspace_id,
                        Relationship.from_entity_id == Entity.id,
                        Relationship.to_entity_id == other,
                        Relationship.type == relation,
                    )
                )
        return statement

    async def around(
        self, ids: Sequence[uuid.UUID], types: Sequence[RelationshipType]
    ) -> Sequence[Relationship]:
        """The relationships of these types that start or end at these
        entities."""
        if not ids:
            return []
        wanted = set(ids)
        return await self.list(
            self.select(Relationship).where(
                Relationship.type.in_(types),
                or_(Relationship.from_entity_id.in_(wanted), Relationship.to_entity_id.in_(wanted)),
            )
        )

    async def dependencies(
        self,
        entity_id: uuid.UUID,
        *,
        downstream: bool,
        depth: int,
        environment: str | None,
        limit: int,
    ) -> tuple[dict[uuid.UUID, int], list[Relationship]]:
        """What an entity depends on (downstream) — or what depends on it
        (upstream: what a failure of it reaches) — `depth` steps of
        `depends_on` away, in one environment or all: each reached entity
        and its distance, and the edges walked. One recursive query,
        bounded by depth and by `limit` entities (docs/adr/001-postgresql.md)."""
        near, far = (
            ("from_entity_id", "to_entity_id") if downstream else ("to_entity_id", "from_entity_id")
        )
        walk = text(
            f"""
            WITH RECURSIVE reach(id, depth) AS (
                SELECT CAST(:root AS uuid), 0
                UNION
                SELECT r.{far}, reach.depth + 1
                FROM reach
                JOIN relationships r
                  ON r.workspace_id = :workspace
                 AND r.{near} = reach.id
                 AND r.type = 'depends_on'
                 AND (CAST(:environment AS text) IS NULL
                      OR NOT jsonb_exists(r.attributes, 'environments')
                      OR jsonb_exists(r.attributes -> 'environments', :environment))
                WHERE reach.depth < :depth
            )
            SELECT reach.id, min(reach.depth) FROM reach
            JOIN entities e ON e.id = reach.id AND e.workspace_id = :workspace
            WHERE e.lifecycle <> 'removed' OR reach.id = CAST(:root AS uuid)
            GROUP BY reach.id
            ORDER BY min(reach.depth), reach.id
            LIMIT :limit
            """  # noqa: S608 — the two column names are chosen above, never given
        )
        rows = await self._session.execute(
            walk,
            {
                "root": entity_id,
                "workspace": self.workspace_id,
                "depth": depth,
                "environment": environment,
                "limit": limit,
            },
        )
        reached = {row[0]: int(row[1]) for row in rows.all()}
        if entity_id not in reached:
            return {}, []
        edges = await self.list(
            self.select(Relationship).where(
                Relationship.type == RelationshipType.DEPENDS_ON,
                Relationship.from_entity_id.in_(reached),
                Relationship.to_entity_id.in_(reached),
            )
        )
        kept = [
            edge
            for edge in edges
            if environment is None or environment in _environments(edge) or not _environments(edge)
        ]
        return reached, kept

    # ── infrastructure and cloud (LEKA-363) ──────────────────────────────────

    def infrastructure(self, filters: InfrastructureFilters) -> Select[tuple[Entity]]:
        """The cloud resources and databases of the workspace, for a page:
        every lifecycle but removed unless asked, and only those of that
        class, kind, provider, region, environment, state, exposure, how
        critical — in that account or group, of that service or team."""
        statement = self.select(Entity).where(Entity.type.in_(RESOURCE_TYPES))
        f = filters
        statement = _lifecycle(statement, f.lifecycle)
        for name, value in (
            ("resource_class", f.resource_class),
            ("resource_kind", f.resource_kind),
            ("provider", f.provider),
            ("region", f.region),
            ("environment", f.environment),
            ("state", f.state),
            ("exposure", f.exposure),
            ("criticality", f.criticality),
        ):
            if value:
                statement = statement.where(Entity.attributes[name].astext == value)
        if f.q:
            statement = statement.where(Entity.name.ilike(f"%{f.q}%"))
        if f.account_id is not None:
            # In it, or in one of its resource groups.
            groups = self._groups_in(f.account_id)
            statement = statement.where(
                exists().where(
                    Relationship.workspace_id == self.workspace_id,
                    Relationship.from_entity_id == Entity.id,
                    Relationship.type == RelationshipType.PART_OF,
                    or_(
                        Relationship.to_entity_id == f.account_id,
                        Relationship.to_entity_id.in_(groups),
                    ),
                )
            )
        for other, relation in (
            (f.service_id, RelationshipType.PART_OF),
            (f.team_id, RelationshipType.OWNED_BY),
        ):
            if other is not None:
                statement = statement.where(
                    exists().where(
                        Relationship.workspace_id == self.workspace_id,
                        Relationship.from_entity_id == Entity.id,
                        Relationship.to_entity_id == other,
                        Relationship.type == relation,
                    )
                )
        return statement

    def cloud_accounts(
        self,
        *,
        lifecycle: Lifecycle | None,
        provider: str | None,
        environment: str | None,
        q: str | None,
    ) -> Select[tuple[Entity]]:
        """The accounts, subscriptions and projects of the workspace, for a
        page."""
        statement = _lifecycle(
            self.select(Entity).where(Entity.type == EntityType.CLOUD_ACCOUNT), lifecycle
        )
        for name, value in (("provider", provider), ("environment", environment)):
            if value:
                statement = statement.where(Entity.attributes[name].astext == value)
        if q:
            statement = statement.where(Entity.name.ilike(f"%{q}%"))
        return statement

    def _groups_in(self, account_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
        """The ids of an account's resource groups."""
        group = Entity.__table__.alias()
        return (
            select(Relationship.from_entity_id)
            .join(group, group.c.id == Relationship.from_entity_id)
            .where(
                Relationship.workspace_id == self.workspace_id,
                Relationship.type == RelationshipType.PART_OF,
                Relationship.to_entity_id == account_id,
                group.c.type == EntityType.RESOURCE_GROUP,
            )
        )

    async def groups_of(self, account_id: uuid.UUID) -> Sequence[Entity]:
        """An account's resource groups, by name."""
        return await self.list(
            self.select(Entity)
            .where(
                Entity.type == EntityType.RESOURCE_GROUP,
                exists().where(
                    Relationship.workspace_id == self.workspace_id,
                    Relationship.from_entity_id == Entity.id,
                    Relationship.type == RelationshipType.PART_OF,
                    Relationship.to_entity_id == account_id,
                ),
            )
            .order_by(Entity.name, Entity.id)
        )

    async def holdings(self, holders: Sequence[uuid.UUID]) -> list[Holding]:
        """How many resources — not removed — each of these accounts and
        groups holds, by class and region: those in it, and those in its
        resource groups."""
        if not holders:
            return []
        resource = select(Entity).subquery()
        found: list[Holding] = []
        for via_group in (False, True):
            outer = Relationship.__table__.alias()
            inner = Relationship.__table__.alias()
            holder = outer.c.to_entity_id
            group = Entity.__table__.alias()
            # Through a resource group — not a cluster: its nodes are in the
            # account already.
            joined = (
                outer.join(inner, inner.c.to_entity_id == outer.c.from_entity_id).join(
                    group,
                    (group.c.id == outer.c.from_entity_id)
                    & (group.c.type == EntityType.RESOURCE_GROUP),
                )
                if via_group
                else outer
            )
            member = inner.c.from_entity_id if via_group else outer.c.from_entity_id
            statement = (
                select(
                    holder,
                    resource.c.attributes["resource_class"].astext.label("resource_class"),
                    resource.c.attributes["region"].astext.label("region"),
                    func.count(),
                )
                .select_from(joined.join(resource, resource.c.id == member))
                .where(
                    outer.c.workspace_id == self.workspace_id,
                    outer.c.type == RelationshipType.PART_OF,
                    holder.in_(set(holders)),
                    resource.c.workspace_id == self.workspace_id,
                    resource.c.type.in_(RESOURCE_TYPES),
                    resource.c.lifecycle != Lifecycle.REMOVED,
                )
                # By the labels: each `->>` is a parameter of its own.
                .group_by(holder, "resource_class", "region")
            )
            if via_group:
                statement = statement.where(
                    inner.c.workspace_id == self.workspace_id,
                    inner.c.type == RelationshipType.PART_OF,
                )
            rows = await self._session.execute(statement)
            found += [Holding(h, c, r, int(n)) for h, c, r, n in rows.all()]
        return found

    async def held(self, entity_id: uuid.UUID, *, limit: int) -> tuple[Sequence[Entity], int]:
        """What is part of a resource, or in it — a cluster's nodes, a
        network's resources — not removed, by name: up to `limit`, and how
        many."""
        inside = select(Relationship.from_entity_id).where(
            Relationship.workspace_id == self.workspace_id,
            Relationship.to_entity_id == entity_id,
            Relationship.type.in_((RelationshipType.PART_OF, RelationshipType.IN_NETWORK)),
        )
        statement = self.select(Entity).where(
            Entity.id.in_(inside), Entity.lifecycle != Lifecycle.REMOVED
        )
        total = await self._session.scalar(select(func.count()).select_from(statement.subquery()))
        found = await self.list(statement.order_by(Entity.name, Entity.id).limit(limit))
        return found, int(total or 0)

    async def counts(self) -> dict[str, dict[str, int]]:
        """How many entities of each type and in each lifecycle; how many
        relationships of each type."""
        by_type = await self._session.execute(
            select(Entity.type, func.count())
            .where(Entity.workspace_id == self.workspace_id, Entity.lifecycle != Lifecycle.REMOVED)
            .group_by(Entity.type)
        )
        by_lifecycle = await self._session.execute(
            select(Entity.lifecycle, func.count())
            .where(Entity.workspace_id == self.workspace_id)
            .group_by(Entity.lifecycle)
        )
        by_relationship = await self._session.execute(
            select(Relationship.type, func.count())
            .where(Relationship.workspace_id == self.workspace_id)
            .group_by(Relationship.type)
        )
        return {
            "types": {kind.value: int(n) for kind, n in by_type.all()},
            "lifecycles": {state.value: int(n) for state, n in by_lifecycle.all()},
            "relationships": {kind.value: int(n) for kind, n in by_relationship.all()},
        }


def _lifecycle(
    statement: Select[tuple[Entity]], lifecycle: Lifecycle | None
) -> Select[tuple[Entity]]:
    """Every lifecycle but removed, unless one is asked."""
    if lifecycle is None:
        return statement.where(Entity.lifecycle != Lifecycle.REMOVED)
    return statement.where(Entity.lifecycle == lifecycle)


def _environments(edge: Relationship) -> list[str]:
    found = (edge.attributes or {}).get("environments")
    return [str(e) for e in found] if isinstance(found, list) else []
