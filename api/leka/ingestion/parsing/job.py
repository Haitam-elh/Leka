"""Parsing a source's extractions (LEKA-355).

Queued by the extraction job when it ends with something to parse — and by
the end of a pass when only parsing has something to do (a new
PARSER_VERSION) — with the key `parse:<source_id>`, one at a time per
source. It:

1. forgets the parse of extractions that failed since;
2. reads, in id order, the extractions that need parsing — never parsed, or
   parsed from another checksum, extractor version or parser version;
3. parses each from its stored result and saves the rows chunk by chunk;
4. queues the normalisation (LEKA-356) when there is something to normalise.

Everything it reads is in the database: no object store, nothing to pass
over. Incremental and idempotent like the extraction: a second run reads
nothing.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from leka.background import enqueue_job
from leka.connectors import Source
from leka.db import session_factory, workspace_scope
from leka.ingestion.models import ExtractedRecordRow, ParseStatus
from leka.ingestion.normalisation.engine import NORMALISER_VERSION
from leka.ingestion.normalisation.job import NORMALISE_JOB
from leka.ingestion.normalisation.job import concurrency_key as normalise_key
from leka.ingestion.parsing.contract import ParsedRecord
from leka.ingestion.parsing.engine import PARSER_VERSION, parse_stored
from leka.ingestion.repository import NormalisationRepository, ParsingRepository

logger = structlog.get_logger(__name__)

PARSE_JOB = "leka.ingestion.parsing.job.run_parsing"
CHUNK = 500


def concurrency_key(source_id: uuid.UUID) -> str:
    return f"parse:{source_id}"


def run_parsing(workspace_id: str, source_id: str) -> dict[str, int]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(parse_source(uuid.UUID(workspace_id), uuid.UUID(source_id)))


async def parse_source(workspace_id: uuid.UUID, source_id: uuid.UUID) -> dict[str, int]:
    """Parse what the source's extractions say needs it. Idempotent."""
    result = {"parsed": 0, "failed": 0, "forgotten": 0}
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            if await session.get(Source, source_id) is None:  # deleted since
                return result
            repository = ParsingRepository(session, workspace_id)
            result["forgotten"] = await repository.forget_unparseable(source_id)
            await session.commit()

            after: uuid.UUID | None = None
            while extractions := await repository.stale(
                source_id, PARSER_VERSION, after=after, limit=CHUNK
            ):
                after = extractions[-1].id
                await repository.save([_row(e, result) for e in extractions])
                await session.commit()

            # What was parsed is normalised next (leka/ingestion/normalisation/job.py).
            normalisation = NormalisationRepository(session, workspace_id)
            if await normalisation.has_stale(source_id, NORMALISER_VERSION):
                await enqueue_job(
                    NORMALISE_JOB,
                    str(workspace_id),
                    str(source_id),
                    for_workspace_id=workspace_id,
                    concurrency_key=normalise_key(source_id),
                )

    logger.info("source_parsed", source_id=str(source_id), **result)
    return result


def _row(extraction: ExtractedRecordRow, result: dict[str, int]) -> dict[str, object]:
    outcome = parse_stored(extraction.result)
    row: dict[str, object] = {
        "source_id": extraction.source_id,
        "extracted_record_id": extraction.id,
        "kind": extraction.kind,
        "checksum": extraction.checksum,
        "extractor_version": extraction.extractor_version,
        "parser_version": PARSER_VERSION,
        "parsed_at": datetime.now(UTC),
    }
    if isinstance(outcome, ParsedRecord):
        result["parsed"] += 1
        return row | {
            "status": ParseStatus.PARSED,
            "result": outcome.model_dump(mode="json"),
            "failure_code": None,
            "message": None,
        }
    result["failed"] += 1
    return row | {
        "status": ParseStatus.FAILED,
        "result": None,
        "failure_code": outcome.code.value,
        "message": outcome.message[:500],
    }
