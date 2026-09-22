# ADR 012 — Events are an outbox in PostgreSQL

**Status:** accepted. Each slice is appended by the pull request that builds it, so
every decision arrives with the code it justifies. This is the sixth: the dispatcher and the service.
**Date:** 2026-09-21
**Ticket:** LEKA-334

## Context

The background loop is the expensive half of LEKA (architecture §4). Until now
it was a Redis queue and four tasks run by hand, and it could not answer a
question a platform engineer asks the first week: **what if the queue loses
the message?**

`enqueue` (then in `leka.platform.jobs`, now `leka.background.jobs`) logs a failure
and carries on. That is right for
housekeeping, which has the reconciliation sweep behind it, and wrong for an
event that nothing else would ever find again — a source sync requested by a
customer, say.

The ticket says "event bus". LEKA has two part-time developers and
architecture §6 rules out anything needing an operator: no Kafka.

## Decisions

### Events are an outbox: a row, written with the change that caused it

An `events` row is inserted **in the same transaction as the business change**.
Since LEKA-330 a request is one transaction — `get_session` commits when the
handler returns and rolls back on any exception — so nothing has to be wired:
the event exists if and only if the change does.

A dispatcher then turns pending events into job runs — rows in the database, one per
job the event triggers — and a separate pass offers those runs to Redis. **Redis is
never on the path of a transaction.** If it is down, the event is not stuck: its runs
exist, and each says it was never enqueued. That is the safety net a lost queue
message never had.

Three things this does **not** give, stated so nobody relies on them:

- **At-least-once, not exactly-once.** A dispatcher can die between creating the
  runs and marking the event, and will do it again; the queue can deliver one
  message twice. Neither becomes a second *execution* — see below — but every
  consumer must still be idempotent. That is a constraint on the consumers, not on
  this module.
- **No global ordering.** Two events written in one transaction are not
  necessarily consumed in order. A case that depends on order must say so
  explicitly and enforce it itself.
- **Not a broker.** Events are small: they say WHAT happened and to WHICH
  thing, never the data. Raw material belongs in the object store (ADR 010).

### Deduplication is a constraint, not a check

`UNIQUE (workspace_id, dedupe_key)`. A webhook delivered twice becomes one
event because the second INSERT is refused — not because code looked first,
which has a race between the look and the write.

It is per workspace, so two customers producing the same key cannot learn about
each other. NULL keys are distinct in PostgreSQL, which is exactly right: an
event with no key has nothing to be a duplicate of.

### Status is text with a CHECK, not a PostgreSQL ENUM

ADR 006. Adding a value to a native ENUM needs a migration that takes a lock,
and this list will move.

An event is `pending`, then `runs_created`, or `failed`. **`runs_created` means
exactly that: the job runs exist.** It does not mean Redis has heard of them — that
is `enqueued_at` on the run, and the two are different facts. It was first called
`dispatched`, a word that reads as "sent", and someone reading the table at three in
the morning would take it for work in flight when nothing may have left the database.
`failed` is final: no route for the event's type, or the dispatcher gave up on it.

### The module sits BELOW `platform`

`leka.background` is layer 2, between `db` and `platform`. Infrastructure every
module must be able to use belongs at the bottom, like `db`, not in the middle:
`platform` itself enqueues work when a workspace is erased, and equal layers may
not import each other (`test_module_boundaries`).

The alternative was to keep the queue transport in `platform` and put the rest
above it. That is a normal stacking, but it splits the answer to "where is this
job?" between Redis and PostgreSQL for anything enqueued from `platform`.

What the placement costs, and it is a healthy constraint: **`background` cannot
import `platform`.** No `Workspace` model, no `secret_box`, no object store.
Event payloads and job arguments are therefore primitives — strings, numbers,
identifiers — never a typed reference to a workspace or a source. RQ serialises
job arguments to JSON regardless, so a model passing business objects would not
work in production even if the layers allowed it. The foreign key to
`workspaces` is declared by table name in the migration, as `db.mixins` already
does; the layer test does not see it and does not need to.

The renumbering that made room for it is its own commit
(`refactor(platform): renumber layers to put background below platform`): it
changes a table of labels and nothing else.

### The request id travels with the event

