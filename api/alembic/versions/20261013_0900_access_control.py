"""Authorization: restricted entities, and every access decision kept.

Revision ID: 9e4b2d7c1a83
Revises: 3c6d9e1f4a72
Created: 2026-10-13

LEKA-402. The entities an admin restricted (`entity_restrictions`): hidden
from every role that may not read them, said why, by whom, since when. The
trail of access decisions (`access_decisions`): who asked to do what, on
what, allowed or refused, by which rule and why — every refusal, every write
and run allowed. Append-only: the one change allowed is who asked forgotten
with their account.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9e4b2d7c1a83"
down_revision: str | None = "3c6d9e1f4a72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column[object]]:
    return [
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
    ]


def _owned(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete="SET NULL"
    )


def _workspace(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id"],
        ["workspaces.id"],
        name=op.f(f"fk_{table}_workspace_id_workspaces"),
        ondelete="CASCADE",
    )


def upgrade() -> None:
    op.create_table(
        "entity_restrictions",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("restricted_by", sa.UUID(), nullable=True),
        sa.Column("restricted_at", sa.DateTime(timezone=True), nullable=False),
        *_base(),
        _owned("entity_restrictions", "restricted_by"),
        _workspace("entity_restrictions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_restrictions")),
        sa.UniqueConstraint("workspace_id", "entity_id", name="uq_entity_restrictions_entity"),
    )
    op.create_index(
        op.f("ix_entity_restrictions_workspace_id"), "entity_restrictions", ["workspace_id"]
    )

    op.create_table(
        "access_decisions",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("permission", sa.String(length=40), nullable=False),
        sa.Column("resource_type", sa.String(length=30), nullable=True),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("decision", sa.String(length=5), nullable=False),
        sa.Column("rule", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("route", sa.String(length=200), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        *_base(),
        sa.CheckConstraint(
            "decision IN ('allow', 'deny')", name=op.f("ck_access_decisions_decision")
        ),
        _owned("access_decisions", "user_id"),
        _workspace("access_decisions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_decisions")),
    )
    op.create_index("ix_access_decisions_workspace_at", "access_decisions", ["workspace_id", "at"])
    op.create_index(op.f("ix_access_decisions_workspace_id"), "access_decisions", ["workspace_id"])
    # A decision is never changed; who asked is forgotten with their account.
    op.execute(
        """
        CREATE FUNCTION access_decisions_append_only() RETURNS trigger AS $$
        BEGIN
            IF NEW.user_id IS NULL AND to_jsonb(NEW) - 'user_id' = to_jsonb(OLD) - 'user_id' THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'access_decisions is append-only: a decision is never changed'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER access_decisions_append_only
        BEFORE UPDATE ON access_decisions
        FOR EACH ROW EXECUTE FUNCTION access_decisions_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER access_decisions_append_only ON access_decisions")
    op.execute("DROP FUNCTION access_decisions_append_only()")
    op.drop_table("access_decisions")
    op.drop_table("entity_restrictions")
