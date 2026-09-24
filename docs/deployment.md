# Deployment — how LEKA ships, and how to undo it

One environment online: **production**, at `https://app.leka-core.com` (the
web app) and `https://api.leka-core.com` (the API). There is no staging: what
protects production is what runs before it — CI and the browser suite on
every pull request, and `deploy.sh`, which puts the previous release back
when a new one does not come up.

For losing data rather than losing a deployment, see
[`runbook.md`](runbook.md). For what every `LEKA_*` variable means, see
[`configuration.md`](configuration.md). For why the shape below and not a
managed platform, see [`adr/014-hosting.md`](adr/014-hosting.md).

---

## What is running, and where

| | |
|---|---|
| **Instance** | one EC2, `eu-central-1`, x86_64, Docker Compose |
| **Containers** | `caddy` → `web` and `api`, plus `worker`, `scheduler`, `redis`, and `migrate` which runs once |
| **Names** | `app.leka-core.com` → `web`, `api.leka-core.com` → `api`; Caddy holds both certificates |
| **Database** | Amazon RDS for PostgreSQL, `eu-central-1` — **not** on the instance, not reachable from the internet |
| **Object storage** | Amazon S3, `eu-central-1` |
| **Email** | the OVH mailbox `support@leka-core.com`, over SMTP (`ssl0.ovh.net:465`) |
| **Images** | `ghcr.io/<owner>/leka/api:<sha>` and `…/web:<sha>` — one commit, two images, never `latest` |
| **Errors** | Sentry, EU region, scrubbed before they leave — from the API **and** from jobs |
| **Files on the box** | `/opt/leka/` — `deploy.sh`, the compose file, the Caddyfile, and `production.env` |

`production.env` exists **only on the instance**. It is the one file that
holds real credentials, it is in `deploy/.gitignore`, and
`deploy/production.env.example` is its documentation.

**The web app's API address is baked in when its image is built.** Next.js
writes `NEXT_PUBLIC_API_URL` into the JavaScript it sends to browsers, so it
comes from the repository variable `PROD_API_URL` at build time, not from
`production.env`. Changing the API's name means rebuilding the web image.

The worker and the scheduler are two processes of the API image:
`python -m leka.platform.worker` runs jobs, `python -m leka.platform.scheduler`
puts the ten-second tick and the sweeps on the queue. **Without the
scheduler the worker waits for ever** — the tick is what turns `events` into
`job_runs`. Both configure logging and Sentry before they run anything, which
plain `rq worker` and `rq cron` do not.

---

## Deploying

Nothing to do. A merge to `main` runs CI; if CI is green, CD builds the two
images, pushes them and runs [`deploy/deploy.sh`](../deploy/deploy.sh) on the box.

`deploy.sh` is the whole procedure, and it is the same file whether CD runs it
or a person does:

1. **pull** both images — if either fails, nothing has been touched;
2. **switch**: write the registry and the release into `production.env`,
   `up -d`;
3. **verify**: the API answers `/api/v1/health` from inside its own
   container, the web app answers `/login`, and the worker and the scheduler
   are still the same processes five seconds later — not restarting in a
   loop;
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
ssh <user>@<production-host>
cd /opt/leka

grep -E '^LEKA_(REGISTRY|RELEASE)=' production.env   # what is running now

docker login ghcr.io -u <github-user>                # a PAT with read:packages
bash deploy.sh ghcr.io/<owner>/leka <sha>
```

---

## Rolling back

The same command with the previous sha. `deploy.sh` does it on its own when a
deployment does not come up; by hand:

```bash
bash deploy.sh ghcr.io/<owner>/leka <previous sha>
```

**Rehearsed, not assumed.** The exact `deploy.sh` and compose file were run
against a local registry with four releases:

| Scenario | Result |
|---|---|
| first deployment, nothing to go back to | `0`, healthy |
| a release carrying a migration | `0`, schema migrated |
| a release whose migration fails | `1`, back on the previous release, the env file says so |
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

1. **Take an RDS snapshot** (`runbook.md`, "Before anything risky"). It is
   the only undo a downgrade has.
2. **Downgrade with the NEWER image**, before switching back. Only the image
   that wrote a migration knows how to undo it; the older one has never
   heard of it and fails exactly as `alembic upgrade head` did.

   ```bash
   docker compose -f docker-compose.production.yml --env-file production.env \
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
`docker compose -f docker-compose.production.yml --env-file production.env`.

**1. Are the worker and the scheduler alive?**

```bash
dc ps worker scheduler
dc logs --tail=100 worker
dc logs --tail=20 scheduler     # "Enqueued job run_maintenance_tick" every 10 s
```

A process in a restart loop is usually a bad `production.env`: it starts, fails
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
the database is RDS's, the files are S3's, the images are GHCR's, and the
only thing that is not reproducible from Git is `production.env`.

So the recovery is the first-time setup below, with `production.env` written
from the password manager, then `bash deploy.sh` with the last good sha. Ten
minutes, and the first nine are AWS booting a machine. The new instance must
join the security group RDS accepts, or the API cannot reach the database.

**Keep a copy of `production.env` in the team password manager.** It is the
one thing that makes the paragraph above true.

---

## Turning production on

