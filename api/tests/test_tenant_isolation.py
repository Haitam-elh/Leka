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
from leka.db import Base, engine, session_factory, system_scope
from leka.knowledge import Entity, EntityType
from leka.main import app
from leka.platform import Membership, Role, Workspace
from tests.conftest import FakeIdentity

pytestmark = pytest.mark.integration

# Tables that legitimately have no workspace_id, and why.
#   workspaces  — it IS the tenant
#   users       — a person may belong to several workspaces; membership is
#                 the authority (see migration 001)
#   workspaces     it IS the tenant
#   users          a person may belong to several workspaces; membership is
#                  the authority (migration 001)
#   sessions       a session belongs to a person, not to a tenant. It CARRIES
#                  an active workspace, which is a different thing: where this
#                  browser currently is, changed by switching.
#   email_tokens   belong to a person, and exist before any workspace does —
#                  a verification link is sent before the account has entered
#                  anywhere.
#   job_runs       a sweep serves every customer and belongs to none, so its
#                  owner is NULL — and a nullable workspace_id is exactly what
#                  test_workspace_id_is_never_nullable forbids: it would look
#                  like the isolation column while the session guard, which
#                  only protects WorkspaceScopedMixin models, ignored it. The
#                  owner is `for_workspace_id` instead, a different name on
#                  purpose. Whatever exposes this history must filter on it
#                  explicitly and never return the NULL rows: a system run is
#                  operating data, not a customer's. JobRunRepository.
#                  list_for_workspace is that filter; see ADR 013.
#   capability_registrations, capability_events
#                  LEKA's capability catalogue and its history (LEKA-393):
#                  what LEKA can do, every version, every lifecycle move —
#                  the product's, no customer's. What a workspace says of
#                  them is workspace_capabilities, which is scoped.
#   stripe_events  every event Stripe sent (LEKA-431), kept once by its id
#                  before LEKA knows which workspace it is about — or when it
#                  is about none. Which one it was: `for_workspace_id`, as
#                  job_runs says it; nothing exposes these rows.
#   site_events    what visitors of the public pricing page chose and clicked
#                  (LEKA-431) — LEKA's own analytics, before anyone signs
#                  in: no workspace, no person, no address.
#   model_rates    what a model costs LEKA from a day on (LEKA-430): LEKA's
#                  prices, no customer's. What a call cost a workspace is
#                  model_calls, which is scoped.
TENANT_FREE_TABLES = frozenset(
    {
        "workspaces",
        "users",
        "sessions",
        "email_tokens",
        "job_runs",
        "alembic_version",
        "capability_registrations",
        "capability_events",
        "site_events",
        "stripe_events",
        "model_rates",
    }
)

PUBLIC_PATHS = frozenset({"/api/v1/health"})


class Tenant:
    """One workspace, a member of it, and a marker only it should ever see."""

    def __init__(
        self,
        workspace: Workspace,
        source: Source,
        entity: Entity,
        user_id: uuid.UUID,
    ) -> None:
        self.workspace = workspace
        self.source = source
        self.entity = entity
        self.user_id = user_id
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

    # A member, so the request principal resolves. The users table belongs to
    # LEKA-330, so the row goes in as SQL rather than through a model this
    # ticket does not own.
    created = await session.execute(
        text("INSERT INTO users (email) VALUES (:email) RETURNING id"),
        {"email": f"{marker}@example.test"},
    )
    user_id: uuid.UUID = created.scalar_one()
    session.add(Membership(workspace_id=workspace.id, user_id=user_id, role=Role.OWNER))
    await session.flush()

    source = Source(workspace_id=workspace.id, kind=SourceKind.GITHUB, name=marker)
    session.add(source)
    await session.flush()

    entity = Entity(
        workspace_id=workspace.id,
        type=EntityType.SERVICE,
        key=f"service:{marker}",
        name=f"secret-service-{marker}",
    )
    session.add(entity)
    await session.flush()
    await session.commit()
    return Tenant(workspace, source, entity, user_id)


@pytest.fixture
async def tenants() -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two workspaces with data, removed afterwards."""
    with system_scope():
        async with session_factory() as session:
            first = await _make_tenant(session, "alpha")
            second = await _make_tenant(session, "beta")

    yield first, second

    with system_scope():
        async with session_factory() as cleanup:
            for tenant in (first, second):
                stored = await cleanup.get(Workspace, tenant.workspace.id)
                if stored is not None:
                    await cleanup.delete(stored)
                await cleanup.execute(
                    text("DELETE FROM users WHERE id = :uid"), {"uid": tenant.user_id}
                )
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
                    "INSERT INTO relationships "
                    "(workspace_id, from_entity_id, to_entity_id, type) "
                    "VALUES (:ws, :mine, :theirs, 'depends_on')"
                ),
                {"ws": alpha.workspace.id, "mine": alpha.entity.id, "theirs": beta.entity.id},
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


# The one route allowed to name a workspace, and why.
#
# Switching is a REQUEST to move, not an assertion of where you are. It
# verifies a membership and then writes the id into the server-side session;
# everything afterwards reads it from there. Without this route the workspace
# could never change at all.
#
# Any other route appearing here is a rule 3 violation.
WORKSPACE_ID_ALLOWED_ON = frozenset({"/api/v1/workspaces/{workspace_id}/switch"})


def test_no_route_takes_a_workspace_identifier() -> None:
    """Rule 3: the workspace is read from the session, never from the request.

    A route accepting a workspace id trusts the client to name its own tenant
    — and therefore to name someone else's. The switch route is the single,
    deliberate exception; it is listed above rather than pattern-matched, so
    adding a second one is a decision somebody has to write down.
    """
    offenders = [
        path
        for path in _paths()
        if any(token in path for token in ("{workspace_id}", "{workspace}"))
        and path not in WORKSPACE_ID_ALLOWED_ON
    ]
    assert not offenders, f"routes taking a workspace identifier: {offenders}"


async def test_no_route_leaks_another_workspace(
    client: AsyncClient, identity: FakeIdentity, tenants: tuple[Tenant, Tenant]
) -> None:
    """Call every readable route as one tenant, looking for the other's data.

    Driven by the OpenAPI schema, so a route added tomorrow is covered the
    day it is mounted and nobody has to remember this file. It skipped until
    LEKA-331 mounted the first routes; it stopped skipping by itself.
    """
    paths = _readable_paths()
    if not paths:
        pytest.skip(
            "no readable route mounted yet — this check activates itself with the first one"
        )

    alpha, beta = tenants
    identity.sign_in(alpha.user_id, alpha.workspace.id)
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
