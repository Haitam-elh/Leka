"""Validating a source's normalised records (LEKA-358).

Queued when the normalisation ends — or by the end of a pass when only
validation has something to do (a new VALIDATOR_VERSION, a record whose
freshness is to be measured again after a full pass) — with the key
`validate:<source_id>`, one at a time per source. It:

1. forgets the validation of records that failed normalisation since;
2. reads, in id order, the normalised records that need validating — never
   validated, normalised again since, or validated by another version —
   with when a pass last saw each;
3. validates each (rules.py) and saves the rows chunk by chunk, each
   traced to this run;

then hands over: `advance`, which, with nothing left for the source,
queues the workspace's entity resolution — which leaves quarantined records
out.

Everything it reads is in the database. Incremental and idempotent, like
the stages before it.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from leka.connectors import Source
from leka.db import session_factory, workspace_scope
from leka.ingestion.models import NormalisedRecordRow, ProcessingStage
from leka.ingestion.pipeline import BY_NAME, advance, stage_run
from leka.ingestion.repository import ValidationRepository
from leka.ingestion.validation.rules import VALIDATOR_VERSION, validate

logger = structlog.get_logger(__name__)

VALIDATE_JOB = BY_NAME[ProcessingStage.VALIDATION].job
CHUNK = 500


def run_validation(workspace_id: str, source_id: str) -> dict[str, int]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(validate_source(uuid.UUID(workspace_id), uuid.UUID(source_id)))


async def validate_source(workspace_id: uuid.UUID, source_id: uuid.UUID) -> dict[str, int]:
    """Validate what the source's normalised records say needs it. Idempotent."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None:  # deleted since the job was queued
                return {}
            run: dict[str, uuid.UUID] = {}
            async with stage_run(
                workspace_id, source, ProcessingStage.VALIDATION, run_ids=run
            ) as result:
                result.update(valid=0, warning=0, quarantined=0, forgotten=0)
                repository = ValidationRepository(session, workspace_id)
                result["forgotten"] = await repository.forget_unvalidatable(source_id)
                await session.commit()

                duplicates = await repository.duplicate_keys(source_id)
                after: uuid.UUID | None = None
                while pairs := await repository.stale(
                    source_id, VALIDATOR_VERSION, after=after, limit=CHUNK
                ):
                    after = pairs[-1][0].id
                    now = datetime.now(UTC)
                    await repository.save(
                        [
                            _row(normalised, seen_at, duplicates, run.get("run"), now, result)
                            for normalised, seen_at in pairs
                        ]
                    )
                    await session.commit()
            await advance(session, workspace_id, source, after=ProcessingStage.VALIDATION)

    logger.info("source_validated", source_id=str(source_id), **result)
    return dict(result)


def _row(
    normalised: NormalisedRecordRow,
    seen_at: datetime | None,
    duplicates: set[str],
    run_id: uuid.UUID | None,
    now: datetime,
    result: dict[str, int],
) -> dict[str, object]:
    found = validate(
        normalised.result,
        seen_at=seen_at,
        now=now,
        duplicate=normalised.entity_key in duplicates,
    )
    result[found.status] += 1
    return {
        "source_id": normalised.source_id,
        "normalised_record_id": normalised.id,
        "kind": normalised.kind,
        "entity_type": normalised.entity_type,
        "entity_key": normalised.entity_key,
        "status": found.status,
        "issues": [issue.as_dict() for issue in found.issues],
        "quality": found.quality,
        "completeness": found.completeness,
        "consistency": found.consistency,
        "freshness": found.freshness,
        "confidence": found.confidence,
        "seen_at": seen_at,
        "normalised_at": normalised.normalised_at,
        "validator_version": VALIDATOR_VERSION,
        "run_id": run_id,
        "validated_at": now,
    }
