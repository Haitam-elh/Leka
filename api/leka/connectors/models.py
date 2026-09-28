"""Tables owned by the connectors module.

A Source is one configured connection to a customer system — "Acme's GitHub
organisation", not "GitHub". GitHub, the kind of system, is a *connector*:
code in leka/connectors/<kind>/, registered once. Everything the background
loop collects carries the id of the source it came from, which is what lets
an answer cite where its evidence originated.

Three tables since LEKA-344:

    sources             the connection: its lifecycle, health and sync state
    source_credentials  the secret, encrypted, one row per source
    source_events       what happened to it, append-only

The secret has a table of its own so that nothing which reads a source —
a list, a health check, an admin screen — ever has the ciphertext in hand.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin


def _values(enum_class: type[enum.StrEnum]) -> list[str]:
    """Store the enum VALUE, not the member name.

    SQLAlchemy defaults to the name, which would put "GITHUB" in a column
    whose constraint allows 'github'. The mismatch only surfaces at the first
    insert.
    """
    return [member.value for member in enum_class]


def _enum(enum_class: type[enum.StrEnum], name: str) -> Enum:
    return Enum(enum_class, name=name, native_enum=False, length=50, values_callable=_values)


class SourceKind(enum.StrEnum):
    """The customer systems LEKA knows the shape of.

    Knowing a kind is not being able to connect to it: only the kinds with a
    registered connector (leka.connectors.registry) can be created. Adding a
    connector adds its member here — inside this module, with no migration:
    the database stopped checking this list in LEKA-344.
    """

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    JIRA = "jira"
    CONFLUENCE = "confluence"
    LINEAR = "linear"
    NOTION = "notion"
    ASANA = "asana"
    TRELLO = "trello"
    CLICKUP = "clickup"
    MONDAY = "monday"
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    DATADOG = "datadog"
    SLACK = "slack"


class SourceStatus(enum.StrEnum):
    """Where a source is in its lifecycle. See leka/connectors/lifecycle.py."""

    DRAFT = "draft"
    TESTED = "tested"
    ACTIVE = "active"
    DEGRADED = "degraded"
    ERROR = "error"
    DISABLED = "disabled"


class HealthStatus(enum.StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class SyncStatus(enum.StrEnum):
    """Filled in by the sync engine (LEKA-352). Only the field exists today."""

    NEVER = "never"
    IDLE = "idle"
    RUNNING = "running"
    FAILED = "failed"


class SourceEventType(enum.StrEnum):
    CREATED = "created"
    TEST_SUCCEEDED = "test_succeeded"
    TEST_FAILED = "test_failed"
    ACTIVATED = "activated"
    RECONFIGURED = "reconfigured"
    CREDENTIALS_ROTATED = "credentials_rotated"
    HEALTH_CHANGED = "health_changed"
    DISABLED = "disabled"
    DELETED = "deleted"
    # Written by the sync (LEKA-352) when a source starts failing and when it
    # recovers — not on every pass, or an hourly sync would bury the rest.
    SYNC_FAILED = "sync_failed"
    SYNC_RECOVERED = "sync_recovered"


class Source(Base, WorkspaceScopedMixin):
    """A configured connection to one customer system."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", "name", name="uq_sources_workspace_kind_name"),
        UniqueConstraint("workspace_id", "id", name="uq_sources_workspace_id_id"),
    )

    kind: Mapped[SourceKind] = mapped_column(_enum(SourceKind, "kind"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus, "status"),
        nullable=False,
        server_default=SourceStatus.DRAFT.value,
    )

    # Non-sensitive connection settings: base URL, organisation, filters.
    # Validated against the connector's config_schema on every write.
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")

    # What the last SUCCESSFUL test was run against — the config and the
    # credentials' revision, hashed. Activation is refused unless the source
    # still matches it: a test proves nothing about settings changed since.
    # Never derived from the secret itself (see lifecycle.fingerprint).
    tested_config_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # What the source turned out to offer, and to be, at its last test.
    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    health_status: Mapped[HealthStatus] = mapped_column(
        _enum(HealthStatus, "health_status"),
        nullable=False,
        server_default=HealthStatus.UNKNOWN.value,
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The last diagnostic (leka.connectors.errors.Diagnostic), already
    # cleaned of anything secret. Null once a test or a check succeeds.
    last_error: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    sync_status: Mapped[SyncStatus] = mapped_column(
        _enum(SyncStatus, "sync_status"),
        nullable=False,
        server_default=SyncStatus.NEVER.value,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SourceCredential(Base, WorkspaceScopedMixin):
    """The secret of one source, encrypted. Deleted with it.

    Written and read only through leka.connectors.secrets.SecretStore — the
    one place that encrypts, decrypts, and knows this table exists.
    """

    __tablename__ = "source_credentials"
    __table_args__ = (
        # Composite, like every reference to a source: a credential cannot
        # belong to one workspace and point at another's source.
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_source_credentials_source",
        ),
        UniqueConstraint("source_id", name="uq_source_credentials_source_id"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Fernet, bytea: nothing about it invites being read. The key lives in the
    # environment, never in the database and never in Git (rule 12).
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Which key wrote it — a fingerprint of the key, never the key. What a
    # rotation checks, and what an operator reads to know it finished.
    key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    # "github_pat_…a1b2": enough to recognise a token, not to use it.
    hint: Mapped[str] = mapped_column(String(64), nullable=False)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceEvent(Base, WorkspaceScopedMixin):
    """One thing that happened to a source. Append-only.

    source_id carries no foreign key, on purpose: this is the history, and
    "deleted" is part of it. A cascade would erase the record of the
    deletion at the moment it was written. The workspace's own cascade still
    removes all of it when the customer leaves.
    """

    __tablename__ = "source_events"
    __table_args__ = (Index("ix_source_events_source_id_created_at", "source_id", "created_at"),)

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type: Mapped[SourceEventType] = mapped_column(_enum(SourceEventType, "type"), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Never a secret: built by the service from diagnostics and statuses.
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
