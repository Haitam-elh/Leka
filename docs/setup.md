# Setting up LEKA

From a machine with nothing on it to a running API and frontend. Written for
macOS and Linux. Roughly twenty minutes, most of it downloads.

If a step fails, jump to [When it does not work](#when-it-does-not-work) at
the bottom — the four failures everyone hits are listed there.

---

## 1. What you need first

| Tool | Version | Why |
| --- | --- | --- |
| Git | any recent | the repository |
| Docker | any recent | runs PostgreSQL and Redis |
| Python | **3.12** exactly | the API. 3.13+ is not supported by the pinned dependencies |
| Node.js | 22 or newer | the frontend |

### macOS

[Homebrew](https://brew.sh) first, then:

```bash
brew install git python@3.12 node
```

For Docker, pick one — they are interchangeable, and the repository cannot
tell the difference:

- **Docker Desktop** — `brew install --cask docker`, then launch it once from
  Applications and accept the licence. Needs your admin password. Note that
  Docker Desktop requires a paid licence in companies above 250 employees or
  $10M revenue.
- **Colima** — no GUI, no admin password, no licence clause:

  ```bash
  brew install colima docker docker-compose
  colima start --cpu 2 --memory 4 --disk 20
  ```

  If `docker compose version` then says `unknown command`, the Compose plugin
  is installed where the Docker CLI does not look. Add it once:

  ```bash
  mkdir -p ~/.docker && python3 - <<'PY'
  import json, pathlib
  p = pathlib.Path.home() / ".docker" / "config.json"
  cfg = json.loads(p.read_text()) if p.exists() else {}
  cfg.setdefault("cliPluginsExtraDirs", []).append("/opt/homebrew/lib/docker/cli-plugins")
  p.write_text(json.dumps(cfg, indent=2))
  PY
  ```

  Colima does not survive a reboot. Run `colima start` again, or
  `brew services start colima` to have it come up at login.

### Linux (Debian/Ubuntu)

```bash
sudo apt install git python3.12 python3.12-venv nodejs npm
```

Docker Engine: follow [docs.docker.com/engine/install](https://docs.docker.com/engine/install/),
then add yourself to the `docker` group so you can drop the `sudo`.

Check everything answers:

```bash
git --version && docker compose version && python3.12 --version && node --version
```

---

## 2. Clone and configure

```bash
git clone git@github.com:Haitam-elh/Leka.git
cd Leka
cp .env.example .env
```

`.env.example` works as-is for local development — every value in it is a
working default. `.env` is git-ignored and must stay that way: no secret ever
enters Git.

Enable the hook that refuses a direct push to `main` (once per clone):

```bash
git config core.hooksPath .githooks
```

---

## 3. Start PostgreSQL, Redis and MinIO

```bash
docker compose up -d
```

That is the whole infrastructure: PostgreSQL 16 with pgvector, Redis 7, and
MinIO. All three are bound to `127.0.0.1` only — nothing is exposed to your
network.

Wait for them to report healthy:

```bash
docker compose ps
```

```
NAME            STATUS
leka-postgres   Up (healthy)
leka-redis      Up (healthy)
leka-minio      Up (healthy)
```

`(health: starting)` is normal for the first ten seconds.

**MinIO is an S3-compatible object store**, and it is running by default for
a reason. `S3ObjectStore` is what production uses; the only other thing
exercising it is a stand-in we wrote ourselves, which agrees with what we
*believe* S3 does. A real server disagrees where it counts — it refuses a
delete of more than 1000 keys, and the stand-in accepts one happily. With
MinIO up, `tests/test_s3_against_minio.py` runs instead of skipping.

Its console is at <http://localhost:9001> (`minioadmin` / `minioadmin`),
which is a quick way to see what a test actually wrote.

None of this changes where YOUR payloads go during development: the default
is still `LEKA_OBJECT_STORE=local`, writing under `var/objects/`. MinIO is
there for the tests.

**MySQL, MariaDB, SQL Server, Oracle and MongoDB are off by default**, in
the `connectors` profile: they stand for a customer's databases, for their
connectors' tests (`tests/test_mysql_connector.py`,
`tests/test_mariadb_connector.py`, `tests/test_sqlserver_connector.py`,
`tests/test_oracle_connector.py`, `tests/test_mongodb_connector.py`), which
skip without them. Start them when working on those connectors — every
start is a clean server; MariaDB listens on 3307, beside MySQL; Oracle on
1521, and with TLS on 2484:

```bash
docker compose up -d mysql mariadb mongodb sqlserver oracle
```

Oracle's image is some 6 GB, and wants about 2 GB of memory: give Docker
room for it.

**SQL Server on an ARM Mac.** Microsoft builds it for x86 only, and QEMU's
emulation cannot run it (`Invalid mapping of address … in reserved address
space`). It runs under Rosetta. With Docker Desktop: Settings → General →
*Use Rosetta for x86_64/amd64 emulation*. With Colima, a second machine
keeps the everyday one as it is:

```bash
colima start leka-x86 --vm-type vz --vz-rosetta --cpu 2 --memory 4
docker context use colima                  # colima start switched to the new one
docker --context colima-leka-x86 compose up -d sqlserver
```

Its port is forwarded to `127.0.0.1:1433` like the others'. `colima stop
leka-x86` when done.

---

## 4. The API

```bash
cd api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Create the schema:

```bash
alembic upgrade head
```

Run it:

```bash
uvicorn leka.main:app --reload
```

The API refuses to start if its environment is incomplete, and tells you
which variables are missing. That is deliberate — see
[docs/adr/](adr/).

Check it is alive:

```bash
curl http://localhost:8000/api/v1/health
```

```json
{ "status": "ok", "services": { "database": true, "redis": true } }
```

`"status": "degraded"` with a 503 means the API is running but a backing
service is not — the JSON names which one.

Interactive documentation: <http://localhost:8000/api/v1/docs>

---

## 4b. Demo data

Optional, and the first thing most people want:

```bash
api/.venv/bin/python scripts/seed.py
```

This recreates the **Acme Corp** workspace — three services, a production
database, twelve connected sources, three people (and Jira's own account for
one of them, which entity resolution linked to her as probably the same
person), and a latency incident that followed a deployment. It is what lets the frontend be built before a single
real connector exists. It writes the company model directly, and each of its
things as resolution would have made it, under the same id — so that an
entity's sheet opens. Its incident has its dates, what it affects and what
caused it, as normalisation writes them, so that its sheet's analysis has
something to say (LEKA-341). Its sources disagree on payment-api's SLA —
GitHub's 99.95, Datadog's 99.9 — so that a context says a conflict and folds
a duplicate (LEKA-372). And its model has a build on record, as a real one
would: an intention's context says when the model was never built
(LEKA-373).

It also creates an account you can sign in with, already verified:

```
nora@acme.example / leka-demo-password
```

Without one the demo data would exist and nobody could look at it — every
screen is behind authentication. This account only ever exists in a local
database, next to a workspace called Acme Corp.

Re-running it rebuilds the workspace from scratch, so it is safe to run as
often as you like. It touches nothing else in your database.

---

## 4c. The background worker

Optional for frontend work, necessary for anything touching retention or
deletion.

LEKA splits two loops: the interactive one answers requests, the background
one does the expensive and the slow. Deleting a customer's stored objects is
the first piece of work that genuinely cannot happen inside a request — a
workspace can hold hundreds of thousands of them.

The worker runs **on your host**, like the API. `docker-compose.yml` provides
backing services only, deliberately (see the note at the top of that file).

```bash
cd api && .venv/bin/python -m leka.platform.worker
```

Three queues, drained in that order: `leka:high` is work a person is waiting for,
`leka` is everything else, `leka:low` is the sweeps.

Without a worker, work is still recorded and simply waits. Nothing breaks — a
deletion goes through and its objects are collected later by the reconciliation
sweep. That is by design, not by luck; see [docs/data-lifecycle.md](data-lifecycle.md).

The periodic sweeps are scheduled by a second process, which only puts jobs on the
queue at the right times:

```bash
cd api && .venv/bin/python -m leka.platform.scheduler
```

Without it nothing is scheduled and published events still flow, because a small
maintenance tick is what dispatches them — and that tick is scheduled too. So for
anything involving events or the sweeps, run both. Everything about how they work,
what they do when Redis or a worker dies, and how to look at what happened is in
[docs/background.md](background.md).

You can still run a sweep by hand:

```bash
api/.venv/bin/python -m leka.ingestion.tasks   # retention, then orphans
api/.venv/bin/python -m leka.platform.tasks    # erasures past their grace period
api/.venv/bin/python -m leka.identity.tasks    # expired sessions and tokens
api/.venv/bin/python -m leka.background.tasks  # one tick of the event loop, and prune
```

Each is safe to run twice.

### Where raw payloads go locally

Nowhere near PostgreSQL. `LEKA_OBJECT_STORE=local` writes them under
`var/objects/`, which is in `.gitignore` — they are customer data, and rule 12
is rule 12.

```
var/objects/{workspace_id}/{source_id}/{yyyy}/{mm}/{dd}/{uuid}.json
```

You can delete that whole directory at any time. The rows will then point at
objects that are gone, which is exactly the state `reconcile_orphaned_objects`
exists to clean up — and a reasonable way to see it work.

Production refuses to start on the local store. A container filesystem is
ephemeral, and a redeploy would take every payload with it. See
[ADR 010](adr/010-object-storage.md).

---

## 5. The frontend

In a second terminal, with the API still running:

```bash
cd web
npm install
npm run gen:api     # regenerates lib/api-types.ts from the running API
npm run dev
```

To drive the whole thing in a real browser — which is the only way to check
cookie behaviour, since those rules are enforced by the browser and by
nothing else:

```bash
npx playwright install chromium   # once
npm run e2e
```

<http://localhost:3000> — you will be sent to the sign-in page. Use the demo
account from step 4b, or create one: with no email provider configured, the
confirmation link is printed in the API's log.

The application shell — sidebar, header, workspace switcher — is LEKA-337 and
does not exist yet, so signing in lands on a deliberately thin page.

**Note the URL the frontend calls**: `http://localhost:8000`, not
`http://127.0.0.1:8000`. A browser treats those as different *sites*, so a
SameSite=Lax session cookie set by one is never sent to the other — sign-in
would appear to work and every request after it would be anonymous. See
[adr/009-cookie-strategy.md](adr/009-cookie-strategy.md).

`npm run gen:api` needs the API up: the TypeScript types are generated from
its OpenAPI schema, never written by hand. Re-run it whenever a backend
response shape changes.

---

## 6. Before you open a pull request

Run what CI runs. Nothing merges on a red pipeline.

```bash
# api/
ruff check . && ruff format --check . && mypy leka/ && alembic check && pytest

# repository root — scripts/ is outside api/ and needs asking for by name
ruff check scripts/ && ruff format --check scripts/

# web/
npm run lint && npm run typecheck && npm run build

# web/ — the browser journey. Needs the API's virtualenv and a running
# database; it starts both servers itself.
npm run e2e
```

`alembic check` is the one people forget: it fails when a model was changed
without a migration to match.

**The tests use their own database.** `pytest` redirects itself to
`<your database>_test`, creating and migrating it on the first run. It has
to: the suite deletes every row in `users` and `workspaces` between cases,
and it used to do that in the development database — which silently erased
the demo data and showed up as "I cannot sign in any more". Nothing you run
in `api/tests` touches what you are working with.

The browser tests are different on purpose: `npm run e2e` drives the real
application against the development database, and re-seeds it first.

Conventions for branches, commits and pull requests are in
[conventions.md](conventions.md).

---

## When it does not work

**`docker compose up` says the port is already allocated.**
Something else on your machine owns 5432 or 6379 — often a PostgreSQL
installed by Homebrew. Change the host port in `.env`:

```bash
POSTGRES_PORT=5433
REDIS_PORT=6380
```

and update `LEKA_DATABASE_URL` / `LEKA_REDIS_URL` to match.

**`Cannot connect to the Docker daemon`.**
Docker is not running. Docker Desktop: launch the application. Colima:
`colima start`.

**The API refuses to start and lists variables.**
It found no `.env`, or one with holes. `cp .env.example .env` and try again.
This is the intended behaviour, not a bug: a missing setting stops the
process now rather than surfacing as a `None` in production three weeks
later.

**`LEKA_DATABASE_URL must use the asyncpg driver`.**
Your URL starts with `postgresql://`. It must be `postgresql+asyncpg://`.

**`pip install` fails on a wheel, or the API behaves strangely.**
Check you are on Python 3.12: `python --version` inside the activated
virtualenv. 3.13 and later are not supported yet.

**`pytest` collects nothing and says `Can't locate revision identified by '…'`.**
Your database is at a migration the branch you are on does not have: you ran
`alembic upgrade` on one branch and then switched to another. `conftest.py`
upgrades the test database to `head` when the session starts, so pytest stops
before it collects a single test — it looks like a broken suite and is not.

Alembic cannot downgrade a revision whose file is gone, so the cheap way out
is to go back **before** switching, once per migration the branch added, on
both databases:

```bash
cd api
.venv/bin/alembic downgrade -1
LEKA_DATABASE_URL="$(grep '^LEKA_DATABASE_URL=' ../.env | cut -d= -f2-)_test" \
  .venv/bin/alembic downgrade -1
```

If you have already switched, go back to the other branch, run the above, and
switch again. Or recreate the databases — they are disposable. Stop the API
first, or PostgreSQL refuses to drop a database in use:

```bash
# from the repository root
docker compose exec -T postgres psql -U leka -d postgres \
  -c "DROP DATABASE IF EXISTS leka_test;" \
  -c "DROP DATABASE IF EXISTS leka;" \
  -c "CREATE DATABASE leka OWNER leka;"
cd api && .venv/bin/alembic upgrade head && .venv/bin/python ../scripts/seed.py
```

`leka_test` is recreated by the next `pytest` run.
