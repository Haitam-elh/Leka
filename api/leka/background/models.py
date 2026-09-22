"""Tables owned by the background module: events, the outbox of the background loop.

An event says something HAPPENED in a customer's workspace. It is written in
the same transaction as the change that caused it, so an event exists if and
only if the change does — which is the whole reason it lives in PostgreSQL and
not on a queue. A dispatcher turns what is pending into job runs — rows, in the
tables that follow — and a separate pass offers those to the queue, so Redis is
never on the path of a transaction.

See docs/adr/012-events-and-job-runs.md for why an outbox rather than a broker.

AT-LEAST-ONCE, NOT EXACTLY-ONCE. A dispatcher can die between creating the runs
and marking the event, and will then do it again. What THIS schema guarantees is
that a producer's retry cannot create a second EVENT
(`uq_events_workspace_dedupe_key`). Everything downstream of that — a consumer
that saw the same event twice — is the consumer's own idempotence to provide.

THIS MODULE DOES NOT IMPORT leka.platform, and cannot: it sits below it, so
that platform can use it. So the payload of an event is JSON — strings, numbers,
identifiers — never a typed reference to a workspace or a source. That is not a
limit to work around. RQ serialises job arguments to JSON anyway.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin


class EventStatus(enum.StrEnum):
    """Where an event is on its way to becoming work.

    `runs_created` means exactly that: the event's job runs exist. It does NOT mean
    Redis has heard of them — that is `enqueued_at` on the run, and the two are
    different facts. (It was first called `dispatched`, which reads as "sent".)
    `failed` is FINAL: nothing consumes this event type, or the dispatcher gave up.
    """

    PENDING = "pending"
    RUNS_CREATED = "runs_created"
    FAILED = "failed"


def _values(enum_class: type[enum.StrEnum]) -> list[str]:
    """Store the enum VALUE, not the member name (see connectors.models)."""
    return [member.value for member in enum_class]


def _enum(enum_class: type[enum.StrEnum], name: str) -> Enum:
    """Text with a CHECK constraint, not a PostgreSQL ENUM type (ADR 006).

    The CHECK is declared explicitly in __table_args__ beside the others, so
    that everything the database refuses is in one visible list.
    """
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        length=50,
        values_callable=_values,
    )


def _in(column: str, enum_class: type[enum.StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_class)
    return f"{column} IN ({values})"


class Event(Base, WorkspaceScopedMixin):
    """Something that happened in one customer's workspace.

    Small on purpose. The payload says WHAT happened and to WHICH thing — a
    source id, a deployment id — never the data itself. Raw material belongs
    in the object store (ADR 010); an event carrying it would make this the
    second largest table in the product.
    """

    __tablename__ = "events"
    __table_args__ = (
        # What tables that point at an event reference, so that the pointer can
        # carry the workspace too (the house pattern, as sources has).
        UniqueConstraint("workspace_id", "id", name="uq_events_workspace_id_id"),
        # A webhook delivered twice becomes one event. Per workspace, so that
        # two customers producing the same key cannot learn about each other.
        # NULL keys are distinct in PostgreSQL, which is exactly right: an
        # event with no key has nothing to be a duplicate OF.
        UniqueConstraint("workspace_id", "dedupe_key", name="uq_events_workspace_dedupe_key"),
        # The dispatcher asks: what is pending, oldest first, across every
        # workspace. Retention asks: what has settled and is older than N days.
        Index("ix_events_status_created_at", "status", "created_at"),
        CheckConstraint(_in("status", EventStatus), name="status"),
        CheckConstraint("length(type) > 0", name="type_not_empty"),
        CheckConstraint("dispatch_attempts >= 0", name="dispatch_attempts_not_negative"),
    )

    type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # The request that caused this, if there was one (LEKA-333). None from a
    # worker, a migration or a test — and that is a real answer, not a gap.
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[EventStatus] = mapped_column(
        _enum(EventStatus, "status"), nullable=False, server_default=EventStatus.PENDING.value
    )
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    runs_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
