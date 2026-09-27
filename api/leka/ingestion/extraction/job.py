"""Extracting a source's records, after each pass (LEKA-354).

Queued at the end of a pass that left something to extract (key
`extract:<source_id>`, one at a time per source), beside the purge. It:

1. forgets what was extracted from records marked deleted;
2. reads, in id order, the live records that need extracting — never
   extracted, changed since (`checksum`), or extracted by another version of
   their strategy — grouped by the batch holding their latest version;
3. reads each batch once, finds each record's line by its identity AND its
   checksum, extracts it, and saves the result — or the failure — batch by
   batch;
4. queues the parsing (LEKA-355) when there is something to parse.

INCREMENTAL, AND IDEMPOTENT. A record extracted from the checksum the index
has, by the current version, is not read again: a second run finds nothing
and reads nothing.

A PASS OR A PURGE MAY RUN BESIDE IT. A batch the purge has rewritten since
is not found: its records are passed over, and the next run reads them from
their new batch. A record a pass changed since is found with its old
checksum, or not at all: either way its row does not match the index, and
the next run extracts it again. Nothing is extracted from what the index no
longer vouches for.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, datetime

import structlog
from pydantic import ValidationError

from leka.background import enqueue_job
from leka.connectors import RawRecord, Source, SourceKind
from leka.db import session_factory, workspace_scope
from leka.ingestion.checksum import checksum
from leka.ingestion.extraction.contract import ExtractedRecord
from leka.ingestion.extraction.engine import extract, strategy_for, supported
from leka.ingestion.models import ExtractionStatus, SourceRecord
from leka.ingestion.parsing.engine import PARSER_VERSION
from leka.ingestion.parsing.job import PARSE_JOB
from leka.ingestion.parsing.job import concurrency_key as parse_key
from leka.ingestion.repository import ExtractionRepository, ParsingRepository
from leka.platform import ObjectStore, ObjectStoreError, object_store

logger = structlog.get_logger(__name__)

EXTRACT_JOB = "leka.ingestion.extraction.job.run_extraction"
CHUNK = 1000  # records per read of the index; batches hold up to 500


def concurrency_key(source_id: uuid.UUID) -> str:
    return f"extract:{source_id}"


def versions(kind: SourceKind) -> dict[str, int | None]:
    """Per capability, the version of the strategy that extracts it for this
    kind of source."""
    return {
        capability.value: found.version
        for source_kind, capability in supported()
        if source_kind is kind and (found := strategy_for(source_kind, capability)) is not None
    }


def run_extraction(workspace_id: str, source_id: str) -> dict[str, int]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(extract_source(uuid.UUID(workspace_id), uuid.UUID(source_id)))


async def extract_source(workspace_id: uuid.UUID, source_id: uuid.UUID) -> dict[str, int]:
    """Extract what the source's index says needs it. Idempotent."""
    result = {"extracted": 0, "failed": 0, "passed_over": 0, "forgotten": 0}
    store = object_store()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            source = await session.get(Source, source_id)
            if source is None:  # deleted since the job was queued
                return result
            repository = ExtractionRepository(session, workspace_id)
            result["forgotten"] = await repository.forget_deleted(source_id)
            await session.commit()

            wanted = versions(source.kind)
            after: uuid.UUID | None = None
            while records := await repository.stale(source_id, wanted, after=after, limit=CHUNK):
                after = records[-1].id
                by_batch: dict[str, list[SourceRecord]] = defaultdict(list)
                for record in records:
                    by_batch[str(record.payload_key)].append(record)
                for key, batch in by_batch.items():
                    rows = await _extract_batch(store, source, key, batch, result)
                    await repository.save(rows)
                    await session.commit()

            # What was extracted is parsed next (leka/ingestion/parsing/job.py).
            if await ParsingRepository(session, workspace_id).has_stale(source_id, PARSER_VERSION):
                await enqueue_job(
                    PARSE_JOB,
                    str(workspace_id),
                    str(source_id),
                    for_workspace_id=workspace_id,
                    concurrency_key=parse_key(source_id),
                )

    logger.info("source_extracted", source_id=str(source_id), **result)
    return result


async def _extract_batch(
    store: ObjectStore,
    source: Source,
    key: str,
    records: list[SourceRecord],
    result: dict[str, int],
) -> list[dict[str, object]]:
    """The rows for these records, from the one batch holding them."""
    try:
        body = b"".join([chunk async for chunk in store.get(key)])
    except ObjectStoreError:
        # Rewritten or withdrawn by the purge since: the next run finds them.
        result["passed_over"] += len(records)
        return []
    lines: dict[tuple[str, str, str], RawRecord] = {}
    for line in body.splitlines():
        try:
            raw = RawRecord.model_validate_json(line)
        except ValidationError:
            continue  # a capability no longer known: not ours to extract
        lines[(raw.kind.value, raw.external_id, checksum(raw))] = raw

    now = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    for record in records:
        found = lines.get((record.kind, record.external_id, record.checksum))
        if found is None:
            result["passed_over"] += 1
            continue
        outcome = extract(found, source_id=source.id, source_kind=source.kind, payload_key=key)
        row: dict[str, object] = {
            "source_id": source.id,
            "source_record_id": record.id,
            "kind": record.kind,
            "extractor": outcome.extractor,
            "extractor_version": outcome.extractor_version,
            "checksum": record.checksum,
            "extracted_at": now,
        }
        if isinstance(outcome, ExtractedRecord):
            result["extracted"] += 1
            row |= {
                "status": ExtractionStatus.EXTRACTED,
                "result": outcome.model_dump(mode="json"),
                "failure_code": None,
                "message": None,
            }
        else:
            result["failed"] += 1
            row |= {
                "status": ExtractionStatus.FAILED,
                "result": None,
                "failure_code": outcome.code.value,
                "message": outcome.message[:500],
            }
        rows.append(row)
    return rows
