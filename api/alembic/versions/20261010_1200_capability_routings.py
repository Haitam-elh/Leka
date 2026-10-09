"""Capability router: where each intention was routed, and why.

Revision ID: 4d9c2b7e6a15
Revises: 8b4e2f7a1c93
Created: 2026-10-10

LEKA-398. A routing (`capability_routings`): an intention, or words asked of
the router alone; what the router read of it; the outcome — routed,
fallback, clarify — what it selected; every candidate with its signals and
score, every one left out with why. Routed again, a new row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4d9c2b7e6a15"
down_revision: str | None = "8b4e2f7a1c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "capability_routings",
        sa.Column("subject_type", sa.String(length=10), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=10), nullable=False),
        _jsonb("selected", "[]"),
        _jsonb("query", "{}"),
        _jsonb("decision", "{}"),
        sa.Column("routed_by", sa.UUID(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
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
            "outcome IN ('routed', 'fallback', 'clarify')",
            name=op.f("ck_capability_routings_outcome"),
        ),
        sa.CheckConstraint(
            "subject_type IN ('intention', 'request')",
            name=op.f("ck_capability_routings_subject_type"),
        ),
        sa.ForeignKeyConstraint(
            ["routed_by"],
            ["users.id"],
            name=op.f("fk_capability_routings_routed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_capability_routings_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capability_routings")),
    )
    op.create_index(
        "ix_capability_routings_subject",
        "capability_routings",
        ["workspace_id", "subject_id", "at"],
    )
    op.create_index(
        op.f("ix_capability_routings_workspace_id"), "capability_routings", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_table("capability_routings")
