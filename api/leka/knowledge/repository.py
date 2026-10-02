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
from sqlalchemy.orm import aliased
from sqlalchemy.sql.expression import Exists

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
class DataFilters:
    """What a list of data objects is narrowed to (LEKA-364): where they
    are, what kind, what they hold, whose they are."""

    lifecycle: Lifecycle | None = None
    database_id: uuid.UUID | None = None
    schema_id: uuid.UUID | None = None
    object_kind: str | None = None
    classification: str | None = None
    category: str | None = None
    personal_data: bool | None = None
    service_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    q: str | None = None


# Documentation (LEKA-366): what documents what, what it can describe, and
# the freshness that is not stale.
DOCUMENTATION = (EntityType.DOCUMENT, EntityType.KNOWLEDGE_SPACE)
DOCUMENTED = (
    EntityType.APPLICATION,
    EntityType.SERVICE,
    EntityType.REPOSITORY,
    EntityType.DATABASE,
    EntityType.DATA_OBJECT,
    EntityType.BUSINESS_CAPABILITY,
    EntityType.BUSINESS_PROCESS,
)
NOT_STALE = ("fresh", "aging")
BUSINESS = (EntityType.BUSINESS_CAPABILITY, EntityType.BUSINESS_PROCESS)


@dataclass(frozen=True)
class DocumentFilters:
    """What a list of documents is narrowed to (LEKA-366): where they are
    kept, how fresh, what they describe, whose they are."""

    lifecycle: Lifecycle | None = None
    space_id: uuid.UUID | None = None
    freshness: str | None = None
    about_id: uuid.UUID | None = None
    person_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    verified: bool | None = None
    q: str | None = None


@dataclass(frozen=True)
class BusinessFilters:
    """What a list of capabilities or processes is narrowed to (LEKA-366):
    where they sit, whose they are, what supports them, what they use."""

    lifecycle: Lifecycle | None = None
    parent_id: uuid.UUID | None = None
    top: bool | None = None
    capability_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    data_id: uuid.UUID | None = None
    q: str | None = None


