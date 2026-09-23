"""Database foundations: declarative base, column mixins, session, scoping.

Imported by every module's models.py and repository.py. Depends on nothing
but leka.core.
"""

from leka.db.base import Base
from leka.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin, WorkspaceScopedMixin
from leka.db.pagination import (
    CursorError,
    Page,
    SortableField,
    decode_cursor,
    encode_cursor,
    paginate,
)
from leka.db.repository import (
    CrossWorkspaceWriteError,
    MissingWorkspaceScopeError,
    TenantScopeError,
    WorkspaceScopedRepository,
    current_workspace,
    system_scope,
    workspace_scope,
)
from leka.db.session import (
    DatabaseSession,
    check_database,
    engine,
    get_session,
    session_factory,
)

__all__ = [
    "Base",
    "CrossWorkspaceWriteError",
    "CursorError",
    "DatabaseSession",
    "MissingWorkspaceScopeError",
    "Page",
    "SortableField",
    "TenantScopeError",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "WorkspaceScopedMixin",
    "WorkspaceScopedRepository",
    "check_database",
    "current_workspace",
    "decode_cursor",
    "encode_cursor",
    "engine",
    "get_session",
    "paginate",
    "session_factory",
    "system_scope",
    "workspace_scope",
]
