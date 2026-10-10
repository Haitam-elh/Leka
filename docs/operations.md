# Operations — seeing LEKA, and getting it back (LEKA-408)

What tells an operator LEKA is working, what tells them it is not, what to
do then, and how the data comes back after the worst. Complements
[deployment.md](deployment.md) (how it ships, the box, the disk, the worker)
and [runbook.md](runbook.md) (restores and secrets, step by step).

## 1. What LEKA says about itself

### Metrics — `GET /api/v1/ops/metrics`

Prometheus text format, for whatever scrapes it (Prometheus, Grafana Agent,
Datadog). Takes the metrics token as a bearer —
`Authorization: Bearer $LEKA_METRICS_TOKEN`; with no token configured it
answers 404, as if it did not exist.

| Family | What |
| --- | --- |
| `leka_up` | the API answers |
| `leka_http_requests_total{method,route,status}` · `leka_http_request_duration_seconds` | requests this API process served — by route **template**, never a path with an id |
| `leka_jobs{status}` · `leka_jobs_failed_1h` · `leka_job_oldest_waiting_seconds` | background jobs live, failed, how long the oldest has waited |
| `leka_worker_last_finished_seconds` · `leka_scheduler_last_scheduled_seconds` | the worker's and the scheduler's heartbeats |
| `leka_queue_depth{queue}` | jobs waiting in each queue |
| `leka_sources{status,health}` · `leka_syncs_failing` · `leka_sync_runs_failed_1h` | connectors |
| `leka_processing_runs_1h{outcome}` | the processing stages |
| `leka_model_calls_1h{provider,outcome}` · `leka_model_latency_ms_1h{provider}` · `leka_model_cost_usd_24h` | AI: calls, failures, latency, cost |
| `leka_agent_runs{status}` · `leka_workflow_runs{status}` · `leka_runs_failed_1h{kind}` | AI executions |
| `leka_action_steps_1h{outcome}` | actions LEKA ran on customers' systems |
| `leka_circuits_open{kind}` | circuit breakers open, by kind of dependency |
| `leka_metrics_unreadable{part}` | what the metrics could not read |

Operating data only: counts, ages, rates — no customer's name, text or id.

### Health

- `GET /api/v1/health` — open: can **this API** serve (PostgreSQL, Redis).
  What the load balancer and the container's healthcheck ask.
- `GET /api/v1/ops/health` — the token: is **LEKA** working — database,
  Redis, object store, worker, scheduler, queues, dependencies (breakers) —
  each `ok`, `degraded` or `down`, said why. `down` (503) when the database,
  Redis, the worker or the scheduler is.

**One check must live outside LEKA**: when the box itself is gone, nothing
on it can say so. Point an external uptime monitor (UptimeRobot, Better
Stack — the free tier is enough) at `https://api.leka-core.com/api/v1/health`
every minute, alerting the same people.

## 2. Alerts

Judged every five minutes on the same numbers as the metrics
(`leka/ops/alerts.py`), from **two** places so that the one down cannot
silence the alert about it: the `ops-watch` job (worker) and a loop in the
API process; a Redis lock makes it one judgement. An alert is told **when it
starts**, again **every six hours** while it lasts, and **when it
resolves** — by email to `LEKA_OPS_ALERT_EMAILS` and to Sentry. A check that
crashes reads as firing, never as all clear. **Redis down**, the alerts are
judged all the same, what is firing kept in the process until Redis is back.
The metrics, the health report and the alerts read the same snapshot, at
most 15 seconds old.

