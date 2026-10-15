"""The agents a workspace may run, and the Checkouts opened to buy one.

Revision ID: 8a3f5c2e9d14
Revises: 6e1c9a4b7d20
Created: 2026-10-23

The product call of 2026-10-14: a workspace on Free runs no agent, and
others run the agents they bought, alone or in a bundle.

- `agent_entitlements`: an agent, a bundle, or every one (`*`, `all`),
  bought (`purchase`, its Stripe subscription) or granted by LEKA
  (`grant`); `active` until ended, never deleted.
- `add_on_checkouts`: a Checkout opened for an agent or a bundle, and the
  agents to launch on an intention once it is paid.

The workspaces on a paid plan as this runs are LEKA's team's, its plans set
by hand for tests: each is granted every agent, said why.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8a3f5c2e9d14"
down_revision: str | None = "6e1c9a4b7d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column[object]]:
    return [
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


def upgrade() -> None:
    op.create_table(
        "agent_entitlements",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("stripe_subscription_id", sa.String(length=100), nullable=True),
        sa.Column("by_whom", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        *_stamps(),
        sa.CheckConstraint(
            "kind IN ('agent', 'bundle', 'all')", name=op.f("ck_agent_entitlements_kind")
        ),
        sa.CheckConstraint(
            "origin IN ('purchase', 'grant')", name=op.f("ck_agent_entitlements_origin")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'ended')", name=op.f("ck_agent_entitlements_status")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_entitlements_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_entitlements")),
    )
    op.create_index(
        op.f("ix_agent_entitlements_workspace_id"), "agent_entitlements", ["workspace_id"]
    )
    op.create_index(
        "ix_agent_entitlements_workspace_status", "agent_entitlements", ["workspace_id", "status"]
    )
    op.create_table(
        "add_on_checkouts",
        sa.Column("stripe_session_id", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="open", nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("intention_id", sa.UUID(), nullable=True),
        sa.Column(
            "launch",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        *_stamps(),
        sa.CheckConstraint("kind IN ('agent', 'bundle')", name=op.f("ck_add_on_checkouts_kind")),
        sa.CheckConstraint(
            "status IN ('open', 'paid', 'expired')", name=op.f("ck_add_on_checkouts_status")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_add_on_checkouts_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_add_on_checkouts")),
        sa.UniqueConstraint("stripe_session_id", name="uq_add_on_checkouts_session"),
    )
    op.create_index(op.f("ix_add_on_checkouts_workspace_id"), "add_on_checkouts", ["workspace_id"])
    # LEKA's team's workspaces, on a paid plan set by hand for tests: every
    # agent, kept (decided 2026-10-14).
    op.execute(
        """
        INSERT INTO agent_entitlements
            (workspace_id, key, kind, origin, status, by_whom, reason, started_at)
        SELECT p.workspace_id, '*', 'all', 'grant', 'active', 'migration',
               'LEKA team workspace, kept for tests (2026-10-14)', now()
          FROM (
              SELECT DISTINCT ON (workspace_id) workspace_id, plan
                FROM workspace_plans
               ORDER BY workspace_id, at DESC, created_at DESC
          ) AS p
         WHERE p.plan IN ('growth', 'business', 'enterprise')
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_add_on_checkouts_workspace_id"), table_name="add_on_checkouts")
    op.drop_table("add_on_checkouts")
    op.drop_index("ix_agent_entitlements_workspace_status", table_name="agent_entitlements")
    op.drop_index(op.f("ix_agent_entitlements_workspace_id"), table_name="agent_entitlements")
    op.drop_table("agent_entitlements")
