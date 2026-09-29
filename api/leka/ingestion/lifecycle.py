"""The lifecycle of processed data (LEKA-360): how long it is kept, what
replaces it, and the sweep that holds the line.

THE POLICIES — one per stage, the same shape for all three:

    kept       while its input is live. An extraction lives while its record
               does; a parse while its extraction is extracted; candidates
               while their parse is parsed. A record gone at the vendor
               takes all three along (the next extraction, then the cascade).
    replaced   in place, one row per input, when the input changes (its
               checksum) or the version that made it does. Never two
               versions side by side: the row says which one it is.
    on demand  `reprocess` drops a stage's rows for a source — and, by
               cascade, the later stages' — and queues the stage again.

    history    `processing_runs`: 90 days, then pruned.

Processed data follows its RECORD, not its raw payload: a payload expires
after 30 to 90 days (docs/data-lifecycle.md) while the record is still at the
vendor, and what was made of it is the working data the model is built
from. Erasing a workspace or a source removes everything, by cascade.

THE SWEEP, daily (`run_processing_sweep`), across every workspace:

- a run left `running` longer than any job may live is `abandoned` — its
  worker died and no later run of its stage came to say so;
- history older than HISTORY_DAYS is pruned — entity resolution's runs
  (LEKA-357) as the stages';
- what was extracted from a record marked deleted is removed, with what was
  made from it — the extraction does it when it runs, the sweep for the
  sources whose extraction no longer runs (switched off);
- a webhook source's log (LEKA-350) is kept DELIVERY_DAYS: its deliveries
  stored, ignored or rejected — never one still pending — and the passes
  deliveries started, which come by the thousand where a schedule's come
  by the hour.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background.runner import RQ_JOB_TIMEOUT
from leka.connectors import Source
from leka.db import session_factory, system_scope
from leka.ingestion.models import (
    DeliveryStatus,
    ExtractedRecordRow,
    ProcessingRun,
    ProcessingRunStatus,
    ProcessingStage,
    ResolutionRun,
    SourceRecord,
    SyncRun,
    SyncRunOutcome,
    SyncTrigger,
    WebhookDelivery,
)
from leka.ingestion.pipeline import advance
from leka.ingestion.repository import ProcessingRunRepository, _affected_rows

logger = structlog.get_logger(__name__)

HISTORY_DAYS = 90
DELIVERY_DAYS = 30
# Longer than RQ lets a job's work-horse live: a run older than this is dead.
STUCK_AFTER = timedelta(seconds=RQ_JOB_TIMEOUT) + timedelta(hours=1)


@dataclass(frozen=True)
class Policy:
    kept: str
    replaced: str


POLICIES: dict[ProcessingStage, Policy] = {
    ProcessingStage.EXTRACTION: Policy(
        kept="while its source record is live",
        replaced="when the record's checksum or its strategy's version changes",
    ),
    ProcessingStage.PARSING: Policy(
        kept="while its extraction is extracted",
        replaced="when the extraction or PARSER_VERSION changes",
    ),
    ProcessingStage.NORMALISATION: Policy(
        kept="while its parse is parsed",
        replaced="when the parse or NORMALISER_VERSION changes",
    ),
    ProcessingStage.VALIDATION: Policy(
        kept="while its normalisation is normalised",
        replaced="when the record is normalised again or VALIDATOR_VERSION changes",
    ),
}


async def reprocess(
    session: AsyncSession, workspace_id: uuid.UUID, source: Source, stage: ProcessingStage
) -> ProcessingStage | None:
    """Drop the stage's rows for the source — the later stages' go with them
    — and queue what now has work: the stage itself, or an earlier one that
    has work of its own and must run first. The caller holds the scope."""
    removed = await ProcessingRunRepository(session, workspace_id).delete_rows(source.id, stage)
    await session.commit()
    logger.info(
        "processing_reprocess", source_id=str(source.id), stage=stage.value, removed=removed
    )
    return await advance(session, workspace_id, source, after=None)


def run_processing_sweep() -> dict[str, int]:
    """Entry point for the scheduler, which is synchronous."""
    return asyncio.run(sweep_processing())


async def sweep_processing(*, now: datetime | None = None) -> dict[str, int]:
    """The daily sweep, across every workspace. Idempotent."""
    now = now or datetime.now(UTC)
    with system_scope():
        async with session_factory() as session:
            abandoned = await session.execute(
                update(ProcessingRun)
                .where(
                    ProcessingRun.status == ProcessingRunStatus.RUNNING,
                    ProcessingRun.started_at < now - STUCK_AFTER,
                )
                .values(
                    status=ProcessingRunStatus.ABANDONED, finished_at=now, updated_at=func.now()
                )
            )
            pruned = await session.execute(
                delete(ProcessingRun).where(
                    ProcessingRun.status != ProcessingRunStatus.RUNNING,
                    ProcessingRun.started_at < now - timedelta(days=HISTORY_DAYS),
                )
            )
            gone = select(SourceRecord.id).where(SourceRecord.deleted_at.is_not(None))
            forgotten = await session.execute(
                delete(ExtractedRecordRow).where(ExtractedRecordRow.source_record_id.in_(gone))
            )
            delivered_before = now - timedelta(days=DELIVERY_DAYS)
            # Entity resolution's history (LEKA-357), as long as the stages'.
            resolution_runs = await session.execute(
                delete(ResolutionRun).where(
                    ResolutionRun.status != "running",
                    ResolutionRun.started_at < now - timedelta(days=HISTORY_DAYS),
                )
            )
            deliveries = await session.execute(
                delete(WebhookDelivery).where(
                    WebhookDelivery.status != DeliveryStatus.PENDING,
                    WebhookDelivery.received_at < delivered_before,
                )
            )
            passes = await session.execute(
                delete(SyncRun).where(
                    SyncRun.trigger == SyncTrigger.WEBHOOK,
                    SyncRun.status != SyncRunOutcome.RUNNING,
                    SyncRun.started_at < delivered_before,
                )
            )
            await session.commit()
    result = {
        "abandoned": _affected_rows(abandoned),
        "pruned": _affected_rows(pruned),
        "forgotten": _affected_rows(forgotten),
        "deliveries": _affected_rows(deliveries),
        "resolution_runs": _affected_rows(resolution_runs),
        "webhook_passes": _affected_rows(passes),
    }
    logger.info("processing_swept", **result)
    return result
