"""An organisation's country, size and internal notes.

Revision ID: a3145035a640
Revises: 5e14651feb40
Created: 2026-11-06

LEKA-549.
- `workspaces.country` (ISO 3166-1 alpha-2) and `workspaces.size` (the
  brackets of the site's forms): what LEKA's team keeps about an
  organisation. Null for every one today: not known, never guessed.
- `admin_notes`: what LEKA's team writes down about an organisation,
  never shown to the customer, deleted with it.
- `organisations:notes`: a new permission, granted to every role as the
  roles stand (the Super Admin may take it back).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3145035a640"
down_revision: str | None = "5e14651feb40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIZES = ("1-10", "11-50", "51-200", "201-1000", "1000+")
NOTES = "organisations:notes"


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("country", sa.String(length=2), nullable=True))
    op.add_column("workspaces", sa.Column("size", sa.String(length=10), nullable=True))
    op.create_check_constraint(
        op.f("ck_workspaces_country"), "workspaces", "country ~ '^[A-Z]{2}$'"
    )
    op.create_check_constraint(
        op.f("ck_workspaces_size"),
        "workspaces",
        "size IN (" + ", ".join(f"'{size}'" for size in SIZES) + ")",
    )
    op.create_table(
        "admin_notes",
        sa.Column("for_workspace_id", sa.UUID(), nullable=False),
        sa.Column("admin_id", sa.UUID(), nullable=True),
        sa.Column("admin_email", sa.String(length=320), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 4000", name=op.f("ck_admin_notes_body")
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_accounts.id"],
            name=op.f("fk_admin_notes_admin_id_admin_accounts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["for_workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_admin_notes_for_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_notes")),
    )
    op.create_index(
        "ix_admin_notes_workspace_created",
        "admin_notes",
        ["for_workspace_id", "created_at"],
        unique=False,
    )
    # Every role may write a note, as the roles stand now: a role the Super
    # Admin already changed gets it too, and may lose it again.
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
            {"id": uuid.uuid4(), "role": role, "permission": NOTES, "granted_by": "LEKA-549"}
            for role in ("operations", "support", "finance")
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM admin_role_permissions WHERE permission = :permission").bindparams(
            permission=NOTES
        )
    )
    op.drop_index("ix_admin_notes_workspace_created", table_name="admin_notes")
    op.drop_table("admin_notes")
    op.drop_constraint(op.f("ck_workspaces_size"), "workspaces", type_="check")
    op.drop_constraint(op.f("ck_workspaces_country"), "workspaces", type_="check")
    op.drop_column("workspaces", "size")
    op.drop_column("workspaces", "country")
