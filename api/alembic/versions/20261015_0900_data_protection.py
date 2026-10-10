"""Data protection: what each extracted record carried, and the protection
policy in the governance trail.

Revision ID: 8d3f6b2e9a41
Revises: 8d3f6b2a9c51
Created: 2026-10-15

An extracted record is protected before it is kept (LEKA-405): a secret or
an identity number in it is replaced, and `sensitivity` says what was found
— kinds and counts, never a value — with the detector's version. Records
kept before are scanned by the protection sweep, which finds them through
`ix_extracted_records_unscanned`. A change to a workspace's data protection
policy joins its governance trail (`subject_type` protection).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8d3f6b2e9a41"
down_revision: str | None = "8d3f6b2a9c51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extracted_records",
        sa.Column("sensitivity", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_extracted_records_unscanned",
        "extracted_records",
        ["workspace_id"],
        unique=False,
        postgresql_where=sa.text("status = 'extracted' AND sensitivity IS NULL"),
    )
    op.drop_constraint(
        op.f("ck_governance_events_subject_type"), "governance_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_governance_events_subject_type"),
        "governance_events",
        "subject_type IN ('role', 'policy', 'assignment', 'ai_control', 'protection')",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE governance_events DISABLE TRIGGER USER")
    op.execute("DELETE FROM governance_events WHERE subject_type = 'protection'")
    op.execute("ALTER TABLE governance_events ENABLE TRIGGER USER")
    op.drop_constraint(
        op.f("ck_governance_events_subject_type"), "governance_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_governance_events_subject_type"),
        "governance_events",
        "subject_type IN ('role', 'policy', 'assignment', 'ai_control')",
    )
    op.drop_index(
        "ix_extracted_records_unscanned",
        table_name="extracted_records",
        postgresql_where=sa.text("status = 'extracted' AND sensitivity IS NULL"),
    )
    op.drop_column("extracted_records", "sensitivity")
