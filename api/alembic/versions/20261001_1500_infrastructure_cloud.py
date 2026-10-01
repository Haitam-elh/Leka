"""Infrastructure and cloud: what resources are in.

Revision ID: 6e1b8c4f2a57
Revises: 4d9a2c7e1f60
Created: 2026-10-01

LEKA-363. The company model gains two kinds — `cloud_account`, an AWS
account, an Azure subscription or a Google Cloud project, and
`resource_group`, an Azure resource group: the entity type CHECK takes them
(docs/adr/006-enum-storage.md). No relationship type is new: a resource is
`part_of` what it is in, as a node is of its cluster.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "6e1b8c4f2a57"
down_revision: str | None = "4d9a2c7e1f60"
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
)
NEW_ENTITY_TYPES = ("cloud_account", "resource_group")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _retype(values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_entities_type"), "entities", type_="check")
    op.create_check_constraint(op.f("ck_entities_type"), "entities", _one_of("type", values))


def upgrade() -> None:
    _retype((*ENTITY_TYPES, *NEW_ENTITY_TYPES))


def downgrade() -> None:
    # What the new kinds made goes: the old constraint could not hold it.
    op.execute("DELETE FROM entities WHERE type IN ('cloud_account', 'resource_group')")
    _retype(ENTITY_TYPES)
