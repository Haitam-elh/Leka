"""Internal notes about a person.

Revision ID: 3643a84285a4
Revises: a3145035a640
Created: 2026-11-06

LEKA-550.
- `admin_notes.for_user_id`: a note may be about a person instead of an
  organisation; one or the other, never both, never none. Deleted with
  them.
- `users:notes`: a new permission, granted to every role as the roles
  stand (the Super Admin may take it back).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3643a84285a4"
down_revision: str | None = "a3145035a640"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTES = "users:notes"


def upgrade() -> None:
    op.add_column("admin_notes", sa.Column("for_user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_admin_notes_for_user_id_users"),
        "admin_notes",
        "users",
        ["for_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("admin_notes", "for_workspace_id", existing_type=sa.UUID(), nullable=True)
    op.create_check_constraint(
        op.f("ck_admin_notes_about"),
        "admin_notes",
        "num_nonnulls(for_workspace_id, for_user_id) = 1",
    )
    op.create_index(
        "ix_admin_notes_user_created", "admin_notes", ["for_user_id", "created_at"], unique=False
    )
    table = sa.table(
        "admin_role_permissions",
        sa.column("id", sa.UUID()),
        sa.column("role", sa.String()),
        sa.column("permission", sa.String()),
        sa.column("granted_by", sa.String()),
    )
    op.bulk_insert(
        table,
        [
            {"id": uuid.uuid4(), "role": role, "permission": NOTES, "granted_by": "LEKA-550"}
            for role in ("operations", "support", "finance")
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM admin_role_permissions WHERE permission = :permission").bindparams(
            permission=NOTES
        )
    )
    op.execute("DELETE FROM admin_notes WHERE for_user_id IS NOT NULL")
    op.drop_index("ix_admin_notes_user_created", table_name="admin_notes")
    op.drop_constraint(op.f("ck_admin_notes_about"), "admin_notes", type_="check")
    op.alter_column("admin_notes", "for_workspace_id", existing_type=sa.UUID(), nullable=False)
    op.drop_constraint(op.f("fk_admin_notes_for_user_id_users"), "admin_notes", type_="foreignkey")
    op.drop_column("admin_notes", "for_user_id")
