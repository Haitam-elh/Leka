"""Database foundations: declarative base, column mixins, session, scoping.

Imported by every module's models.py and repository.py. Depends on nothing
but leka.core.
"""

from leka.db.base import Base
from leka.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin
from leka.db.repository import (
    CrossWorkspaceWriteError,
    MissingWorkspaceScopeError,
    TenantScopeError,
    WorkspaceScopedRepository,
    current_workspace,
    system_scope,
    workspace_scope,
)
from leka.db.session import check_database, engine, get_session, session_factory

__all__ = [
    "Base",
    "CrossWorkspaceWriteError",
    "MissingWorkspaceScopeError",
    "TenantScopeError",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "WorkspaceScopedMixin",
    "WorkspaceScopedRepository",
    "check_database",
    "current_workspace",
    "engine",
    "get_session",
    "session_factory",
    "system_scope",
    "workspace_scope",
]
