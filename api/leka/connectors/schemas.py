"""Types the connectors module exposes to the rest of the codebase.

Two families. What a connector hands the sync engine (RawRecord,
SyncResult) — deliberately untyped payloads, because the vendor decides
their shape. And what the API reads and writes about a source.

NO SCHEMA HERE CAN CARRY A SECRET OUT. Credentials come in as a plain
mapping, are validated against the connector's SecretStr fields, and leave
only as a masked hint.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from leka.connectors.base import (
    Capability,
    ConnectionTestResult,
    ConnectorCategory,
    ScopeOption,
)
from leka.connectors.errors import Diagnostic
from leka.connectors.models import (
    HealthStatus,
    SourceEventType,
    SourceKind,
    SourceStatus,
    SyncStatus,
)
from leka.connectors.settings import Finding, SourceSettings


class RawRecord(BaseModel):
    """One object as its source described it, untouched.

    No source id: a connector does not know which source it is serving. The
    sync engine, which does, stores the record against it.
    """

    model_config = ConfigDict(frozen=True)

    kind: Capability
    # The vendor's own identifier, stable across renames where the vendor
    # has one (GitHub's node_id): what a later pass updates rather than
    # duplicates.
    external_id: str
    # Where it lives inside the source, for a human: "acme/api". None for
    # what lives at the top (a repository).
    container: str | None = None
    payload: dict[str, object]
    # When the vendor says it last changed; None when it does not say.
    updated_at: datetime | None = None
    fetched_at: datetime


class SyncResult(BaseModel):
    """What one pass over a source produced."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    records: int
    started_at: datetime
    finished_at: datetime
    error: str | None = None


# ── The API ─────────────────────────────────────────────────────────────────


class CatalogEntry(BaseModel):
    key: SourceKind
    display_name: str
    category: ConnectorCategory
    auth_type: str
    capabilities: list[Capability]
    read_only: bool
    config_schema: dict[str, object] = Field(description="JSON Schema of the settings.")
    credentials_schema: dict[str, object] = Field(
        description="JSON Schema of the secrets. Every field is write-only."
    )


class SourceCreate(BaseModel):
    type: SourceKind
    display_name: str = Field(min_length=1, max_length=200)
    config: dict[str, object] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(description="Write-only. Never returned.")


class SourceUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, object] | None = None


class CredentialsUpdate(BaseModel):
    credentials: dict[str, str] = Field(description="Write-only. Never returned.")


class CredentialsRead(BaseModel):
    hint: str = Field(description="Enough to recognise the secret, never to use it.")
    rotated_at: datetime


class SourceRead(BaseModel):
    id: uuid.UUID
    type: SourceKind
    display_name: str
    status: SourceStatus
    config: dict[str, object]
    capabilities: list[str]
    source_metadata: dict[str, object]
    health_status: HealthStatus
    last_health_check_at: datetime | None
    last_error: Diagnostic | None
    sync_status: SyncStatus
    last_sync_at: datetime | None
    credentials: CredentialsRead | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class SourceTestOutcome(BaseModel):
    """A test's answer. A failed test is an answer, not an HTTP error."""

    ok: bool
    result: ConnectionTestResult | None = None
    diagnostic: Diagnostic | None = None
    source: SourceRead


class ScopeOptionsRead(BaseModel):
    """What a source's scope can be chosen from. Like a test, a vendor that
    refuses is an answer: ok false, with its diagnostic."""

    ok: bool
    options: list[ScopeOption] = Field(default_factory=list)
    truncated: bool = False
    diagnostic: Diagnostic | None = None


class HealthRead(BaseModel):
    status: SourceStatus
    health_status: HealthStatus
    last_health_check_at: datetime | None
    last_error: Diagnostic | None


class SourceEventRead(BaseModel):
    id: uuid.UUID
    type: SourceEventType
    actor_user_id: uuid.UUID | None
    payload: dict[str, object]
    created_at: datetime


# ── Settings: scope rules and mapping (LEKA-351) ─────────────────────────────


class SourceSettingsRead(BaseModel):
    """A source's current settings. Version 0: never set, the defaults."""

    version: int
    settings: SourceSettings
    retention_policy_days: int | None = Field(
        default=None,
        description="LEKA's retention for this kind of source: the most a source may keep.",
    )


class SettingsCheck(BaseModel):
    findings: list[Finding]


class SettingsSaved(BaseModel):
    version: int
    changed: list[str] = Field(
        description="scope, mapping, retention — empty: nothing changed, no version."
    )
    findings: list[Finding] = Field(description="Warnings: saved, but worth a look.")
    full_sync_queued: bool = Field(
        description="The scope changed on an active source: a full pass follows."
    )


class SettingsVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    scope: dict[str, object]
    mapping: dict[str, object]
    retention: dict[str, object]
    created_by: uuid.UUID | None
    created_at: datetime
