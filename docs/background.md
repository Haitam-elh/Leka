# The background loop — operating it

How work gets done when nobody is waiting: what runs, how to run it, how to see what
happened, and what to do when it breaks. The reasoning is in
[ADR 013](adr/013-events-and-job-runs.md); this is the part you need at three in
the morning.

---

## What it is

```
  a change in a request ──▶ events        (same transaction: exists iff the change does)
                              │  dispatcher
                              ▼
                           job_runs       (queued · running · retrying · succeeded · failed)
                              │  enqueue pass
                              ▼
                        Redis / RQ  ──▶  worker  ──▶ your job
```

Two hops, and **each is a database write first**. Redis is never on the path of a
transaction: a run is durable before anyone tells the queue about it, and "the queue
was down" is a row that says `enqueued_at IS NULL`.

A **tick** runs every 10 seconds and does all of it: dispatch pending events, repair
what broke, offer waiting runs to Redis. The periodic sweeps are scheduled by `rq cron`,
which only puts jobs on the queue; the worker runs them.

The guarantee is **at-least-once**. A message can be delivered twice, a dispatcher can
run twice, a worker can die halfway. What is guaranteed is that none of those becomes a
second *execution* — the run is unique per event and job, and claiming it is a single
UPDATE only one worker can win. What a job did before it died is the job's own
idempotence to provide.

---

## Running it

Two processes, on your host (`docker-compose.yml` is backing services only):

```bash
# the worker: three queues, drained in this order
cd api && .venv/bin/python -m leka.platform.worker

# the scheduler: puts the tick and the sweeps on the queue at the right times
cd api && .venv/bin/python -m leka.platform.scheduler
```

**On macOS**, a job that makes a network call (a connector, the sync) kills its
work-horse: RQ forks one per job, and macOS refuses Objective-C initialisation
after `fork()` (`objc[…]: … may have been in progress in another thread when
fork() was called`). Start the worker with
`OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` in front. Linux — production, CI — is
unaffected.

`leka:high` is work a person is waiting for, `leka` is everything else, `leka:low` is the
sweeps. That is the only priority RQ has, and it has two limits worth knowing:

- **A continuous stream of `high` starves `low`.** With one worker that is guaranteed,
  not theoretical.
- **A long job blocks everything, whatever its queue.** Priority chooses the *next* job,
  never the one running. A ten-minute retention sweep makes the tick wait ten minutes —
  events wait, nothing is lost. **Run a second worker on `leka:high` alone** and the
  tick and the scheduling calls never sit behind a sweep:

  ```bash
  cd api && .venv/bin/python -m leka.platform.worker leka:high
  ```

Nothing needs either process to be running to *record* work: events, runs and
history are written by the API. Without a worker they wait; without the scheduler nothing
is dispatched or scheduled, which is the state of the world before LEKA-334.

To run one tick by hand — dispatch, repair, enqueue, and prune old events:

```bash
api/.venv/bin/python -m leka.background.tasks
```

### Settings

All optional, all bounded — a `0` reads as "disabled" to whoever types it and as "never
try" to the code, so it is refused at startup.

| Variable | Default | Meaning |
|---|---|---|
| `LEKA_DISPATCH_BATCH_SIZE` | 100 (1–1000) | events, and runs, handled per pass |
| `LEKA_DISPATCH_MAX_ATTEMPTS` | 5 (1–50) | a failing event is given up on after this many passes |
| `LEKA_EVENT_RETENTION_DAYS` | 14 (1–365) | settled events (runs created or failed) are kept this long |
| `LEKA_JOB_MAX_ATTEMPTS` | 3 (1–20) | a run is failed for good after this many attempts |
| `LEKA_JOB_RETRY_BASE_SECONDS` | 30 | the first retry waits this; each next one doubles |
| `LEKA_JOB_RETRY_MAX_SECONDS` | 3600 | ...up to this. Must be at least the base |
| `LEKA_JOB_LEASE_SECONDS` | 300 (30–7200) | a worker silent this long is taken to be dead |
| `LEKA_JOB_STALE_ENQUEUED_SECONDS` | 3600 | a run the queue never picked up is offered again |
| `LEKA_RECONCILE_DELETES` | false | the scheduled orphan sweep only *reports* until this is true |

