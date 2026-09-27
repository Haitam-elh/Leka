"""Normalising a source's parses (LEKA-356).

Queued when the parsing ends with something to normalise — or by the end
of a pass when only normalisation has something to do (a new
NORMALISER_VERSION) — with the key `normalise:<source_id>`, one at a time
per source. It:

1. forgets the candidates of parses that failed since;
2. reads, in id order, the parses that need normalising — never normalised,
   or normalised from another checksum or version — with their extraction;
3. normalises each and saves the rows chunk by chunk.

Everything it reads is in the database. Incremental and idempotent, like the
two stages before it.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from leka.connectors import Source
from leka.db import session_factory, workspace_scope
from leka.ingestion.models import (
    ExtractedRecordRow,
    NormalisationStatus,
    ParsedRecordRow,
    ProcessingStage,
)
from leka.ingestion.normalisation import engine
from leka.ingestion.normalisation.contract import NormalisedRecord
from leka.ingestion.pipeline import BY_NAME, stage_run
from leka.ingestion.repository import NormalisationRepository

logger = structlog.get_logger(__name__)

NORMALISE_JOB = BY_NAME[ProcessingStage.NORMALISATION].job
CHUNK = 500


def run_normalisation(workspace_id: str, source_id: str) -> dict[str, int]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(normalise_source(uuid.UUID(workspace_id), uuid.UUID(source_id)))


async def normalise_source(workspace_id: uuid.UUID, source_id: uuid.UUID) -> dict[str, int]:
    """Normalise what the source's parses say needs it. Idempotent. The last
    stage: nothing is queued after it."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None:  # deleted since the job was queued
                return {}
            async with stage_run(workspace_id, source, ProcessingStage.NORMALISATION) as result:
                result.update(normalised=0, failed=0, forgotten=0)
                repository = NormalisationRepository(session, workspace_id)
                result["forgotten"] = await repository.forget_unnormalisable(source_id)
                await session.commit()

                after: uuid.UUID | None = None
                while pairs := await repository.stale(
                    source_id, engine.NORMALISER_VERSION, after=after, limit=CHUNK
                ):
                    after = pairs[-1][0].id
                    await repository.save(
                        [_row(parsed, extracted, result) for parsed, extracted in pairs]
                    )
                    await session.commit()

    logger.info("source_normalised", source_id=str(source_id), **result)
    return dict(result)


def _row(
    parsed: ParsedRecordRow, extracted: ExtractedRecordRow, result: dict[str, int]
) -> dict[str, object]:
    outcome = engine.normalise_stored(extracted.result, parsed.result)
    row: dict[str, object] = {
        "source_id": parsed.source_id,
        "parsed_record_id": parsed.id,
        "kind": parsed.kind,
        "checksum": parsed.checksum,
        "extractor_version": parsed.extractor_version,
        "parser_version": parsed.parser_version,
        "normaliser_version": engine.NORMALISER_VERSION,
        "normalised_at": datetime.now(UTC),
    }
    if isinstance(outcome, NormalisedRecord):
        result["normalised"] += 1
        return row | {
            "status": NormalisationStatus.NORMALISED,
            "entity_type": outcome.entity.type,
            "entity_key": outcome.entity.key[:1000],
            "result": outcome.model_dump(mode="json"),
            "failure_code": None,
            "message": None,
        }
    result["failed"] += 1
    return row | {
        "status": NormalisationStatus.FAILED,
        "entity_type": None,
        "entity_key": None,
        "result": None,
        "failure_code": outcome.code.value,
        "message": outcome.message[:500],
    }
