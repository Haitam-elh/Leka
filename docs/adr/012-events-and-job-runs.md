# ADR 012 — Events are an outbox in PostgreSQL

**Status:** accepted. Each slice is appended by the pull request that builds it, so
every decision arrives with the code it justifies. This is the second: publishing an event.
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

