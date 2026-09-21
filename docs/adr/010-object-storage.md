# ADR 010 — Raw payloads live outside the database

**Status:** accepted
**Date:** 2026-09-21
**Ticket:** LEKA-332

## Context

The background loop collects raw material before it normalises anything: a
GitHub API response, a Datadog log export, a Confluence page as the vendor
sent it. Two properties set these apart from every other kind of data LEKA
holds.

They are the **largest volume** in the product. One customer with a dozen
connected sources produces more bytes of raw payload in a week than their
entire entity graph will hold in a year.

They are the **shortest-lived**. A payload is read once, normalised, and then
kept only so that "why did LEKA say that?" has an answer and a re-parse is
possible after a bug is fixed. Nobody reads a raw log export from last
quarter.

PostgreSQL is a poor fit for exactly that combination. Large, short-lived
rows swell every backup, lengthen every restore, and make deletion expensive:
removing them rewrites table pages and leaves bloat behind, so the cost of
keeping data and the cost of getting rid of it are both paid in the same
place — the database that also has to serve queries.

## Decision

### The bytes go to an object store; the row holds the metadata

`raw_payloads` carries the workspace, the source, an object key, the content
type, the size, a SHA-256, when it was collected and when it expires. The
payload itself is in an object store.

The immediate, measurable consequence is on the restore path. The drill in
`docs/runbook.md` restored a 93 MB database in 72 seconds. The same customer's
payloads at any realistic volume would be tens of gigabytes; with them inside,
that number is minutes to hours, and a restore that takes hours is a decision
nobody makes at 3am.

### One protocol, two implementations

```
ObjectStore        put / get / delete / delete_prefix / exists / iter_prefix
LocalObjectStore   a directory. The default, everywhere but production
S3ObjectStore      anything speaking S3 — Cloudflare R2 today, Amazon S3 later
```

Chosen by configuration, never by an `if` in business code. This is the shape
`leka.platform.secrets` and `leka.identity.email` already use, and it buys the
same thing it bought LEKA-330: the default implementation needs no account
anywhere, so the whole platform is runnable on a laptop and in CI with nothing
to set up. A test of the retention sweep must not depend on the weather in
us-east-1.

S3 rather than R2's own API, although R2 is what we will run first. The
difference between the two is an endpoint URL, and writing against the
narrower one would mean rewriting this module the day we move.

`iter_prefix` is not part of the minimum. It exists because reconciling
orphaned objects means walking the store, and without it that sweep cannot be
written at all.

### The adapter streams

`put` consumes an async iterator and `get` produces one. A connector
exporting a day of logs will hand this a 200 MB body, and an adapter that
materialised it as one `bytes` would take the process down with it.

The size and the SHA-256 are computed **while the bytes go past** and
returned by the store, never accepted from the caller. That is what makes
them usable later as evidence: they describe what was actually written.

### Key shape

```
{workspace_id}/{source_id}/{yyyy}/{mm}/{dd}/{uuid}.{ext}
```

**The workspace first** makes erasing one customer a single prefix delete
rather than a walk of the entire store asking who owns what — and it makes a
cross-tenant leak visible to the naked eye. A key beginning with the wrong
workspace is wrong at a glance, in a log line or a bug report, with no query
to run.

**The date next** because both the retention sweep and manual archaeology
move through time. It is written in **UTC**, so the same payload does not land
in a different day's prefix depending on which machine collected it.

**A fresh uuid last**, never a counter and never a name derived from the
content. A predictable key is an enumerable key. A content hash would be
worse than predictable: the same payload in two workspaces would produce the
same key, which turns the store into a way of asking "does that customer have
this file too?".

### The bucket is never public

Not in production, not in development. Nothing in `S3ObjectStore` grants
anonymous access, sets an ACL or writes a bucket policy. Reading a payload
goes through the application, which knows which workspace is asking.

**Signed URLs are deliberately not implemented yet.** Nothing consumes them —
no interface displays a raw payload, no connector hands one to a third party.
Writing them now would mean guessing a lifetime and a shape. When they are
added, the lifetime is minutes, not hours.

### Production refuses to start on the local store

