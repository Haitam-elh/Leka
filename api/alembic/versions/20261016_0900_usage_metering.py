"""Usage and cost metering: the rates models cost LEKA, what each call
used — or that it is not known — and the usage ledger.

Revision ID: b939e6b4cd71
Revises: 8d3f6b2a9c51
Created: 2026-10-16

LEKA-430. `model_rates`: what a model costs from a day on, per million
tokens — a new price is a new row; a rate is never rewritten (the database
refuses it), so what was priced with it can be priced again. Seeded with
the list prices of capabilities/gateway/profiles.py as they stand.
`model_calls.usage_reported`: whether the provider said what the call used
— none for the calls kept before (not known); `model_calls.rate_id`: the
rate it was priced with. `usage_records`: one row per execution, derived
from the calls and the runs (leka/metering).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b939e6b4cd71"
down_revision: str | None = "8d3f6b2a9c51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# profiles.py on 2026-10-16: provider, model, since, in, out, cached — and
# where the price was read.
GOOGLE = "ai.google.dev/gemini-api/docs/pricing, read 2026-10-09"
RATES = (
    ("google", "gemini-3.8-flash", "2025-01-01", 0.75, 3.75, 0.075, GOOGLE),
    ("google", "gemini-3.8-flash", "2027-01-01", 1.50, 7.50, 0.15, GOOGLE),
    ("mistral", "mistral-large-latest", "2025-01-01", 0.5, 1.5, None, "list price"),
    ("anthropic", "claude-sonnet-5", "2025-01-01", 2.0, 10.0, None, "list price"),
    ("anthropic", "claude-haiku-4-5", "2025-01-01", 1.0, 5.0, None, "list price"),
)

KINDS = "'agent_run', 'workflow_run', 'intention', 'llm_run', 'work'"
TOKENS = "'measured', 'partial', 'unknown', 'none'"
COSTS = "'estimated', 'partial', 'unknown', 'none'"


def _stamps() -> list[sa.Column[object]]:
    return [
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
    rates = op.create_table(
        "model_rates",
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("since", sa.Date(), nullable=False),
        sa.Column("per_million_in", sa.Float(), nullable=False),
        sa.Column("per_million_out", sa.Float(), nullable=False),
        sa.Column("per_million_cached", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=300), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        *_stamps(),
        sa.CheckConstraint(
            "per_million_in >= 0 AND per_million_out >= 0"
            " AND (per_million_cached IS NULL OR per_million_cached >= 0)",
            name=op.f("ck_model_rates_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_rates")),
        sa.UniqueConstraint(
            "provider", "model", "since", name="uq_model_rates_provider_model_since"
        ),
    )
    op.execute(
        """
        CREATE FUNCTION model_rates_never_rewritten() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'model_rates: a rate is never rewritten — add one from its day'
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER model_rates_never_rewritten
        BEFORE UPDATE ON model_rates
        FOR EACH ROW EXECUTE FUNCTION model_rates_never_rewritten()
        """
    )
    op.bulk_insert(
        rates,
        [
            {
                "provider": provider,
                "model": model,
                "since": date.fromisoformat(since),
                "per_million_in": per_in,
                "per_million_out": per_out,
                "per_million_cached": cached,
                "source": source,
            }
            for provider, model, since, per_in, per_out, cached, source in RATES
        ],
    )

    op.add_column("model_calls", sa.Column("usage_reported", sa.Boolean(), nullable=True))
    op.add_column("model_calls", sa.Column("rate_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_model_calls_rate_id_model_rates"),
        "model_calls",
        "model_rates",
        ["rate_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_model_calls_rate_id", "model_calls", ["rate_id"])
    # The ledger reads an execution's calls by what they are about.
    op.create_index("ix_model_calls_workspace_ref", "model_calls", ["workspace_id", "ref"])

    op.create_table(
        "usage_records",
        sa.Column("execution", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("intention_id", sa.UUID(), nullable=True),
        sa.Column("subject", sa.String(length=100), nullable=False),
        sa.Column("subject_version", sa.String(length=20), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("failed_calls", sa.Integer(), nullable=False),
        sa.Column("invalid_calls", sa.Integer(), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("fallbacks", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("unreported_calls", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.BigInteger(), nullable=True),
        sa.Column("tokens_out", sa.BigInteger(), nullable=True),
        sa.Column("tokens_thinking", sa.BigInteger(), nullable=True),
        sa.Column("tokens_cached", sa.BigInteger(), nullable=True),
        sa.Column("tokens_status", sa.String(length=10), nullable=False),
        sa.Column("llm_cost_usd", sa.Float(), nullable=True),
        sa.Column("leka_cost_usd", sa.Float(), nullable=True),
        sa.Column("workspace_cost_usd", sa.Float(), nullable=True),
        sa.Column("cost_status", sa.String(length=10), nullable=False),
        sa.Column("embedding_cost", sa.String(length=16), nullable=False),
        sa.Column("tool_cost", sa.String(length=16), nullable=False),
        sa.Column("infra_cost", sa.String(length=16), nullable=False),
        sa.Column(
            "models", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "rates", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "steps", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("metered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        *_stamps(),
        sa.CheckConstraint(f"kind IN ({KINDS})", name=op.f("ck_usage_records_kind")),
        sa.CheckConstraint(
            f"tokens_status IN ({TOKENS})", name=op.f("ck_usage_records_tokens_status")
        ),
        sa.CheckConstraint(f"cost_status IN ({COSTS})", name=op.f("ck_usage_records_cost_status")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_usage_records_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_usage_records_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
        sa.UniqueConstraint("workspace_id", "execution", name="uq_usage_records_execution"),
    )
    op.create_index(op.f("ix_usage_records_workspace_id"), "usage_records", ["workspace_id"])
    op.create_index(
        "ix_usage_records_workspace_started", "usage_records", ["workspace_id", "started_at"]
    )
    op.create_index(
        "ix_usage_records_workspace_intention", "usage_records", ["workspace_id", "intention_id"]
    )
    op.create_index("ix_usage_records_user_id", "usage_records", ["user_id"])


def downgrade() -> None:
    op.drop_table("usage_records")
    op.drop_index("ix_model_calls_workspace_ref", table_name="model_calls")
    op.drop_index("ix_model_calls_rate_id", table_name="model_calls")
    op.drop_constraint(
        op.f("fk_model_calls_rate_id_model_rates"), "model_calls", type_="foreignkey"
    )
    op.drop_column("model_calls", "rate_id")
    op.drop_column("model_calls", "usage_reported")
    op.execute("DROP TRIGGER model_rates_never_rewritten ON model_rates")
    op.execute("DROP FUNCTION model_rates_never_rewritten()")
    op.drop_table("model_rates")
