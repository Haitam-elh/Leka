"""Background work for ingestion: enforcing retention, and catching what escapes.

Two sweeps that answer two different questions.

    sweep_expired_payloads   what have we kept longer than we said we would?
    reconcile_orphaned       what is in the store that no row speaks for?

The first is the policy. The second is the net under it, and it exists
because every other mechanism can fail: a queue can drop a message, a worker
can die between deleting a row and deleting its object, a bucket can refuse
a call for ninety seconds. Without the net the guarantee would be "usually",
and "usually deleted" is not a thing you can tell a customer or a regulator.

THE ORDER IS THE ROW FIRST, THEN THE OBJECT, and it is not arbitrary.
Interrupted after the row, we have an object nobody claims — the second sweep
finds it and removes it. Interrupted the other way round, we have a row
pointing at bytes that no longer exist, and nothing can repair that: the
metadata is all we would have left, and it describes something gone.

Run by hand, or by whatever drives the background loop:

    python -m leka.ingestion.tasks
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog

from leka.db import load_schema, session_factory, system_scope
from leka.ingestion.models import RawPayload
from leka.ingestion.repository import RawPayloadSweeper
from leka.platform.storage import ObjectStoreError, object_store

logger = structlog.get_logger(__name__)

# How long an object must have existed before reconciliation is allowed to
# call it an orphan.
#
# THIS IS THE DANGEROUS PART OF THIS FILE. A payload is written to the store
# BEFORE its row is committed — it has to be, since the row records the size
# and checksum the store measured. For a moment, an object legitimately has
# no row. A reconciliation that ran in that moment would delete data that was
# arriving correctly.
#
# Two days, read from the date inside the key rather than from the store,
# because the date is in the key on purpose and asking the store for an
# object's age would mean a stat() call per object and a seventh method on
# the protocol.
ORPHAN_GRACE = timedelta(days=2)


def _key_date(key: str) -> datetime | None:
    """The day an object key says it was written, if it says one.

    Keys are {workspace}/{source}/{yyyy}/{mm}/{dd}/{uuid}.{ext}. A key that
    does not parse gets None, and a None is treated as "too recent to judge"
    by the caller — an unrecognised key is left alone rather than deleted.
    Being wrong in the other direction destroys a customer's data.
    """
    parts = key.split("/")
    if len(parts) < 6:
        return None
    try:
        return datetime(int(parts[2]), int(parts[3]), int(parts[4]), tzinfo=UTC)
    except (ValueError, IndexError):
        return None


async def sweep_expired_payloads(
    *, now: datetime | None = None, batch: int = 500, max_batches: int = 20
) -> dict[str, int]:
    """Delete what has outlived its retention: the row, then the object.

    Batched and bounded. The first run after a retention change can match
    millions of rows, and a task that tries to finish in one go is a task
    that is killed halfway and starts from the beginning next time. It stops
    after max_batches and the next run picks up where this one left off —
    which is fine because there is nothing stateful about where it stopped.

    A failure to delete one object does not stop the sweep. The row is
    already gone, so the object is now an orphan, and orphans are exactly
    what the other sweep in this file is for.
    """
    moment = now or datetime.now(UTC)
    store = object_store()
    rows_removed = 0
    objects_removed = 0
    objects_failed = 0

    for _ in range(max_batches):
        keys: list[str] = []
        due: Sequence[RawPayload] = []
        with system_scope():
            async with session_factory() as session:
                sweeper = RawPayloadSweeper(session)
                due = await sweeper.due_for_deletion(now=moment, limit=batch)
                if not due:
                    break

                # Read the keys out before the rows go: after the DELETE
                # there is nothing left to tell us what to remove.
                keys = [payload.object_key for payload in due]
                identifiers: list[uuid.UUID] = [payload.id for payload in due]
                rows_removed += await sweeper.delete_rows(identifiers)
                await session.commit()

        for key in keys:
            try:
                if await store.delete(key):
                    objects_removed += 1
            except ObjectStoreError as error:
                # Logged, not raised. The row is gone; reconciliation will
                # find this object and try again.
                objects_failed += 1
                logger.warning("payload_object_not_deleted", key=key, error=str(error))

        if len(due) < batch:
            break

    result = {
        "rows": rows_removed,
        "objects": objects_removed,
        "objects_failed": objects_failed,
    }
    logger.info("retention_sweep_completed", **result)
    return result


async def reconcile_orphaned_objects(
    *, now: datetime | None = None, dry_run: bool = False
) -> dict[str, int]:
    """Remove stored objects that no row speaks for.

    The net under everything else: a workspace erased while Redis was down, a
    worker killed between a row and its object, a purge that half worked.
    Whatever the reason, the bytes are still with us and nobody is going to
    read them — which is a bill, and, if the customer asked to be deleted, a
    promise we have not actually kept.

    dry_run reports what it would delete without deleting it. The first run
    against a real bucket should always use it: this function's failure mode
    is deleting live data, so seeing the number before trusting it is cheap.
    """
    moment = now or datetime.now(UTC)
    cutoff = moment - ORPHAN_GRACE
    store = object_store()

    with system_scope():
        async with session_factory() as session:
            claimed = await RawPayloadSweeper(session).every_object_key()

    examined = 0
    orphans = 0
    removed = 0
    skipped_recent = 0

    async for key in store.iter_prefix(""):
        examined += 1
        if key in claimed:
            continue

        written = _key_date(key)
        # An unparseable key is treated as too recent to judge. Leaving
        # something we do not understand is recoverable; deleting it is not.
        if written is None or written > cutoff:
            skipped_recent += 1
            continue

        orphans += 1
        if dry_run:
            continue
        try:
            if await store.delete(key):
                removed += 1
        except ObjectStoreError as error:
            logger.warning("orphan_not_deleted", key=key, error=str(error))

    result = {
        "examined": examined,
        "orphans": orphans,
        "removed": removed,
        "skipped_recent": skipped_recent,
    }
    logger.info("orphan_reconciliation_completed", dry_run=dry_run, **result)
    return result


def run_sweep() -> dict[str, int]:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(sweep_expired_payloads())


def run_reconcile(*, dry_run: bool = False) -> dict[str, int]:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(reconcile_orphaned_objects(dry_run=dry_run))


async def _by_hand() -> None:
    """Both sweeps in ONE loop: the connection pool belongs to the loop that
    opened it, and a second asyncio.run() inherits connections of a closed one."""
    await sweep_expired_payloads()
    await reconcile_orphaned_objects()


if __name__ == "__main__":  # pragma: no cover
    load_schema()  # every table, as the API has (leka/schema.py)
    asyncio.run(_by_hand())
