"""Database access for the governance module.

The only place in this module where a query is written (architecture rule 4).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class AuditRepository:
    """Appends to the audit trail and reads it back."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session


class MembershipRepository:
    """Resolves which workspaces a user may enter, and as what.

    Reads the memberships table. The identity module owns authentication;
    this owns authorisation.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