Like `_refuse_unsafe_cookies_in_production`, checked at startup rather than
left to a review. On a container the filesystem is ephemeral: the payloads
survive exactly as long as the container, a redeploy loses every one of them,
and the rows keep pointing at keys whose bytes are gone. Silently, which is
the part that matters.

### The checksum is stored, but payloads are NOT deduplicated

Storing the fingerprint costs nothing and buys corruption detection
immediately: an object that has silently rotted is caught before we analyse
it and answer a customer with something untrue.

Deduplicating on it is a different proposition and is **not** being done.

Doing it properly needs a unique constraint on `(workspace_id,
checksum_sha256)`. PostgreSQL requires every unique constraint on a
partitioned table to include the partition key, so that constraint would
block the partitioning this same ADR wants to keep possible. Doing it without
the constraint means several rows sharing one object, which means reference
counting before any deletion — real machinery, for a saving nobody can
measure yet because no ingestion loop is running.

**Revisit when** a month of `SELECT count(*) - count(DISTINCT
checksum_sha256)` over `raw_payloads` exceeds **30% of rows**. Below that the
saving does not pay for reference counting.

### Ready to partition, not partitioned

`raw_payloads` grows without bound. It is **not** partitioned today:
partitioning complicates every migration, every unique constraint and every
query plan from the moment it is introduced, and phase 3 is soon enough.

What this ticket does is avoid closing the door:

- `fetched_at` is `NOT NULL` and never rewritten. It is the partition key.
- **No unique constraint anywhere on the table.** Not on `object_key`, not on
  the checksum. Every one of them would have to include `fetched_at` under
  partitioning, and adding one later is a rewrite.

**Revisit when either of these is true:**

- `raw_payloads` passes **50 million rows**, or
- a full logical restore of the database passes **30 minutes**.

The second is the one that will fire first and the one that matters: it is
measured by the drill in `docs/runbook.md`, which is run quarterly, so the
trigger is observed rather than remembered.

### Known future tables, deliberately not created here

Recorded so the decision is traceable rather than rediscovered:

- **`entity_versions`** — the history of attribute changes on an entity.
  Belongs to `leka.knowledge`. Designing it before the ingestion loop exists
  would be guessing at what changes and how often.
- **`sync_runs`** — ingestion telemetry. Arrives with ingestion.
  `raw_payloads.source_id` is enough to attribute a payload until then.
- **`chunks` / `embeddings`** — the pgvector extension is installed and no
  column uses it, which is correct. This belongs to the context layer, after
  there is something to chunk.
- **`audit_log`** — its own ticket.

## Consequences

**Good.** Backups stay small and restores stay fast, which is what makes the
numbers in the runbook liveable. Retention becomes a prefix delete and an
indexed range scan instead of a `DELETE` over the largest table in the
product. Development and CI need no cloud account.

**Bad, and handled.** `ON DELETE CASCADE` no longer removes everything: it
takes the rows and cannot touch the objects. Deleting a customer without
handling that explicitly would leave their data with us for ever — a GDPR
failure and a bill. The answer is two mechanisms, a prefix purge on erasure
and a reconciliation sweep behind it, described in `docs/data-lifecycle.md`.

**Bad, and accepted.** A row and its object can disagree. The ordering rule
is that the row goes first, so the surviving inconsistency is always an
object nobody claims — which reconciliation fixes. The other direction, a row
pointing at nothing, is unrecoverable and is what the ordering exists to
prevent.

## Alternatives considered

**Payloads in PostgreSQL, as `bytea` or `jsonb`.** Simplest, one transaction,
no consistency problem between two stores. Rejected on the restore path
alone: the backup grows by the largest and least valuable data we hold, and
every restore drill after that is a conversation about hours.

**"Just the small ones" in the database.** Splits the retention logic in two,
gives every reader two paths to handle, and the threshold is argued about for
ever. The rule is worth more than the saving.

**Content-addressed keys.** Free deduplication and integrity. Rejected: the
same payload in two workspaces would share a key, which leaks the existence
of one customer's content to another. Cross-tenant inference is not worth a
storage saving.

**An async S3 client (`aioboto3`).** Cleaner than threads. Rejected as a
second dependency for calls the background loop makes a handful of times per
sync; `boto3` in `asyncio.to_thread` is the same pattern `SmtpEmailSender`
already uses for `smtplib`.
