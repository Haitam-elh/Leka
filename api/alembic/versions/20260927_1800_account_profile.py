"""Account profile: who registered, as they said it.

Revision ID: 3f7a9c1d2e84
Revises: 3f7a9c2d5e18
Created: 2026-09-27

Registration now happens on leka-core.com, and asks what the site's forms
have always asked: first and last name, company, and — if they want to
say — role and company size. Five nullable columns on `users`: the
accounts made before stay as they are, and nothing about signing in
depends on them.

`company_size` is a closed set, checked by the database like every other
(ADR 006).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3f7a9c1d2e84"
down_revision: str | None = "3f7a9c2d5e18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIZES = ("1-10", "11-50", "51-200", "201-1000", "1000+")


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("company", sa.String(length=200), nullable=True))
    op.add_column("users", sa.Column("job_title", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("company_size", sa.String(length=20), nullable=True))
    # The naming convention makes it ck_users_company_size.
    op.create_check_constraint(
        "company_size",
        "users",
        "company_size IN (" + ", ".join(f"'{size}'" for size in SIZES) + ")",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_company_size"), "users", type_="check")
    op.drop_column("users", "company_size")
    op.drop_column("users", "job_title")
    op.drop_column("users", "company")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
