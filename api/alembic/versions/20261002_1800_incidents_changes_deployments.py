"""Incidents, changes and deployments: what changed, when, and what it did.

Revision ID: 8d3f6a2c9e41
Revises: 5a8c1e3f7b92
Created: 2026-10-02

LEKA-367. The company model gains a kind — `change` — and a relationship —
`deploys`, a deployment to the commit or release it ships; both type CHECK
constraints take them (docs/adr/006-enum-storage.md). And `occurred_at`:
when an event happened — an incident opened, a deployment done, a change
made — indexed with its workspace and type, for timelines.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8d3f6a2c9e41"
down_revision: str | None = "5a8c1e3f7b92"
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
    "schema",
    "data_object",
    "knowledge_space",
    "business_capability",
    "business_process",
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
    "references",
    "reads_from",
    "reports_to",
    "contributes_to",
    "describes",
    "edited_by",
    "supported_by",
    "uses",
    "realizes",
)
NEW_ENTITY_TYPES = ("change",)
NEW_RELATIONSHIP_TYPES = ("deploys",)


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _retype(table: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(f"ck_{table}_type"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_type"), table, _one_of("type", values))


def upgrade() -> None:
    _retype("entities", (*ENTITY_TYPES, *NEW_ENTITY_TYPES))
    _retype("relationships", (*RELATIONSHIP_TYPES, *NEW_RELATIONSHIP_TYPES))
    op.add_column("entities", sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_entities_workspace_type_occurred",
        "entities",
        ["workspace_id", "type", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_entities_workspace_type_occurred", table_name="entities")
    op.drop_column("entities", "occurred_at")
    # What the new kinds made goes: the old constraints could not hold it.
    op.execute("DELETE FROM relationships WHERE type IN ('deploys')")
    op.execute("DELETE FROM entities WHERE type IN ('change')")
    _retype("relationships", RELATIONSHIP_TYPES)
    _retype("entities", ENTITY_TYPES)
