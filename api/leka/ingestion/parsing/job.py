"""Parsing a source's extractions (LEKA-355).

Queued when the extraction ends with something to parse — or by the end of
a pass when only parsing has something to do (a new PARSER_VERSION) — with
the key `parse:<source_id>`, one at a time per source. It:

1. forgets the parse of extractions that failed since;
2. reads, in id order, the extractions that need parsing — never parsed, or
   parsed from another checksum, extractor version or parser version;
3. parses each from its stored result and saves the rows chunk by chunk;
4. records its run, then queues the next stage that has work
   (leka/ingestion/pipeline.py).

Everything it reads is in the database: no object store, nothing to pass
over. Incremental and idempotent like the extraction: a second run reads
nothing.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from leka.connectors import Source
from leka.db import session_factory, workspace_scope
from leka.ingestion.models import ExtractedRecordRow, ParseStatus, ProcessingStage
from leka.ingestion.parsing import engine
from leka.ingestion.parsing.contract import ParsedRecord
from leka.ingestion.parsing.engine import parse_stored
from leka.ingestion.pipeline import BY_NAME, advance, stage_run
from leka.ingestion.repository import ParsingRepository

logger = structlog.get_logger(__name__)

PARSE_JOB = BY_NAME[ProcessingStage.PARSING].job
CHUNK = 500


def run_parsing(workspace_id: str, source_id: str) -> dict[str, int]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(parse_source(uuid.UUID(workspace_id), uuid.UUID(source_id)))


async def parse_source(workspace_id: uuid.UUID, source_id: uuid.UUID) -> dict[str, int]:
    """Parse what the source's extractions say needs it, then queue the next
    stage. Idempotent."""
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None:  # deleted since the job was queued
                return {}
            async with stage_run(workspace_id, source, ProcessingStage.PARSING) as result:
                result.update(parsed=0, failed=0, forgotten=0)
                repository = ParsingRepository(session, workspace_id)
                result["forgotten"] = await repository.forget_unparseable(source_id)
                await session.commit()

                after: uuid.UUID | None = None
                while extractions := await repository.stale(
                    source_id, engine.PARSER_VERSION, after=after, limit=CHUNK
                ):
                    after = extractions[-1].id
                    await repository.save([_row(e, result) for e in extractions])
                    await session.commit()
            # Recorded as succeeded: what was parsed is normalised next.
            await advance(session, workspace_id, source, after=ProcessingStage.PARSING)

    logger.info("source_parsed", source_id=str(source_id), **result)
    return dict(result)


def _row(extraction: ExtractedRecordRow, result: dict[str, int]) -> dict[str, object]:
    outcome = parse_stored(extraction.result)
    row: dict[str, object] = {
        "source_id": extraction.source_id,
        "extracted_record_id": extraction.id,
        "kind": extraction.kind,
        "checksum": extraction.checksum,
        "extractor_version": extraction.extractor_version,
        "parser_version": engine.PARSER_VERSION,
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
