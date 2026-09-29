"""Tables owned by the ingestion module.

Ingestion writes entities and relationships, but it does not own them —
leka.knowledge does. What ingestion owns is the record of its own work: what
ran, over which source, what it produced, what it could not parse.

A failed parse is data, not an exception to swallow. It is how we find out a
vendor changed a payload shape.

`raw_payloads` is the first of those tables; `source_syncs`, where each
source's synchronisation stands, the second (LEKA-352); `sync_runs`, what
each pass did, the third (LEKA-353); `source_records`, what was seen of
each vendor object, the fourth; `extracted_records`, what extraction made
of each of them, the fifth (LEKA-354); `parsed_records`, what parsing read
in each extraction, the sixth (LEKA-355); `normalised_records`, the
candidates normalisation made of each, the seventh (LEKA-356);
`processing_runs`, each run of those three stages, the eighth (LEKA-360);
`webhook_deliveries`, what webhook sources received, the ninth (LEKA-350);
`resolved_entities`, `resolved_keys`, `resolution_decisions` and
`resolution_runs`, what entity resolution made of it all (LEKA-357);
`validated_records`, what validation found of each normalised record
(LEKA-358).
It is the row half of the split
described in docs/adr/010-object-storage.md: the bytes live in the object
store, and this is everything we know about them — where they came from, how
big they are, what they hash to, and when they stop being ours to keep.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leka.db import Base, WorkspaceScopedMixin


class RawPayload(Base, WorkspaceScopedMixin):
    """One thing we fetched from a customer system, kept outside the database.

    THE BYTES ARE NOT HERE. `object_key` points into the object store; this
    row is the metadata and the lifecycle. Two reasons, both operational:
    payloads are the largest volume and the shortest-lived thing LEKA holds,
    so keeping them in PostgreSQL would swell every backup and lengthen every
    restore — and deleting them, which we must do on a schedule, would mean
    rewriting table pages rather than dropping objects.

    NO UNIQUE CONSTRAINT, anywhere, on purpose. This table grows without
    bound and will be partitioned by `fetched_at` one day; PostgreSQL
    requires every unique constraint on a partitioned table to include the
    partition key, so a unique index written today is a migration blocked
    tomorrow. The uuid inside each object key makes collisions a non-problem
    without one.
    """

    __tablename__ = "raw_payloads"
    __table_args__ = (
        # The house pattern, the same one entities uses: a composite foreign
        # key through workspace_id. A single-column reference to sources.id
        # would let one workspace's payload point at another workspace's
        # source — the database itself refuses that here.
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_raw_payloads_workspace_source",
            ondelete="CASCADE",
        ),
        # What the background loop asks for: this source, most recent first.
        Index(
            "ix_raw_payloads_workspace_source_fetched", "workspace_id", "source_id", "fetched_at"
        ),
        # What the retention sweep asks for, across every tenant: what has
        # outlived its policy. Without this it is a full scan of the largest
        # table in the product, every hour, for ever.
        Index("ix_raw_payloads_expires_at", "expires_at"),
        # Finding the copies of one payload: the same content fetched again,
        # or a stored object that no longer matches what we recorded.
        Index("ix_raw_payloads_checksum", "workspace_id", "checksum_sha256"),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Where the bytes are: {workspace}/{source}/{yyyy}/{mm}/{dd}/{uuid}.{ext}
    # See leka.platform.storage.object_key for why that shape.
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)

    content_type: Mapped[str] = mapped_column(String(200), nullable=False)

    # BigInteger, not Integer. A 2 GB log export is not a strange thing for a
    # connector to produce, and int4 stops at 2 147 483 647 bytes.
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # SHA-256 of the payload, measured while it was written. 64 hex
    # characters. Two jobs: telling the same payload from a changed one when
    # we re-sync a repository we already have, and catching an object that
    # has silently rotted before we analyse it and answer a customer with
    # something untrue.
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # When it was collected. This is the future partition key, so it is
    # NOT NULL and never rewritten.
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # When the retention policy says this stops being ours to keep. NOT NULL:
    # a nullable expiry reads as "keep for ever", and the one thing a
    # retention policy must never have is a quiet way to opt out of it.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Set when a payload is withdrawn before its expiry — a source
    # disconnected, a customer asking for one thing to go. The sweep removes
    # the object and then the row; until it runs, this is what keeps the row
    # out of every read.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncRunStatus(enum.StrEnum):
    """Where one capability of one source stands. See leka/ingestion/sync.py."""

    IDLE = "idle"
    RUNNING = "running"
    FAILED = "failed"


def _statuses(enum_class: type[enum.StrEnum]) -> list[str]:
    """Store the VALUE, not the member name (see connectors.models)."""
    return [member.value for member in enum_class]


class SourceSync(Base, WorkspaceScopedMixin):
    """How far one capability of one source has been read — "acme's GitHub,
    its commits" — and how the last pass went.

    One row per (source, capability), made by the first pass and updated by
    every one after. The source's own `sync_status` is the summary a list
    shows; this is the detail a page and an operator need.

    `since` IS THE CURSOR, and it is when the last SUCCESSFUL pass STARTED —
    not when it ended, and not the newest record seen. Anything changed while
    that pass was reading is at or after its start, so the next pass asks for
    it again; the other two choices each lose what changed mid-pass or what a
    vendor dates late. Reading something twice costs a write; missing it
    costs a wrong answer (docs/connectors/framework.md).

    A failed pass does not move it: the next one starts from the same place.
    """

    __tablename__ = "source_syncs"
    __table_args__ = (
        # Composite, like every reference to a source (raw_payloads, the
        # credentials): a sync cannot belong to one workspace and point at
        # another's source. Deleted with the source.
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_source_syncs_workspace_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint("source_id", "capability", name="uq_source_syncs_source_capability"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _statuses(SyncRunStatus)) + ")",
            name="status",
        ),
        CheckConstraint("length(capability) > 0", name="capability_not_empty"),
        CheckConstraint("records_last_run >= 0", name="records_last_run_not_negative"),
        CheckConstraint("records_total >= 0", name="records_total_not_negative"),
        CheckConstraint("consecutive_failures >= 0", name="consecutive_failures_not_negative"),
        # What the scheduler asks for, across every tenant: whose last
        # success is oldest.
        Index("ix_source_syncs_last_succeeded_at", "last_succeeded_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # A Capability value ("commits"). Not checked by the database, like
    # sources.kind since LEKA-344: adding a capability must not be a migration.
    capability: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[SyncRunStatus] = mapped_column(
        Enum(
            SyncRunStatus,
            name="status",
            native_enum=False,
            length=50,
            values_callable=_statuses,
            create_constraint=False,
        ),
        nullable=False,
        server_default=SyncRunStatus.IDLE.value,
    )

    since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The last pass that ignored the cursor and read everything: the net
    # under incremental reads, which trust every vendor's dates.
    last_full_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    records_last_run: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # BigInteger: a large organisation's commits pass int4 within a year of syncs.
    records_total: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # The last diagnostic (leka.connectors.Diagnostic), already cleaned of
    # anything secret. Null once a pass succeeds.
    last_error: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class SyncTrigger(enum.StrEnum):
    """What started a pass."""

    ACTIVATION = "activation"
    SCHEDULE = "schedule"
    MANUAL = "manual"
    # The source's scope rules changed (LEKA-351): a full pass, to read what
    # came in and sweep what went out.
    SETTINGS = "settings"
    # A webhook source received a delivery (LEKA-350): the pass stores it.
    WEBHOOK = "webhook"


class SyncRunOutcome(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # Found `running` by the next pass: its worker died (leka/ingestion/sync.py).
    ABANDONED = "abandoned"


class SyncRun(Base, WorkspaceScopedMixin):
    """One pass over one source, from start to end (LEKA-353).

    `source_syncs` says where each capability stands; this says what each
    pass did: what started it, whether it read everything, when it ran, how
    far it got — updated batch by batch, which is what makes a pass in
    progress observable — and how it ended.

    PROVENANCE. A payload in `raw_payloads` carries its source and the moment
    it was fetched; the pass that fetched it is the run of that source whose
    [started_at, finished_at] holds that moment. One pass at a time per
    source (sync:<source_id>) is what makes that unambiguous.
    """

    __tablename__ = "sync_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_sync_runs_workspace_source",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "trigger IN (" + ", ".join(f"'{s}'" for s in _statuses(SyncTrigger)) + ")",
            name="trigger",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _statuses(SyncRunOutcome)) + ")",
            name="status",
        ),
        CheckConstraint(
            "records >= 0 AND payloads >= 0 AND bytes >= 0", name="counts_not_negative"
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finished_after_started"
        ),
        # A source's history, newest first — the only way it is read.
        Index("ix_sync_runs_source_started_at", "source_id", "started_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    trigger: Mapped[SyncTrigger] = mapped_column(
        Enum(
            SyncTrigger,
            name="trigger",
            native_enum=False,
            length=50,
            values_callable=_statuses,
            create_constraint=False,
        ),
        nullable=False,
    )
    # Not `full`, a reserved word in SQL: an operator's query would fail on it.
    full_read: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[SyncRunOutcome] = mapped_column(
        Enum(
            SyncRunOutcome,
            name="status",
            native_enum=False,
            length=50,
            values_callable=_statuses,
            create_constraint=False,
        ),
        nullable=False,
        server_default=SyncRunOutcome.RUNNING.value,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Progress, as each batch is committed.
    capability: Mapped[str | None] = mapped_column(String(50), nullable=True)
    records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    payloads: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    # The diagnostic it ended on, cleaned of secrets.
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class SourceRecord(Base, WorkspaceScopedMixin):
    """What LEKA has seen of one vendor object — a repository, a commit, an
    issue — in one source: the per-record index (LEKA-353, decided with
    Haitam on 2026-09-27).

    Three things need it, none of which a JSON-lines batch can answer:

    DEDUPLICATION. A record whose checksum (sha256 of its payload's canonical
    JSON) has not changed is not written again; the pass only notes it saw it.
    DELETIONS. After a full pass of a capability succeeded, what that run did
    not see (`last_seen_run_id`) is gone at the vendor, or out of the
    credentials' reach: `deleted_at`. Deliberately by run, not by time — a
    retry or the quota reserve can stretch a pass over hours.
    SCOPE. A reactivation reads in full, so the same sweep removes what left
    the scope, for every connector, without knowing what a container is.

    A record seen again comes back: `deleted_at` goes back to NULL.
    `payload_key` is the batch holding its latest version, for the job that
    rewrites batches without what was deleted.

    Not an entity: an issue can make several entities or none, and an entity
    can come from several records. leka.knowledge reads this; ingestion never
    writes there.
    """

    __tablename__ = "source_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_source_records_workspace_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "source_id", "kind", "external_id", name="uq_source_records_source_kind_external"
        ),
        CheckConstraint("length(kind) > 0 AND length(external_id) > 0", name="identity_not_empty"),
        CheckConstraint("length(checksum) = 64", name="checksum_is_sha256"),
        # The sweep: this capability's records the run did not see.
        Index("ix_source_records_sweep", "source_id", "kind", "last_seen_run_id"),
        # The purge job: deleted records whose batch still holds them.
        Index(
            "ix_source_records_to_purge",
            "source_id",
            postgresql_where=text("deleted_at IS NOT NULL AND payload_key IS NOT NULL"),
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # A Capability value; unchecked, like source_syncs.capability.
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    container: Mapped[str | None] = mapped_column(String(500), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # A single-column reference on purpose: through workspace_id, SET NULL
    # would null the workspace too (the trap job_runs documents). Runs go
    # only with their source, and so do records.
    last_seen_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sync_runs.id", ondelete="SET NULL"), nullable=True
    )
    payload_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExtractionStatus(enum.StrEnum):
    """What extraction made of one record (leka/ingestion/extraction)."""

    EXTRACTED = "extracted"
    FAILED = "failed"


# FailureCode's values (leka/ingestion/extraction/contract.py), repeated
# rather than imported: this module is below the extraction package.
EXTRACTION_FAILURES = ("unsupported", "malformed")


class ExtractedRecordRow(Base, WorkspaceScopedMixin):
    """What extraction made of one indexed record (LEKA-354): its
    ExtractedRecord, or why there is none.

    ONE ROW PER source_records ROW, replaced when the record changes
    (`checksum`) or its strategy does (`extractor_version`) — that is what
    makes extraction incremental. A record marked deleted loses its row at
    the next extraction; a source, or a record, deleted takes it along.

    `result` is the ExtractedRecord as JSON, provenance included: what
    parsing (LEKA-355) reads. Its texts are capped at 100 000 characters by
    the contract; the whole payload stays in the object store.

    A failure is a row too — `failure_code`, and a `message` that names a
    field and never quotes the payload: that is how a vendor changing a
    payload's shape is seen, one strategy failing all at once.
    """

    __tablename__ = "extracted_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_extracted_records_workspace_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint("source_record_id", name="uq_extracted_records_source_record"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _statuses(ExtractionStatus)) + ")",
            name="status",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            + ", ".join(f"'{c}'" for c in EXTRACTION_FAILURES)
            + ")",
            name="failure_code",
        ),
        # A result exactly when extracted, a failure code exactly when not.
        CheckConstraint(
            "(status = 'extracted') = (result IS NOT NULL AND failure_code IS NULL)",
            name="result_or_failure",
        ),
        CheckConstraint("length(checksum) = 64", name="checksum_is_sha256"),
        # A source's extraction at a glance, and its failures.
        Index("ix_extracted_records_source_status", "source_id", "status"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Single-column, like last_seen_run_id: a record goes only with its source.
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_records.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ExtractionStatus] = mapped_column(
        Enum(
            ExtractionStatus,
            name="status",
            native_enum=False,
            length=20,
            values_callable=_statuses,
            create_constraint=False,
        ),
        nullable=False,
    )
    # The strategy and its version; none when no strategy knows the record.
    extractor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extractor_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The source record's checksum when it was extracted.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ParseStatus(enum.StrEnum):
    """What parsing made of one extraction (leka/ingestion/parsing)."""

    PARSED = "parsed"
    FAILED = "failed"


class ParsedRecordRow(Base, WorkspaceScopedMixin):
    """What parsing read in one extraction (LEKA-355): its ParsedRecord —
    facts with their confidence and evidence, structure, quality — or why
    there is none.

    ONE ROW PER extracted_records ROW THAT WAS EXTRACTED, replaced when the
    extraction changes (`checksum`, `extractor_version`) or parsing does
    (`parser_version`). An extraction that failed, or whose record is gone,
    has none: the cascade and the job see to it.
    """

    __tablename__ = "parsed_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_parsed_records_workspace_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint("extracted_record_id", name="uq_parsed_records_extracted_record"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _statuses(ParseStatus)) + ")",
            name="status",
        ),
        CheckConstraint("failure_code IS NULL OR failure_code = 'malformed'", name="failure_code"),
        CheckConstraint(
            "(status = 'parsed') = (result IS NOT NULL AND failure_code IS NULL)",
            name="result_or_failure",
        ),
        CheckConstraint("length(checksum) = 64", name="checksum_is_sha256"),
        Index("ix_parsed_records_source_status", "source_id", "status"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    extracted_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_records.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ParseStatus] = mapped_column(
        Enum(
            ParseStatus,
            name="status",
            native_enum=False,
            length=20,
            values_callable=_statuses,
            create_constraint=False,
        ),
        nullable=False,
    )
    # What was parsed: the extraction's checksum and extractor version, and
    # the parser's own version.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NormalisationStatus(enum.StrEnum):
    """What normalisation made of one parse (leka/ingestion/normalisation)."""

    NORMALISED = "normalised"
    FAILED = "failed"


# NormalisationFailureCode's values, repeated: this module is below the
# normalisation package.
NORMALISATION_FAILURES = ("unsupported", "invalid", "malformed")


class NormalisedRecordRow(Base, WorkspaceScopedMixin):
    """The candidates normalisation made of one parse (LEKA-356): the
    NormalisedRecord — the record's entity under its canonical key, the
    people, services and teams it names, relationships between keys — or
    why there are none.

    ONE ROW PER parsed_records ROW THAT WAS PARSED, replaced when the parse
    changes (its checksum, extractor or parser version) or the rules do
    (`normaliser_version`). `entity_key` and `entity_type` repeat the
    record's own entity, for entity resolution (LEKA-357) to find every
    record naming one key without reading the JSON.
    """

    __tablename__ = "normalised_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_normalised_records_workspace_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint("parsed_record_id", name="uq_normalised_records_parsed_record"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _statuses(NormalisationStatus)) + ")",
            name="status",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN ("
            + ", ".join(f"'{c}'" for c in NORMALISATION_FAILURES)
            + ")",
            name="failure_code",
        ),
        CheckConstraint(
            "(status = 'normalised') = "
            "(result IS NOT NULL AND entity_key IS NOT NULL AND failure_code IS NULL)",
            name="result_or_failure",
        ),
        CheckConstraint("length(checksum) = 64", name="checksum_is_sha256"),
        Index("ix_normalised_records_source_status", "source_id", "status"),
        # Every record naming one entity, across the workspace's sources.
        Index("ix_normalised_records_entity_key", "workspace_id", "entity_key"),
        # What entity resolution (LEKA-357) asks before it runs: has anything
        # of the workspace been normalised since?
        Index("ix_normalised_records_workspace_normalised_at", "workspace_id", "normalised_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parsed_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parsed_records.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[NormalisationStatus] = mapped_column(
        Enum(
            NormalisationStatus,
            name="status",
            native_enum=False,
            length=20,
            values_callable=_statuses,
            create_constraint=False,
        ),
        nullable=False,
    )
    # What was normalised: the parse's checksum and versions, and the rules'.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser_version: Mapped[int] = mapped_column(Integer, nullable=False)
    normaliser_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The source's settings version whose mapping it was made with (LEKA-351);
    # 0 before any. A new mapping normalises the source's records again.
    settings_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    normalised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessingStage(enum.StrEnum):
    """The stages after collection, in their order (leka/ingestion/pipeline.py)."""

    EXTRACTION = "extraction"
    PARSING = "parsing"
    NORMALISATION = "normalisation"
    # What normalisation made, checked before it is trusted (LEKA-358).
    VALIDATION = "validation"


class ProcessingRunStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # Left `running` by a worker that died: found by the stage's next run.
    ABANDONED = "abandoned"


class ProcessingRun(Base, WorkspaceScopedMixin):
    """One run of one processing stage over one source (LEKA-360).

    What each run did, and with which versions: the history of a source's
    processing, and what its processed rows are traced to — one run of a
    stage at a time per source (its concurrency key), so a row's
    `extracted_at`, `parsed_at` or `normalised_at` falls inside exactly one
    run of its stage.
    """

    __tablename__ = "processing_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_processing_runs_workspace_source",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "stage IN (" + ", ".join(f"'{s}'" for s in _statuses(ProcessingStage)) + ")",
            name="stage",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _statuses(ProcessingRunStatus)) + ")",
            name="status",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finished_after_started"
        ),
        # A source's history per stage, newest first; and the run under way.
        Index("ix_processing_runs_source_stage_started", "source_id", "stage", "started_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stage: Mapped[ProcessingStage] = mapped_column(
        Enum(
            ProcessingStage,
            name="stage",
            native_enum=False,
            length=20,
            values_callable=_statuses,
            create_constraint=False,
        ),
        nullable=False,
    )
    status: Mapped[ProcessingRunStatus] = mapped_column(
        Enum(
            ProcessingRunStatus,
            name="status",
            native_enum=False,
            length=20,
            values_callable=_statuses,
            create_constraint=False,
        ),
        nullable=False,
        server_default=ProcessingRunStatus.RUNNING.value,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # What the run did: extracted, parsed, failed, forgotten, passed_over, …
    counts: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # The versions it ran with: the stage's, or each strategy's for extraction.
    versions: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Why it stopped: the exception's type — its details are in the logs,
    # a database error's may quote a record.
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)


class DeliveryStatus(enum.StrEnum):
    """Where a delivery a webhook source received stands (LEKA-350)."""

    # Kept, with its body, for the source's next pass.
    PENDING = "pending"
    # Its records stored, or marked gone.
    STORED = "stored"
    # No resource of the definition is it: nothing to keep.
    IGNORED = "ignored"
    # Signed, but not what the definition says: not JSON, a record without id.
    REJECTED = "rejected"


class WebhookDelivery(Base, WorkspaceScopedMixin):
    """One delivery a webhook source received, signed (LEKA-350).

    THE INBOX, THEN THE LOG. A delivery is kept `pending`, its body with it,
    until the source's next pass stores what it holds — one pass at a time
    per source, as for every source (leka/ingestion/sync.py). Then its body
    goes, and the row stays 30 days: the log an admin reads — when each came,
    what it was, what was kept of it, and why not.

    ONLY WHAT WAS SIGNED with the source's secret is written. Anyone can
    reach the address; a POST without the signature is refused at the door
    and leaves a line in the logs, not a row here.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_webhook_deliveries_workspace_source",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _statuses(DeliveryStatus)) + ")",
            name="status",
        ),
        CheckConstraint(
            "size_bytes >= 0 AND records >= 0 AND gone >= 0", name="counts_not_negative"
        ),
        # A body is kept for the pass, and only until it.
        CheckConstraint("status = 'pending' OR body IS NULL", name="body_only_while_pending"),
        # The log of a source, newest first.
        Index("ix_webhook_deliveries_source_received_at", "source_id", "received_at"),
        # The pass: a source's deliveries still to store, oldest first.
        Index(
            "ix_webhook_deliveries_pending",
            "source_id",
            "received_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(
            DeliveryStatus,
            name="status",
            native_enum=False,
            length=20,
            values_callable=_statuses,
            create_constraint=False,
        ),
        nullable=False,
    )
    # The sender's own id for it, when it gives one — webhook-id,
    # X-GitHub-Delivery, X-Request-Id: what its log and this one share.
    delivery_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # The resource it was, and what it held: records to store, ids gone.
    resource: Mapped[str | None] = mapped_column(String(40), nullable=True)
    records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    gone: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # What it was, as it came — for the pass, and let go after it.
    body: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Why it was rejected: {"reason", "message"} — never the body.
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The pass that stored it. Single-column, as source_records': SET NULL
    # through workspace_id would null the workspace too.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sync_runs.id", ondelete="SET NULL"), nullable=True
    )


