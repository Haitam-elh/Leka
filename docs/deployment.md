# Deployment — how LEKA ships, and how to undo it

Staging, today. Production does not exist yet; when it does, it is this file
with a second environment and two instances behind a balancer.

For losing data rather than losing a deployment, see
[`runbook.md`](runbook.md). For what every `LEKA_*` variable means, see
[`configuration.md`](configuration.md). For why the shape below and not a
managed platform, see [`adr/014-hosting.md`](adr/014-hosting.md).

---

## What is running, and where

| | |
|---|---|
| **Instance** | one EC2, `eu-central-1`, Docker Compose |
| **Containers** | `caddy` → `api`, plus `worker`, `scheduler`, `redis`, and `migrate` which runs once |
| **Database** | Neon, project `Leka`, `aws-eu-central-1` — **not** on the instance |
| **Object storage** | Amazon S3, `eu-central-1` |
| **Images** | `ghcr.io/haitam-elh/leka/api:<commit sha>` — lower case, never `latest` |
| **Errors** | Sentry, EU region, scrubbed before they leave — from the API **and** from jobs |
| **Files on the box** | `/opt/leka/` — `deploy.sh`, the compose file, the Caddyfile, and `staging.env` |

`staging.env` exists **only on the instance**. It is the one file that holds
real credentials, it is in `deploy/.gitignore`, and
`deploy/staging.env.example` is its documentation.

The worker and the scheduler are two processes of the same image:
`python -m leka.platform.worker` runs jobs, `python -m leka.platform.scheduler`
puts the ten-second tick and the sweeps on the queue. **Without the
scheduler the worker waits for ever** — the tick is what turns `events` into
`job_runs`. Both configure logging and Sentry before they run anything, which
plain `rq worker` and `rq cron` do not.

---

## Deploying

Nothing to do. A merge to `main` runs CI; if CI is green, CD builds the image,
pushes it and runs [`deploy/deploy.sh`](../deploy/deploy.sh) on the box.

`deploy.sh` is the whole procedure, and it is the same file whether CD runs it
or a person does:

1. **pull** the image — if that fails, nothing has been touched;
2. **switch**: write the image and the release into `staging.env`, `up -d`;
3. **verify**: the API answers `/api/v1/health` from inside its own
   container, and the worker and the scheduler are still the same processes
   five seconds later — not restarting in a loop;
4. if any of that fails within ninety seconds, **switch back** to the
   previous release and verify that too.

| Exit | Meaning |
|---|---|
| `0` | deployed and healthy |
| `1` | **not** deployed; the previous release is running |
| `2` | nothing healthy is running — the box needs a person |

To deploy a specific commit — or to roll back after the fact — run the **CD**
workflow manually from the Actions tab with `release` set to a commit sha,
short or full. An image that already exists is deployed as it is, never
rebuilt: what goes out is byte for byte what went out the first time.

### By hand, on the box

For when GitHub is down, or the SSH key is being rotated:

```bash
ssh <user>@<staging-host>
cd /opt/leka

grep -E '^LEKA_(IMAGE|RELEASE)=' staging.env   # what is running now

docker login ghcr.io -u <github-user>           # a PAT with read:packages
bash deploy.sh ghcr.io/haitam-elh/leka/api <sha>
```

---

## Rolling back

The same command with the previous sha. `deploy.sh` does it on its own when a
deployment does not come up; by hand:

```bash
bash deploy.sh ghcr.io/haitam-elh/leka/api <previous sha>
```

**Rehearsed, not assumed.** The exact `deploy.sh` and compose file were run
against a local registry with four releases:

| Scenario | Result |
|---|---|
| first deployment, nothing to go back to | `0`, healthy |
| a release carrying a migration | `0`, schema migrated |
| a release whose migration fails | `1`, back on the previous release, `staging.env` says so |
| migration applied, then the API does not start | `1`, back on the previous release **with the newer schema in place** |
| an image that does not exist | `1`, nothing touched |
| going back two releases, by hand | `0`, healthy |

The fourth line is the one that used to fail. See below.

### The schema is not rolled back

Rolling the image back does **not** roll the database back, and that is
deliberate — an automatic `alembic downgrade` during an incident is how a
bad deployment becomes a lost afternoon.

So after a rollback the database is usually **ahead** of the image. The
`migrate` container runs `python -m leka.db.migrate`, which recognises that
and leaves the schema alone with a `schema_ahead_of_release` warning. It used
to run `alembic upgrade head`, which fails on a revision it has never heard
of — and since the API waits for `migrate`, every rollback after a release
that carried a migration failed there, leaving the broken release running.

Almost every rollback needs nothing more: a migration that only adds things
leaves the previous version working. Go further only when the old code
genuinely cannot run against the new schema — a dropped or renamed column.
Then:

1. **Take a Neon branch.** It costs half a second (`runbook.md` measured
   0.54 s) and it is the only undo a downgrade has.
2. **Downgrade with the NEWER image**, before switching back. Only the image
   that wrote a migration knows how to undo it; the older one has never
   heard of it and fails exactly as `alembic upgrade head` did.

   ```bash
   docker compose -f docker-compose.staging.yml --env-file staging.env \
     run --rm migrate alembic downgrade <revision the previous release expects>
   ```

