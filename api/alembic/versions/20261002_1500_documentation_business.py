"""Documentation and business knowledge: where documents are kept, what
they describe; what the business does, how, and what it relies on.

Revision ID: 5a8c1e3f7b92
Revises: 2f7d9b4c6e15
Created: 2026-10-02

LEKA-366. The company model gains three kinds — `knowledge_space`, where
documents are kept; `business_capability` and `business_process` — and five
relationships: `describes`, a document to what it is about; `edited_by`, a
document to who last changed it; `supported_by`, a capability or a process
to an application or a service; `uses`, to the data it uses; `realizes`, a
process to its capability. Both type CHECK constraints take them
(docs/adr/006-enum-storage.md).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5a8c1e3f7b92"
down_revision: str | None = "2f7d9b4c6e15"
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
)
NEW_ENTITY_TYPES = ("knowledge_space", "business_capability", "business_process")
NEW_RELATIONSHIP_TYPES = ("describes", "edited_by", "supported_by", "uses", "realizes")


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
    op.execute(
        "DELETE FROM relationships WHERE type IN "
        "('describes', 'edited_by', 'supported_by', 'uses', 'realizes')"
    )
    op.execute(
        "DELETE FROM entities WHERE type IN "
        "('knowledge_space', 'business_capability', 'business_process')"
    )
    _retype("relationships", RELATIONSHIP_TYPES)
    _retype("entities", ENTITY_TYPES)
