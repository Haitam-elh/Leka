"""What the database refuses to store.

LEKA is multi-tenant on shared tables. The guarantee that one customer never
reads another's graph cannot rest on every future query remembering to filter
by workspace_id — it has to be impossible to write the row in the first
place. These tests assert that PostgreSQL, not application code, is what
holds the line.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import Source, SourceKind, SourceStatus
from leka.knowledge import (
    Entity,
    EntityType,
    EntityVersion,
    Lifecycle,
    Relationship,
    RelationshipType,
)
from leka.platform import Workspace

pytestmark = pytest.mark.integration


async def _workspace(session: AsyncSession, label: str) -> Workspace:
    workspace = Workspace(name=label, slug=f"{label}-{uuid.uuid4().hex[:8]}")
    session.add(workspace)
    await session.flush()
    return workspace


async def _source(session: AsyncSession, workspace: Workspace) -> Source:
    source = Source(
        workspace_id=workspace.id,
        kind=SourceKind.GITHUB,
        name=f"gh-{uuid.uuid4().hex[:8]}",
    )
    session.add(source)
    await session.flush()
    return source


async def _entity(session: AsyncSession, workspace: Workspace, name: str) -> Entity:
    entity = Entity(
        workspace_id=workspace.id,
        type=EntityType.SERVICE,
        key=f"service:{name}-{uuid.uuid4().hex[:8]}",
        name=name,
    )
    session.add(entity)
    await session.flush()
    return entity


async def test_defaults_are_applied_by_the_database(session: AsyncSession) -> None:
    workspace = await _workspace(session, "defaults")
    source = await _source(session, workspace)
    await session.refresh(source)

    assert source.id is not None
    assert source.status is SourceStatus.DRAFT
    assert source.config == {}
    # Timestamps come from PostgreSQL, so the API, the worker and psql agree.
    assert source.created_at.tzinfo is not None
    # A new source has proven nothing and been checked by nothing.
    assert source.health_status.value == "unknown"
    assert source.sync_status.value == "never"


async def test_a_version_cannot_belong_to_another_workspace_entity(
    session: AsyncSession,
) -> None:
    mine = await _workspace(session, "mine")
    theirs = await _workspace(session, "theirs")
    their_entity = await _entity(session, theirs, "their-billing")

    session.add(
        EntityVersion(
            workspace_id=mine.id,
            entity_id=their_entity.id,
            version=1,
            content={"name": "stolen"},
            schema_version=1,
            recorded_at=datetime.now(UTC),
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


async def test_relationship_cannot_span_two_workspaces(session: AsyncSession) -> None:
    mine = await _workspace(session, "mine")
    theirs = await _workspace(session, "theirs")
    my_entity = await _entity(session, mine, "payment-api")
    their_entity = await _entity(session, theirs, "their-billing")

    session.add(
        Relationship(
            workspace_id=mine.id,
            from_entity_id=my_entity.id,
            to_entity_id=their_entity.id,
            type=RelationshipType.DEPENDS_ON,
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


async def test_a_version_is_recorded_once(session: AsyncSession) -> None:
    """History is append-only per entity: two builds cannot both write its
    version 2 — the second is refused, not merged."""
    workspace = await _workspace(session, "versions")
    entity = await _entity(session, workspace, "payment-api")
    for _ in range(2):
        session.add(
            EntityVersion(
                workspace_id=workspace.id,
                entity_id=entity.id,
                version=1,
                content={"name": "payment-api"},
                schema_version=1,
                recorded_at=datetime.now(UTC),
            )
        )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


@pytest.mark.parametrize(
    ("lifecycle", "removed_at"),
    [(Lifecycle.REMOVED, None), (Lifecycle.ACTIVE, datetime(2026, 9, 1, tzinfo=UTC))],
)
async def test_removed_goes_with_the_date_it_was(
    session: AsyncSession, lifecycle: Lifecycle, removed_at: datetime | None
) -> None:
    workspace = await _workspace(session, "removed")
    session.add(
        Entity(
            workspace_id=workspace.id,
            type=EntityType.SERVICE,
            key="service:gone",
            name="gone",
            lifecycle=lifecycle,
            removed_at=removed_at,
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


async def test_a_relationship_is_stated_or_inferred(session: AsyncSession) -> None:
    workspace = await _workspace(session, "origin")
    one = await _entity(session, workspace, "one")
    other = await _entity(session, workspace, "other")
    session.add(
        Relationship(
            workspace_id=workspace.id,
            from_entity_id=one.id,
            to_entity_id=other.id,
            type=RelationshipType.DEPENDS_ON,
            origin="guessed",
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


@pytest.mark.parametrize("confidence", [-0.1, 1.5])
async def test_confidence_stays_within_zero_and_one(
    session: AsyncSession, confidence: float
) -> None:
    workspace = await _workspace(session, "confidence")

    session.add(
        Entity(
            workspace_id=workspace.id,
            type=EntityType.SERVICE,
            key="service:c",
            name="c",
            confidence=confidence,
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


async def test_deleting_a_workspace_removes_its_data_and_only_its_data(
    session: AsyncSession,
) -> None:
    from sqlalchemy import select

    from leka.db import session_factory, system_scope

    mine = await _workspace(session, "leaving")
    theirs = await _workspace(session, "staying")
    await _source(session, mine)
    await _entity(session, mine, "gone")
    survivor = await _entity(session, theirs, "kept")
    await session.commit()

    async with session_factory() as other:
        workspace = await other.get(Workspace, mine.id)
        assert workspace is not None
        await other.delete(workspace)
        await other.commit()

    # system_scope: this assertion is deliberately cross-tenant — it checks
    # that one workspace's rows went and another's stayed. Reading both is
    # the whole point, so it says so. Without it the scope guard refuses,
    # which is how we know the guard is doing its job.
    with system_scope():
        async with session_factory() as check:
            remaining = (await check.execute(select(Entity))).scalars().all()
            assert survivor.id in {entity.id for entity in remaining}
            assert all(entity.workspace_id != mine.id for entity in remaining)
