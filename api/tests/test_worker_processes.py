"""The worker and the scheduler: set up like the API, and heard when they fail.

LEKA-336. Both used to be started with `rq worker` and `rq cron`, which start
RQ and nothing else. A worker started that way wrote its logs without the
secret masker, never initialised Sentry, and could not have reported a job's
exception anyway: the runner catches it to record the attempt, so neither RQ
nor Sentry ever sees it. docs/deployment.md said "look in Sentry first" for a
failing job. There was nothing there to look at.

And staging ran a worker with no scheduler, which is a worker that waits for
ever: the tick that turns events into runs is put on the queue by the
scheduler, and nothing else.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
import yaml
from pydantic import SecretStr
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport
from sqlalchemy.ext.asyncio import AsyncSession

from leka.background import JobQueue, worker_connection
from leka.background.runner import run_job
from leka.core.config import settings
from leka.core.logging import MASK, configure_logging
from leka.core.settings.paths import REPO_ROOT
from leka.platform import scheduler, worker
from leka.platform.monitoring import configure_monitoring
from tests import background_jobs
from tests.job_run_helpers import PATH, insert_run, make_workspace


@pytest.fixture
def sentry_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Sentry configured the way production configures it, minus the network.

    Goes through configure_monitoring itself, so the before_send hook that
    scrubs secrets is the real one; only the transport is swapped for a list.
    Shut down afterwards: a live client left behind by one test would report
    every deliberate failure in the rest of the suite.
    """
    events: list[dict[str, Any]] = []

    class Capture(Transport):
        def capture_envelope(self, envelope: Envelope) -> None:
            events.extend(
                item.payload.json
                for item in envelope.items
                if item.type == "event" and item.payload.json is not None
            )

    real_init = sentry_sdk.init
    monkeypatch.setattr(
        sentry_sdk, "init", lambda *args, **kwargs: real_init(*args, transport=Capture, **kwargs)
    )
    configured = settings.model_copy(
        update={"sentry_dsn": SecretStr("https://public@o0.ingest.sentry.io/0")}
    )
    configure_logging(configured)
    assert configure_monitoring(configured) is True

    yield events

    real_init()


async def _failing_run(session: AsyncSession, job: str, args: list[str] | None = None) -> uuid.UUID:
    workspace = await make_workspace(session)
    run_id = await insert_run(session, workspace, job=job, args=json.dumps(args or []))
    await session.commit()
    return run_id


# ── A job's exception reaches Sentry ──────────────────────────────────────


@pytest.mark.integration
async def test_a_failing_job_is_reported_with_the_job_it_came_from(
    session: AsyncSession, sentry_events: list[dict[str, Any]]
) -> None:
    background_jobs.reset()
    run_id = await _failing_run(session, f"{PATH}.fail")

    assert await run_job(run_id) == "retrying"
    sentry_sdk.flush()

    [event] = sentry_events
    [exception] = event["exception"]["values"]
    assert (exception["type"], exception["value"]) == ("RuntimeError", "boom: the job failed")
    # The first two questions about any job failure: which job, which run.
    assert event["tags"] == {"job": f"{PATH}.fail", "run_id": str(run_id)}


@pytest.mark.integration
async def test_a_job_that_does_not_exist_is_reported_too(
    session: AsyncSession, sentry_events: list[dict[str, Any]]
) -> None:
    """A typo in a job path is a deployment defect, and it fails for good at
    once — the one failure nobody will see if it is only written to a row."""
    run_id = await _failing_run(session, f"{PATH}.does_not_exist")

    assert await run_job(run_id) == "failed"
    sentry_sdk.flush()

    [event] = sentry_events
    assert event["tags"]["job"] == f"{PATH}.does_not_exist"


@pytest.mark.integration
async def test_a_secret_in_a_job_error_does_not_leave_with_it(
    session: AsyncSession, sentry_events: list[dict[str, Any]]
) -> None:
    """The report goes through the same scrubbing as an API error.

    The runner cannot scrub — background sits below platform and never
    sees a secret — so this is what proves the hook it relies on is really
    on the path.
    """
    background_jobs.reset()
    secret = settings.secret_key.get_secret_value()
    run_id = await _failing_run(session, f"{PATH}.leak", [secret])

    await run_job(run_id)
    sentry_sdk.flush()

    [event] = sentry_events
    assert secret not in json.dumps(event)
    assert MASK in event["exception"]["values"][0]["value"]


