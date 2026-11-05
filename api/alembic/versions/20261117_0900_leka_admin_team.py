"""LEKA ADMIN's team: invitations, forgotten passwords, roles the Super Admin sets.

Revision ID: 4d8f2a6c9e13
Revises: 9b2e4c7a1f08
Created: 2026-11-05

LEKA-545. An admin can be invited (`status` 'invited', no password until
they choose it with the code sent to them); `admin_codes` keeps those codes
and the ones sent for a forgotten password, hashed and single-use;
`admin_role_permissions` keeps what each role may do, as the Super Admin
sets it, starting from the defaults of leka/admin/access.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4d8f2a6c9e13"
down_revision: str | None = "9b2e4c7a1f08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_role_permissions",
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("permission", sa.String(length=40), nullable=False),
        sa.Column("granted_by", sa.String(length=320), nullable=False),
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
            "role IN ('super_admin', 'operations', 'support', 'finance')",
            name=op.f("ck_admin_role_permissions_role"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_role_permissions")),
        sa.UniqueConstraint("role", "permission", name="uq_admin_role_permissions_role_permission"),
    )
    op.create_table(
        "admin_codes",
        sa.Column("admin_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(length=10), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("purpose IN ('invite', 'reset')", name=op.f("ck_admin_codes_purpose")),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_accounts.id"],
            name=op.f("fk_admin_codes_admin_id_admin_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_codes")),
    )
    op.create_index(op.f("ix_admin_codes_admin_id"), "admin_codes", ["admin_id"], unique=False)
    op.alter_column(
        "admin_accounts", "password_hash", existing_type=sa.VARCHAR(length=255), nullable=True
    )

    op.drop_constraint(op.f("ck_admin_accounts_status"), "admin_accounts", type_="check")
    op.create_check_constraint(
        op.f("ck_admin_accounts_status"),
        "admin_accounts",
        "status IN ('invited', 'active', 'disabled')",
    )
    # What each role may do to start with: leka/admin/access.py
    # ROLE_PERMISSIONS, written down here as it stood (a migration never
    # reads code that may change after it).
    table = sa.table(
        "admin_role_permissions",
        sa.column("id", sa.UUID()),
        sa.column("role", sa.String()),
        sa.column("permission", sa.String()),
        sa.column("granted_by", sa.String()),
    )
    common = ["dashboard:read", "organisations:read", "users:read", "activity:read"]
    defaults = {
        "operations": [
            *common,
            "organisations:write",
            "intentions:read",
            "agents:read",
            "credits:read",
            "environments:read",
        ],
        "support": [
            *common,
            "intentions:read",
            "intentions:content",
            "agents:read",
            "credits:read",
            "environments:read",
        ],
        "finance": [*common, "agents:read", "credits:read", "credits:write", "billing:read"],
    }
    op.bulk_insert(
        table,
        [
            {"id": uuid.uuid4(), "role": role, "permission": permission, "granted_by": "LEKA-545"}
            for role, permissions in defaults.items()
            for permission in permissions
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM admin_accounts WHERE status = 'invited'")
    op.drop_constraint(op.f("ck_admin_accounts_status"), "admin_accounts", type_="check")
    op.create_check_constraint(
        op.f("ck_admin_accounts_status"), "admin_accounts", "status IN ('active', 'disabled')"
    )
    op.alter_column(
        "admin_accounts", "password_hash", existing_type=sa.VARCHAR(length=255), nullable=False
    )
    op.drop_index(op.f("ix_admin_codes_admin_id"), table_name="admin_codes")
    op.drop_table("admin_codes")
    op.drop_table("admin_role_permissions")
