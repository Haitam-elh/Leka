"""Replace PostgreSQL ENUM types with text and CHECK constraints.

Revision ID: 002
Revises: 001
Created: 2026-09-19

Migration 001 used native ENUM types. That was a mistake, and it is cheaper
to undo now — the tables are empty — than in a month.

Two costs, both certain:

- **A value can never be removed.** PostgreSQL has no DROP VALUE. A typo, or
  a source kind we stop supporting, stays in the type forever.
- **A value cannot be added and used in the same transaction.** PostgreSQL
  rejects it with "unsafe use of new value", and Alembic wraps every
  migration in a transaction. So any migration that adds a type *and*
  backfills rows with it has to be split in two.

Both matter here precisely because these lists grow: every new connector adds
source kinds and entity types.

A CHECK constraint is dropped and recreated in one ordinary statement, inside
a transaction, and can remove values as easily as add them. The trade is a
slightly larger column and no ordering — neither of which we use.

See docs/adr/006-enum-storage.md.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column, postgres enum type, constraint name, allowed values)
# The constraint name is the bare suffix: Base's naming convention expands
# it to ck_<table>_<name>, and passing the full name would double it.
CONVERSIONS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    (
        "sources",
        "kind",
        "source_kind",
        "kind",
        ("github", "jira", "confluence", "aws", "datadog", "slack"),
    ),
    (
        "sources",
        "status",
        "source_status",
        "status",
        ("pending", "active", "error", "disabled"),
    ),
    (
        "entities",
        "type",
        "entity_type",
        "type",
        (
            "service",
            "repository",
            "incident",
            "deployment",
            "person",
            "document",
            "infra_resource",
            "database",
        ),
    ),
    (
        "relationships",
        "type",
        "relationship_type",
        "type",
        ("depends_on", "owns", "deployed_to", "mentions", "caused_by", "member_of"),
    ),
    (
        "memberships",
        "role",
        "membership_role",
        "role",
        ("owner", "admin", "member"),
    ),
)

# sources.status carries a server default, which has to be dropped before the
# column type changes and restored afterwards.
DEFAULTED = {("sources", "status"): "pending"}


def _check_expression(column: str, values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({allowed})"


# Migration 001 passed full constraint names where the naming convention
# expects a bare suffix, so PostgreSQL ended up with
# ck_entities_ck_entities_confidence_range. Cosmetic, but constraint names are
# what a developer reads in an integrity error at 2am. Renamed here rather
# than by editing 001, which is merged (architecture rule 10).
RENAMES: tuple[tuple[str, str, str], ...] = (
    ("entities", "ck_entities_ck_entities_confidence_range", "ck_entities_confidence_range"),
    (
        "relationships",
        "ck_relationships_ck_relationships_confidence_range",
        "ck_relationships_confidence_range",
    ),
)


def upgrade() -> None:
    for table, old_name, new_name in RENAMES:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old_name} TO {new_name}")

    for table, column, enum_type, constraint, values in CONVERSIONS:
        default = DEFAULTED.get((table, column))
        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")

        # USING: the existing enum values are already the strings we want.
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE VARCHAR(50) USING {column}::text"
        )

        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}'")

        op.create_check_constraint(constraint, table, _check_expression(column, values))
        op.execute(f"DROP TYPE {enum_type}")


def downgrade() -> None:
    for table, old_name, new_name in RENAMES:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new_name} TO {old_name}")

    for table, column, enum_type, constraint, values in reversed(CONVERSIONS):
        allowed = ", ".join(f"'{value}'" for value in values)
        op.execute(f"CREATE TYPE {enum_type} AS ENUM ({allowed})")
        op.drop_constraint(constraint, table, type_="check")

        default = DEFAULTED.get((table, column))
        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")

        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE {enum_type} USING {column}::{enum_type}"
        )

        if default is not None:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}'::{enum_type}"
            )


# sa is imported for the Alembic template's benefit; the operations above are
# expressed in SQL because a type change with USING has no ORM equivalent.
_ = sa