3. Then roll the image back with `deploy.sh`.

The downgrade path is exercised in CI on every pull request
(`alembic downgrade base` then `upgrade head`), so step 2 is tested rather
than hoped for. It was not, before: the downgrade of
`20260920_0930_workspace_lifecycle.py` had never run and did not work.

---

## When the worker stops consuming

The symptom: intentions are accepted and nothing happens. `events` rows stay
`pending`, or `job_runs` rows stay `queued`.

In the commands below, `dc` stands for
`docker compose -f docker-compose.staging.yml --env-file staging.env`.

**1. Are the worker and the scheduler alive?**

```bash
dc ps worker scheduler
dc logs --tail=100 worker
dc logs --tail=20 scheduler     # "Enqueued job run_maintenance_tick" every 10 s
```

A process in a restart loop is usually a bad `staging.env`: it starts, fails
to reach Redis or Postgres, and dies. The logs say which. A scheduler that is
not running is the quiet version of this: nothing fails, nothing is
dispatched.

**2. Is Redis alive, and does it hold the jobs?**

```bash
dc exec redis redis-cli ping
dc exec redis redis-cli llen leka:high leka leka:low
```

Long queues with a live worker means jobs are failing and being retried; go to
step 4. Empty queues with `pending` events means dispatch is not running; go
to step 3.

**3. Is anything dispatching?** The tick the scheduler enqueues runs
`leka.background.tasks.run_maintenance_tick`, which dispatches events into
job runs; the worker logs `event_dispatch_completed` each time. The queries
that answer "is the loop alive" are in [`background.md`](background.md) —
that file is the dashboard, by decision, and this is what that decision
means in practice.

**4. What is actually failing?** Look in Sentry first: an exception inside a
job lands there with its release and two tags, `job` and `run_id`.
`job_runs.last_error` holds the same thing without the stack.

**5. Restart it.** Safe at any moment. A job interrupted halfway is retried,
and LEKA-334's leases mean only one worker can win it:

```bash
dc restart worker
```

**6. Drain a poisoned queue.** When one job kills the worker on every retry
and blocks everything behind it, that job is not worth the outage. Empty the
queue in Redis and re-dispatch from `events`, which is the durable record:

```bash
dc exec redis redis-cli del leka:high leka leka:low
```

---

## When the whole box is unreachable

Everything on the instance is disposable. Nothing on it is a source of truth:
the database is Neon's, the files are S3's, the image is GHCR's, and the only
thing that is not reproducible from Git is `staging.env`.

So the recovery is the first-time setup below, with `staging.env` written
from the password manager, then `bash deploy.sh` with the last good sha. Ten
minutes, and the first nine are AWS booting a machine.

**Keep a copy of `staging.env` in the team password manager.** It is the one
thing that makes the paragraph above true.

---

## Turning the pipeline on

**The CD workflow does nothing until you say so.** It is guarded by a
repository variable, `STAGING_ENABLED`, which does not exist yet — so the
pipeline can be merged and sit in the repository costing nothing, running
nothing and deploying nothing. That is deliberate: a workflow that fails on
every merge because it has nowhere to go teaches people to ignore a red
tick, and that is the one habit CI does not survive.

### The instance, once

1. An EC2 instance in `eu-central-1` with **at least 16 GB of disk** — each
   release is a ~450 MB image, and `deploy.sh` keeps a week of them.
2. Docker Engine and the Compose plugin (`docker compose version` answers).
3. `/opt/leka/`, owned by the SSH user, holding `staging.env` filled in from
   `deploy/staging.env.example`. CD copies the other three files on every
   deployment.
4. Ports 80 and 443 open to the internet; 22 open to GitHub Actions.
5. When DNS points at the instance: `LEKA_STAGING_DOMAIN` in `staging.env`.
   Caddy obtains and renews the certificate itself.

### GitHub, once

Repository secrets:

| Secret | What it is |
|---|---|
| `STAGING_HOST` | the instance's address |
| `STAGING_USER` | the SSH user |
| `STAGING_SSH_KEY` | its private key — a deploy key for this alone, not anyone's personal key |

`GITHUB_TOKEN` is provided by Actions: it pushes the image, and the box pulls
with it during the deployment. Nothing to create.

Then the switch:

    Settings → Secrets and variables → Actions → Variables
    STAGING_ENABLED = true

Remove it, or set it to anything else, and deployment stops again — which is
also how you pause it during an incident without reverting anything.

On AWS, a **budget alarm** — already set, at €10. Not because a bill is
expected, but because a forgotten resource is otherwise discovered a month
later. It costs nothing: it is an alert, not a reservation.

---

## What is deliberately not here

- **No production.** One environment, one instance. Production needs two
  instances, a real balancer and a deployment that does not drop requests in
  flight — see `adr/014-hosting.md`.
- **No metrics, no alerting.** Sentry catches exceptions. Nothing watches
  queue depth or answers "is it slow". `background.md` already stated that
  assumption; this makes it a deployed fact.
- **The web application is not deployed.** The API is. See the ADR for what
  the frontend needs and why it is next.
