"""Initial schema: tenancy, sources, and the entity graph.

Revision ID: 001
Revises:
Created: 2026-09-19

Six tables.

workspaces, sources, entities and relationships are complete — they are this
ticket (LEKA-329).

users and memberships carry the bare minimum: an id, an email, and the
user<->workspace link with a role. They exist only because other tables must
be able to reference a person. A user is NOT workspace-scoped: the same
person can hold a membership in several workspaces. Authentication columns
(password_hash, sessions, MFA) belong to LEKA-330 and arrive in migration
002. Do not add them here — rule 10: a merged migration is never edited.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001"
down_revision: str | None = None
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
)
RELATIONSHIP_TYPES = (
    "depends_on",
    "owns",
    "deployed_to",
    "mentions",
    "caused_by",
    "member_of",
)
SOURCE_KINDS = ("github", "jira", "confluence", "aws", "datadog", "slack")
SOURCE_STATUSES = ("pending", "active", "error", "disabled")
MEMBERSHIP_ROLES = ("owner", "admin", "member")


def upgrade() -> None:
    bind = op.get_bind()

    # pgvector, enabled here rather than by a docker-only init script, so a
    # database created on RDS goes through the exact same path. No column
    # uses it yet; embeddings arrive with the context module.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    entity_type = postgresql.ENUM(*ENTITY_TYPES, name="entity_type")
    relationship_type = postgresql.ENUM(*RELATIONSHIP_TYPES, name="relationship_type")
    source_kind = postgresql.ENUM(*SOURCE_KINDS, name="source_kind")
    source_status = postgresql.ENUM(*SOURCE_STATUSES, name="source_status")
    membership_role = postgresql.ENUM(*MEMBERSHIP_ROLES, name="membership_role")
    for enum_type in (entity_type, relationship_type, source_kind, source_status, membership_role):
        enum_type.create(bind, checkfirst=True)

    # ── workspaces ───────────────────────────────────────────────────────────
    # The tenant. It has no workspace_id because it IS the workspace; users
    # has none because a person may belong to several. Those are the only
    # two exceptions to architecture rule 2.
    op.create_table(
        "workspaces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
    )

    # ── users ────────────────────────────────────────────────────────────────
    # MINIMAL — LEKA-330 owns this table. Four columns, no credentials.
    #
    # Deliberately NOT workspace-scoped, and therefore one of the two
    # exceptions to architecture rule 2 (the other being workspaces itself).
    # A person is a person: a consultant working for two customers signs in
    # once. Which workspaces they may enter, and as what, is recorded in
    # memberships below — that table is the authority, not this one.
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        # Globally unique: one account per person across the whole platform.
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # ── memberships ──────────────────────────────────────────────────────────
    # The user <-> workspace link, with a role. THIS is what grants access:
    # one row per workspace a person may enter, removing the row removes the
    # access. LEKA-330 may extend the role list; it does so in migration 002.
    op.create_table(
        "memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(*MEMBERSHIP_ROLES, name="membership_role", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_memberships_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_memberships_user_id_users",
            ondelete="CASCADE",
        ),
        # One seat per person per workspace. The same person holds a separate
        # row, with its own role, in every workspace they work for.
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_memberships_workspace_user"),
    )
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])
    # "which workspaces may this person enter" is asked on every request.
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    # ── sources ──────────────────────────────────────────────────────────────
    op.create_table(
        "sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(*SOURCE_KINDS, name="source_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*SOURCE_STATUSES, name="source_status", create_type=False),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        # A pointer to the secret store, never the secret (rule 12).
        sa.Column("credentials_ref", sa.String(length=255), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_sources_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("workspace_id", "kind", "name", name="uq_sources_workspace_kind_name"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_sources_workspace_id_id"),
    )
    op.create_index("ix_sources_workspace_id", "sources", ["workspace_id"])

    # ── entities ─────────────────────────────────────────────────────────────
    op.create_table(
        "entities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM(*ENTITY_TYPES, name="entity_type", create_type=False),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=500), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entities"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_entities_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        # An entity's source must belong to the same workspace.
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_entities_workspace_source",
            ondelete="CASCADE",
        ),
        # Re-syncing a source updates rows instead of duplicating the graph.
        sa.UniqueConstraint(
            "workspace_id", "source_id", "external_id", name="uq_entities_workspace_source_external"
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_entities_workspace_id_id"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_entities_confidence_range"
        ),
    )
    op.create_index("ix_entities_workspace_id", "entities", ["workspace_id"])
    op.create_index("ix_entities_workspace_type", "entities", ["workspace_id", "type"])
    op.create_index("ix_entities_attributes", "entities", ["attributes"], postgresql_using="gin")

    # ── relationships ────────────────────────────────────────────────────────
    op.create_table(
        "relationships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "type",
            postgresql.ENUM(*RELATIONSHIP_TYPES, name="relationship_type", create_type=False),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_relationships"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_relationships_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        # Both ends pinned to this row's workspace: an edge can never join two
        # tenants' graphs.
        sa.ForeignKeyConstraint(
            ["workspace_id", "from_entity_id"],
            ["entities.workspace_id", "entities.id"],
            name="fk_relationships_workspace_from_entity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "to_entity_id"],
            ["entities.workspace_id", "entities.id"],
            name="fk_relationships_workspace_to_entity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_relationships_workspace_source",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id", "from_entity_id", "to_entity_id", "type", name="uq_relationships_edge"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_relationships_confidence_range"
        ),
    )
    op.create_index("ix_relationships_workspace_id", "relationships", ["workspace_id"])
    # The graph is walked in both directions, so both directions are indexed.
    op.create_index(
        "ix_relationships_from", "relationships", ["workspace_id", "from_entity_id", "type"]
    )
    op.create_index(
        "ix_relationships_to", "relationships", ["workspace_id", "to_entity_id", "type"]
    )


def downgrade() -> None:
    op.drop_table("relationships")
    op.drop_table("entities")
    op.drop_table("sources")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("workspaces")

    bind = op.get_bind()
    for name in (
        "membership_role",
        "source_status",
        "source_kind",
        "relationship_type",
        "entity_type",
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)

    # Left in place on purpose: another schema in the same database may rely
    # on it, and dropping an extension is not the business of a table
    # migration.
    # op.execute("DROP EXTENSION IF EXISTS vector")