`leka.core.request_context.current_request_id()` returns None outside a
request — a worker, a migration, a test — which is an answer and not a failure.
Events carry a nullable `request_id`. The publisher captures it when it writes
the event; when the work runs, the worker binds it with
`structlog.contextvars.bind_contextvars`. One search then joins "the user
clicked" to "the worker crashed three minutes later".

### What an event may carry

A type is dotted lowercase words (`source.sync_requested`), at most 100
characters. A payload is JSON of at most 16 KiB. Both are refused where the event
is written, not in the dispatcher: an outbox row that is too big or malformed is
a bug in the publisher, and the publisher is the one who can fix it.

### `job_runs` carries the execution; `sync_runs` will carry only ingestion

A sync is a job. `job_runs` owns state, attempts, timestamps and the error. When
ingestion arrives, `sync_runs` — reserved by ADR 010 — holds **only** the
telemetry specific to ingestion (what was fetched, how much), with a foreign key
to `job_runs.id`. Two parallel histories with their own `status` and `started_at`
would diverge; one history and one extension table cannot.

### `job_runs` has no `workspace_id`, on purpose

A sweep serves every customer and belongs to none, so its owner is NULL.

`workspace_id` nullable was rejected. `test_workspace_id_is_never_nullable` forbids
it — "a row belonging to no one, readable by anyone who forgets to filter" — and
weakening a security test to fit a table is the wrong direction. The deeper problem
is real too: the session guard only protects models inheriting
`WorkspaceScopedMixin`, which declares the column NOT NULL, so a nullable
`workspace_id` would look like the isolation column while nothing protected it.

Instead the column is `for_workspace_id`, nullable, and the table is listed in
`TENANT_FREE_TABLES` with the reason, like `sessions` and `email_tokens`. The
distinct name is the point: nobody will mistake it for the guard.

**Whatever exposes the history filters on `for_workspace_id` explicitly and never
returns the NULL rows.** A system run is operating data, not a customer's.
`JobRunRepository.list_for_workspace` is that filter, and a test holds it there
against the query that would leak them.

**`ON DELETE CASCADE` on `for_workspace_id`:** erasing a customer erases their job
history with the rest, which is what `docs/data-lifecycle.md` already promises. A
consequence worth knowing: a run whose workspace was deleted after it was enqueued
has no row left, so the worker's claim finds nothing and does nothing — there is no
"cancelled" state to invent. The event reference is `ON DELETE SET NULL
(event_id)`, and the column list matters: a plain `SET NULL` would also null
`for_workspace_id` and quietly turn a customer's run into a system run when its
event was pruned.

### The state machine

```
queued ──claim──▶ running ──▶ succeeded              (final)
   ▲                 │
   │                 ├──▶ retrying ──due──▶ queued
   │                 │
   │                 └──▶ failed                      (final)
   └─────────────────────────┘
```

| From | To | When |
|---|---|---|
| `queued` | `running` | a worker claims it; `attempts` goes up by one |
| `running` | `succeeded` | the job returned |
| `running` | `retrying` | the attempt failed and `attempts < max_attempts` |
| `running` | `failed` | out of attempts, or a failure no retry can fix |
| `running` | `retrying` / `failed` | the worker died (lease expired): the same two exits, and it uses up an attempt |
| `retrying` | `queued` | `next_run_at` has passed |

**`retrying` is not `queued`.** `queued` is waiting for a worker; `retrying` is an
attempt that failed, waiting in the database for its next time. A retry is held in
PostgreSQL and not in Redis (`enqueue_in`) because a Redis that loses its memory
must not lose a retry. Collapsing the two would make "is this going to run again by
itself?" unanswerable from the history.

**`failed` is final and terminal.** A run that failed and will be tried again is
`retrying`. Retrying a failed run creates a NEW run, so the history stays true.
Status is text with a CHECK (ADR 006). The transitions are data
(`TRANSITIONS`), and tests assert that every status is reachable, that no status can
get stuck, that the final ones are terminal, and that every repository method, from
every status, only ever moves a run along a declared edge.

**`enqueued_at` is a different question from `status`.** Status says where the run
is in its life; `enqueued_at` says whether Redis was told. A queued run with
`enqueued_at IS NULL` is offered by the next pass, and one Redis was told about long
ago and nobody claimed (`job_stale_enqueued_seconds`) is offered again — the net
under a Redis that lost its memory. A duplicate message is harmless.

### One UPDATE decides every race

