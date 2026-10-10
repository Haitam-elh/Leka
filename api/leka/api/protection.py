"""Data protection, over HTTP (LEKA-405): how the platform protects data,
what LEKA found in the workspace's records, and what the workspace decides.

    GET /governance/data-protection          the platform's protections as they
                                             stand, the policy, per source what
                                             was found — counts, never a value
    PUT /governance/data-protection/policy   the policy changed; kept in the
                                             governance trail, before and after

Reading takes `access:read`, changing it `policy:manage` — both decided,
and kept, as every permission is (LEKA-402).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from leka.api.dependencies import SessionDep
from leka.api.errors import ApiError
from leka.connectors import Source
from leka.core.errors import ErrorCode
from leka.governance import GovernanceEvent, Permission, Principal, require_permission
from leka.ingestion import (
    PROTECTION_POLICY_KEY,
    ProtectionPolicyError,
    findings_by_source,
    protection_policy,
    set_protection_policy,
)
from leka.platform import Workspace, platform_posture

router = APIRouter(prefix="/governance/data-protection", tags=["governance"])

Auditor = Annotated[Principal, Depends(require_permission(Permission.ACCESS_READ))]
Manager = Annotated[Principal, Depends(require_permission(Permission.POLICY_MANAGE))]


class PostureRead(BaseModel):
    """The platform's protections, read from the running process."""

    model_config = ConfigDict(frozen=True)

    environment: str
    database_tls: bool | None = Field(description="PostgreSQL says this connection is TLS.")
    database_tls_version: str | None
    object_store: str = Field(description="s3, or local (never in production).")
    object_store_encryption: str | None = Field(
        description="What each write asks S3 to encrypt with: AES256, aws:kms; none: nothing."
    )
    credentials_encryption: str = Field(description="Credentials and endpoint secrets: fernet.")
    credential_keys: int = Field(description="Keys in use: more than one while a rotation runs.")
    session_cookie_secure: bool
    overdue_secrets: list[str] = Field(description="Secrets past their lifetime, by name.")


class ProtectionPolicyRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    found_payload_days: int = Field(
        description="A raw payload a secret or an identity number was found in: kept at most "
        "this many days from then."
    )
    customised: bool


class ProtectionPolicyUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    found_payload_days: int = Field(ge=1, le=30)


class SourceFindingsRead(BaseModel):
    """What one source's records carried — counts by kind, never a value."""

    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    name: str | None
    kind: str | None
    records: int
    scanned: int
    with_secrets: int
    secrets: dict[str, int]
    personal_data: dict[str, int]


class DataProtectionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    posture: PostureRead
    policy: ProtectionPolicyRead
    sources: list[SourceFindingsRead]


async def _policy_read(session: SessionDep, workspace_id: uuid.UUID) -> ProtectionPolicyRead:
    policy = await protection_policy(session, workspace_id)
    workspace = await session.get(Workspace, workspace_id)
    said = workspace.settings.get(PROTECTION_POLICY_KEY) if workspace is not None else None
    return ProtectionPolicyRead(
        found_payload_days=policy.found_payload_days, customised=said is not None
    )


@router.get("", response_model=DataProtectionRead)
async def data_protection(principal: Auditor, session: SessionDep) -> DataProtectionRead:
    """The platform's protections as they stand now, the workspace's policy,
    and per source what LEKA found in its records and took out."""
    posture = await platform_posture(session)
    found = await findings_by_source(session, principal.workspace_id)
    sources = {
        s.id: s
        for s in await session.scalars(
            select(Source).where(Source.workspace_id == principal.workspace_id)
        )
    }
    return DataProtectionRead(
        posture=PostureRead(
            environment=posture.environment,
            database_tls=posture.database_tls,
            database_tls_version=posture.database_tls_version,
            object_store=posture.object_store,
            object_store_encryption=posture.object_store_encryption,
            credentials_encryption=posture.credentials_encryption,
            credential_keys=posture.credential_keys,
            session_cookie_secure=posture.session_cookie_secure,
            overdue_secrets=list(posture.overdue_secrets),
        ),
        policy=await _policy_read(session, principal.workspace_id),
        sources=[
            SourceFindingsRead(
                source_id=f.source_id,
                name=sources[f.source_id].name if f.source_id in sources else None,
                kind=sources[f.source_id].kind.value if f.source_id in sources else None,
                records=f.records,
                scanned=f.scanned,
                with_secrets=f.with_secrets,
                secrets=dict(f.secrets),
                personal_data=dict(f.personal_data),
            )
            for f in found
        ],
    )


@router.put("/policy", response_model=ProtectionPolicyRead)
async def set_policy(
    payload: ProtectionPolicyUpdate, principal: Manager, session: SessionDep
) -> ProtectionPolicyRead:
    """Changed from now on: what was found before keeps the expiry it was
    given, what is found next gets this one. Kept in the governance trail."""
    try:
        before, after = await set_protection_policy(
            session, principal.workspace_id, payload.model_dump()
        )
    except ProtectionPolicyError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_FAILED, str(error)
        ) from error
    if after != before:
        session.add(
            GovernanceEvent(
                workspace_id=principal.workspace_id,
                id=uuid.uuid4(),
                subject_type="protection",
                subject_id="data_protection",
                kind="updated",
                by=principal.user_id,
                at=datetime.now(UTC),
                before=before.to_settings(),
                after=after.to_settings(),
            )
        )
    await session.commit()
    return await _policy_read(session, principal.workspace_id)
