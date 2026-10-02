"""Search over the company model: each entity's words, indexed.

Revision ID: 6f1a8c3d2b57
Revises: 3c7e9b1d5f24
Created: 2026-10-02

LEKA-369. An entity carries what search reads: its names (`search_name`)
and what else says what it is (`search_text`), folded at each build
(leka/knowledge/search.py), and their words as a tsvector computed by
PostgreSQL — the names weighted A — under a GIN index. Until the next build
writes them folded, the existing rows read their name and key in lower
case: the new MODEL_VERSION makes the hourly sweep rebuild every model.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "6f1a8c3d2b57"
down_revision: str | None = "3c7e9b1d5f24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_VECTOR = (
    "(setweight(to_tsvector('simple'::regconfig, search_name), 'A'::\"char\") || "
    "setweight(to_tsvector('simple'::regconfig, search_text), 'B'::\"char\"))"
)


def upgrade() -> None:
    for column in ("search_name", "search_text"):
        op.add_column(
            "entities",
            sa.Column(column, sa.Text(), server_default="", nullable=False),
        )
    op.execute("UPDATE entities SET search_name = lower(name), search_text = lower(key)")
    op.add_column(
        "entities",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_entities_search",
        "entities",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_entities_search", table_name="entities", postgresql_using="gin")
    op.drop_column("entities", "search_vector")
    op.drop_column("entities", "search_text")
    op.drop_column("entities", "search_name")
