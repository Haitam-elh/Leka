"""Platform-level tables.

The workspace is LEKA's tenant boundary. It lives here rather than in
leka.identity because every module is scoped by it, while identity only
decides who may enter one.
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Workspace(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One customer company.

    The only table without workspace_id: it *is* the workspace. Everything
    else references it (architecture rule 2).
    """

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
