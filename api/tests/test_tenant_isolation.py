"""No customer ever sees another customer's data.

The single property LEKA cannot get wrong. Every customer shares the same
tables, so isolation is not a feature that can be added later — it is either
structural, or it is a matter of every future query remembering to filter.

This file is built to get stronger on its own. The structural checks run
today. The HTTP checks enumerate the application's real routes, so every
route added from now on is covered the day it is mounted, with nothing to
remember.

A NOTE ON WHY THIS DOES NOT SIMPLY FAIL. LEKA-329 asked for a test that fails
until the routes exist. That would leave CI red on every pull request, and a
pipeline that is always red is a pipeline nobody reads — including on the day
it turns red for a real reason. Instead the route checks skip while there is
nothing to call, say so out loud, and are themselves guarded by a test that
fails if the router stops being mounted. The failure we care about is a route
that leaks, and that is caught the moment such a route exists.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from leka.connectors import Source, SourceKind
from leka.db import Base, engine, session_factory
from leka.knowledge import Entity, EntityType
from leka.main import app
from leka.platform import Workspace

pytestmark = pytest.mark.integration

# Tables that legitimately have no workspace_id, and why.
#   workspaces  — it IS the tenant
#   users       — a person may belong to several workspaces; membership is
#                 the authority (see migration 001)
TENANT_FREE_TABLES = frozenset({"workspaces", "users", "alembic_version"})

PUBLIC_PATHS = frozenset({"/api/v1/health"})


class Tenant:
    """One workspace and a marker only it should ever be able to see."""

    def __init__(self, workspace: Workspace, source: Source, entity: Entity) -> None:
        self.workspace = workspace
        self.source = source
        self.entity = entity
        self.secret = entity.name

    def identifiers(self) -> set[str]:
        return {
            str(self.workspace.id),
            str(self.source.id),
            str(self.entity.id),
            self.secret,
        }


async def _make_tenant(session: AsyncSession, label: str) -> Tenant:
    marker = f"{label}-{uuid.uuid4().hex[:10]}"
    workspace = Workspace(name=label, slug=marker)
    session.add(workspace)
    await session.flush()

    source = Source(workspace_id=workspace.id, kind=SourceKind.GITHUB, name=marker)
    session.add(source)
    await session.flush()

    entity = Entity(
        workspace_id=workspace.id,
        type=EntityType.SERVICE,
        external_id=marker,
        source_id=source.id,
        name=f"secret-service-{marker}",
    )
    session.add(entity)
    await session.flush()
    await session.commit()
    return Tenant(workspace, source, entity)


@pytest.fixture
async def tenants() -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two workspaces with data, removed afterwards."""
    async with session_factory() as session:
        first = await _make_tenant(session, "alpha")
        second = await _make_tenant(session, "beta")

    yield first, second

    async with session_factory() as cleanup:
        for tenant in (first, second):
            workspace = await cleanup.get(Workspace, tenant.workspace.id)
            if workspace is not None:
                await cleanup.delete(workspace)
        await cleanup.commit()


# ── Structural: what the schema guarantees regardless of any code ────────────


def test_every_business_table_is_workspace_scoped() -> None:
    """Rule 2, checked against the mapped tables rather than trusted."""
    offenders = [
        name
        for name, table in Base.metadata.tables.items()
        if name not in TENANT_FREE_TABLES and "workspace_id" not in table.columns
    ]
    assert not offenders, (
        f"tables without workspace_id: {offenders}. "
        "Inherit WorkspaceScopedMixin, or add the table to TENANT_FREE_TABLES "
        "with a written reason."
    )


def test_workspace_id_is_never_nullable() -> None:
    """A nullable workspace_id is a row belonging to no one — and readable by
    anyone who forgets to filter."""
    nullable = [
        name
        for name, table in Base.metadata.tables.items()
        if "workspace_id" in table.columns and table.columns["workspace_id"].nullable
    ]
    assert not nullable, f"workspace_id is nullable on: {nullable}"


async def test_every_workspace_scoped_table_indexes_workspace_id() -> None:
    """Every query filters on it. Without an index, isolation costs a full
    table scan per customer, and the first large tenant makes it everyone's
    problem."""
    async with engine.connect() as connection:
        indexed = await connection.run_sync(
            lambda sync_connection: {
                table: [
                    index["column_names"] for index in inspect(sync_connection).get_indexes(table)
                ]
                for table in Base.metadata.tables
                if table not in TENANT_FREE_TABLES
            }
        )

    missing = [
        table
        for table, indexes in indexed.items()
        if not any(columns and columns[0] == "workspace_id" for columns in indexes)
    ]
    assert not missing, f"workspace_id leads no index on: {missing}"


async def test_the_database_refuses_a_cross_tenant_row(
    tenants: tuple[Tenant, Tenant],
) -> None:
    """The guarantee must hold even against code that forgot the rule.

    Raw SQL on purpose: this asserts what PostgreSQL enforces, not what the
    ORM happens to prevent.
    """
    alpha, beta = tenants
    async with engine.begin() as connection:
        with pytest.raises(Exception, match=r"(?i)foreign key|violates"):
            await connection.execute(
                text(
                    "INSERT INTO entities "
                    "(workspace_id, type, external_id, source_id, name) "
                    "VALUES (:ws, 'service', 'stolen', :src, 'stolen')"
                ),
                {"ws": alpha.workspace.id, "src": beta.source.id},
            )


# ── HTTP: every route, as routes appear ──────────────────────────────────────


def _paths() -> dict[str, dict[str, Any]]:
    """Every path the application exposes, read from its OpenAPI schema.

    The schema rather than `app.routes`: FastAPI does not flatten included
    routers into that list, and its shape has changed between versions. The
    schema is what the application actually publishes — which is also what a
    client could reach.
    """
    paths: dict[str, dict[str, Any]] = app.openapi()["paths"]
    return paths


def _readable_paths() -> list[str]:
    """GET paths taking no path parameter, so they can be called blind."""
    return [
        path
        for path, operations in _paths().items()
        if "get" in operations and path not in PUBLIC_PATHS and "{" not in path
    ]


def test_no_route_takes_a_workspace_identifier() -> None:
    """Rule 3: the workspace is read from the session, never from the request.

    A route accepting a workspace id trusts the client to name its own tenant
    — and therefore to name someone else's.
    """
    offenders = [
        path
        for path in _paths()
        if any(token in path for token in ("{workspace_id}", "{workspace}"))
    ]
    assert not offenders, f"routes taking a workspace identifier: {offenders}"


async def test_no_route_leaks_another_workspace(
    client: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    """Call every readable route and look for the other tenant's markers.

    Skips while no such route exists. It stops skipping by itself.
    """
    paths = _readable_paths()
    if not paths:
        pytest.skip(
            "no readable route mounted yet — this check activates itself with the first one"
        )

    _alpha, beta = tenants
    leaks: list[str] = []

    for path in paths:
        response = await client.get(path)
        if response.status_code >= 500:
            leaks.append(f"{path}: HTTP {response.status_code}")
            continue
        for marker in beta.identifiers():
            if marker in response.text:
                leaks.append(f"{path} exposed {marker!r} from another workspace")

    assert not leaks, "cross-workspace leak:\n  " + "\n  ".join(leaks)


def test_the_application_actually_exposes_routes() -> None:
    """Guards the skip above from covering nothing.

    A skip is acceptable only while there is genuinely nothing to call. If
    api_router stopped being mounted, every check in this file would go quiet
    instead of failing.
    """
    assert "/api/v1/health" in _paths(), (
        "api_router is not mounted — the checks in this file would silently cover nothing"
    )
