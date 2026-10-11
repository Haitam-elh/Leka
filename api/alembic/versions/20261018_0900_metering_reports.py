"""The metering reports: views over the usage ledger, across workspaces —
LEKA's to read, by its server command or SQL, never over HTTP.

Revision ID: 0a074280012e
Revises: b2aa4e15dd98
Created: 2026-10-18

LEKA-430. Each view reads usage_records (and model_calls, llm_runs) as they
are; none keeps anything. Every cost is LEKA's, in US dollars, at the rates
in force; what is not known stays NULL — never averaged as 0.

    metering_executions     each execution, its workspace, the plan it was
                            on when it ran, its month
    metering_steps          each execution's steps by purpose — an
                            intention's reading, analysis, an agent's deck
    metering_agents         by month and agent: runs, cost — avg, P50,
                            P90, P95 — retries, invalid answers
    metering_intentions     each intention's cost, end to end
    metering_intention_months  by month: intentions, their cost — avg,
                            P50, P90, P95
    metering_workspace_months  by month and workspace: its plan, executions,
                            LEKA's cost, its own model's
    metering_waste          by month and purpose: what was spent on answers
                            not asked for and on tries past the first
    metering_context        by month and purpose: tokens in a call — avg,
                            P95 — the share read from the provider's cache,
                            the context items given
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0a074280012e"
down_revision: str | None = "b2aa4e15dd98"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWS = {
    "metering_executions": """
        SELECT
            r.workspace_id,
            w.name AS workspace,
            COALESCE(p.plan, 'free') AS plan,
            (date_trunc('month', r.started_at AT TIME ZONE 'UTC'))::date AS month,
            r.execution,
            r.kind,
            r.subject,
            r.subject_version,
            r.intention_id,
            r.outcome,
            r.started_at,
            r.duration_ms,
            r.calls,
            r.failed_calls,
            r.invalid_calls,
            r.retries,
            r.fallbacks,
            r.tool_calls,
            r.unreported_calls,
            r.tokens_in,
            r.tokens_out,
            r.tokens_cached,
            r.tokens_status,
            r.llm_cost_usd,
            r.leka_cost_usd,
            r.workspace_cost_usd,
            r.cost_status
        FROM usage_records r
        JOIN workspaces w ON w.id = r.workspace_id
        LEFT JOIN LATERAL (
            SELECT wp.plan FROM workspace_plans wp
            WHERE wp.workspace_id = r.workspace_id AND wp.at <= r.started_at
            ORDER BY wp.at DESC, wp.created_at DESC
            LIMIT 1
        ) p ON true
    """,
    "metering_steps": """
        SELECT
            e.workspace_id,
            e.plan,
            e.month,
            e.execution,
            e.kind,
            e.subject,
            s.key AS purpose,
            (s.value ->> 'calls')::int AS calls,
            (s.value ->> 'failed')::int AS failed,
            (s.value ->> 'invalid')::int AS invalid,
            (s.value ->> 'retries')::int AS retries,
            (s.value ->> 'tokens_in')::bigint AS tokens_in,
            (s.value ->> 'tokens_out')::bigint AS tokens_out,
            (s.value ->> 'cost_usd')::double precision AS cost_usd,
            (s.value ->> 'unpriced')::int AS unpriced,
            (s.value ->> 'invalid_cost_usd')::double precision AS invalid_cost_usd,
            (s.value ->> 'retry_cost_usd')::double precision AS retry_cost_usd
        FROM metering_executions e
        JOIN usage_records r ON r.workspace_id = e.workspace_id AND r.execution = e.execution
        CROSS JOIN LATERAL jsonb_each(r.steps) s
    """,
    "metering_agents": """
        SELECT
            month,
            subject AS agent,
            count(*) AS runs,
            count(*) FILTER (WHERE outcome = 'succeeded') AS succeeded,
            sum(calls) AS calls,
            sum(retries) AS retries,
            sum(invalid_calls) AS invalid_calls,
            count(*) FILTER (WHERE cost_status IN ('unknown', 'partial')) AS cost_not_known,
            sum(leka_cost_usd) AS cost_usd,
            avg(leka_cost_usd) AS avg_usd,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY leka_cost_usd) AS p50_usd,
            percentile_cont(0.9) WITHIN GROUP (ORDER BY leka_cost_usd) AS p90_usd,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY leka_cost_usd) AS p95_usd,
            avg(duration_ms) AS avg_duration_ms
        FROM metering_executions
        WHERE kind = 'agent_run'
        GROUP BY month, subject
    """,
    "metering_intentions": """
        SELECT
            intention_id,
            workspace_id,
            min(plan) AS plan,
            min(month) AS month,
            count(*) AS executions,
            sum(calls) AS calls,
            sum(retries) AS retries,
            sum(leka_cost_usd) AS cost_usd,
            bool_or(cost_status IN ('unknown', 'partial')) AS cost_not_known
        FROM metering_executions
        WHERE intention_id IS NOT NULL
        GROUP BY intention_id, workspace_id
    """,
    "metering_intention_months": """
        SELECT
            month,
            count(*) AS intentions,
            count(*) FILTER (WHERE cost_not_known) AS cost_not_known,
            sum(cost_usd) AS cost_usd,
            avg(cost_usd) AS avg_usd,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY cost_usd) AS p50_usd,
            percentile_cont(0.9) WITHIN GROUP (ORDER BY cost_usd) AS p90_usd,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY cost_usd) AS p95_usd
        FROM metering_intentions
        GROUP BY month
    """,
    "metering_workspace_months": """
        SELECT
            month,
            workspace_id,
            min(workspace) AS workspace,
            (array_agg(plan ORDER BY started_at DESC))[1] AS plan,
            count(*) AS executions,
            sum(calls) AS calls,
            sum(leka_cost_usd) AS leka_cost_usd,
            sum(workspace_cost_usd) AS workspace_cost_usd,
            count(*) FILTER (WHERE cost_status IN ('unknown', 'partial')) AS cost_not_known
        FROM metering_executions
        GROUP BY month, workspace_id
    """,
    "metering_waste": """
        SELECT
            month,
            purpose,
            sum(calls) AS calls,
            sum(invalid) AS invalid,
            sum(retries) AS retries,
            sum(cost_usd) AS cost_usd,
            sum(invalid_cost_usd) AS invalid_cost_usd,
            sum(retry_cost_usd) AS retry_cost_usd,
            CASE WHEN sum(cost_usd) > 0
                THEN (sum(invalid_cost_usd) + sum(retry_cost_usd)) / sum(cost_usd)
            END AS wasted_share
        FROM metering_steps
        GROUP BY month, purpose
    """,
    "metering_context": """
        SELECT
            (date_trunc('month', c.at AT TIME ZONE 'UTC'))::date AS month,
            c.purpose,
            count(*) AS calls,
            avg(c.tokens_in) AS avg_tokens_in,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY c.tokens_in) AS p95_tokens_in,
            CASE WHEN sum(c.tokens_in) > 0
                THEN sum(c.tokens_cached)::double precision / sum(c.tokens_in)
            END AS cached_share,
            avg(r.context_items) AS avg_context_items
        FROM model_calls c
        LEFT JOIN llm_runs r ON r.id = c.run_id
        WHERE c.status <> 'failed' AND COALESCE(c.usage_reported, c.tokens_in > 0)
        GROUP BY 1, c.purpose
    """,
}

# Dropped in reverse: a view read by another goes after it.
ORDER = (
    "metering_executions",
    "metering_steps",
    "metering_agents",
    "metering_intentions",
    "metering_intention_months",
    "metering_workspace_months",
    "metering_waste",
    "metering_context",
)


def upgrade() -> None:
    for name in ORDER:
        op.execute(f"CREATE VIEW {name} AS {VIEWS[name]}")


def downgrade() -> None:
    for name in reversed(ORDER):
        op.execute(f"DROP VIEW {name}")
