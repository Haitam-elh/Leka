"""What the database refuses to store.

LEKA is multi-tenant on shared tables. The guarantee that one customer never
reads another's graph cannot rest on every future query remembering to filter
by workspace_id — it has to be impossible to write the row in the first
place. These tests assert that PostgreSQL, not application code, is what
holds the line.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import Source, SourceKind, SourceStatus
from leka.knowledge import Entity, EntityType, Relationship, RelationshipType
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


async def _entity(session: AsyncSession, workspace: Workspace, source: Source, name: str) -> Entity:
    entity = Entity(
        workspace_id=workspace.id,
        type=EntityType.SERVICE,
        external_id=f"ext-{uuid.uuid4().hex[:8]}",
        source_id=source.id,
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
    assert source.status is SourceStatus.PENDING
    assert source.config == {}
    # Timestamps come from PostgreSQL, so the API, the worker and psql agree.
    assert source.created_at.tzinfo is not None
    # Credentials are encrypted before they reach this column (rule 12).
    assert source.credentials_encrypted is None


async def test_entity_cannot_reference_another_workspace_source(session: AsyncSession) -> None:
    mine = await _workspace(session, "mine")
    theirs = await _workspace(session, "theirs")
    their_source = await _source(session, theirs)

    session.add(
        Entity(
            workspace_id=mine.id,
            type=EntityType.SERVICE,
            external_id="stolen",
            source_id=their_source.id,
            name="stolen",
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


async def test_relationship_cannot_span_two_workspaces(session: AsyncSession) -> None:
    mine = await _workspace(session, "mine")
    theirs = await _workspace(session, "theirs")
    my_source = await _source(session, mine)
    their_source = await _source(session, theirs)
    my_entity = await _entity(session, mine, my_source, "payment-api")
    their_entity = await _entity(session, theirs, their_source, "their-billing")

    session.add(
        Relationship(
            workspace_id=mine.id,
            from_entity_id=my_entity.id,
            to_entity_id=their_entity.id,
            type=RelationshipType.DEPENDS_ON,
            source_id=my_source.id,
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


async def test_resyncing_a_source_does_not_duplicate_the_graph(session: AsyncSession) -> None:
    """Identity is (workspace, source, external_id) — the background loop
    runs continuously, and a second pass must update, never duplicate."""
    workspace = await _workspace(session, "resync")
    source = await _source(session, workspace)
    first = await _entity(session, workspace, source, "payment-api")

    session.add(
        Entity(
            workspace_id=workspace.id,
            type=EntityType.SERVICE,
            external_id=first.external_id,
            source_id=source.id,
            name="payment-api seen again",
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


@pytest.mark.parametrize("confidence", [-0.1, 1.5])
async def test_confidence_stays_within_zero_and_one(
    session: AsyncSession, confidence: float
) -> None:
    workspace = await _workspace(session, "confidence")
    source = await _source(session, workspace)

    session.add(
        Entity(
            workspace_id=workspace.id,
            type=EntityType.SERVICE,
            external_id="c",
            source_id=source.id,
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

    from leka.db import session_factory

    mine = await _workspace(session, "leaving")
    theirs = await _workspace(session, "staying")
    my_source = await _source(session, mine)
    their_source = await _source(session, theirs)
    await _entity(session, mine, my_source, "gone")
    survivor = await _entity(session, theirs, their_source, "kept")
    await session.commit()

    async with session_factory() as other:
        workspace = await other.get(Workspace, mine.id)
        assert workspace is not None
        await other.delete(workspace)
        await other.commit()

    async with session_factory() as check:
        remaining = (await check.execute(select(Entity))).scalars().all()
        assert survivor.id in {entity.id for entity in remaining}
        assert all(entity.workspace_id != mine.id for entity in remaining)
