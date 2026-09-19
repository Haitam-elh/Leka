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

## 3. Start PostgreSQL and Redis

```bash
docker compose up -d
```

That is the whole infrastructure: PostgreSQL 16 with pgvector, and Redis 7.
Both are bound to `127.0.0.1` only — nothing is exposed to your network.

Wait for both to report healthy:

```bash
docker compose ps
```

```
NAME            STATUS
leka-postgres   Up (healthy)
leka-redis      Up (healthy)
```

`(health: starting)` is normal for the first ten seconds.

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
curl http://127.0.0.1:8000/api/v1/health
```

```json
{ "status": "ok", "services": { "database": true, "redis": true } }
```

`"status": "degraded"` with a 503 means the API is running but a backing
service is not — the JSON names which one.

Interactive documentation: <http://127.0.0.1:8000/api/v1/docs>

---

## 4b. Demo data

Optional, and the first thing most people want:

```bash
api/.venv/bin/python scripts/seed.py
```

This recreates the **Acme Corp** workspace — three services, a production
database, twelve connected sources, three people, and a latency incident that
followed a deployment. It is what lets the frontend be built before a single
real connector exists.

Re-running it rebuilds the workspace from scratch, so it is safe to run as
often as you like. It touches nothing else in your database.

---

## 5. The frontend

In a second terminal, with the API still running:

```bash
cd web
npm install
npm run gen:api     # regenerates lib/api-types.ts from the running API
npm run dev
```

<http://localhost:3000> — an intentionally empty page. The application shell
is LEKA-330.

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
```

`alembic check` is the one people forget: it fails when a model was changed
without a migration to match.

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
