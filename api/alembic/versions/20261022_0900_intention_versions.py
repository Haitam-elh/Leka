"""An intention's versions, the request it came from, an analysis stopped.

Revision ID: 6e1c9a4b7d20
Revises: 3dee77e03bf8
Created: 2026-10-22

LEKA-443:
- `intentions.version`: 1 as asked, one more each time it was asked again
  (its words, scope or answers). An intention that exists counts the times
  its history says a person asked it again.
- `intentions.request_key`: the Idempotency-Key its request came with, unique
  per asker, so the same request sent twice is one intention.
- `intention_analyses.intention_version`: the version it analysed. An analysis
  that exists analysed the version it was in when it started.
- `intention_analyses.status` may be `stopped`: a person stopped it while it
  ran.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6e1c9a4b7d20"
down_revision: str | None = "3dee77e03bf8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "status IN ('running', 'complete', 'partial', 'inconclusive', 'failed', 'blocked'{})"


def upgrade() -> None:
    op.add_column(
        "intentions", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("intentions", sa.Column("request_key", sa.String(length=100), nullable=True))
    op.create_index(
        "uq_intentions_request_key",
        "intentions",
        ["workspace_id", "created_by", "request_key"],
        unique=True,
        postgresql_where=sa.text("request_key IS NOT NULL"),
    )
    op.add_column("intention_analyses", sa.Column("intention_version", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE intentions i SET version = 1 + (
            SELECT count(*) FROM intention_events e
            WHERE e.intention_id = i.id AND e.kind = 'moved'
              AND e.name IN ('asked_again', 'clarified')
        )
        """
    )
    op.execute(
        """
        UPDATE intention_analyses a SET intention_version = 1 + (
            SELECT count(*) FROM intention_events e
            WHERE e.intention_id = a.intention_id AND e.kind = 'moved'
              AND e.name IN ('asked_again', 'clarified') AND e.at <= a.started_at
        )
        """
    )
    op.drop_constraint(op.f("ck_intention_analyses_status"), "intention_analyses", type_="check")
    op.create_check_constraint(
        op.f("ck_intention_analyses_status"), "intention_analyses", STATUSES.format(", 'stopped'")
    )


def downgrade() -> None:
    # A stopped analysis was, before, one that did not finish.
    op.execute("UPDATE intention_analyses SET status = 'failed' WHERE status = 'stopped'")
    op.drop_constraint(op.f("ck_intention_analyses_status"), "intention_analyses", type_="check")
    op.create_check_constraint(
        op.f("ck_intention_analyses_status"), "intention_analyses", STATUSES.format("")
    )
    op.drop_column("intention_analyses", "intention_version")
    op.drop_index("uq_intentions_request_key", table_name="intentions")
    op.drop_column("intentions", "request_key")
    op.drop_column("intentions", "version")
