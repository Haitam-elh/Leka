"""Intention decisions: what people decided on what an intention asks to do.

Revision ID: 7a3d9e1c5b42
Revises: 5e7b2c9d4a61
Created: 2026-10-08

LEKA-390. A decision per proposal (`intention_decisions`): the actions
proposed, the risk, how many must approve under the policy in force, where
it stands. Every vote kept (`intention_decision_votes`): who, when, why,
on which revision, in which context — append-only, the database refusing
to change one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7a3d9e1c5b42"
down_revision: str | None = "5e7b2c9d4a61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "status IN ('proposed', 'approved', 'rejected', 'changes_requested', 'superseded')"
RISKS = "risk IN ('low', 'medium', 'high')"
VERDICTS = "verdict IN ('approve', 'reject', 'modify', 'request_changes')"


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False
    )


def _scoped(table: str) -> list[sa.SchemaItem]:
    """What every workspace-scoped table has: its workspace, id, times."""
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
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(f"fk_{table}_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    op.create_table(
        "intention_decisions",
        sa.Column("intention_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=True),
        sa.Column("context_version", sa.Integer(), nullable=True),
        sa.Column("asked_by", sa.UUID(), nullable=True),
        sa.Column("analysis_risk", sa.String(length=10), nullable=True),
        sa.Column("risk", sa.String(length=10), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column("separate_asker", sa.Boolean(), server_default="false", nullable=False),
        _jsonb("policy", "{}"),
        _jsonb("proposals", "[]"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        _jsonb("detail", "{}"),
        *_scoped("intention_decisions"),
        sa.CheckConstraint(STATUSES, name=op.f("ck_intention_decisions_status")),
        sa.CheckConstraint(RISKS, name=op.f("ck_intention_decisions_risk")),
        sa.CheckConstraint(
            "required_approvals BETWEEN 1 AND 5",
            name=op.f("ck_intention_decisions_required_approvals"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "intention_id"],
            ["intentions.workspace_id", "intentions.id"],
            name="fk_intention_decisions_intention",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asked_by"],
            ["users.id"],
            name=op.f("fk_intention_decisions_asked_by_users"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_intention_decisions_workspace_id_id"),
        sa.UniqueConstraint("intention_id", "number", name="uq_intention_decisions_number"),
    )
    op.create_index(
        op.f("ix_intention_decisions_workspace_id"), "intention_decisions", ["workspace_id"]
    )
    op.create_index(
        "ix_intention_decisions_intention", "intention_decisions", ["intention_id", "number"]
    )
    op.create_index(
        "ix_intention_decisions_queue",
        "intention_decisions",
        ["workspace_id", "status", "created_at"],
    )

    op.create_table(
        "intention_decision_votes",
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        _jsonb("changes", "{}"),
        _jsonb("context", "{}"),
        *_scoped("intention_decision_votes"),
        sa.CheckConstraint(VERDICTS, name=op.f("ck_intention_decision_votes_verdict")),
        sa.ForeignKeyConstraint(
            ["workspace_id", "decision_id"],
            ["intention_decisions.workspace_id", "intention_decisions.id"],
            name="fk_intention_decision_votes_decision",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["by"],
            ["users.id"],
            name=op.f("fk_intention_decision_votes_by_users"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        op.f("ix_intention_decision_votes_workspace_id"),
        "intention_decision_votes",
        ["workspace_id"],
    )
    op.create_index(
        "ix_intention_decision_votes_decision", "intention_decision_votes", ["decision_id", "at"]
    )

    # A vote is never changed, as an intention's event is not (LEKA-384):
    # the one change allowed is who cast it forgotten, with the user.
    op.execute(
        """
        CREATE FUNCTION intention_decision_votes_append_only() RETURNS trigger AS $$
        BEGIN
            IF NEW."by" IS NULL AND to_jsonb(NEW) - 'by' = to_jsonb(OLD) - 'by' THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'intention_decision_votes is append-only: a vote is never changed'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER intention_decision_votes_append_only
        BEFORE UPDATE ON intention_decision_votes
        FOR EACH ROW EXECUTE FUNCTION intention_decision_votes_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER intention_decision_votes_append_only ON intention_decision_votes")
    op.execute("DROP FUNCTION intention_decision_votes_append_only()")
    op.drop_table("intention_decision_votes")
    op.drop_table("intention_decisions")
