"""Tables owned by the connectors module.

A Source is one configured connection to a customer system — "Acme's GitHub
organisation", not "GitHub". Everything the background loop collects carries
the id of the source it came from, which is what lets an answer cite where
its evidence originated.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin


def _values(enum_class: type[enum.StrEnum]) -> list[str]:
    """Store the enum VALUE, not the member name.

    SQLAlchemy defaults to the name, which would put "GITHUB" in a column
    whose constraint allows 'github'. The mismatch only surfaces at the first
    insert.
    """
    return [member.value for member in enum_class]


class SourceKind(enum.StrEnum):
    """The customer systems LEKA connects to."""

    GITHUB = "github"
    JIRA = "jira"
    CONFLUENCE = "confluence"
    AWS = "aws"
    DATADOG = "datadog"
    SLACK = "slack"


class SourceStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


class Source(Base, WorkspaceScopedMixin):
    """A configured connection to one customer system."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", "name", name="uq_sources_workspace_kind_name"),
        # Referenced by the composite foreign keys that keep a workspace's
        # rows from ever pointing at another workspace's source.
        UniqueConstraint("workspace_id", "id", name="uq_sources_workspace_id_id"),
    )

    kind: Mapped[SourceKind] = mapped_column(
        Enum(
            SourceKind,
            name="kind",
            native_enum=False,
            length=50,
            values_callable=_values,
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[SourceStatus] = mapped_column(
        Enum(
            SourceStatus,
            name="status",
            native_enum=False,
            length=50,
            values_callable=_values,
        ),
        nullable=False,
        server_default=SourceStatus.PENDING.value,
    )

    # Non-sensitive connection settings: base URL, organisation, repo filters.
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")

    # A POINTER to the credential in the secret store — never the credential
    # itself. Architecture rule 12: no secret in the database we back up and
    # no secret in Git.
    credentials_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
