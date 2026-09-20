"""Workspace lifecycle, settings, and invitations.

Revision ID: a7f3c1e9b204
Revises: 003
Created: 2026-09-20

LEKA-331. Three things:

**Workspace lifecycle.** A workspace is active, suspended or awaiting
deletion. Suspended means reads work and writes do not — an unpaid invoice
must not look like a bug. pending_deletion means no access at all, during a
grace period in which a customer who changed their mind loses nothing. These
states are enforced in one place, the dependency that resolves the request
principal, never route by route.

**Workspace settings.** JSONB rather than a column per preference: this list
grows with the product, and a migration per preference is a tax we would pay
forever.

**Invitations.** An offer of a seat, sent to an email address. The token is
stored hashed — whoever holds one joins a customer's workspace, so it is a
credential, and a leaked backup must not be a set of usable invitations.

The revision id is a random hex string rather than "004" on purpose: LEKA-330
is writing a migration in parallel, and two migrations both called 004 give
Alembic a forked history.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7f3c1e9b204"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


WORKSPACE_STATUSES = ("active", "suspended", "pending_deletion")
INVITATION_STATUSES = ("pending", "accepted", "revoked")
ROLES = ("owner", "admin", "member")


def _check(column: str, values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})"


def upgrade() -> None:
    # ── workspaces: lifecycle and settings ───────────────────────────────────
    op.add_column(
        "workspaces",
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="active",
        ),
    )
    op.create_check_constraint("status", "workspaces", _check("status", WORKSPACE_STATUSES))
    op.add_column(
        "workspaces",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )

    # ── invitations ──────────────────────────────────────────────────────────
    op.create_table(
        "invitations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        # sha256 of the token we emailed. The clear value exists only in the
        # invitee's inbox.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_invitations"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_invitations_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        # The inviter is kept for the audit trail; removing them must not
        # erase the record that the invitation happened.
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name="fk_invitations_invited_by_user_id_users",
            ondelete="SET NULL",
        ),
        # One live invitation per address per workspace: re-inviting replaces
        # rather than accumulating, so revoking one does not leave three.
        sa.UniqueConstraint("workspace_id", "email", name="uq_invitations_workspace_email"),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
        sa.CheckConstraint(_check("role", ROLES), name="ck_invitations_role"),
        sa.CheckConstraint(_check("status", INVITATION_STATUSES), name="ck_invitations_status"),
    )
    op.create_index("ix_invitations_workspace_id", "invitations", ["workspace_id"])
    # Accepting an invitation looks it up by the hash of the token presented.
    op.create_index("ix_invitations_token_hash", "invitations", ["token_hash"])


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_constraint("ck_workspaces_status", "workspaces", type_="check")
    op.drop_column("workspaces", "settings")
    op.drop_column("workspaces", "deletion_requested_at")
    op.drop_column("workspaces", "suspended_at")
    op.drop_column("workspaces", "status")
