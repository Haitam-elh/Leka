"""Applications and services: environments, and relationships true in some.

Revision ID: 4d9a2c7e1f60
Revises: 8b3f6d2a9e41
Created: 2026-09-30

LEKA-362. The company model gains two kinds — `application`, a group of
services the company names as one, and `environment`, where things run —
and one relationship, `runs_in`: both type CHECK constraints take them
(docs/adr/006-enum-storage.md).

`relationships.attributes`: what holds of an edge beyond its ends — the
`environments` it is true in, so that a service's production database and
its staging one stay apart. Empty for every edge there is: the next build,
under the new model version, fills it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4d9a2c7e1f60"
down_revision: str | None = "8b3f6d2a9e41"
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
)
NEW_ENTITY_TYPES = ("application", "environment")
NEW_RELATIONSHIP_TYPES = ("runs_in",)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _retype(table: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(f"ck_{table}_type"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_type"), table, _one_of("type", values))


def upgrade() -> None:
    _retype("entities", (*ENTITY_TYPES, *NEW_ENTITY_TYPES))
    _retype("relationships", (*RELATIONSHIP_TYPES, *NEW_RELATIONSHIP_TYPES))
    op.add_column(
        "relationships",
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("relationships", "attributes")
    # What the new kinds made goes: the old constraints could not hold it.
    op.execute("DELETE FROM relationships WHERE type = 'runs_in'")
    op.execute("DELETE FROM entities WHERE type IN ('application', 'environment')")
    _retype("relationships", RELATIONSHIP_TYPES)
    _retype("entities", ENTITY_TYPES)
