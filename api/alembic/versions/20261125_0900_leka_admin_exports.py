"""The exports of LEKA ADMIN's lists: their permission.

Revision ID: 1cc8d1da702c
Revises: b1323b797096
Created: 2026-11-07

LEKA-557. `exports:create` takes a list away as a CSV file, as filtered, on
top of reading that list: granted to Operations and Finance as the roles
stand (the Super Admin may grant it to Support, or take it back). Nothing
else is kept: each export is a row of the admin trail (`admin.exported`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1cc8d1da702c"
down_revision: str | None = "b1323b797096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPORTS = "exports:create"
GRANTS = [("operations", EXPORTS), ("finance", EXPORTS)]


def upgrade() -> None:
    table = sa.table(
        "admin_role_permissions",
        sa.column("id", sa.UUID()),
        sa.column("role", sa.String()),
        sa.column("permission", sa.String()),
        sa.column("granted_by", sa.String()),
    )
    op.bulk_insert(
        table,
        [
            {"id": uuid.uuid4(), "role": role, "permission": permission, "granted_by": "LEKA-557"}
            for role, permission in GRANTS
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM admin_role_permissions WHERE permission = :exports").bindparams(
            exports=EXPORTS
        )
    )
