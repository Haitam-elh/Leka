"""Tenant scoping: the repository base class and the session guard.

The single property LEKA cannot get wrong is that one customer never reads
another's rows. Migration 001 made cross-tenant *writes* impossible with
composite foreign keys. These tests cover the other half: reads.

Two layers are tested separately because they fail differently. The
repository makes the correct query easy; the guard makes the incorrect query
impossible, including when someone bypasses the repository entirely.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import Source, SourceKind
from leka.db import (
    CrossWorkspaceWriteError,
    MissingWorkspaceScopeError,
    WorkspaceScopedRepository,
    current_workspace,
    session_factory,
    system_scope,
    workspace_scope,
)
from leka.platform import Workspace

pytestmark = pytest.mark.integration


class SourceRepositoryForTest(WorkspaceScopedRepository):
    """A concrete repository, so the base class is exercised as subclassed."""

    async def all_sources(self) -> list[Source]:
        return list(await self.list(self.select(Source)))


class Tenant:
    def __init__(self, workspace: Workspace, source: Source) -> None:
        self.workspace = workspace
        self.source = source


@pytest.fixture
async def tenants() -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two workspaces, one source each, removed afterwards."""
    made: list[Tenant] = []
    with system_scope():
        async with session_factory() as session:
            for label in ("alpha", "beta"):
                marker = f"{label}-{uuid.uuid4().hex[:8]}"
                workspace = Workspace(name=label, slug=marker)
                session.add(workspace)
                await session.flush()
                source = Source(workspace_id=workspace.id, kind=SourceKind.GITHUB, name=marker)
                session.add(source)
                await session.flush()
                made.append(Tenant(workspace, source))
            await session.commit()

    yield made[0], made[1]

    with system_scope():
        async with session_factory() as cleanup:
            for tenant in made:
                stored = await cleanup.get(Workspace, tenant.workspace.id)
                if stored is not None:
                    await cleanup.delete(stored)
            await cleanup.commit()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
        await session.rollback()


# ── The repository base class ────────────────────────────────────────────────


async def test_a_repository_cannot_exist_without_a_workspace(
    session: AsyncSession,
) -> None:
    """The workspace is a constructor argument, not a method parameter.

    A method parameter is a thing a caller can forget or get from the wrong
    place. A constructor argument is a thing the object cannot exist without.
    """
    with pytest.raises(MissingWorkspaceScopeError, match="without a workspace"):
        SourceRepositoryForTest(session, None)


async def test_reads_are_filtered_without_the_caller_asking(
    session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    alpha, beta = tenants
    repository = SourceRepositoryForTest(session, alpha.workspace.id)

    with workspace_scope(alpha.workspace.id):
        found = await repository.all_sources()

    assert [source.id for source in found] == [alpha.source.id]
    assert beta.source.id not in {source.id for source in found}


async def test_get_by_primary_key_does_not_cross_tenants(
    session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """session.get() would return the row: it looks up by primary key alone.
    The repository's get() is scoped, which is why it exists."""
    alpha, beta = tenants
    repository = SourceRepositoryForTest(session, alpha.workspace.id)

    with workspace_scope(alpha.workspace.id):
        assert await repository.get(Source, beta.source.id) is None
        assert await repository.get(Source, alpha.source.id) is not None


async def test_a_write_without_a_workspace_is_given_the_right_one(
    session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """Forgetting workspace_id has exactly one correct answer, so the
    repository supplies it rather than raising."""
    alpha, _ = tenants
    repository = SourceRepositoryForTest(session, alpha.workspace.id)

    source = Source(kind=SourceKind.JIRA, name=f"new-{uuid.uuid4().hex[:8]}")
    repository.add(source)

    assert source.workspace_id == alpha.workspace.id


async def test_a_write_to_another_workspace_is_refused(
    session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """A row bearing a DIFFERENT workspace is a bug, not an omission, and
    gets an exception rather than a silent correction."""
    alpha, beta = tenants
    repository = SourceRepositoryForTest(session, alpha.workspace.id)

    source = Source(workspace_id=beta.workspace.id, kind=SourceKind.JIRA, name="smuggled")

    with pytest.raises(CrossWorkspaceWriteError, match="belongs to workspace"):
        repository.add(source)


async def test_deleting_another_workspaces_row_is_refused(
    session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    alpha, beta = tenants
    repository = SourceRepositoryForTest(session, alpha.workspace.id)

    with workspace_scope(beta.workspace.id):
        loaded = (
            await session.execute(select(Source).where(Source.id == beta.source.id))
        ).scalar_one()

    with pytest.raises(CrossWorkspaceWriteError, match="refusing to delete"):
        await repository.delete(loaded)


# ── The session guard: what makes the wrong query impossible ─────────────────


async def test_an_unscoped_query_is_refused(
    session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """No declared workspace, no rows — and an exception rather than an empty
    result. A silent empty list is how "my dashboard is blank" becomes a
    three-day investigation."""
    with pytest.raises(MissingWorkspaceScopeError, match="no workspace declared"):
        await session.execute(select(Source))


async def test_the_guard_filters_even_when_the_repository_is_bypassed(
    session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """A base class cannot stop someone importing select and using the
    session. The guard can."""
    alpha, _beta = tenants

    with workspace_scope(alpha.workspace.id):
        rows = (await session.execute(select(Source))).scalars().all()

    assert {row.workspace_id for row in rows} == {alpha.workspace.id}


async def test_asking_explicitly_for_another_tenant_returns_nothing(
    session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """The interesting attempt: the caller names the other workspace itself."""
    alpha, beta = tenants

    with workspace_scope(alpha.workspace.id):
        rows = (
            (await session.execute(select(Source).where(Source.workspace_id == beta.workspace.id)))
            .scalars()
            .all()
        )

    assert rows == []


async def test_system_scope_sees_everything_and_says_so(
    session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """Workers and seed scripts legitimately cross tenants. They declare it
    in one visible line that shows up in a diff."""
    alpha, beta = tenants

    with system_scope():
        rows = (await session.execute(select(Source))).scalars().all()

    found = {row.id for row in rows}
    assert alpha.source.id in found
    assert beta.source.id in found


async def test_a_scope_is_restored_when_it_ends(
    tenants: tuple[Tenant, Tenant],
) -> None:
    """Nested and sequential scopes must not leak into one another — a leaked
    scope on a pooled connection is the exact bug this design avoids."""
    alpha, beta = tenants
    assert current_workspace() is None

    with workspace_scope(alpha.workspace.id):
        assert current_workspace() == alpha.workspace.id
        with workspace_scope(beta.workspace.id):
            assert current_workspace() == beta.workspace.id
        assert current_workspace() == alpha.workspace.id

    assert current_workspace() is None


async def test_unscoped_tables_are_untouched(session: AsyncSession) -> None:
    """Workspaces themselves are not workspace-scoped — querying the tenant
    list must not require being inside a tenant."""
    result = await session.execute(select(Workspace).limit(1))

    assert result.scalars().all() is not None
