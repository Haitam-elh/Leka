"""Removing deleted records from the stored batches (LEKA-353).

A record the index marks deleted — gone at the vendor, a page made
restricted, a repository out of scope — must not stay in LEKA's store until
retention: that is the permission boundary (Haitam, 2026-09-27). The pass
only marks it; this job, queued at the end of a pass that left something to
purge, rewrites the batches without it. The pass stays fast and can be run
again; the purge follows within minutes.

WHAT IS REMOVED IS CHECKED AGAIN, batch by batch, with the index rows
locked until that batch commits: a pass (sync:<source_id>) can run beside
this job (purge:<source_id>), and a record seen again since the job started
must keep its line — otherwise its only copy would go, and the index would
point at a batch that no longer holds it.

EVERY live batch of the source is read, not only the one holding a record's
latest version: a record that changed three times is in three batches, and
all three hold what is no longer ours to keep. It runs only when there is
something to purge, and it is idempotent — a batch with nothing deleted in
it is left untouched, so a second run finds nothing and writes nothing.

For each batch that holds deleted records:

    only deleted records     the row is withdrawn (deleted_at); the retention
                             sweep removes the object within the hour
    some                     rewritten without them, under a NEW key: the new
                             object first, then the row and the index point
                             at it and commit, then the old object is deleted
                             — an old object left by a crash is an orphan the
                             reconciliation removes

The new key is dated now, not with the original fetch: reconciliation reads
an object's age from its key, and an old date on an object whose row has not
committed yet would make it look like an orphan.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

import structlog

from leka.db import session_factory, workspace_scope
from leka.ingestion.repository import RawPayloadRepository, SourceRecordRepository
from leka.platform import ObjectStoreError, from_bytes, object_key, object_store

logger = structlog.get_logger(__name__)

PURGE_JOB = "leka.ingestion.purge.run_purge_deleted"
CONTENT_TYPE = "application/x-ndjson"


def concurrency_key(source_id: uuid.UUID) -> str:
    return f"purge:{source_id}"


def run_purge_deleted(workspace_id: str, source_id: str) -> dict[str, int]:
    """Entry point for the job runner, which is synchronous."""
    return asyncio.run(purge_deleted(uuid.UUID(workspace_id), uuid.UUID(source_id)))


async def purge_deleted(workspace_id: uuid.UUID, source_id: uuid.UUID) -> dict[str, int]:
    """Rewrite the source's batches without its deleted records. Idempotent."""
    result = {"examined": 0, "rewritten": 0, "withdrawn": 0, "records_removed": 0}
    store = object_store()
    with workspace_scope(workspace_id):
        async with session_factory() as session:
            records = SourceRecordRepository(session, workspace_id)
            payloads = RawPayloadRepository(session, workspace_id)
            gone = await records.pending_purge(source_id)
            if not gone:
                return result

            for payload in await payloads.all_for_source(source_id):
                result["examined"] += 1
                lines = (
                    b"".join([chunk async for chunk in store.get(payload.object_key)])
                ).splitlines()
                candidates = {_identity(line) for line in lines} & gone
                if not candidates:
                    continue
                # Checked again now, rows locked until this batch commits: one
                # seen again by a pass since `gone` was read keeps its line —
                # and the pass that revives it waits for this batch.
                removing = await records.still_deleted(source_id, candidates)
                kept = [line for line in lines if _identity(line) not in removing]
                if len(kept) == len(lines):
                    await session.commit()  # release the locks
                    continue
                result["records_removed"] += len(lines) - len(kept)

                if not kept:
                    payloads.mark_deleted(payload)
                    await session.commit()
                    result["withdrawn"] += 1
                    continue

                old_key = payload.object_key
                new_key = object_key(workspace_id, source_id, datetime.now(UTC), extension="jsonl")
                stored = await store.put(
                    new_key, from_bytes(b"\n".join(kept)), content_type=CONTENT_TYPE
                )
                payload.object_key = new_key
                payload.size_bytes = stored.size_bytes
                payload.checksum_sha256 = stored.checksum_sha256
                await records.move_payload(source_id, old_key, new_key)
                await session.commit()
                try:
                    await store.delete(old_key)
                except ObjectStoreError as error:
                    # The row no longer claims it: reconciliation will remove it.
                    logger.warning("purged_object_not_deleted", key=old_key, error=str(error))
                result["rewritten"] += 1

            # Every batch was read: no copy of these is left anywhere.
            await records.purged(source_id, gone)
            await session.commit()

    logger.info("deleted_records_purged", source_id=str(source_id), **result)
    return result


def _identity(line: bytes) -> tuple[str, str]:
    record = json.loads(line)
    return str(record["kind"]), str(record["external_id"])