---

## What runs by itself

`leka/background/schedule.py`. Each is a sweep that used to be run by hand; each is
recorded as a run, and is not started again while the previous one is still active.

| Name | Job | When (UTC) | Queue |
|---|---|---|---|
| `retention-sweep` | `leka.ingestion.tasks.run_sweep` | hourly, :00 | low |
| `erase-workspaces` | `leka.platform.tasks.run_erase_workspaces_past_grace` | hourly, :15 | low |
| `purge-sessions` | `leka.identity.tasks.run_purge` | hourly, :30 | low |
| `reconcile-orphans` | `leka.ingestion.tasks.run_reconcile` | Sundays 03:00 | low |
| `prune-events` | `leka.background.tasks.run_prune_events` | daily 03:30 | low |
| `processing-sweep` | `leka.ingestion.lifecycle.run_processing_sweep` — processed data, see [processing.md](processing.md) | daily 03:45 | low |
| `source-health` | `leka.connectors.health.run_health_checks` | :05 :20 :35 :50 | low |
| `source-sync` | `leka.ingestion.sync.run_enqueue_due_syncs` — queues the passes, see [sync.md](sync.md) | :10 :25 :40 :55 | low |
| `model-sweep` | `leka.knowledge.job.run_model_sweep` — the company models behind their enrichment, or a rebuild asked (LEKA-383); old snapshots forgotten, see [company-model.md](company-model.md) | hourly, :48 | low |
| `context-sweep` | `leka.context.job.run_context_sweep` — a pass for each workspace whose contexts follow the model; old checks forgotten, see [context.md](context.md) § 14 | hourly, :52 | low |
| `intelligence-sweep` | `leka.intelligence.job.run_intelligence_sweep` — a run for each workspace whose analysis is behind: never analysed, a newer build, a new catalogue, a day old; dead runs closed, old ones forgotten, see [intelligence.md](intelligence.md) § 2, § 8 | hourly, :56 | low |
| `intention-analysis-sweep` | `leka.intentions.processing.run_pending_analyses` — the intentions analysing whose context has no analysis yet, analysed: what no worker took, see [intentions.md](intentions.md) § 12 | :07 :22 :37 :52 | low |

---

## Looking at what happened

Every run is a row. A workspace's admins can read their own through `GET /api/v1/jobs`
(see [api.md](api.md)). What follows is SQL against `job_runs`, which belongs to no workspace, so
**it is for operating the system, not for showing a customer**: it includes the system's own runs,
and the error text the API deliberately never returns.

```sql
-- the shape of things
SELECT status, count(*) FROM job_runs GROUP BY 1;

-- what failed for good, and why
SELECT id, job, attempts, last_error, finished_at
FROM job_runs WHERE status = 'failed' ORDER BY finished_at DESC LIMIT 20;

-- what is failing right now and will try again
SELECT id, job, attempts, next_run_at, last_error
FROM job_runs WHERE status = 'retrying' ORDER BY next_run_at;

-- runs Redis has not been told about (should be ~0; growing means Redis or the tick is down)
SELECT count(*), min(created_at) FROM job_runs WHERE status = 'queued' AND enqueued_at IS NULL;

-- the event backlog (an old `pending` means the tick is not running)
SELECT status, count(*), min(created_at) FROM events GROUP BY 1;

-- follow one request through: the id is in every log line as `request_id`
SELECT job, status, attempts FROM job_runs WHERE request_id = '01J...';
```

And what Redis and the workers think: `api/.venv/bin/rq info --url redis://127.0.0.1:6379/0`.

Logs are structured. A job's lines carry `run_id`, `job`, `attempt` and `request_id`, so
"the user clicked" and "the worker crashed three minutes later" are one search.

---

## When it breaks

**Redis is down.** Nothing is lost. The API and the tick keep recording work; runs pile up
with `enqueued_at IS NULL` and are offered when Redis is back (the tick stops at the first
refusal rather than timing out on every run). Watch the "not been told about" query above.

**A worker died mid-job.** It cannot report it. Its lease runs out after
`LEKA_JOB_LEASE_SECONDS`, the tick moves the run to `retrying` (using up an attempt) and
it runs again — so the job must be safe to run twice. Until then the run is `running`,
and it *holds its concurrency key*.