Each transition is a single statement with the state it expects in the `WHERE`,
and says whether it changed anything. RQ delivers at least once, so two workers can
hold the same message; `UPDATE ... WHERE status = 'queued'` lets exactly one win. A
worker that lost its lease and finishes late finds the run no longer `running` and
leaves it alone rather than overwriting what recovery decided. There is a test that
races eight workers for one run.

### A worker holds a lease, and a dead one loses it

A claimed run has `locked_until`; the worker renews it at a third of
`job_lease_seconds`, so it survives two missed beats. A worker that dies cannot
report its own death, so **recovery** finds runs whose lease expired and moves them
to `retrying` or `failed`. Without it the run stays `running` for ever and — worse —
holds its concurrency key, so nothing else can run in its place. A lost worker uses
up an attempt, or a job that kills its worker every time would be retried without
ever looking like it was failing.

Retries wait `job_retry_base_seconds` doubling each attempt, capped at
`job_retry_max_seconds`: a downstream that is down for a minute should not be
hammered every thirty seconds.

### The runner: a thread for the job, its own engine for the bookkeeping

Existing tasks are synchronous RQ entry points that call `asyncio.run` themselves,
which cannot run inside a running loop. The runner executes the job in a thread and
keeps its own loop free to renew the lease — which is what stops a job that
legitimately takes ten minutes from looking like a dead one. Its own state writes
use an engine **without a pool**: an asyncpg connection belongs to the loop that
opened it, and the job's loop and the runner's would otherwise share `leka.db`'s
pool.

A job that cannot be imported fails at once and is not retried: it will not import
next time either. The request that caused a run is set on `current_request_id()` for
the job's duration and bound into every log line.

### Concurrency: at most one active run per key

`concurrency_key` is unique among active runs, per owner (`queued`, `running`,
`retrying`), by two partial indexes — because NULLs are distinct in a unique index
and a system sweep has no workspace; with one, two workers could run the same
retention sweep at once. `enqueue_job` returns None when the key is held: two
people clicking "sync" is not an error, it is already happening.

### Dispatch is two hops, and each is a database write first

An event reaches a worker in two steps, and **Redis is never on the path of a
transaction**:

1. The **dispatcher** claims pending events (`FOR UPDATE SKIP LOCKED`), creates a
   `job_runs` row per route, marks the event `runs_created`, and commits.
2. The **enqueue pass** takes runs the queue has not been told about
   (`enqueued_at IS NULL`), offers each to Redis, and stamps `enqueued_at`.

The first version of this ADR had the dispatcher talk to Redis itself. That held a
row lock for a Redis timeout per event, and let a worker pick a message up before
the transaction that created its run had committed. Splitting it means a run is
durable before anyone hears of it, and "the queue was down" is a row that says so
rather than an event stuck in a pass.

Within each hop the order is the design. The dispatcher may die after creating the
runs and before marking the event, and will then create them again: `UNIQUE
(event_id, job)` refuses the second, which is what turns at-least-once into one
run. The enqueue pass offers a run to Redis and THEN stamps `enqueued_at` — in that
order, never the reverse, because a crash between the two must re-enqueue rather than
lose the job silently. **So a run can be picked up twice**, and it is the claim that
makes that harmless: one UPDATE that only one worker can win. Two tests hold it — one
runs the same run from five workers at once, one enqueues the same run twice on a real
Redis — and each asserts the job executed once.

If the first offer fails Redis is down, and the rest would fail the same way, each
after a timeout. So **a pass stops at its first failure** and leaves the others
exactly as they were, to be found again. An event that cannot be turned into runs at all
— a bug, a constraint — is retried and after `dispatch_max_attempts` marked
`failed`; each is handled in a savepoint, so one poisoned event cannot hold up the
ones behind it.

### Routing is a table

`leka.background.routes.ROUTES` maps an event type to dotted job paths. Adding
a consumer is one line. The alternative, a registry every module writes itself
into, keeps the layering but makes the worker import every consumer before it can
dispatch anything: a dependency on import order that fails only in production.
The price of the table is that a file names things it does not own; when it has
more than a handful of entries that is the moment to reconsider.

**An event with no route is marked `failed`, not ignored** — dropping it silently
would look exactly like it working. A job named in the table receives one
argument, the event id as a string, and must check its workspace still exists:
a workspace can be deleted between the event and the job. A test checks that
every path in the table names a function that exists, so a rename cannot leave a
route pointing at nothing until a worker fails at three in the morning.