@dataclass(frozen=True)
class Documented:
    """How one thing is documented: by how many documents, the latest
    changed when."""

    count: int
    last_changed_at: str | None


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
        types: Sequence[RelationshipType] = (RelationshipType.DEPENDS_ON,),
    ) -> tuple[dict[uuid.UUID, int], list[Relationship]]:
        """What an entity depends on (downstream) — or what depends on it
        (upstream: what a failure of it reaches) — `depth` steps of
        `depends_on` away — or of `types`: a table's foreign keys and what
        a view reads (LEKA-364) — in one environment or all: each reached
        entity and its distance, and the edges walked. One recursive query,
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
                 AND r.type = ANY(CAST(:types AS text[]))
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
                "types": [kind.value for kind in types],
            },
        )
        reached = {row[0]: int(row[1]) for row in rows.all()}
        if entity_id not in reached:
            return {}, []
        edges = await self.list(
            self.select(Relationship).where(
                Relationship.type.in_(types),
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

    # ── data (LEKA-364) ──────────────────────────────────────────────────────

    def databases(
        self,
        *,
        lifecycle: Lifecycle | None,
        engine: str | None,
        classification: str | None,
        personal_data: bool | None,
        environment: str | None,
        team_id: uuid.UUID | None,
        q: str | None,
    ) -> Select[tuple[Entity]]:
        """The databases of the workspace — what database sources read, and
        the cloud instances serving them — for a page."""
        statement = _lifecycle(
            self.select(Entity).where(Entity.type == EntityType.DATABASE), lifecycle
        )
        for name, value in (
            ("engine", engine),
            ("classification", classification),
            ("environment", environment),
        ):
            if value:
                statement = statement.where(Entity.attributes[name].astext == value)
        statement = _personal(statement, personal_data)
        if q:
            statement = statement.where(Entity.name.ilike(f"%{q}%"))
        if team_id is not None:
            statement = statement.where(self._points_at(team_id, RelationshipType.OWNED_BY))
        return statement

    def data_objects(self, filters: DataFilters) -> Select[tuple[Entity]]:
        """The tables, views and collections of the workspace, for a page:
        in that database or schema, of that kind, holding that data, of
        that service or team."""
        f = filters
        statement = _lifecycle(
            self.select(Entity).where(Entity.type == EntityType.DATA_OBJECT), f.lifecycle
        )
        for name, value in (("object_kind", f.object_kind), ("classification", f.classification)):
            if value:
                statement = statement.where(Entity.attributes[name].astext == value)
        if f.category:
            statement = statement.where(
                Entity.attributes.contains({"data_categories": [f.category]})
            )
        statement = _personal(statement, f.personal_data)
        if f.q:
            statement = statement.where(Entity.name.ilike(f"%{f.q}%"))
        if f.schema_id is not None:
            statement = statement.where(self._points_at(f.schema_id, RelationshipType.PART_OF))
        if f.database_id is not None:
            schemas = select(Relationship.from_entity_id).where(
                Relationship.workspace_id == self.workspace_id,
                Relationship.type == RelationshipType.PART_OF,
                Relationship.to_entity_id == f.database_id,
            )
            statement = statement.where(
                exists().where(
                    Relationship.workspace_id == self.workspace_id,
                    Relationship.from_entity_id == Entity.id,
                    Relationship.type == RelationshipType.PART_OF,
                    Relationship.to_entity_id.in_(schemas),
                )
            )
        for other, relation in (
            (f.service_id, RelationshipType.PART_OF),
            (f.team_id, RelationshipType.OWNED_BY),
        ):
            if other is not None:
                statement = statement.where(self._points_at(other, relation))
        return statement

    def _points_at(self, other: uuid.UUID, relation: RelationshipType) -> Exists:
        return exists().where(
            Relationship.workspace_id == self.workspace_id,
            Relationship.from_entity_id == Entity.id,
            Relationship.to_entity_id == other,
            Relationship.type == relation,
        )

    async def parts(
        self, holders: Sequence[uuid.UUID], kind: EntityType
    ) -> dict[uuid.UUID, list[Entity]]:
        """What is part of each of these — of a kind — not removed."""
        if not holders:
            return {}
        rows = await self._session.execute(
            select(Relationship.to_entity_id, Entity)
            .join(Entity, Entity.id == Relationship.from_entity_id)
            .where(
                Relationship.workspace_id == self.workspace_id,
                Relationship.type == RelationshipType.PART_OF,
                Relationship.to_entity_id.in_(set(holders)),
                Entity.workspace_id == self.workspace_id,
                Entity.type == kind,
                Entity.lifecycle != Lifecycle.REMOVED,
            )
            .order_by(Entity.name, Entity.id)
        )
        found: dict[uuid.UUID, list[Entity]] = {holder: [] for holder in holders}
        for holder, part in rows.tuples().all():
            found[holder].append(part)
        return found

    # ── people and teams (LEKA-365) ──────────────────────────────────────────

    def teams(
        self,
        *,
        lifecycle: Lifecycle | None,
        team_type: str | None,
        parent_id: uuid.UUID | None,
        q: str | None,
    ) -> Select[tuple[Entity]]:
        """The teams — and departments — of the workspace, for a page."""
        statement = _lifecycle(self.select(Entity).where(Entity.type == EntityType.TEAM), lifecycle)
        if team_type:
            statement = statement.where(Entity.attributes["team_type"].astext == team_type)
        if parent_id is not None:
            statement = statement.where(self._points_at(parent_id, RelationshipType.CHILD_OF))
        if q:
            statement = statement.where(Entity.name.ilike(f"%{q}%"))
        return statement

    def people(
        self,
        *,
        lifecycle: Lifecycle | None,
        team_id: uuid.UUID | None,
        department: str | None,
        bots: bool,
        contributors: bool | None,
        q: str | None,
    ) -> Select[tuple[Entity]]:
        """The people of the workspace, for a page — bots left out unless
        asked; those of a team, of a department, who contribute."""
        statement = _lifecycle(
            self.select(Entity).where(Entity.type == EntityType.PERSON), lifecycle
        )
        if not bots:
            statement = statement.where(
                or_(
                    Entity.attributes["bot"].astext.is_(None),
                    Entity.attributes["bot"].astext != "true",
                )
            )
        if team_id is not None:
            statement = statement.where(self._points_at(team_id, RelationshipType.MEMBER_OF))
        if department:
            statement = statement.where(Entity.attributes["department"].astext == department)
        if contributors is not None:
            contributing = exists().where(
                Relationship.workspace_id == self.workspace_id,
                Relationship.from_entity_id == Entity.id,
                Relationship.type == RelationshipType.CONTRIBUTES_TO,
            )
            statement = statement.where(contributing if contributors else ~contributing)
        if q:
            statement = statement.where(
                or_(Entity.name.ilike(f"%{q}%"), Entity.attributes["email"].astext.ilike(f"%{q}%"))
            )
        return statement

    async def owned_counts(self, owners: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
        """What each of these owns, by type, not removed."""
        if not owners:
            return {}
        rows = await self._session.execute(
            select(Relationship.to_entity_id, Entity.type, func.count())
            .join(Entity, Entity.id == Relationship.from_entity_id)
            .where(
                Relationship.workspace_id == self.workspace_id,
                Relationship.type == RelationshipType.OWNED_BY,
                Relationship.to_entity_id.in_(set(owners)),
                Entity.workspace_id == self.workspace_id,
                Entity.lifecycle != Lifecycle.REMOVED,
            )
            .group_by(Relationship.to_entity_id, Entity.type)
        )
        found: dict[uuid.UUID, dict[str, int]] = {owner: {} for owner in owners}
        for owner, kind, count in rows.tuples().all():
            found[owner][kind.value] = int(count)
        return found

    async def chain(
        self, start: uuid.UUID, relation: RelationshipType, *, limit: int
    ) -> list[Entity]:
        """What `start` points at through `relation`, then what that points
        at — a manager's manager, a team's parent's parent — the surest
        first at each step, never twice: up to `limit`."""
        found: list[Entity] = []
        seen = {start}
        current = start
        for _ in range(limit):
            edge = await self._session.scalar(
                self.select(Relationship)
                .where(
                    Relationship.from_entity_id == current,
                    Relationship.type == relation,
                )
                .order_by(Relationship.confidence.desc(), Relationship.id)
                .limit(1)
            )
            if edge is None or edge.to_entity_id in seen:
                break
            entity = await self.get(Entity, edge.to_entity_id)
            if entity is None:
                break
            found.append(entity)
            seen.add(entity.id)
            current = entity.id
        return found

    # ── documentation and business knowledge (LEKA-366) ─────────────────────

    def documents(self, filters: DocumentFilters) -> Select[tuple[Entity]]:
        """The documents of the workspace, for a page: in that space, that
        fresh, about that thing, of that person — written, edited, owned —
        or that team, verified or not."""
        f = filters
        statement = _lifecycle(
            self.select(Entity).where(Entity.type == EntityType.DOCUMENT), f.lifecycle
        )
        if f.freshness:
            statement = statement.where(Entity.attributes["freshness"].astext == f.freshness)
        if f.verified is not None:
            word = "true" if f.verified else "false"
            statement = statement.where(Entity.attributes["verified"].astext == word)
        if f.q:
            statement = statement.where(Entity.name.ilike(f"%{f.q}%"))
        for other, relation in (
            (f.space_id, RelationshipType.PART_OF),
            (f.about_id, RelationshipType.DESCRIBES),
            (f.team_id, RelationshipType.OWNED_BY),
        ):
            if other is not None:
                statement = statement.where(self._points_at(other, relation))
        if f.person_id is not None:
            statement = statement.where(
                exists().where(
                    Relationship.workspace_id == self.workspace_id,
                    Relationship.from_entity_id == Entity.id,
                    Relationship.to_entity_id == f.person_id,
                    Relationship.type.in_(
                        (
                            RelationshipType.AUTHORED_BY,
                            RelationshipType.EDITED_BY,
                            RelationshipType.OWNED_BY,
                        )
                    ),
                )
            )
        return statement

    def knowledge_spaces(
        self,
        *,
        lifecycle: Lifecycle | None,
        space_kind: str | None,
        team_id: uuid.UUID | None,
        q: str | None,
    ) -> Select[tuple[Entity]]:
        """The spaces documents are kept in, for a page."""
        statement = _lifecycle(
            self.select(Entity).where(Entity.type == EntityType.KNOWLEDGE_SPACE), lifecycle
        )
        if space_kind:
            statement = statement.where(Entity.attributes["space_kind"].astext == space_kind)
        if team_id is not None:
            statement = statement.where(self._points_at(team_id, RelationshipType.OWNED_BY))
        if q:
            statement = statement.where(Entity.name.ilike(f"%{q}%"))
        return statement

    async def space_documents(self, spaces: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
        """How many documents — not removed — each of these spaces holds, by
        freshness: `unknown` for those without a date."""
        if not spaces:
            return {}
        freshness = Entity.attributes["freshness"].astext.label("freshness")
        rows = await self._session.execute(
            select(Relationship.to_entity_id, freshness, func.count())
            .join(Entity, Entity.id == Relationship.from_entity_id)
            .where(
                Relationship.workspace_id == self.workspace_id,
                Relationship.type == RelationshipType.PART_OF,
                Relationship.to_entity_id.in_(set(spaces)),
                Entity.workspace_id == self.workspace_id,
                Entity.type == EntityType.DOCUMENT,
                Entity.lifecycle != Lifecycle.REMOVED,
            )
            # By the label: each `->>` is a parameter of its own.
            .group_by(Relationship.to_entity_id, "freshness")
        )
        found: dict[uuid.UUID, dict[str, int]] = {space: {} for space in spaces}
        for space, word, count in rows.tuples().all():
            found[space][word or "unknown"] = int(count)
        return found

    async def documents_of(self, space: uuid.UUID, *, stale: bool, limit: int) -> Sequence[Entity]:
        """A space's documents, not removed: the latest changed first — or
        its stale ones, the longest unchanged first."""
        statement = self.select(Entity).where(
            Entity.type == EntityType.DOCUMENT,
            Entity.lifecycle != Lifecycle.REMOVED,
            self._points_at(space, RelationshipType.PART_OF),
        )
        changed = Entity.attributes["last_activity_at"].astext
        if stale:
            statement = statement.where(Entity.attributes["freshness"].astext == "stale")
            ordered = statement.order_by(changed.asc().nulls_last(), Entity.id)
        else:
            ordered = statement.order_by(changed.desc().nulls_last(), Entity.id)
        return await self.list(ordered.limit(limit))

    def _documented(self, *, fresh: bool) -> Exists:
        """Something a document or a space — not removed — describes; or a
        document that is not stale."""
        describer = aliased(Entity)
        condition = exists().where(
            Relationship.workspace_id == self.workspace_id,
            Relationship.to_entity_id == Entity.id,
            Relationship.type == RelationshipType.DESCRIBES,
            describer.id == Relationship.from_entity_id,
            describer.workspace_id == self.workspace_id,
            describer.lifecycle != Lifecycle.REMOVED,
        )
        if fresh:
            return condition.where(
                describer.type == EntityType.DOCUMENT,
                describer.attributes["freshness"].astext.in_(NOT_STALE),
            )
        return condition.where(describer.type.in_(DOCUMENTATION))

    async def coverage(self) -> dict[EntityType, tuple[int, int, int]]:
        """How many of each kind documentation can describe there are — not
        removed — how many are described, how many by a document that is
        not stale."""
        rows = await self._session.execute(
            select(
                Entity.type,
                func.count(),
                func.count().filter(self._documented(fresh=False)),
                func.count().filter(self._documented(fresh=True)),
            )
            .where(
                Entity.workspace_id == self.workspace_id,
                Entity.type.in_(DOCUMENTED),
                Entity.lifecycle != Lifecycle.REMOVED,
            )
            .group_by(Entity.type)
        )
        return {kind: (int(t), int(d), int(f)) for kind, t, d, f in rows.tuples().all()}

    async def documentation_counts(self) -> tuple[dict[str, int], int, int]:
        """The documents — not removed — by freshness, how many their tool
        says need verifying; and how many spaces."""
        freshness = Entity.attributes["freshness"].astext.label("freshness")
        rows = await self._session.execute(
            select(freshness, func.count())
            .where(
                Entity.workspace_id == self.workspace_id,
                Entity.type == EntityType.DOCUMENT,
                Entity.lifecycle != Lifecycle.REMOVED,
            )
            .group_by("freshness")
        )
        by_freshness = {word or "unknown": int(n) for word, n in rows.tuples().all()}
        unverified = await self._session.scalar(
            select(func.count()).where(
                Entity.workspace_id == self.workspace_id,
                Entity.type == EntityType.DOCUMENT,
                Entity.lifecycle != Lifecycle.REMOVED,
                Entity.attributes["verified"].astext == "false",
            )
        )
        spaces = await self._session.scalar(
            select(func.count()).where(
                Entity.workspace_id == self.workspace_id,
                Entity.type == EntityType.KNOWLEDGE_SPACE,
                Entity.lifecycle != Lifecycle.REMOVED,
            )
        )
        return by_freshness, int(unverified or 0), int(spaces or 0)

    def gaps(
        self,
        kind: EntityType,
        *,
        stale: bool,
        lifecycle: Lifecycle | None,
        criticality: str | None,
        team_id: uuid.UUID | None,
        q: str | None,
    ) -> Select[tuple[Entity]]:
        """The things of a kind no document or space describes — or, `stale`,
        only stale documents do — for a page."""
        statement = _lifecycle(self.select(Entity).where(Entity.type == kind), lifecycle)
        if stale:
            statement = statement.where(
                self._documented(fresh=False), ~self._documented(fresh=True)
            )
        else:
            statement = statement.where(~self._documented(fresh=False))
        if criticality:
            statement = statement.where(Entity.attributes["criticality"].astext == criticality)
        if team_id is not None:
            statement = statement.where(self._points_at(team_id, RelationshipType.OWNED_BY))
        if q:
            statement = statement.where(Entity.name.ilike(f"%{q}%"))
        return statement

    async def documented(self, things: Sequence[uuid.UUID]) -> dict[uuid.UUID, Documented]:
        """How many documents and spaces — not removed — describe each of
        these, and when the latest of them changed."""
        if not things:
            return {}
        changed = func.max(Entity.attributes["last_activity_at"].astext)
        rows = await self._session.execute(
            select(Relationship.to_entity_id, func.count(), changed)
            .join(Entity, Entity.id == Relationship.from_entity_id)
            .where(
                Relationship.workspace_id == self.workspace_id,
                Relationship.type == RelationshipType.DESCRIBES,
                Relationship.to_entity_id.in_(set(things)),
                Entity.workspace_id == self.workspace_id,
                Entity.type.in_(DOCUMENTATION),
                Entity.lifecycle != Lifecycle.REMOVED,
            )
            .group_by(Relationship.to_entity_id)
        )
        found = {thing: Documented(0, None) for thing in things}
        for thing, count, last in rows.tuples().all():
            found[thing] = Documented(int(count), last)
        return found

    def business(self, kind: EntityType, filters: BusinessFilters) -> Select[tuple[Entity]]:
        """The capabilities — or the processes — of the workspace, for a
        page: under that one, at the top, realizing that capability, of
        that team, supported by that application or service, using that
        data."""
        f = filters
        statement = _lifecycle(self.select(Entity).where(Entity.type == kind), f.lifecycle)
        up = (
            RelationshipType.CHILD_OF
            if kind is EntityType.BUSINESS_CAPABILITY
            else RelationshipType.PART_OF
        )
        if f.parent_id is not None:
            statement = statement.where(self._points_at(f.parent_id, up))
        if f.top is not None:
            above = aliased(Entity)
            parented = exists().where(
                Relationship.workspace_id == self.workspace_id,
                Relationship.from_entity_id == Entity.id,
                Relationship.type == up,
                above.id == Relationship.to_entity_id,
                above.type == kind,
            )
            statement = statement.where(~parented if f.top else parented)
        for other, relation in (
            (f.capability_id, RelationshipType.REALIZES),
            (f.team_id, RelationshipType.OWNED_BY),
            (f.application_id, RelationshipType.SUPPORTED_BY),
            (f.data_id, RelationshipType.USES),
        ):
            if other is not None:
                statement = statement.where(self._points_at(other, relation))
        if f.q:
            statement = statement.where(Entity.name.ilike(f"%{f.q}%"))
        return statement

    async def pointing(
        self,
        targets: Sequence[uuid.UUID],
        types: Sequence[RelationshipType],
        kinds: Sequence[EntityType],
    ) -> list[tuple[Relationship, Entity]]:
        """The relationships of these types to these entities from entities
        of these kinds, not removed — and those entities."""
        if not targets:
            return []
        rows = await self._session.execute(
            select(Relationship, Entity)
            .join(Entity, Entity.id == Relationship.from_entity_id)
            .where(
                Relationship.workspace_id == self.workspace_id,
                Relationship.type.in_(types),
                Relationship.to_entity_id.in_(set(targets)),
                Entity.workspace_id == self.workspace_id,
                Entity.type.in_(kinds),
                Entity.lifecycle != Lifecycle.REMOVED,
            )
            .order_by(Relationship.confidence.desc(), Entity.name, Entity.id)
        )
        return [(edge, entity) for edge, entity in rows.tuples().all()]

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


def _personal(statement: Select[tuple[Entity]], personal: bool | None) -> Select[tuple[Entity]]:
    """Holding personal data, or not — said so, or not said."""
    if personal is None:
        return statement
    said = Entity.attributes["personal_data"].astext == "true"
    unsaid = or_(~said, Entity.attributes["personal_data"].astext.is_(None))
    return statement.where(said if personal else unsaid)


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
