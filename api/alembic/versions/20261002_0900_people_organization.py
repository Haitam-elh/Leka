"""People and teams: who reports to whom, and what each works on.

Revision ID: 2f7d9b4c6e15
Revises: 9c4e2b7a1d38
Created: 2026-10-02

LEKA-365. The company model gains two relationships: `reports_to`, a
person to their manager, and `contributes_to`, a person to what their work
shows they know. The relationship type CHECK takes them
(docs/adr/006-enum-storage.md). People and teams are kinds already.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "2f7d9b4c6e15"
down_revision: str | None = "9c4e2b7a1d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RELATIONSHIP_TYPES = (
    "depends_on",
    "owns",
    "deployed_to",
    "mentions",
    "caused_by",
    "member_of",
    "part_of",
    "owned_by",
    "maintained_by",
    "authored_by",
    "assigned_to",
    "reviewed_by",
    "reported_by",
    "led_by",
    "affects",
    "resolves",
    "implements",
    "merges",
    "child_of",
    "in_network",
    "runs_in",
    "references",
    "reads_from",
)
NEW_RELATIONSHIP_TYPES = ("reports_to", "contributes_to")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _retype(values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_relationships_type"), "relationships", type_="check")
    op.create_check_constraint(
        op.f("ck_relationships_type"), "relationships", _one_of("type", values)
    )


def upgrade() -> None:
    _retype((*RELATIONSHIP_TYPES, *NEW_RELATIONSHIP_TYPES))


def downgrade() -> None:
    # What the new relationships made goes: the old constraint could not hold it.
    op.execute("DELETE FROM relationships WHERE type IN ('reports_to', 'contributes_to')")
    _retype(RELATIONSHIP_TYPES)
