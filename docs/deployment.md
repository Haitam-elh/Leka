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
| **Containers** | `caddy` → `api`, plus `worker`, `redis`, and `migrate` which runs once |
| **Database** | Neon, project `Leka`, `aws-eu-central-1` — **not** on the instance |
| **Object storage** | Amazon S3, `eu-central-1` |
| **Images** | `ghcr.io/<repo>/api:<commit sha>` — never `latest` |
| **Errors** | Sentry, EU region, scrubbed before they leave |
| **Files on the box** | `/opt/leka/` — the compose file, the Caddyfile, and `staging.env` |

`staging.env` exists **only on the instance**. It is the one file that holds
real credentials, it is in `deploy/.gitignore`, and
`deploy/staging.env.example` is its documentation.

---

## Deploying

Nothing to do. A merge to `main` runs CI; if CI is green, CD builds the image,
pushes it and deploys it. If the API does not answer `/api/v1/health` within
ninety seconds, **CD rolls back to the previous release on its own** and
reports a failure.

To deploy a specific commit — or to roll back after the fact — run the **CD**
workflow manually from the Actions tab with `release` set to a commit sha.
That path does not rebuild: the image already exists, so what goes out is
byte for byte what was tested.

### By hand, on the box

For when GitHub is down, or the SSH key is being rotated:

```bash
ssh <user>@<staging-host>
cd /opt/leka

# What is running now. Write it down before changing it.
grep LEKA_RELEASE staging.env

docker login ghcr.io -u <github-user>          # a PAT with read:packages
docker pull ghcr.io/<repo>/api:<sha>
sed -i "s|^LEKA_RELEASE=.*|LEKA_RELEASE=<sha>|" staging.env
docker compose -f docker-compose.staging.yml --env-file staging.env up -d

curl -fsS http://127.0.0.1/api/v1/health
```

---

## Rolling back

**Measured: 20 seconds** from the command to a healthy API, in the local
rehearsal of this exact compose file.

```bash
cd /opt/leka
sed -i "s|^LEKA_RELEASE=.*|LEKA_RELEASE=<previous sha>|" staging.env
docker compose -f docker-compose.staging.yml --env-file staging.env up -d
curl -fsS http://127.0.0.1/api/v1/health
```

### The part that is not automatic: the schema

Rolling the image back does **not** roll the database back, and that is
deliberate — an automatic `alembic downgrade` during an incident is how a
bad deployment becomes a lost afternoon.

Almost every rollback needs nothing: a migration that only adds things leaves
the previous version working. Go further only when the old code genuinely
cannot run against the new schema — a dropped or renamed column:

```bash
docker compose -f docker-compose.staging.yml --env-file staging.env \
  run --rm migrate alembic downgrade -1
```

Since LEKA-336 the downgrade path is exercised in CI on every pull request
(`alembic downgrade base` then `upgrade head`), so this command is tested
rather than hoped for. It was not, before: the downgrade of
`20260920_0930_workspace_lifecycle.py` had never run and did not work.

**Before running it, take a Neon branch.** It costs half a second
(`runbook.md` measured 0.54 s) and it is the only undo a downgrade has.

---

## When the worker stops consuming

The symptom: intentions are accepted and nothing happens. `events` rows stay
`pending`, or `job_runs` rows stay `queued`.

**1. Is the worker alive?**

```bash
docker compose -f docker-compose.staging.yml --env-file staging.env ps worker
docker compose -f docker-compose.staging.yml --env-file staging.env logs --tail=100 worker
```

A worker in a restart loop is usually a bad `staging.env`: the process starts,
fails to reach Redis or Postgres, and dies. The logs say which.

**2. Is Redis alive, and does it hold the jobs?**

```bash
docker compose -f docker-compose.staging.yml --env-file staging.env exec redis redis-cli ping
docker compose -f docker-compose.staging.yml --env-file staging.env exec redis \
  redis-cli llen leka:high leka leka:low
```

Long queues with a live worker means jobs are failing and being retried; go to
step 4. Empty queues with `pending` events means dispatch is not running; go
to step 3.

**3. Is anything dispatching?** The loop that turns `events` into `job_runs`
is `leka.background.tasks.run_dispatch`. The queries that answer "is the loop
alive" are in [`background.md`](background.md) — that file is the dashboard,
by decision, and this is what that decision means in practice.

**4. What is actually failing?** Look in Sentry first: an exception inside a
job lands there with its release. `job_runs.last_error` holds the same thing
without the stack.

**5. Restart it.** Safe at any moment. A job interrupted halfway is retried,
and LEKA-334's leases mean only one worker can win it:

```bash
docker compose -f docker-compose.staging.yml --env-file staging.env restart worker
```

**6. Drain a poisoned queue.** When one job kills the worker on every retry
and blocks everything behind it, that job is not worth the outage. Empty the
queue in Redis and re-dispatch from `events`, which is the durable record:

```bash
docker compose -f docker-compose.staging.yml --env-file staging.env exec redis \
  redis-cli del leka:high leka leka:low
```

---

## When the whole box is unreachable

Everything on the instance is disposable. Nothing on it is a source of truth:
the database is Neon's, the files are S3's, the image is GHCR's, and the only
thing that is not reproducible from Git is `staging.env`.

So the recovery is: new instance, Docker installed, `/opt/leka` recreated,
`staging.env` written from the password manager, `docker compose up -d`.
Ten minutes, and the first nine are AWS booting a machine.

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

When the instance exists and the secrets below are set, add the variable:

    Settings → Secrets and variables → Actions → Variables
    STAGING_ENABLED = true

Remove it, or set it to anything else, and deployment stops again — which is
also how you pause it during an incident without reverting anything.

### Set once, before the first deployment

Repository secrets:

| Secret | What it is |
|---|---|
| `STAGING_HOST` | the instance's address |
| `STAGING_USER` | the SSH user |
| `STAGING_SSH_KEY` | its private key — a deploy key for this alone, not anyone's personal key |

`GITHUB_TOKEN` is provided by Actions and is what pushes to GHCR; nothing to
create.

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
