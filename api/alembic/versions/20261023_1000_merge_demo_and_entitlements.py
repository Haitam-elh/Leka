"""The demonstration and the agent entitlements, one history again.

Revision ID: c4d7e2a9f013
Revises: 8a3f5c2e9d14, 9b3e5d7c1a42
Created: 2026-10-23

LEKA-449 (workspaces.demo) and the paid agents (agent entitlements) both
followed 6e1c9a4b7d20, merged the same day: two heads, which
`alembic upgrade head` refuses. Nothing changes in the schema.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "c4d7e2a9f013"
down_revision: str | Sequence[str] | None = ("8a3f5c2e9d14", "9b3e5d7c1a42")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
