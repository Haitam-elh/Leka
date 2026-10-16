"""Several agents bought in one Checkout (LEKA-458): the intention's agents,
paid together — a checkout's kind « agents », its key their keys.

Revision ID: 3f7b2d9e6c18
Revises: c4d7e2a9f013
Create Date: 2026-10-15 21:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3f7b2d9e6c18"
down_revision: str | None = "c4d7e2a9f013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_add_on_checkouts_kind"), "add_on_checkouts", type_="check")
    op.create_check_constraint(
        op.f("ck_add_on_checkouts_kind"),
        "add_on_checkouts",
        "kind IN ('agent', 'bundle', 'agents')",
    )
    op.alter_column("add_on_checkouts", "key", type_=sa.String(400), existing_type=sa.String(100))


def downgrade() -> None:
    op.execute("DELETE FROM add_on_checkouts WHERE kind = 'agents'")
    op.alter_column("add_on_checkouts", "key", type_=sa.String(100), existing_type=sa.String(400))
    op.drop_constraint(op.f("ck_add_on_checkouts_kind"), "add_on_checkouts", type_="check")
    op.create_check_constraint(
        op.f("ck_add_on_checkouts_kind"), "add_on_checkouts", "kind IN ('agent', 'bundle')"
    )
