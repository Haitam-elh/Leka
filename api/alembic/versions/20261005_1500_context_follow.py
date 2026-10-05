"""Dynamic context: a context keeps up with the company model.

Revision ID: 5c7e1f9a2d34
Revises: 9d2f4c6a8b10
Created: 2026-10-05

LEKA-374. A context says whether it follows the model (`follow`), when it
was last used (`used_at`), which build its last check read
(`checked_model_at`), and — when the model has changed what it holds since
— from when and what (`stale_since`, `pending`, `pending_count`). A version
says what made it: the model's changes it followed, or what of its request
or intention changed (`changes`, `change_count`, and the triggers
`changed`, `expanded`, `compressed`, `reasked`), and how it differs from
the last version that held something (`delta`). Every time a context is
made again is kept (`context_checks`), whatever came of it; each workspace
says up to which build its contexts were followed (`context_follows`).

The contexts made before are taken as checked against the build their
latest version read, and as used when they were last refreshed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5c7e1f9a2d34"
down_revision: str | None = "9d2f4c6a8b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGERS = "('created', 'refreshed', 'changed', 'expanded', 'compressed', 'reasked')"


def _table(name: str, *columns: sa.Column[object], others: Sequence[object] = ()) -> None:
    """A workspace's table, as leka.db's mixin makes them."""
    op.create_table(
        name,
        *columns,
        sa.Column("workspace_id", sa.UUID(), nullable=False),
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
        *others,
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(f"fk_{name}_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    op.create_index(op.f(f"ix_{name}_workspace_id"), name, ["workspace_id"])


def upgrade() -> None:
    op.add_column(
        "contexts", sa.Column("follow", sa.Boolean(), server_default="true", nullable=False)
    )
    op.add_column("contexts", sa.Column("used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "contexts", sa.Column("checked_model_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("contexts", sa.Column("stale_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "contexts",
        sa.Column(
            "pending", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
    )
    op.add_column(
        "contexts", sa.Column("pending_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_check_constraint(op.f("ck_contexts_pending_count"), "contexts", "pending_count >= 0")
    op.create_index(
        "ix_contexts_workspace_stale_since", "contexts", ["workspace_id", "stale_since"]
    )
    op.execute(
        """
        UPDATE contexts c
           SET used_at = coalesce(c.refreshed_at, c.created_at),
               checked_model_at = (
                   SELECT v.model_built_at FROM context_versions v
                    WHERE v.context_id = c.id
                    ORDER BY v.version DESC
                    LIMIT 1
               )
        """
    )

    op.add_column(
        "context_versions",
        sa.Column(
            "changes", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
    )
    op.add_column(
        "context_versions",
        sa.Column("change_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "context_versions",
        sa.Column("delta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.drop_constraint(op.f("ck_context_versions_trigger"), "context_versions", type_="check")
    op.create_check_constraint(
        op.f("ck_context_versions_trigger"), "context_versions", f"trigger IN {TRIGGERS}"
    )

    _table(
        "context_checks",
        sa.Column("context_id", sa.UUID(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("checked_by", sa.UUID(), nullable=True),
        sa.Column(
            "changes", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("change_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("model_built_at", sa.DateTime(timezone=True), nullable=True),
        others=(
            sa.CheckConstraint(
                "outcome IN ('version', 'unchanged', 'failed')",
                name=op.f("ck_context_checks_outcome"),
            ),
            sa.ForeignKeyConstraint(
                ["workspace_id", "context_id"],
                ["contexts.workspace_id", "contexts.id"],
                name="fk_context_checks_workspace_context",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["checked_by"],
                ["users.id"],
                name=op.f("fk_context_checks_checked_by_users"),
                ondelete="SET NULL",
            ),
        ),
    )
    op.create_index(
        "ix_context_checks_workspace_context",
        "context_checks",
        ["workspace_id", "context_id", "checked_at"],
    )

    _table(
        "context_follows",
        sa.Column("followed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        others=(sa.UniqueConstraint("workspace_id", name="uq_context_follows_workspace"),),
    )


def downgrade() -> None:
    op.drop_table("context_follows")
    op.drop_table("context_checks")
    op.drop_constraint(op.f("ck_context_versions_trigger"), "context_versions", type_="check")
    op.execute(
        "UPDATE context_versions SET trigger = 'refreshed' "
        "WHERE trigger NOT IN ('created', 'refreshed')"
    )
    op.create_check_constraint(
        op.f("ck_context_versions_trigger"),
        "context_versions",
        "trigger IN ('created', 'refreshed')",
    )
    op.drop_column("context_versions", "delta")
    op.drop_column("context_versions", "change_count")
    op.drop_column("context_versions", "changes")
    op.drop_index("ix_contexts_workspace_stale_since", table_name="contexts")
    op.drop_constraint(op.f("ck_contexts_pending_count"), "contexts", type_="check")
    op.drop_column("contexts", "pending_count")
    op.drop_column("contexts", "pending")
    op.drop_column("contexts", "stale_since")
    op.drop_column("contexts", "checked_model_at")
    op.drop_column("contexts", "used_at")
    op.drop_column("contexts", "follow")
