# Conventions

How we work on LEKA. Two people, part-time — these exist so that neither of us
has to guess what the other is doing.

---

## Branches

**Two permanent branches: `main`, and nothing else.** `main` is always
deployable. No `develop` — pointless at two people.

Everything else is temporary and named with the Jira key:

| Prefix | For | Example |
| --- | --- | --- |
| `feature/` | new functionality | `feature/LEKA-345-github-connector` |
| `fix/` | a bug | `fix/LEKA-412-sync-timeout` |
| `refactor/` | reorganisation, no behaviour change | `refactor/entity-repository` |
| `docs/` | documentation only | `docs/adr-003-postgres` |
| `chore/` | dependencies, config, tooling | `chore/bump-fastapi` |

**The Jira key is not optional.** It is our only link between the code and the
board.

**A branch lives less than three days.** Past that it diverges too far. A
ticket that needs more than three days needs splitting.

### `main` is protected

No direct push. Everything goes through a pull request.

The repository is private on a GitHub plan without branch protection, so the
guard is local and **every clone must enable it once**:

```bash
git config core.hooksPath .githooks
```

`.githooks/pre-push` then refuses any push to `main`. It is a guard against
accident, not against intent — it only protects the machine that enabled it,
and `--no-verify` bypasses it. If we move to a plan with branch protection,
turn it on server-side and keep the hook as a first line of defence.

---

## Commits

[Conventional Commits](https://www.conventionalcommits.org/), in English.

```
feat(connectors): add GitHub repository discovery
fix(ingestion): handle empty payload from Jira API
refactor(knowledge): extract relationship validation
docs(adr): record PostgreSQL decision
chore(deps): bump sqlalchemy to 2.0.35
```

The scope is the module. The subject says what changed, not what file you
touched.

---

## Pull requests

- **400 changed lines maximum.** Past that, nobody reviews properly — they
  skim and approve. Split it.
- A description saying **what, why, and how to test**.
- **1 approval + green CI**, both required.
- **Squash merge**, so `main` reads one line per feature rather than one line
  per false start.
- **The author merges**, not the reviewer. You merge when you are ready, not
  when someone else happens to be looking.

Delete the branch after merging. Its content is in `main`; the empty branch is
clutter. GitHub keeps a *Restore branch* button if you need it back.

---

## Shared files — handle with care

| File | Rule |
| --- | --- |
| `api/alembic/versions/*` | **LEKA-329 only.** Ask before adding one |
| `api/leka/core/config.py` | **LEKA-329 only.** Request a setting rather than adding it |
| `web/lib/api-types.ts` | **generated** by `npm run gen:api`. Never edited by hand |
| `docker-compose.yml` | both of us, in a dedicated PR |
| `pyproject.toml`, `package.json` | whoever adds the dependency |
| `web/package-lock.json` | **regenerate with `npm run lock`, never `npm install`** — see below |

### Never regenerate the web lockfile on macOS

Run `npm run lock`, which regenerates it inside a `linux/amd64` container.

npm writes a lockfile for the platform it runs on and **omits optional
dependencies belonging to other platforms**. A lockfile produced on a Mac is
missing the Linux-only packages that `@tailwindcss/oxide` and friends pull
in, so `npm ci` succeeds on both our laptops and fails on every CI runner
with `Missing: @emnapi/runtime from lock file`.

This has now happened twice: once when the project was created, and again
when Playwright was added with a plain `npm install`. The macOS check passes
both times, which is exactly why it is worth a rule rather than care.

## Territories

Each of us owns whole modules, from the database schema to the screen.

**Never touch a file that belongs to the other**, not even to fix something
small. A one-line fix in someone else's module is a merge conflict plus a
decision made without them.

| Territory | Owner |
| --- | --- |
| `api/leka/identity/`, authentication screens, `web/components/layout/` | LEKA-330 |
| everything else in the foundation | LEKA-329 |

---

## The twelve architecture rules

Every change is held to these. They are the shape of the system, not
preferences.

**1. Dependencies point one way, never the other.**
`intentions → context → knowledge → ingestion → connectors`. A module is
imported **only through its `__init__.py`**.

**2. Every business table carries `workspace_id NOT NULL` with a foreign
key.** Shared-table multi-tenancy. Two documented exceptions: `workspaces`
(it *is* the tenant) and `users` (a person may belong to several).

**3. The workspace never comes from a URL or a request body.** It is read from
the session, server side. A client that can name its own workspace can name
someone else's.

**4. No database query outside a `repository.py`. Never SQL built by string
interpolation.**

**5. Permissions go through a FastAPI dependency**, never an `if` in a route
body. An `if` gets forgotten in the fourteenth route by someone in a hurry.

**6. A route validates, calls one service, and returns.** Over fifteen lines,
the logic is in the wrong place.

**7. Exactly one place in the codebase calls a language model: `capabilities/`.**

**8. Agents are content (`agents/`), never code.** `capabilities/` loads them;
it does not contain them.

**9. Every schema change goes through an Alembic migration.** Including
`CREATE EXTENSION`.

**10. A merged migration is never edited. Add a new one.** Someone else's
database has already run it.

**11. Every third-party import is recorded in
[THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md).** See below.

**12. Never a secret in Git.** A customer's credentials are encrypted with
Fernet before they reach the database; the keys live in `LEKA_ENCRYPTION_KEYS`,
in the environment. Neither the plaintext nor the key is ever committed.

---

## Third-party code and skills

We import and adapt open-source skills, mostly Apache 2.0 and MIT. Both allow
commercial use. Both require keeping copyright notices. **Apache 2.0 also
requires stating that the file was modified.**

**Any pull request that imports third-party code or a skill adds its row to
[THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md). No exceptions.**

Not paperwork: a licence obligation we cannot meet retroactively once nobody
remembers where a file came from. A reviewer who sees imported code without a
new row in that file requests changes.

For anything landing in `agents/vendor/`, the licence row is the *second*
requirement. The first is a **line-by-line review** — an agent is text that
becomes an instruction executed by a model with access to a customer's
production data.

---

## Before opening a pull request

Run what CI runs:

```bash
# api/
ruff check . && ruff format --check . && mypy leka/ && alembic check && pytest

# web/
npm run lint && npm run typecheck && npm run build
npm run e2e
```

`npm run e2e` drives a real browser. It is the only thing that can check
cookie behaviour — `Secure`, `SameSite`, and what counts as "the same site"
are enforced by the browser and by nothing else. Three of the defects found
in LEKA-330 compiled cleanly and passed every other check.

`alembic check` is the one people forget: it fails when a model changed
without a migration to match.