# ── entity resolution (LEKA-357) ─────────────────────────────────────────────


class ResolvedEntity(Base, WorkspaceScopedMixin):
    """One real thing, as the workspace's sources show it: the candidates
    of `normalised_records` that entity resolution found to be one
    (leka/ingestion/resolution). What the company model is built from.

    MADE AGAIN WHOLE at each resolution run of the workspace, its id KEPT:
    the id a key had stays that key's, so what reads an entity by its id
    reads the same thing tomorrow.
    """

    __tablename__ = "resolved_entities"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_resolved_entities_workspace_id_id"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_resolved_entities_workspace_type_name", "workspace_id", "type", "name"),
    )

    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # The key that says it best (docs/resolution.md); every other it goes by
    # is in resolved_keys.
    key: Mapped[str] = mapped_column(String(1000), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    # Every name it goes by, the chosen one first.
    names: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    # What its sources say it is, one value each: where they disagree, the
    # chosen one — the disagreement is in `conflicts`, every value kept.
    attributes: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    conflicts: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # How sure the merges that made it are: 1.0 for one key, or keys that
    # say they are one another.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    sources: Mapped[int] = mapped_column(Integer, nullable=False)
    # The best quality validation gave the records that are it (LEKA-358);
    # none when no record of its own was validated — only named by others.
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolver_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResolvedKey(Base, WorkspaceScopedMixin):
    """A key a resolved entity goes by, as one source gave it — its own key,
    an alias it asserted, or one derived from it: the PROVENANCE of an
    entity, and how anything that holds a key finds it. A key two entities
    hold is an ambiguous one (a ticket key in two tools)."""

    __tablename__ = "resolved_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "entity_id"],
            ["resolved_entities.workspace_id", "resolved_entities.id"],
            name="fk_resolved_keys_workspace_entity",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_resolved_keys_workspace_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "entity_id", "key", "source_id", name="uq_resolved_keys_entity_key_source"
        ),
        CheckConstraint("kind IN ('key', 'alias', 'derived')", name="kind"),
        CheckConstraint("records >= 0 AND named >= 0", name="counts_not_negative"),
        Index("ix_resolved_keys_workspace_key", "workspace_id", "key"),
        Index("ix_resolved_keys_entity", "entity_id"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    key: Mapped[str] = mapped_column(String(1000), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    # How the source names it, and how often: as the record itself, and
    # as named by another record.
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    named: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A normalised_records row that says it. No foreign key: those rows are
    # replaced as their records change, and this is an example, not a link.
    example_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class ResolutionDecision(Base, WorkspaceScopedMixin):
    """What entity resolution decided, and why: a merge that made an entity,
    a link to another that is probably the same thing, or an ambiguity it
    would not guess — with its rule, its confidence and its evidence."""

    __tablename__ = "resolution_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "entity_id"],
            ["resolved_entities.workspace_id", "resolved_entities.id"],
            name="fk_resolution_decisions_workspace_entity",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "other_entity_id"],
            ["resolved_entities.workspace_id", "resolved_entities.id"],
            name="fk_resolution_decisions_workspace_other",
            ondelete="CASCADE",
        ),
        CheckConstraint("kind IN ('merge', 'link', 'ambiguous')", name="kind"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("(kind = 'link') = (other_entity_id IS NOT NULL)", name="link_has_other"),
        Index("ix_resolution_decisions_entity", "entity_id"),
        Index("ix_resolution_decisions_other", "other_entity_id"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # A link's other end; a merge and an ambiguity are within one entity.
    other_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    rule: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    evidence: Mapped[str] = mapped_column(String(1000), nullable=False)


class ResolutionRun(Base, WorkspaceScopedMixin):
    """One run of entity resolution over a workspace: when, from what
    (`fingerprint`: what normalisation had made by then), by which version,
    what it found — or the type of the error it stopped on."""

    __tablename__ = "resolution_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed', 'abandoned')", name="status"),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="finished_after_started"
        ),
        Index("ix_resolution_runs_workspace_started_at", "workspace_id", "started_at"),
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolver_version: Mapped[int] = mapped_column(Integer, nullable=False)
    counts: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)