**The CD workflow does nothing until you say so.** It is guarded by a
repository variable, `PRODUCTION_ENABLED`, which does not exist until the
box is ready — so the pipeline can be merged and sit in the repository
costing nothing, running nothing and deploying nothing. A workflow that
fails on every merge because it has nowhere to go teaches people to ignore a
red tick, and that is the one habit CI does not survive.

Everything below happens in a console, by a person. The order matters: the
account before anything is created on it, DNS before Caddy asks for
certificates, the database before the first deployment.

### 1. The AWS account, first

It must be on the **paid plan** before production and customer data go on
it: a free-plan account closes itself after six months or when its credit
runs out. The procedure, and AWS's own words, are in
[`runbook.md`](runbook.md#the-aws-account-convert-it-before-production).

### 2. The database: RDS, once

In the RDS console, `eu-central-1`, **Create database**:

| Setting | Value | Why |
|---|---|---|
| Engine | PostgreSQL, version 16 | what CI tests against |
| Template | Production is overkill; **Dev/Test**, single instance | one box, two developers — see ADR 014 |
| Identifier | `leka` | the name the runbook's commands use |
| Master user | `leka`, password **generated**, stored in the password manager | it goes in `production.env` and nowhere else |
| Instance | `db.t4g.micro` to start | smallest that runs it; resize later without data loss |
| Storage | gp3, 20 GB, **encryption on** (default KMS key) | encryption can only be chosen at creation |
| Public access | **No** | the database is reached by the box, never by the internet |
| Security group | a new one, `leka-db`: inbound 5432 **only from the instance's security group** | not from an IP, not from 0.0.0.0/0 |
| Initial database | `leka` | |
| Automated backups | **on, 7 days** | the point-in-time window; see the runbook |
| Deletion protection | **on** | a deleted instance takes its automated backups with it |

Then in `production.env`:

    LEKA_DATABASE_URL=postgresql+asyncpg://leka:<password>@<endpoint>:5432/leka?ssl=require

The endpoint is on the instance's page, under *Connectivity & security*.
The schema is created by the first deployment (`migrate`), from nothing:
there is no data to carry over from Neon, which only ever held seeded data.

**It costs money, unlike Neon's free plan:** RDS bills per hour the
instance exists, plus storage and backups beyond the database's size. The
credit covers it at first; after that it is a line on the bill. Check it in
the AWS Pricing Calculator before creating it, not after.

### 3. The instance, once

1. An EC2 instance in `eu-central-1`, **x86_64** (the images CD builds are
   amd64), with **at least 20 GB of disk** — each release is two images, and
   `deploy.sh` keeps a week of them.
2. Docker Engine and the Compose plugin (`docker compose version` answers).
3. `/opt/leka/`, owned by the SSH user, holding `production.env` filled in
   from `deploy/production.env.example`. CD copies the other three files on
   every deployment.
4. Security group: 80 and 443 open to the internet, 22 open to GitHub
   Actions. The RDS group admits this one on 5432.
5. An Elastic IP, so the address DNS points at survives a stop and start.

### 4. DNS, at OVH

In the zone of `leka-core.com`, two A records pointing at the Elastic IP:
`app` and `api`. Wait until `dig +short app.leka-core.com` answers it.
Caddy then obtains both certificates on its first start. The email records
(SPF, DKIM, DMARC) are in the same zone; see
[`runbook.md`](runbook.md#email-the-dns-records-that-get-it-delivered).

### 5. GitHub, once

Repository secrets, in an environment called `production`
(Settings → Environments → production):

| Secret | What it is |
|---|---|
| `PROD_HOST` | the Elastic IP, or the instance's DNS name |
| `PROD_USER` | the SSH user |
| `PROD_SSH_KEY` | its private key — a deploy key for this alone, not anyone's personal key |

Repository variables (Settings → Secrets and variables → Actions →
Variables) — not secrets, the browser sees the first one anyway:

| Variable | Value |
|---|---|
| `PROD_API_URL` | `https://api.leka-core.com` — baked into the web build |
| `PRODUCTION_ENABLED` | `true` — **last**, once everything above is in place |

`GITHUB_TOKEN` is provided by Actions: it pushes the images, and the box
pulls with it during the deployment. Nothing to create.

Remove `PRODUCTION_ENABLED`, or set it to anything else, and deployment
stops again — which is also how you pause it during an incident without
reverting anything.

On AWS, a **budget alarm** — already set, at €10. With RDS it will be
crossed: raise it to what the calculator said, so that it still means
"something unexpected is running".

### 6. The first deployment

Run the **CD** workflow by hand (Actions → CD → Run workflow). Then, from a
laptop:

```bash
curl -fsS https://api.leka-core.com/api/v1/health
curl -fsSI https://app.leka-core.com/login | head -1
```

and create an account through the page, as a user would: the email must
arrive, and its link must open `https://app.leka-core.com/verify/…`.

---

## What is deliberately not here

- **No staging.** One environment. A change is tested by CI and the browser
  suite before it merges, and rolled back by `deploy.sh` if it does not come
  up — but nothing is tried online before users see it.
- **One instance.** Deploying restarts the API and the web app; requests in
  flight are dropped. Two instances and a balancer are the answer when that
  starts to matter — see `adr/014-hosting.md`.
- **No metrics, no alerting.** Sentry catches exceptions. Nothing watches
  queue depth or answers "is it slow". `background.md` already stated that
  assumption; this makes it a deployed fact.
