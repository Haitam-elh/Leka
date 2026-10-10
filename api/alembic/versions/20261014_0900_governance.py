"""Governance of consequential actions: risk to four levels, approvals
by role, delegated and escalated, freezes and waivers, every move kept.

Revision ID: 5b8e1d4a7c26
Revises: 9e4b2d7c1a83
Created: 2026-10-14

A decision's risk is classified by the workspace's rules (LEKA-404) and may
now be critical. What the policy said of it is kept with it (`governance`):
why that risk, the role one approver must hold (`required_role`), until when
an approval holds (`valid_until`), when it was escalated (`escalated_at`). A
vote may be cast with another's authority, delegated (`on_behalf_of`), and
keeps the role of the authority used (`role`).

`governance_exceptions` — freezes and waivers an admin granted, on what,
from when to when, why; `approval_delegations` — an approver's authority
lent; `governance_events` — every change of the policy, every exception and
delegation granted or revoked, every decision escalated, waived or frozen:
append-only, the database refuses to change one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5b8e1d4a7c26"
down_revision: str | None = "9e4b2d7c1a83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RISKS = "risk IN ('low', 'medium', 'high', 'critical')"
OLD_RISKS = "risk IN ('low', 'medium', 'high')"


def upgrade() -> None:
    op.create_table(
        "approval_delegations",
        sa.Column("delegated_by", sa.UUID(), nullable=False),
        sa.Column("delegated_to", sa.UUID(), nullable=False),
        sa.Column("max_risk", sa.String(length=10), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "max_risk IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_approval_delegations_max_risk"),
        ),
        sa.CheckConstraint(
            "delegated_by <> delegated_to", name=op.f("ck_approval_delegations_not_oneself")
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_approval_delegations_window")),
        sa.ForeignKeyConstraint(
            ["delegated_by"],
            ["users.id"],
            name=op.f("fk_approval_delegations_delegated_by_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["delegated_to"],
            ["users.id"],
            name=op.f("fk_approval_delegations_delegated_to_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["users.id"],
            name=op.f("fk_approval_delegations_revoked_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_approval_delegations_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_delegations")),
    )
    op.create_index(
        "ix_approval_delegations_to",
        "approval_delegations",
        ["workspace_id", "delegated_to", "ends_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_delegations_workspace_id"),
        "approval_delegations",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "governance_events",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
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
        sa.CheckConstraint(
            "kind IN ('policy_changed', 'exception_granted', 'exception_revoked', 'delegation_granted', 'delegation_revoked', 'decision_escalated', 'decision_waived', 'decision_frozen')",
            name=op.f("ck_governance_events_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["by"], ["users.id"], name=op.f("fk_governance_events_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_governance_events_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_governance_events")),
    )
    op.create_index(
        "ix_governance_events_workspace_at",
        "governance_events",
        ["workspace_id", "at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_governance_events_workspace_id"),
        "governance_events",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "governance_exceptions",
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column(
            "actions", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "environments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "targets", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("max_risk", sa.String(length=10), server_default="low", nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "kind IN ('freeze', 'waiver')", name=op.f("ck_governance_exceptions_kind")
        ),
        sa.CheckConstraint(
            "max_risk IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_governance_exceptions_max_risk"),
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_governance_exceptions_window")),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name=op.f("fk_governance_exceptions_granted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["users.id"],
            name=op.f("fk_governance_exceptions_revoked_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_governance_exceptions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_governance_exceptions")),
    )
    op.create_index(
        "ix_governance_exceptions_live",
        "governance_exceptions",
        ["workspace_id", "ends_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_governance_exceptions_workspace_id"),
        "governance_exceptions",
        ["workspace_id"],
        unique=False,
    )
    op.add_column("intention_decision_votes", sa.Column("on_behalf_of", sa.UUID(), nullable=True))
    op.add_column(
        "intention_decision_votes", sa.Column("role", sa.String(length=10), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_intention_decision_votes_on_behalf_of_users"),
        "intention_decision_votes",
        "users",
        ["on_behalf_of"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "intention_decisions", sa.Column("required_role", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "intention_decisions",
        sa.Column(
            "governance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        "intention_decisions", sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "intention_decisions", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True)
    )

    # A decision's risk may now be critical.
    op.drop_constraint(op.f("ck_intention_decisions_risk"), "intention_decisions", type_="check")
    op.create_check_constraint(op.f("ck_intention_decisions_risk"), "intention_decisions", RISKS)

    # What happened to the governance is never changed.
    op.execute(
        """
        CREATE FUNCTION governance_events_append_only() RETURNS trigger AS $$
        BEGIN
            -- Who did it, forgotten when their account is deleted: nothing else.
            IF NEW."by" IS NULL AND to_jsonb(NEW) - 'by' = to_jsonb(OLD) - 'by' THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'governance_events is append-only: what happened is never changed'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER governance_events_append_only
        BEFORE UPDATE ON governance_events
        FOR EACH ROW EXECUTE FUNCTION governance_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER governance_events_append_only ON governance_events")
    op.execute("DROP FUNCTION governance_events_append_only()")
    # Critical was high before.
    op.execute("UPDATE intention_decisions SET risk = 'high' WHERE risk = 'critical'")
    op.drop_constraint(op.f("ck_intention_decisions_risk"), "intention_decisions", type_="check")
    op.create_check_constraint(
        op.f("ck_intention_decisions_risk"), "intention_decisions", OLD_RISKS
    )
    op.drop_column("intention_decisions", "escalated_at")
    op.drop_column("intention_decisions", "valid_until")
    op.drop_column("intention_decisions", "governance")
    op.drop_column("intention_decisions", "required_role")
    op.drop_constraint(
        op.f("fk_intention_decision_votes_on_behalf_of_users"),
        "intention_decision_votes",
        type_="foreignkey",
    )
    op.drop_column("intention_decision_votes", "role")
    op.drop_column("intention_decision_votes", "on_behalf_of")
    op.drop_index(op.f("ix_governance_exceptions_workspace_id"), table_name="governance_exceptions")
    op.drop_index("ix_governance_exceptions_live", table_name="governance_exceptions")
    op.drop_table("governance_exceptions")
    op.drop_index(op.f("ix_governance_events_workspace_id"), table_name="governance_events")
    op.drop_index("ix_governance_events_workspace_at", table_name="governance_events")
    op.drop_table("governance_events")
    op.drop_index(op.f("ix_approval_delegations_workspace_id"), table_name="approval_delegations")
    op.drop_index("ix_approval_delegations_to", table_name="approval_delegations")
    op.drop_table("approval_delegations")
