"""Authentication: password hashes, sessions, and one-time email tokens.

Revision ID: c4d81b6f2e70
Revises: a7f3c1e9b204
Created: 2026-09-20

LEKA-330. Three things.

**users gains the columns that let a person sign in.** password_hash is
nullable on purpose: NULL means "this account cannot sign in with a
password" — someone who accepted an invitation before choosing one, or later
an SSO account. Forcing NOT NULL would mean inventing a hash that must never
verify, which is a landmine.

**sessions.** Opaque and server-side: the browser holds a random token, this
table holds its hash. No JWT — a JWT cannot be revoked, and LEKA-331 requires
that removing someone's membership cuts their access immediately. See
docs/adr/008-opaque-sessions.md.

active_workspace_id is what makes LEKA-331's workspace switching work, and
why the workspace never travels in a header. ON DELETE SET NULL: deleting a
workspace must not delete the sessions of people who were looking at it.

**email_tokens.** Verification and reset share a table because they share
every rule: hashed at rest, single use, time limited, and consumed rather
than deleted so a replay can be told apart from a token that never existed.

None of these tables carries workspace_id. They belong to a person, not to a
tenant — the same reason users does not. tests/test_tenant_isolation.py
records that exemption with its justification.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4d81b6f2e70"
down_revision: str | None = "a7f3c1e9b204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOKEN_PURPOSES = ("verification", "reset")


def upgrade() -> None:
    # ── users: the columns that make signing in possible ─────────────────────
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    # Counted for observability only. Never used to lock an account: locking
    # after N failures lets anyone who knows an email address deny that person
    # access. Rate limiting handles abuse.
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
    )

    # ── sessions ─────────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # sha256 of the token in the cookie. The clear value exists only in
        # the browser.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("active_workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Two limits, not one: expires_at is the absolute maximum, and
        # last_seen_at drives the idle timeout.
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        # Truncated before storage — /24 for IPv4, /48 for IPv6. A full
        # address is personal data and we have no use for one.
        sa.Column("ip_prefix", sa.String(length=45), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["active_workspace_id"],
            ["workspaces.id"],
            name="fk_sessions_active_workspace_id_workspaces",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    # The cleanup job sweeps by expiry.
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    # ── email_tokens ─────────────────────────────────────────────────────────
    op.create_table(
        "email_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_email_tokens"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_email_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_email_tokens_token_hash"),
        # text + CHECK, never a PostgreSQL ENUM — docs/adr/006-enum-storage.md.
        sa.CheckConstraint("purpose IN ('verification', 'reset')", name="ck_email_tokens_purpose"),
    )
    op.create_index("ix_email_tokens_user_id", "email_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("email_tokens")
    op.drop_table("sessions")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "password_hash")
