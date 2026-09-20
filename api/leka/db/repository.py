"""Tenant scoping, enforced rather than agreed.

LEKA is multi-tenant on shared tables. Architecture rule 4 says every query
lives in a repository; nothing so far said those queries must filter by
workspace. This module makes that structural.

Two layers, because one is not enough:

**WorkspaceScopedRepository** takes the workspace at construction, not as a
method argument, and refuses to exist without one. Every read it produces is
already filtered; every write it accepts is checked. It makes the correct
query the easy one.

**The session guard** is what makes the incorrect query impossible. A base
class cannot stop someone writing `select(Entity)` against the session
directly — so a SQLAlchemy event intercepts every ORM statement touching a
workspace-scoped table and either scopes it or refuses it. Fail-closed: no
declared workspace, no rows. Not even an empty result — an exception, because
a silent empty list is how "my dashboard is blank" becomes a three-day
investigation.

System work that legitimately crosses tenants — the seed script, a
migration, a worker sweeping every workspace — declares itself with
`system_scope()`. Explicitly, in one visible line, reviewable in a diff.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Final, TypeVar

from sqlalchemy import Select, event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, with_loader_criteria

from leka.db.mixins import WorkspaceScopedMixin


class TenantScopeError(RuntimeError):
    """Base of the errors this module raises. All of them are bugs."""


class MissingWorkspaceScopeError(TenantScopeError):
    """A workspace-scoped table was queried with no workspace declared.

    Either the code should run inside `workspace_scope(...)` — which the
    request principal does automatically — or it is system work that must say
    so with `system_scope()`.
    """


class CrossWorkspaceWriteError(TenantScopeError):
    """An attempt to write a row belonging to another workspace."""


class _System:
    """Marks a scope that deliberately spans every tenant."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<system scope>"


SYSTEM: Final = _System()

# None means "nothing declared", which is the fail-closed default. It is not
# the same as SYSTEM, which means "every tenant, on purpose".
_current_workspace: ContextVar[uuid.UUID | _System | None] = ContextVar(
    "leka_current_workspace", default=None
)


@contextmanager
def workspace_scope(workspace_id: uuid.UUID) -> Iterator[None]:
    """Run a block against exactly one workspace."""
    token = _current_workspace.set(workspace_id)
    try:
        yield
    finally:
        _current_workspace.reset(token)


@contextmanager
def system_scope() -> Iterator[None]:
    """Run a block across every workspace.

    For the seed script, data migrations, and workers that sweep all tenants.
    Never for serving a request: a request has a principal, and a principal
    has exactly one workspace.
    """
    token = _current_workspace.set(SYSTEM)
    try:
        yield
    finally:
        _current_workspace.reset(token)


def current_workspace() -> uuid.UUID | _System | None:
    """What scope is active right now. None means none was declared."""
    return _current_workspace.get()


def _touches_scoped_table(execute_state: Any) -> bool:
    return any(
        issubclass(mapper.class_, WorkspaceScopedMixin) for mapper in execute_state.all_mappers
    )


@event.listens_for(Session, "do_orm_execute")
def _enforce_workspace_scope(execute_state: Any) -> None:
    """Scope every ORM statement, or refuse it.

    Column and relationship loads are exempt: they refresh an object already
    loaded — and therefore already scoped — by primary key. Filtering them
    again would break lazy loading without adding a guarantee.
    """
    if execute_state.is_column_load or execute_state.is_relationship_load:
        return
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    if not _touches_scoped_table(execute_state):
        return

    scope = _current_workspace.get()

    if scope is None:
        tables = sorted(
            mapper.class_.__name__
            for mapper in execute_state.all_mappers
            if issubclass(mapper.class_, WorkspaceScopedMixin)
        )
        msg = (
            f"query touches workspace-scoped table(s) {tables} with no workspace "
            "declared. Serve it inside workspace_scope(...) — the request "
            "principal does this for you — or, if it deliberately spans every "
            "tenant, say so with system_scope()."
        )
        raise MissingWorkspaceScopeError(msg)

    if scope is SYSTEM:
        return

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            WorkspaceScopedMixin,
            lambda cls: cls.workspace_id == scope,
            include_aliases=True,
        )
    )


ModelT = TypeVar("ModelT", bound=WorkspaceScopedMixin)


class WorkspaceScopedRepository:
    """Base class for every repository over a workspace-scoped table.

    The workspace is a constructor argument, never a method parameter. A
    method parameter is a thing a caller can forget, or get from the wrong
    place; a constructor argument is a thing the object cannot exist without.

    The session is private. Subclasses build queries with `self.select(...)`
    and persist with `self.add(...)`, both already scoped. Reaching around
    them means importing sqlalchemy and using the session directly, which is
    visible in a diff — and caught by the session guard above anyway.
    """

    def __init__(self, session: AsyncSession, workspace_id: uuid.UUID | None) -> None:
        # Typed as optional on purpose. A caller CAN pass None — from an
        # unauthenticated request, from a principal that failed to resolve —
        # and the honest thing is to accept that call and refuse it loudly,
        # rather than declare it impossible and crash somewhere further down.
        if workspace_id is None:
            msg = (
                f"{type(self).__name__} cannot be built without a workspace. "
                "The workspace comes from the request principal, never from a "
                "URL or a request body (architecture rule 3)."
            )
            raise MissingWorkspaceScopeError(msg)
        self._session = session
        self._workspace_id = workspace_id

    @property
    def workspace_id(self) -> uuid.UUID:
        return self._workspace_id

    def select(self, model: type[ModelT]) -> Select[tuple[ModelT]]:
        """A SELECT already restricted to this repository's workspace.

        The filter is explicit here as well as in the session guard. Belt and
        braces on purpose: this one appears in the SQL a developer reads while
        debugging, which the guard's loader criteria does less obviously.
        """
        return select(model).where(model.workspace_id == self._workspace_id)

    def add(self, instance: ModelT) -> None:
        """Stage a row, refusing one that belongs elsewhere.

        A row with no workspace_id is given this repository's — forgetting it
        is the common case and it has exactly one right answer. A row bearing
        a DIFFERENT workspace is a bug, and gets an exception rather than a
        silent correction.
        """
        existing = getattr(instance, "workspace_id", None)
        if existing is None:
            instance.workspace_id = self._workspace_id
        elif existing != self._workspace_id:
            msg = (
                f"{type(instance).__name__} belongs to workspace {existing}, but "
                f"this repository is scoped to {self._workspace_id}. Writing it "
                "would put one customer's row in another customer's data."
            )
            raise CrossWorkspaceWriteError(msg)
        self._session.add(instance)

    async def get(self, model: type[ModelT], row_id: uuid.UUID) -> ModelT | None:
        """Fetch by primary key, within this workspace.

        Deliberately not session.get(): that looks up by primary key alone
        and would happily return another tenant's row.
        """
        result = await self._session.execute(self.select(model).where(model.id == row_id))
        return result.scalar_one_or_none()

    async def list(self, statement: Select[tuple[ModelT]]) -> Sequence[ModelT]:
        result = await self._session.execute(statement)
        return result.scalars().all()

    async def delete(self, instance: ModelT) -> None:
        if instance.workspace_id != self._workspace_id:
            msg = (
                f"refusing to delete a {type(instance).__name__} from workspace "
                f"{instance.workspace_id} through a repository scoped to "
                f"{self._workspace_id}."
            )
            raise CrossWorkspaceWriteError(msg)
        await self._session.delete(instance)

    async def flush(self) -> None:
        await self._session.flush()