| Alert | Severity | Fires when |
| --- | --- | --- |
| [worker_stalled](#worker-stalled) | critical | a job has waited over 10 minutes, or none has finished for 15 (ops-watch alone runs every 5) |
| [scheduler_stopped](#scheduler-stopped) | critical | nothing scheduled for 15 minutes — said only while the worker runs: it is the worker that turns a tick into a scheduled run, so a stopped worker is told as such, not as a stopped scheduler |
| [system_unreadable](#system-unreadable) | critical | LEKA cannot read its own state |
| [models_failing](#models-failing) | critical | over 25 % of at least 20 model calls failed in an hour |
| [actions_failing](#actions-failing) | critical | 3 actions on customers' systems failed in an hour |
| [backup_stale](#backup-stale) | critical | backups expected, none good in 26 hours |
| [queue_backlog](#queue-backlog) | warning | over 500 jobs waiting |
| [jobs_failing](#jobs-failing) | warning | 10 jobs failed in an hour |
| [circuit_open](#circuit-open) | warning | a dependency is cut off by its breaker |
| [connectors_failing](#connectors-failing) | warning | 5 sync passes failed in an hour |
| [processing_failing](#processing-failing) | warning | over 20 % of at least 10 processing runs failed |

### What to do

#### worker-stalled
Jobs wait, nothing runs them. `docker compose ps worker` — restarting?
[deployment.md § When the worker stops consuming](deployment.md#when-the-worker-stops-consuming).
A job running for ever holds a lease: `job_runs` where `status = 'running'`
and `locked_until` is long past — the sweep reclaims it.
Worker back and nothing scheduled still: the scheduler is down too — see
below.

#### scheduler-stopped
Without it nothing is put on the queue — the worker waits for ever.
`docker compose ps scheduler`, its logs; `docker compose up -d scheduler`.

#### system-unreadable
The database or Redis does not answer the metrics. `GET /api/v1/health`;
RDS console (status, storage, connections); `docker compose ps redis`.

#### models-failing
`leka_model_calls_1h` by provider says which. A provider's status page; the
key (`LEKA_GOOGLE_API_KEY`…) not revoked or out of quota. The breakers move
traffic to the fallbacks by themselves (§ 3) — if every one fails, the
intentions and the agents say "no model answered": nothing is lost, the
runs fail and can be retried.

#### actions-failing
LEKA cannot reach a customer's system it is authorized to call. The failed
steps in the plan say why (`circuit_open`, `no_answer`, an HTTP status). It
is theirs to fix; tell the workspace's owner. A step that failed is not run
again by itself — a person retries it.

#### backup-stale
`python -m leka.ops.backup dump … --upload` has not succeeded in a day: the
cron on the box (§ 4), its log, the bucket's credentials.

#### queue-backlog
More work than the worker gets through. `leka_queue_depth` says which queue;
a sweep on `leka:low` can wait, `leka:high` cannot. More workers:
`docker compose up -d --scale worker=2`.

#### jobs-failing
`job_runs` where `status = 'failed'` in the last hour, grouped by `job`;
Sentry has their exceptions.

#### circuit-open
`leka_circuits_open` says which kind. It closes by itself once the
dependency answers (one try after 30 seconds). Open for long: the
dependency is down — its status page, its credentials.

#### connectors-failing
`GET /ingestion/sources/{id}/…` and the Sources screen say which and why —
usually a customer's credential revoked or a vendor's outage; the source's
health says it, the next pass retries.

#### processing-failing
`processing_runs` where `status = 'failed'`: which stage. A new parser or
normaliser version is the usual suspect: roll back
([deployment.md § Rolling back](deployment.md#rolling-back)), then reprocess.

## 3. Retries, breakers, degradation — one policy

| Dependency | Retry | Breaker | Degraded service |
| --- | --- | --- | --- |
| A model provider (`model:<provider>:<account>`) | a temporary failure (5xx, timeout, 429) again, with backoff, `LEKA_LLM_RETRIES` times | counts **one** failure per request, once its retries are spent, and only the provider's own: unreachable, timeout, 5xx, 429 — never an empty or malformed answer; opens after 5 in 60 s, for 30 s; then **one** caller tries; LEKA's key shared by every workspace, a workspace's own by it alone | the next model of the route answers (the fallbacks, LEKA's default after a workspace's own); none: "no model answered", the run fails, retryable |
| A customer's system an action calls (`action_endpoint:<id>`) | **never by itself**: an action may have acted — a person decides | opens after 5 failures (timeouts, 5xx) in 60 s, for 30 s | the step fails `circuit_open` — nothing built, signed or sent; a person retries it |
| A vendor a connector reads | backoff on 429/5xx, the vendor's `Retry-After`, a quota reserve (connectors/http.py) | — the next pass retries it | the source's health says it; what was read stays |
| Background jobs | `max_attempts` with backoff; a lost worker's lease reclaimed | — | the job's history says each attempt and its error |
| Redis (rate limits, breakers, alerts) | — | — | **never in the way**: a breaker or a limit whose store is down lets the call through, logged |

Only a failure of the **dependency** counts against its breaker — never a
4xx the request caused. The breakers' state is in Redis, shared by the API
and the workers: a provider down for one is down for all.

## 4. Backup, restore, disaster recovery

### What protects the data

| Layer | What | Where | RPO |
| --- | --- | --- | --- |
| RDS automated backups | point in time, 7 days | the same AWS account | ~5 minutes |
| **Nightly logical dump** (LEKA-408) | `pg_dump` from one snapshot + a manifest of every table's row count | **the backup bucket** — its own credentials, encrypted at rest; in another account for the account itself to fail | 24 hours |
| S3 payloads | raw payloads, re-read from the vendors by the next passes | AWS | — (re-read) |

### Taking one — and proving it restores

```bash
# Once, on the box (and again when the API image changes): the API's image
# with PostgreSQL's own client tools — Debian's are older than RDS and
# pg_dump refuses a newer server. See deploy/backup.Dockerfile.
docker build -f /opt/leka/backup.Dockerfile \
  --build-arg API_IMAGE=ghcr.io/<owner>/leka/api:<sha> -t leka-backup /opt/leka

# Where the dumps land: writable by the image's user (uid 10001).
sudo install -d -o 10001 -g 10001 /opt/leka/backups

# Nightly (crontab, 03:30): dumped from one snapshot, uploaded to the backup
# bucket, the alerts told it happened.
docker run --rm --env-file /opt/leka/production.env -v /opt/leka/backups:/backups \
  leka-backup python -m leka.ops.backup dump /backups/leka.dump --upload

# Monthly, or after any doubt: restored into a throwaway database beside the
# source, every table counted against the manifest, the sha256 checked first.
docker run --rm --env-file /opt/leka/production.env -v /opt/leka/backups:/backups \
  leka-backup python -m leka.ops.backup verify /backups/leka.dump
# restored and verified: 89 tables, 1527 rows, restore took 1.4s
```

On a laptop, the tools of the local PostgreSQL container do:
`LEKA_PG_TOOLS="docker exec -i leka-postgres" python -m leka.ops.backup …`.

`verify` creates its throwaway database on the same server: the database
user needs `CREATEDB` (on RDS, the master user has it). `verify` exits 1 on any difference and names the table: a backup that does
not restore is not one. **Run it monthly** on the last night's dump, and
record the restore time below — it is the RTO, measured.

Validated (2026-10-10, LEKA-408): the full schema — every migration,
pgvector, the append-only triggers — dumped and restored, every table equal;
a changed count and a changed byte both refused (`tests/test_ops.py`).

### Restoring for real

[runbook.md](runbook.md) holds the procedures: point-in-time on RDS (the
primary path), logical restore from a dump (the portable one). In order:

1. **Stop writers**: `docker compose stop api worker scheduler` — nothing
   writes while the base comes back.
2. **Restore** (RDS point in time beside the live one, or `pg_restore` of
   the last dump into a fresh instance).
3. **Verify** — `python -m leka.ops.backup verify` for a dump; table counts
   for RDS (runbook.md § Then verify).
4. **Point** `LEKA_DATABASE_URL` at it, `alembic upgrade head` (a dump older
   than the code), start the API, then the scheduler and the worker.
5. **Check** `GET /api/v1/ops/health` all `ok`; the alerts resolve.

### Recovery expectations

| | Target | Basis |
| --- | --- | --- |
| **RPO** — data lost | 5 minutes (RDS point in time); 24 hours if the AWS account is lost (the dump) | RDS backups; the nightly dump |
| **RTO** — back in service | 1 hour (RDS restore + redeploy); 4 hours from the dump on a new account | RDS restore time; the measured `verify` time + provisioning |

### Critical dependencies

| Dependency | Without it | Recovery |
| --- | --- | --- |
| PostgreSQL (RDS) | nothing works — `/health` 503 | point-in-time restore; the dump |
| Redis | jobs are not queued; rate limits, breakers, alerts state forgotten (all rebuilt) | restart the container: nothing in it is the only copy — `job_runs` re-enqueues what Redis lost |
| The box (EC2) | everything down | new instance, `deploy.sh` (deployment.md § When the whole box is unreachable) |
| S3 | payloads not stored — passes fail and retry | the next passes read again |
| Model providers | intentions and agents fail over to the fallbacks; all down: "no model answered" | the breakers, the fallbacks |
| SMTP (OVH) | invitations and alerts not emailed | Sentry still has the alerts |
| Sentry | errors only in the logs | none needed |

## 5. Gaps, said

- The nightly dump is **built and validated locally, not yet scheduled on the
  box**: building `leka-backup` there (deploy/backup.Dockerfile, not yet built
  against RDS), the crontab lines above, `LEKA_BACKUP_*` in `production.env`
  and the backup bucket in another account are a step on the instance, with
  Haitam. Until then `LEKA_BACKUP_EXPECTED` stays off.
- The RDS point-in-time restore is still to be rehearsed on our instance
  (runbook.md § Honest gaps).
- The external uptime check is to be created (§ 1).
- HTTP metrics are per API process: with several, sum them.
