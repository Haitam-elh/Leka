"""What runs by itself, and when.

A table, like the event routes: each row is a job that used to be run by hand,
named by dotted path, with when to run it and which queue it goes on. Adding a
scheduled task is one row here; `tests/test_background_schedule.py` checks every
row names a function that exists, is synchronous, and has a valid schedule the day
it is added.

THE SCHEDULER ONLY SCHEDULES. `rq cron` (see cron_config.py) does not run these
tasks; it puts `run_scheduled` on the queue, which creates a job RUN — visible in
the history, and refused if the previous one is still active — and offers that
run to the queue named here. So a sweep that takes ten minutes shows up as a
system run with its attempts and its error like any other job, and cannot overlap
itself.

The scheduling call goes on `leka:high` because it is cheap and must never wait
behind the sweep it is scheduling. The sweep goes where its row says.

THE TASKS ARE NOT RE-WRITTEN. Retention, erasure, session purge and reconciliation
are tested and their order is deliberate (docs/data-lifecycle.md); this only
decides when they run. Every one is safe to run twice, which is what lets a
schedule that fires while the last run is still going simply be refused.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from leka.background.models import JobQueue
from leka.background.service import enqueue_job
from leka.core.config import settings

# How often the maintenance tick runs: dispatch events, repair broken runs, offer
# waiting ones to Redis. Cheap when idle, so short; it sets the floor on how soon
# a published event starts.
TICK_INTERVAL_SECONDS = 10


@dataclass(frozen=True)
class Scheduled:
    name: str
    job: str
    cron: str | None = None
    interval: int | None = None
    queue: JobQueue = JobQueue.LOW
    kwargs: dict[str, object] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """The concurrency key: one active run of this sweep at a time."""
        return f"schedule:{self.name}"


# Minutes are staggered so the sweeps do not all start at the top of the hour and
# contend for the same connections.
SCHEDULE: tuple[Scheduled, ...] = (
    Scheduled("retention-sweep", "leka.ingestion.tasks.run_sweep", cron="0 * * * *"),
    Scheduled(
        "erase-workspaces",
        "leka.platform.tasks.run_erase_workspaces_past_grace",
        cron="15 * * * *",
    ),
    Scheduled("purge-sessions", "leka.identity.tasks.run_purge", cron="30 * * * *"),
    # Weekly, and dry unless LEKA_RECONCILE_DELETES says otherwise: its failure
    # mode is deleting live data (docs/data-lifecycle.md).
    Scheduled(
        "reconcile-orphans",
        "leka.ingestion.tasks.run_reconcile",
        cron="0 3 * * 0",
        kwargs={"dry_run": not settings.reconcile_deletes},
    ),
    Scheduled("prune-events", "leka.background.tasks.run_prune_events", cron="30 3 * * *"),
    # Processed data (LEKA-360): runs a dead worker left, history past 90
    # days, what deleted records gave to sources no longer extracted.
    Scheduled(
        "processing-sweep", "leka.ingestion.lifecycle.run_processing_sweep", cron="45 3 * * *"
    ),
    # Every activated source, a light call each (LEKA-344). Off the hour's
    # busy minutes, like the rest.
    Scheduled(
        "source-health", "leka.connectors.health.run_health_checks", cron="5,20,35,50 * * * *"
    ),
    # Offers a pass to every switched-on source not tried for an hour
    # (LEKA-352). The passes themselves run on the default queue, one per
    # source at a time.
    Scheduled(
        "source-sync", "leka.ingestion.sync.run_enqueue_due_syncs", cron="10,25,40,55 * * * *"
    ),
    # The company model (LEKA-361) of every workspace behind its enrichment:
    # what no event queues — a failed build, a new model version.
    Scheduled("model-sweep", "leka.knowledge.job.run_model_sweep", cron="48 * * * *"),
    # The contexts that follow the model (LEKA-374): what an event lost,
    # what a pass left; the checks past 90 days forgotten.
    Scheduled("context-sweep", "leka.context.job.run_context_sweep", cron="52 * * * *"),
    # The analyses (LEKA-377): a workspace behind its model, a new analysis
    # or version, a day without a run; dead runs closed, old ones forgotten.
    Scheduled(
        "intelligence-sweep", "leka.intelligence.job.run_intelligence_sweep", cron="56 * * * *"
    ),
    # The intentions analysing whose context no analysis read (LEKA-388):
    # a worker that died, a queue that was down.
    Scheduled(
        "intention-analysis-sweep",
        "leka.intentions.processing.run_pending_analyses",
        cron="7,22,37,52 * * * *",
    ),
    # Plans scheduled for a window run when it opens (LEKA-391).
    Scheduled(
        "intention-plans-due",
        "leka.intentions.actions.run_due_plans",
        cron="*/5 * * * *",
    ),
    # What ran, read again until what was expected came — or its deadline
    # (LEKA-392).
    Scheduled(
        "intention-verifications-due",
        "leka.intentions.verification.run_due_verifications",
        cron="2,7,12,17,22,27,32,37,42,47,52,57 * * * *",
    ),
    # The capability catalogue registered — every version, every move of its
    # lifecycle — as the API does when it starts, for a release whose API has
    # not restarted yet (LEKA-393).
    Scheduled(
        "capability-registry-sync",
        "leka.capabilities.catalogue.run_catalogue_sync",
        cron="23 * * * *",
    ),
    # The agent runs no worker will finish (LEKA-395): its worker went away,
    # its job was lost — failed, abandoned, said.
    Scheduled("agent-runs-sweep", "leka.capabilities.runs.run_runs_sweep", cron="*/10 * * * *"),
    # The workflow runs no worker will finish (LEKA-397): failed,
    # abandoned — retried, they go on from where they were.
    Scheduled(
        "workflow-runs-sweep",
        "leka.capabilities.workflow_runs.run_workflows_sweep",
        cron="44 * * * *",
    ),
    # The extracted records kept before LEKA-405, or under an older detector:
    # protected in place, a batch per workspace (ingestion.protection).
    Scheduled(
        "data-protection-sweep",
        "leka.ingestion.protection.run_protection_sweep",
        cron="9,24,39,54 * * * *",
    ),
    # The decisions waiting past their policy's hours (LEKA-404): escalated,
    # the asker and the owners told.
    Scheduled(
        "decisions-escalation",
        "leka.intentions.oversight.run_escalation",
        cron="4,19,34,49 * * * *",
    ),
    # The audit trail's retention (LEKA-407): what has outlived each
    # workspace's, deleted — and said, in the trail itself.
    Scheduled("audit-sweep", "leka.governance.audit.run_audit_sweep", cron="15 4 * * *"),
    # The operational alerts (LEKA-408), judged every five minutes. On the low
    # queue like every sweep — behind one, it is late: the API judges them
    # too (main.py), every five minutes whatever the queues and the worker do.
    Scheduled("ops-watch", "leka.ops.alerts.run_watch", cron="*/5 * * * *"),
    # The environment watched after the sources are read (LEKA-442): alerts
    # for the plans that include them.
    Scheduled(
        "monitoring-sweep",
        "leka.monitoring.service.run_monitoring_sweep",
        cron="14,29,44,59 * * * *",
    ),
    # The usage ledger (LEKA-430): the executions of the last hours metered
    # again from their calls and runs — late calls, runs that ended.
    Scheduled(
        "metering-sweep", "leka.metering.service.run_metering_sweep", cron="9,24,39,54 * * * *"
    ),
    # The AI credits (LEKA-430): each share of a month's credits passed, told
    # to the workspace's owners and admins — once.
    Scheduled("credit-watch", "leka.metering.credits.run_credit_watch", cron="3,18,33,48 * * * *"),
    # Files uploaded for an intention never asked: removed after a day.
    Scheduled("attachments-purge", "leka.intentions.attachments.run_purge", cron="40 * * * *"),
    # The notification centre (LEKA-476): what the systems kept, read into
    # notifications — also on each look at the bell.
    Scheduled("notifications-sweep", "leka.notifications.projector.run_sweep", cron="*/5 * * * *"),
)


async def schedule_job(
    job: str, concurrency_key: str, queue: str, job_kwargs: dict[str, object] | None = None
) -> Literal["scheduled", "already_active"]:
    """Create a system run of `job` and offer it to `queue`.

    `already_active` means the previous run of this sweep has not finished, which
    is not an error: the sweep is bounded per run and picks up where it stopped, so
    two at once would only fight over the same rows.
    """
    run = await enqueue_job(
        job,
        job_kwargs=job_kwargs,
        queue=JobQueue(queue),
        concurrency_key=concurrency_key,
    )
    return "scheduled" if run is not None else "already_active"


def run_scheduled(
    job: str, concurrency_key: str, queue: str, job_kwargs: dict[str, object] | None = None
) -> str:
    """Entry point for RQ, which is synchronous."""
    return asyncio.run(schedule_job(job, concurrency_key, queue, job_kwargs))
