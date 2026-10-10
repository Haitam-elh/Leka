"""Sensitive data in what LEKA ingests (LEKA-405): found, taken out,
counted, and its original kept no longer than it must be.

    extraction    every record is protected before it is kept (protect()):
                  a secret, an IBAN, a card, a social security number in it
                  replaced by [redacted:<what>]; what was found — kinds and
                  counts, never a value — kept with it (`sensitivity`).
                  Parsing, the company model, the search index, contexts and
                  every prompt read the protected record: no copy of what
                  was taken out is made downstream.
    the original  the raw payload a secret or an identity number was found
                  in is kept at most the workspace's `found_payload_days`
                  (7 by default) from then — never longer than its source's
                  retention would keep it.
    the sweep     what was kept before, or under an older detector, is
                  scanned in place, the same way (run_protection_sweep).

The detector is core.sensitive's — one for all of LEKA.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import Integer, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.core.sensitive import SENSITIVE_VERSION, TAKEN_OUT, Protected, protect, taken_out
from leka.db import session_factory, system_scope, workspace_scope
from leka.ingestion.models import ExtractedRecordRow, ExtractionStatus, RawPayload
from leka.platform import Workspace

logger = structlog.get_logger(__name__)

POLICY_KEY = "data_protection"
# How many records a sweep scans in one workspace, per pass.
SWEEP_BATCH = 1000


class ProtectionPolicyError(ValueError):
    """A data protection policy that cannot be kept."""


@dataclass(frozen=True)
class ProtectionPolicy:
    """What a workspace decides of its protected data."""

    # The raw payload a secret or an identity number was found in: kept at
    # most this many days from then.
    found_payload_days: int = 7

    def to_settings(self) -> dict[str, object]:
        return {"found_payload_days": self.found_payload_days}

    @classmethod
    def from_settings(cls, said: object) -> ProtectionPolicy:
        if said is None:
            return cls()
        if not isinstance(said, Mapping):
            raise ProtectionPolicyError("The data protection policy is an object.")
        days = said.get("found_payload_days", cls.found_payload_days)
        if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 30:
            raise ProtectionPolicyError("found_payload_days: between 1 and 30.")
        return cls(found_payload_days=days)


async def protection_policy(session: AsyncSession, workspace_id: uuid.UUID) -> ProtectionPolicy:
    workspace = await session.get(Workspace, workspace_id)
    said = workspace.settings.get(POLICY_KEY) if workspace is not None else None
    try:
        return ProtectionPolicy.from_settings(said)
    except ProtectionPolicyError:
        return ProtectionPolicy()


async def set_protection_policy(
    session: AsyncSession, workspace_id: uuid.UUID, change: Mapping[str, object]
) -> tuple[ProtectionPolicy, ProtectionPolicy]:
    """The policy changed — before and after; ProtectionPolicyError when it
    cannot be."""
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        msg = "the workspace is gone"
        raise LookupError(msg)
    before = await protection_policy(session, workspace_id)
    after = ProtectionPolicy.from_settings({**before.to_settings(), **dict(change)})
    workspace.settings = {**workspace.settings, POLICY_KEY: after.to_settings()}
    await session.flush()
    return before, after


def protected(result: Mapping[str, Any]) -> Protected:
    """An extracted record as kept: what it carried taken out, counted."""
    return protect(result)


def holds_taken_out(protected_: Protected) -> bool:
    """Whether something was taken out of it: its original holds it."""
    return bool(protected_.secrets) or any(k in TAKEN_OUT for k in protected_.personal_data)


async def shorten_payloads(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    keys: Iterable[str],
    *,
    days: int,
    now: datetime | None = None,
) -> int:
    """The raw payloads at these keys, kept at most `days` from now — the
    earlier of that and their own expiry."""
    wanted = sorted({k for k in keys if k})
    if not wanted:
        return 0
    until = (now or datetime.now(UTC)) + timedelta(days=days)
    result = await session.execute(
        update(RawPayload)
        .where(
            RawPayload.workspace_id == workspace_id,
            RawPayload.object_key.in_(wanted),
            RawPayload.expires_at > until,
        )
        .values(expires_at=until)
    )
    return int(getattr(result, "rowcount", 0) or 0)


def _payload_key(result: Mapping[str, Any]) -> str | None:
    provenance = result.get("provenance")
    key = provenance.get("payload_key") if isinstance(provenance, Mapping) else None
    return str(key) if key else None


def _unscanned() -> Any:
    return (ExtractedRecordRow.status == ExtractionStatus.EXTRACTED) & or_(
        ExtractedRecordRow.sensitivity.is_(None),
        cast(ExtractedRecordRow.sensitivity["version"].astext, Integer) < SENSITIVE_VERSION,
    )


async def sweep_workspace(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    limit: int = SWEEP_BATCH,
    now: datetime | None = None,
) -> dict[str, int]:
    """Records kept before, or under an older detector, protected in place —
    and their originals' retention shortened when something was taken out."""
    rows = (
        await session.scalars(
            select(ExtractedRecordRow)
            .where(ExtractedRecordRow.workspace_id == workspace_id, _unscanned())
            .order_by(ExtractedRecordRow.id)
            .limit(limit)
        )
    ).all()
    counts = Counter[str]()
    keys: list[str] = []
    for row in rows:
        found = protected(row.result or {})
        if found.found and found.value != row.result:
            row.result = found.value  # type: ignore[assignment]
        row.sensitivity = found.summary()
        counts["scanned"] += 1
        counts["secrets"] += sum(found.secrets.values())
        if holds_taken_out(found):
            counts["taken_out"] += 1
            key = _payload_key(row.result or {})
            if key:
                keys.append(key)
    if keys:
        policy = await protection_policy(session, workspace_id)
        counts["payloads_shortened"] = await shorten_payloads(
            session, workspace_id, keys, days=policy.found_payload_days, now=now
        )
    await session.flush()
    return dict(counts)