**Redis lost its memory** (a restart with no persistence). A run that says `queued` and
was offered long ago — `LEKA_JOB_STALE_ENQUEUED_SECONDS` — is offered again. The claim makes
a duplicate message harmless. Retries are held in the database, so they are unaffected.

**A job keeps failing.** It is retried with a doubling delay, then `failed` and left for you:
`last_error` has the exception. Fix the cause and *run it again as a new run* — a failed run
is terminal, so the history stays true.

**A job path is wrong** (a typo, a renamed function). It fails on the first attempt and is
not retried; the error says it could not resolve the path. A test checks every scheduled and
routed path exists, so this should only reach production from a row added without one.

**Events stay `pending`.** The tick is not running (the scheduler down, or no worker on the
queue it is on). Start them; nothing is lost, and the oldest go first.

**An event is `failed` with "no route".** Something published an event type nobody consumes
(`leka/background/routes.py`). It is failed rather than dropped so it cannot look like it
worked. Add the route, then republish.

**A run sits `queued` and nothing happens.** Is there a worker on that run's queue? `rq info`
shows workers per queue. A run on `leka:low` needs a worker that lists it.

---

## Adding to it

**A consumer for an event.** One line in `leka/background/routes.py`: the event type, the
job's dotted path, optionally the queue. The job receives one argument, the event id as a
string. It must check its workspace still exists — a workspace can be deleted between the
event and the job — and it must be safe to run twice.

**A scheduled task.** One row in `leka/background/schedule.py`. Do not write a new scheduler,
and do not re-write the task: it stays a plain function with a synchronous entry point.

**Publishing an event.** `publish_event(session, workspace_id, "thing.happened", {...})` from
inside the request's own session, so it commits with the change and rolls back with it. Give it
a `dedupe_key` when the source can deliver twice (a webhook). The payload names *what* happened
and *to which thing*, never the data — 16 KiB at most; data goes to the object store.

**A job that is not the consequence of a change** — a "sync now" button, say:
`await enqueue_job("leka.x.tasks.run", arg, for_workspace_id=..., concurrency_key="sync:<id>")`.
It returns None if that key is already active: two people clicking is not an error.

**What a job must be.** Idempotent, synchronous at its entry point, and never dependent on a
`workspace_id` argument being trustworthy: it is a fact about the past, not an authorisation.
If it touches a workspace-scoped table it declares `system_scope()` or builds a scoped
repository, exactly as the existing sweeps do.

---

## What it does not do

- **No ordering.** Two events written together are not necessarily consumed in order. A case
  that depends on order must say so and enforce it itself.
- **No exactly-once.** See the top. Jobs must be idempotent.
- **Job runs are not pruned.** Events are; runs are the history and there is no volume yet to
  set a retention against. The trigger to decide is written in ADR 013.
- **No error text for customers.** `GET /api/v1/jobs` shows status, attempts and timing but never
  `last_error`: an exception names hosts, paths and queries. You have it in SQL and in the logs.
- **No dashboard, no alerting.** The queries above are the dashboard. An alert on "runs not
  told about" and "events `pending` for more than a few minutes" is the first one to add.

---

## Where it is tested

| File | What it proves |
|---|---|
| `tests/test_background_schema.py`, `test_job_runs_schema.py` | what PostgreSQL refuses: duplicate events, two runs on one key, a run pointing at another customer's event |
| `tests/test_event_dispatch.py` | publishing and dispatching, including a poisoned event and a dead queue |
| `tests/test_job_runs.py` | the state machine, the claim race, retry, recovery, the customer-facing history |
| `tests/test_background_schedule.py` | every scheduled job exists, is synchronous, and has a valid schedule |
| `tests/test_job_history_api.py` | what a customer may read: only their own runs, never the system's, never an error text, 404 not 403 |
| `tests/test_background_e2e.py` | the whole loop on a real Redis and worker: success, retry, exhaustion, a dead worker, a Redis that forgot, priority, duplicates |

The end-to-end tests use **Redis database 15**, never 0, so a worker running on your own
machine cannot consume a test's jobs.
