"""Permissions and audit.

Permissions are exposed as FastAPI dependencies, never as an `if` inside a
route body (architecture rule 5). A dependency is declared once in the route
signature and cannot be forgotten halfway down a function; an `if` is
forgotten in the fourteenth route by someone in a hurry.
"""

from __future__ import annotations

from leka.governance.repository import AuditRepository, MembershipRepository


class GovernanceService:
    """Answers "may this principal do this?" and records that it was asked."""

    def __init__(
        self,
        memberships: MembershipRepository,
        audit: AuditRepository,
    ) -> None:
        self._memberships = memberships
        self._audit = audit
