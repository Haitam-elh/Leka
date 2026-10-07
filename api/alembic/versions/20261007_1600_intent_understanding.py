"""Intent understanding: what LEKA understood of each intention.

Revision ID: 6d2a9f4c8e13
Revises: 3c8e5a1f7d92
Created: 2026-10-07

LEKA-385. What LEKA understood of an intention — its goal, whether it asks
or requests, the actions, the entities, the ambiguities, each with the words
it came from — kept with it (`intentions.understanding`, its goal alone in
`intentions.goal`); and a state for what it could not understand enough:
`needs_clarification`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "6d2a9f4c8e13"
down_revision: str | None = "3c8e5a1f7d92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BEFORE = (
    "submitted",
    "analysing",
    "awaiting_decision",
    "approved",
    "scheduled",
    "executing",
    "verifying",
    "completed",
    "rejected",
    "failed",
    "cancelled",
)
AFTER = ("submitted", "needs_clarification", *BEFORE[1:])


def _statuses(values: Sequence[str]) -> None:
    op.drop_constraint(op.f("ck_intentions_status"), "intentions", type_="check")
    op.create_check_constraint(
        op.f("ck_intentions_status"),
        "intentions",
        f"status IN ({', '.join(repr(value) for value in values)})",
    )


def upgrade() -> None:
    op.add_column(
        "intentions",
        sa.Column("understanding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("intentions", sa.Column("goal", sa.String(length=30), nullable=True))
    _statuses(AFTER)


def downgrade() -> None:
    # An intention waiting for clarification is analysing to an older LEKA.
    op.execute("UPDATE intentions SET status = 'analysing' WHERE status = 'needs_clarification'")
    _statuses(BEFORE)
    op.drop_column("intentions", "goal")
    op.drop_column("intentions", "understanding")
