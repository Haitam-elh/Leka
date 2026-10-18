"""Several bundles bought in one Checkout (LEKA-500): a checkout's kind
« bundles », its key their keys.

Revision ID: 7a2c9e4b1d36
Revises: 1edec9bb485e
Created: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "7a2c9e4b1d36"
down_revision: str | None = "1edec9bb485e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_add_on_checkouts_kind"), "add_on_checkouts", type_="check")
    op.create_check_constraint(
        op.f("ck_add_on_checkouts_kind"),
        "add_on_checkouts",
        "kind IN ('agent', 'bundle', 'agents', 'bundles')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM add_on_checkouts WHERE kind = 'bundles'")
    op.drop_constraint(op.f("ck_add_on_checkouts_kind"), "add_on_checkouts", type_="check")
    op.create_check_constraint(
        op.f("ck_add_on_checkouts_kind"),
        "add_on_checkouts",
        "kind IN ('agent', 'bundle', 'agents')",
    )
