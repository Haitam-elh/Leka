"""Data: schemas, data objects, and how they depend on one another.

Revision ID: 9c4e2b7a1d38
Revises: 6e1b8c4f2a57
Created: 2026-10-01

LEKA-364. The company model gains two kinds — `schema`, a database's, and
`data_object`, a table, a view or a collection — and two relationships:
`references`, a foreign key to the table it points at, and `reads_from`, a
view to what it reads. Both type CHECK constraints take them
(docs/adr/006-enum-storage.md).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "9c4e2b7a1d38"
down_revision: str | None = "6e1b8c4f2a57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTITY_TYPES = (
    "service",
    "repository",
    "incident",
    "deployment",
    "person",
    "document",
    "infra_resource",
    "database",
    "team",
    "project",
    "issue",
    "pull_request",
    "commit",
    "release",
    "application",
    "environment",
    "cloud_account",
    "resource_group",
)
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
)
NEW_ENTITY_TYPES = ("schema", "data_object")
NEW_RELATIONSHIP_TYPES = ("references", "reads_from")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _retype(table: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(f"ck_{table}_type"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_type"), table, _one_of("type", values))


def upgrade() -> None:
    _retype("entities", (*ENTITY_TYPES, *NEW_ENTITY_TYPES))
    _retype("relationships", (*RELATIONSHIP_TYPES, *NEW_RELATIONSHIP_TYPES))


def downgrade() -> None:
    # What the new kinds made goes: the old constraints could not hold it.
    op.execute("DELETE FROM relationships WHERE type IN ('references', 'reads_from')")
    op.execute("DELETE FROM entities WHERE type IN ('schema', 'data_object')")
    _retype("relationships", RELATIONSHIP_TYPES)
    _retype("entities", ENTITY_TYPES)