# ── validation (LEKA-358) ────────────────────────────────────────────────────


class ValidationStatus(enum.StrEnum):
    VALID = "valid"
    # Usable; what is doubtful is said.
    WARNING = "warning"
    # An error: kept out of entity resolution, and so of the company model,
    # until its record is corrected — normalised again, validated again.
    QUARANTINED = "quarantined"


class ValidatedRecordRow(Base, WorkspaceScopedMixin):
    """What validation found of one normalised record (LEKA-358): its
    status, its issues and what to do about them, its quality and what made
    it — traceable to its source, its record and the run that validated it.

    ONE ROW PER normalised_records ROW THAT WAS NORMALISED, remade when that
    row is (its `normalised_at`) or the rules change (`validator_version`).
    Gone with it.
    """

    __tablename__ = "validated_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_id"],
            ["sources.workspace_id", "sources.id"],
            name="fk_validated_records_workspace_source",
            ondelete="CASCADE",
        ),
        UniqueConstraint("normalised_record_id", name="uq_validated_records_normalised_record"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _statuses(ValidationStatus)) + ")",
            name="status",
        ),
        CheckConstraint(
            "quality >= 0 AND quality <= 1 AND completeness >= 0 AND completeness <= 1 "
            "AND consistency >= 0 AND consistency <= 1 AND freshness >= 0 AND freshness <= 1 "
            "AND confidence >= 0 AND confidence <= 1",
            name="scores_range",
        ),
        Index("ix_validated_records_source_status", "source_id", "status"),
        Index("ix_validated_records_workspace_validated_at", "workspace_id", "validated_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    normalised_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("normalised_records.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[ValidationStatus] = mapped_column(
        Enum(
            ValidationStatus,
            name="status",
            native_enum=False,
            length=20,
            values_callable=_statuses,
            create_constraint=False,
        ),
        nullable=False,
    )
    # {code, severity, field, message, remediation} — never a record's value.
    issues: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    quality: Mapped[float] = mapped_column(Float, nullable=False)
    completeness: Mapped[float] = mapped_column(Float, nullable=False)
    consistency: Mapped[float] = mapped_column(Float, nullable=False)
    freshness: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # When a pass last saw its record: what freshness was measured from.
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The normalised row's own stamp: a row normalised again is validated again.
    normalised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validator_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The processing run that validated it. Single-column, as source_records':
    # SET NULL through workspace_id would null the workspace too.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_runs.id", ondelete="SET NULL"), nullable=True
    )
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