async def protection_sweep(*, now: datetime | None = None) -> dict[str, int]:
    """Every workspace's records not yet scanned, a batch each."""
    with system_scope():
        async with session_factory() as session:
            workspaces = (
                await session.scalars(
                    select(ExtractedRecordRow.workspace_id).where(_unscanned()).distinct()
                )
            ).all()
    total = Counter[str](workspaces=len(workspaces))
    for workspace_id in workspaces:
        with workspace_scope(workspace_id):
            async with session_factory() as session:
                total.update(await sweep_workspace(session, workspace_id, now=now))
                await session.commit()
    if total.get("scanned"):
        logger.info("protection_sweep", **total)
    return dict(total)


def run_protection_sweep() -> dict[str, int]:
    """Entry point for the schedule."""
    return asyncio.run(protection_sweep())


@dataclass(frozen=True)
class SourceFindings:
    """What one source's records carried, as the detector found it."""

    source_id: uuid.UUID
    records: int
    scanned: int
    with_secrets: int
    secrets: Mapping[str, int]
    personal_data: Mapping[str, int]


async def findings_by_source(
    session: AsyncSession, workspace_id: uuid.UUID
) -> list[SourceFindings]:
    """Per source: how many records, how many scanned, what was found —
    counts by kind, never a value."""
    totals = (
        await session.execute(
            select(
                ExtractedRecordRow.source_id,
                func.count(),
                func.count(ExtractedRecordRow.sensitivity),
            )
            .where(
                ExtractedRecordRow.workspace_id == workspace_id,
                ExtractedRecordRow.status == ExtractionStatus.EXTRACTED,
            )
            .group_by(ExtractedRecordRow.source_id)
        )
    ).tuples()
    kinds = (
        await session.execute(
            select(ExtractedRecordRow.source_id, ExtractedRecordRow.sensitivity).where(
                ExtractedRecordRow.workspace_id == workspace_id,
                ExtractedRecordRow.status == ExtractionStatus.EXTRACTED,
                ExtractedRecordRow.sensitivity.is_not(None),
                or_(
                    ExtractedRecordRow.sensitivity["secrets"].astext != "{}",
                    ExtractedRecordRow.sensitivity["personal_data"].astext != "{}",
                ),
            )
        )
    ).tuples()
    secrets: dict[uuid.UUID, Counter[str]] = {}
    personal: dict[uuid.UUID, Counter[str]] = {}
    with_secrets: Counter[uuid.UUID] = Counter()

    def counts(said: object) -> dict[str, int]:
        if not isinstance(said, Mapping):
            return {}
        return {str(k): int(v) for k, v in said.items() if isinstance(v, int)}

    for source_id, said in kinds:
        found_secrets = counts((said or {}).get("secrets"))
        if found_secrets:
            with_secrets[source_id] += 1
        secrets.setdefault(source_id, Counter()).update(found_secrets)
        personal.setdefault(source_id, Counter()).update(counts((said or {}).get("personal_data")))
    return [
        SourceFindings(
            source_id=source_id,
            records=records,
            scanned=scanned,
            with_secrets=with_secrets[source_id],
            secrets=dict(sorted(secrets.get(source_id, Counter()).items())),
            personal_data=dict(sorted(personal.get(source_id, Counter()).items())),
        )
        for source_id, records, scanned in totals
    ]


__all__ = [
    "POLICY_KEY",
    "ProtectionPolicy",
    "ProtectionPolicyError",
    "SourceFindings",
    "findings_by_source",
    "holds_taken_out",
    "protected",
    "protection_policy",
    "protection_sweep",
    "run_protection_sweep",
    "set_protection_policy",
    "shorten_payloads",
    "sweep_workspace",
    "taken_out",
]
