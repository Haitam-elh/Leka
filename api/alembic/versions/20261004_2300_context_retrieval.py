"""Context retrieval: what each retriever did, and the records' words.

Revision ID: f6f99d6d6f4a
Revises: 40c229408919
Created: 2026-10-04

LEKA-371. A context's version says what each retriever did — found how
much, in how long, or failed, timed out, was skipped, and why
(`context_versions.retrieval`; the versions before it, none). And the
records' own text — a page's body, a ticket's description — is searched by
its words: a GIN index on the extracted records' title and texts, as
PostgreSQL's full-text search reads them ('simple', the first 100 000
characters), the extracted ones only. The expression is the one in
leka/ingestion/models.py (CONTENT_WORDS), word for word, or the index is
not used.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f6f99d6d6f4a"
down_revision: str | None = "40c229408919"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTENT_WORDS = (
    "to_tsvector('simple'::regconfig, \"left\"((COALESCE(result ->> 'title'::text, ''::text) "
    "|| ' '::text) || COALESCE(jsonb_path_query_array(result, "
    "'$.\"content\"[*].\"text\"'::jsonpath) #>> '{}'::text[], ''::text), 100000))"
)


def upgrade() -> None:
    op.add_column(
        "context_versions",
        sa.Column(
            "retrieval",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_extracted_records_words",
        "extracted_records",
        [sa.literal_column(CONTENT_WORDS)],
        postgresql_using="gin",
        postgresql_where=sa.text("status = 'extracted'"),
    )


def downgrade() -> None:
    op.drop_index("ix_extracted_records_words", table_name="extracted_records")
    op.drop_column("context_versions", "retrieval")
