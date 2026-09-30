"""Database access for the knowledge module.

The only place in this module where a query is written (architecture rule 4),
and the only place a graph traversal is expressed.

Every repository is scoped to one workspace: rule 2 and rule 3 mean there is
no legitimate query here that is not.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Select, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from leka.db import WorkspaceScopedRepository
from leka.knowledge.build import Built, Current
from leka.knowledge.models import Entity, EntityVersion, Lifecycle, ModelRun, Relationship

CHUNK = 1_000


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
