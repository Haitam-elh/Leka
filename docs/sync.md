# The sync — reading sources into LEKA, and watching it happen

How a connected source's data reaches LEKA, how often, what happens when it
fails, and how to see all of it. LEKA-352. The code is
[`leka/ingestion/sync.py`](../api/leka/ingestion/sync.py); it runs on the
background loop described in [background.md](background.md).

---

## What a pass does

One **pass** reads one source. For each capability its last connection test
found readable (repositories first, then branches, commits, issues, pull
requests, releases):

1. ask the connector for what changed **since** the last successful pass of
   that capability started (`iter_resources(capability, since=…)`, see
   [connectors/framework.md](connectors/framework.md));
2. write what comes back in **batches of 500**, each a JSON-lines object in
   the object store with its `raw_payloads` row, **committed batch by
   batch** — a pass that fails later keeps what it stored;
3. record where the capability stands in `source_syncs`.

Then the source's summary: `sources.sync_status` (`idle` / `failed`) and
`last_sync_at`.

**The cursor (`source_syncs.since`) is when the last successful pass
started.** What changes while a pass reads is at or after its start, so the
next pass reads it again. A failed pass does not move it. Reading something
twice costs a write; missing it would cost a wrong answer.

**A full pass every 7 days** per capability ignores the cursor and reads
everything: incremental reads trust each vendor's dates, and this is the
net under that trust. An admin can also ask for one (`full=true`).

## When passes run

| Trigger | What | Guarantee |
|---|---|---|
| A source is **activated** | `source.activated` is published in the activation's transaction; its route queues a **full** pass | the pass exists only if the activation committed; full because changing settings or credentials sends a source back to draft, so a widened scope always comes back through here and its history is read |
| The **schedule** | `source-sync`, at :10 :25 :40 :55 — queues a pass for every activated source **not tried for an hour** | "tried", not "succeeded": a source failing for a person to fix is not hammered every 15 minutes |
| **"Synchroniser maintenant"** | `POST /ingestion/sources/{id}/sync` (`source:manage`), on `leka:high` | a person is waiting |

Every pass holds the concurrency key **`sync:<source_id>`**: whoever asks
while one is queued or running gets `already_active` / `{"queued": false}`,
not a second pass. Only `active` and `degraded` sources are read: a source
in `error` waits for a person, `disabled` for someone to switch it on.

## When a pass fails

| The vendor's failure | Examples | What happens |
|---|---|---|
| **Retryable, soon** | network, timeout, 5xx, a quota back within 5 minutes | recorded, then the job runner **retries** with its backoff (`LEKA_JOB_*`) |
| **Retryable, later** | a quota reset an hour away | recorded, **not retried**: the next scheduled pass comes sooner than useful retries would |
| **Not retryable** | token refused or expired, permission withdrawn | recorded, the source goes to **`error`** with the diagnostic and its remediation — a person must act |

A pass stops at the first failing capability. The source's history
(`source_events`) says **`sync_failed`** when it starts failing and
**`sync_recovered`** at the first success after — not one line an hour.
`consecutive_failures` counts the passes in between.

## Seeing it

**In the product.** The Sources screen shows each source's sync status and
records; a source's page shows each capability (`GET
/ingestion/sources/{id}/syncs`) and its history.

**Over the API** (every member reads, admins start passes):

| | |
|---|---|
| `GET /ingestion/syncs` | per source: records so far, last success — one call for a list |
| `GET /ingestion/sources/{id}/syncs` | per capability: status, cursor, starts, counts, failures, last diagnostic |
| `POST /ingestion/sources/{id}/sync?full=` | queue a pass; 409 if the source is not activated |

**For operations** — SQL, across every workspace, not for customers:

```sql
-- what is failing, for how long, and why
SELECT s.workspace_id, s.name, y.capability, y.consecutive_failures,
       y.last_error->>'code' AS code, y.last_succeeded_at
FROM source_syncs y JOIN sources s ON s.id = y.source_id
WHERE y.status = 'failed' ORDER BY y.consecutive_failures DESC;

-- activated sources not read for more than a day (the schedule should keep this empty)
SELECT s.workspace_id, s.name, max(y.last_succeeded_at) AS last_success
FROM sources s LEFT JOIN source_syncs y ON y.source_id = s.id
WHERE s.status IN ('active', 'degraded')
GROUP BY s.id HAVING coalesce(max(y.last_succeeded_at), 'epoch') < now() - interval '1 day';

-- passes left "running" by a worker that died (the schedule retries them after an hour)
SELECT source_id, capability, last_started_at FROM source_syncs
WHERE status = 'running' AND last_started_at < now() - interval '1 hour';

-- the passes themselves, as job runs
SELECT status, count(*) FROM job_runs WHERE job = 'leka.ingestion.sync.run_sync' GROUP BY 1;
```

Log lines: `source_synced` (one per pass, with the records per capability
and the error code), `syncs_scheduled` (per schedule tick).

## Where it is tested

| File | What it proves |
|---|---|
| `tests/test_source_syncs_schema.py` | what the database refuses; one row per (source, capability) under concurrency; isolation |
| `tests/test_sync.py` | batches and JSON lines; the cursor; the weekly full pass; the three failures; the history lines; what is not read |
| `tests/test_sync_schedule.py` | the activation event and its single pass; the schedule's choice; the API, its permissions and isolation |

## Not yet

- **Deduplication across passes, checkpoints inside a capability,
  backpressure** — LEKA-353 (collection pipeline). Today a re-read writes a
  new payload; the retention sweep removes the old ones on schedule.
- **Turning payloads into entities** — LEKA-354 and after.
- **Alerting.** The queries above are the dashboard, as in background.md.
