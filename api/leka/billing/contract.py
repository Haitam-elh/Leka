"""An Enterprise contract, as its organisation reads it (2026-10-25): « La
page Facturation devient Contrat » — its type, the organisation, since when,
how many members, its dedicated contact. Never a price, never credits.

The contract is LEKA's to make (python -m leka.ops.enterprise), kept with
the workspace (settings["enterprise"]); an admin of the organisation reads
it, never changes it: WorkspacePreferences forbids that key.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from leka.billing.schemas import ContractContactRead, ContractRead
from leka.billing.subscriptions import ENTERPRISE
from leka.governance import plan_of
from leka.platform import MembershipRepository, Workspace


async def is_enterprise(session: AsyncSession, workspace_id: uuid.UUID) -> bool:
    """Whether the workspace is under an Enterprise contract."""
    return (await plan_of(session, workspace_id)).name == ENTERPRISE


async def contract_now(session: AsyncSession, workspace_id: uuid.UUID) -> ContractRead | None:
    """Its contract — None on a public plan: it has none."""
    plan = await plan_of(session, workspace_id)
    if plan.name != ENTERPRISE:
        return None
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:  # pragma: no cover - the principal proves it exists
        return None
    said = (workspace.settings or {}).get("enterprise")
    kept = said if isinstance(said, dict) else {}
    since = kept.get("since")
    contact = kept.get("contact")
    person = contact if isinstance(contact, dict) else {}
    name, email = person.get("name"), person.get("email")
    return ContractRead(
        type="enterprise",
        organisation=workspace.name,
        since=(
            date.fromisoformat(since)
            if isinstance(since, str)
            else (plan.since.date() if plan.since else None)
        ),
        members=await MembershipRepository(session, workspace_id).count_members(),
        contact=(
            ContractContactRead(
                name=name if isinstance(name, str) else None,
                email=email if isinstance(email, str) else None,
            )
            if name or email
            else None
        ),
    )