# ── Both processes are set up before they run anything ────────────────────


class _Recorder:
    """Stands in for RQ, and writes down in what order things happened."""

    def __init__(self) -> None:
        self.calls: list[object] = []


def _record_setup(monkeypatch: pytest.MonkeyPatch, module: Any, recorder: _Recorder) -> None:
    monkeypatch.setattr(module, "configure_logging", lambda _s: recorder.calls.append("logging"))
    monkeypatch.setattr(
        module, "configure_monitoring", lambda _s: recorder.calls.append("monitoring")
    )


def test_the_worker_is_set_up_before_it_takes_a_job(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    _record_setup(monkeypatch, worker, recorder)

    class FakeWorker:
        def __init__(self, queues: list[Any], connection: Any) -> None:
            recorder.calls.append(("queues", [queue.name for queue in queues]))

        def work(self) -> None:
            recorder.calls.append("work")

    monkeypatch.setattr(worker, "Worker", FakeWorker)

    worker.main()

    assert recorder.calls == [
        # Logging first: Sentry scrubs with the masker that logging builds.
        "logging",
        "monitoring",
        # The only priority RQ has is this order.
        ("queues", ["leka:high", "leka", "leka:low"]),
        "work",
    ]


def test_a_worker_can_be_given_one_queue_and_not_a_misspelt_one() -> None:
    """docs/background.md runs a second worker on leka:high alone, so the
    tick never waits behind a sweep. A misspelt queue would be drained by
    nobody, silently: it is refused instead."""
    assert worker.queues_to_drain(["leka:high"]) == (JobQueue.HIGH,)
    with pytest.raises(ValueError, match="leka:hgih"):
        worker.queues_to_drain(["leka:hgih"])


def test_the_worker_does_not_borrow_the_enqueueing_timeout() -> None:
    """A worker blocks on the queue for minutes at a time. With the two-second
    socket timeout the enqueueing side uses, it would take every quiet
    moment for Redis being down."""
    connection = worker_connection()

    assert connection.connection_pool.connection_kwargs.get("socket_timeout") is None


def test_the_scheduler_is_set_up_before_it_schedules(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    _record_setup(monkeypatch, scheduler, recorder)

    class FakeScheduler:
        def __init__(self, connection: Any) -> None:
            pass

        def load_config_from_file(self, path: str) -> None:
            recorder.calls.append(("config", path))

        def start(self) -> None:
            recorder.calls.append("start")

    monkeypatch.setattr(scheduler, "CronScheduler", FakeScheduler)

    scheduler.main()

    assert recorder.calls == [
        "logging",
        "monitoring",
        ("config", "leka.background.cron_config"),
        "start",
    ]


def test_the_scheduler_loads_the_real_schedule() -> None:
    """The dotted path is a string, so nothing else would notice it going
    stale: this loads it for real and counts what it registered."""
    from rq.cron import CronScheduler

    from leka.background.schedule import SCHEDULE

    cron = CronScheduler(connection=worker_connection())
    cron.load_config_from_file(scheduler.CRON_CONFIG)

    # The maintenance tick, plus every entry of the schedule table.
    assert len(cron.get_jobs()) == 1 + len(SCHEDULE)


# ── Staging runs all of it ────────────────────────────────────────────────


def test_staging_runs_every_process_the_background_loop_needs() -> None:
    """Staging once shipped a worker and no scheduler, and nothing failed:
    the worker simply waited for work that nothing would ever dispatch."""
    compose = yaml.safe_load(
        (REPO_ROOT / "deploy" / "docker-compose.staging.yml").read_text(encoding="utf-8")
    )
    commands = {name: service.get("command") for name, service in compose["services"].items()}

    assert commands["worker"] == ["python", "-m", "leka.platform.worker"]
    assert commands["scheduler"] == ["python", "-m", "leka.platform.scheduler"]
