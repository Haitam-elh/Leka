"""Database access for the governance module.

The only place in this module where a query is written (architecture rule 4).

Membership queries are NOT here: leka.platform owns the Membership model, and
the module that owns a model owns its queries. Governance imports
MembershipResolver from there rather than writing a second set of queries
that would drift from the first.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class AuditRepository:
    """Appends to the audit trail and reads it back.

    Append-only by intent: a row is written when something happens and never
    updated. An audit log that can be edited is not an audit log.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
