# The collection contract — from a connector to a stored payload

What each link of the collection pipeline promises the next, from a vendor's
answer to the bytes the extraction of LEKA-354 will read. LEKA-353. How the
passes run and fail is [sync.md](sync.md); how a connector is written is
[connectors/framework.md](connectors/framework.md).

```
 connector.iter_resources(capability, since)      leka/connectors
        │  RawRecord, one per vendor object
        ▼
 the pass (leka/ingestion/sync.py)                one per source at a time
        │  batches of 500
        ▼
 object store: {workspace}/{source}/{yyyy}/{mm}/{dd}/{uuid}.jsonl
 raw_payloads: one row per object                 committed batch by batch
        │
        ▼
 source_syncs (the cursor), sync_runs (the pass)  what was read, and by whom
```

---

## 1. A record — what a connector hands over

`RawRecord` (`leka/connectors/schemas.py`), one per vendor object:

| Field | | Promise |
|---|---|---|
| `kind` | a `Capability`: `repositories`, `commits`, … | always one the connector declared |
| `external_id` | the vendor's own id — GitHub `node_id`, GitLab numeric ids, Bitbucket `uuid`; project- or repository-prefixed for what has none of its own | **stable across renames**; with `kind`, identifies the object within its source |
| `container` | where it lives: `acme/api` | null for what lives at the top (a repository) |
| `payload` | the vendor's JSON, **untouched** | nothing removed, nothing renamed |
| `updated_at` | when the vendor says it last changed | null when the vendor does not say |
| `fetched_at` | when LEKA read it | always set |

A connector never writes to the database or the store; it only yields.

## 2. A payload — what is stored

Each batch of up to **500 records** becomes one object:

- **Format**: JSON lines (`application/x-ndjson`), one `RawRecord` per line,
  UTF-8. Records of one batch share a capability; they may span containers.
- **Key**: `{workspace}/{source}/{yyyy}/{mm}/{dd}/{uuid}.jsonl` — the
  workspace first (erasing a customer is one prefix), the UTC date of the
  fetch, a random uuid (never guessable, never derived from the content).
- **Its row** in `raw_payloads`: source, key, content type, **size and
  SHA-256 measured by the store while writing**, `fetched_at`, and
  `expires_at` from the source kind's retention
  ([data-lifecycle.md](data-lifecycle.md)).
- **Order**: the object first, the row second, then commit. An object whose
  row never committed is an orphan the weekly reconciliation removes; a row
  without its object cannot happen.

## 3. Provenance — where a record came from

- **Source** and **workspace**: on the payload's row and in its key.
- **When**: `fetched_at`, on the row and on every record.
- **Which pass**: the source's `sync_runs` row whose `[started_at,
  finished_at]` holds the payload's `fetched_at`. Unambiguous, because one
  pass at a time holds `sync:<source_id>`.
- **Which vendor object**: `kind` + `external_id` (+ `container`).

## 4. The per-record index

`source_records` (decided with Haitam, 2026-09-27): one row per `(source,
kind, external_id)` — the checksum of its latest payload (sha256 of the
canonical JSON, keys sorted), when it was first and last seen, **by which
run** (`last_seen_run_id`), the batch holding its latest version
(`payload_key`), and `deleted_at`.

- **Deduplication.** Each batch is checked against the index: a record
  whose checksum is unchanged, still live and still in a batch is **not
  written again** — the pass only records it saw it. New or changed records
  are written. A vendor field that changes on every read (a signed URL)
  defeats it for that record: a write, not a wrong answer.
- **Deletions.** After a **full** read of a capability **succeeds**, what
  its run did not see is marked `deleted_at` — gone at the vendor, restricted,
  made private — and purged from the stored batches (§ 8). By run, not by time: a retry or the quota reserve can stretch
  a pass. Never after an incremental read, never after a full read cut short.
- **Scope.** A reactivation reads in full, so the same sweep removes what
  left the scope — for every connector, whatever its containers mean.
- **Return.** A record seen again comes back: `deleted_at` goes back to NULL.
- **Before the index.** A capability that stored records under LEKA-352 is
  read in full once, so the index knows all of it.

## 5. Guarantees

| | |
|---|---|
| **No loss** | The cursor (`source_syncs.since`) is the start of the last *successful* pass; a failed pass does not move it, so what it did not reach is read by the next. A weekly full pass, per source, reads everything regardless. |
| **At-least-once, deduplicated** | A record may be *read* more than once — a retry, an incremental overlap, the weekly full pass — but is *written* again only when its content changed. |
| **Deletions known** | Within a week (the full pass), or at once after a reactivation. |
| **Ordering** | None across payloads. Within a capability, records come in the vendor's order. |

## 6. Reading it — for the extraction (LEKA-354)

1. Take a source's live payloads (`raw_payloads`, `deleted_at IS NULL`),
   in `fetched_at` order, from where the extraction last stopped.
2. Read each object line by line; each line is a `RawRecord`.
3. **Keep the latest version of each `(kind, external_id)`**: the greatest
   `updated_at`, then the greatest `fetched_at` — or read `payload_key` in
   the index, which names the batch holding it.
4. **Drop what the index says is deleted** (`deleted_at IS NOT NULL`), and
   follow it into `entities`: that is where a deletion reaches the model.
5. Verify the SHA-256 if the payload is to be trusted for an answer — the
   row has what the store measured.

## 7. Backpressure and failures

In [sync.md](sync.md): the 10 % quota reserve on bulk reads, the cap of
passes under way (20, 3 per workspace), the three kinds of failure and who
handles each, an abandoned pass found by the next.

## 8. Purging what was deleted

A record marked deleted must not stay in the store until retention — a page
made restricted is no longer LEKA's to keep. A pass that leaves deleted
records in some batch queues `leka.ingestion.purge.run_purge_deleted`
(key `purge:<source_id>`, one at a time), which reads **every** live batch
of the source — a record that changed three times is in three — and:

- leaves a batch with nothing deleted untouched;
- **withdraws** a batch holding only deleted records (its row is out of
  every read at once; the retention sweep removes the object within the hour);
- **rewrites** a mixed batch without them under a new key: new object, then
  the row and the index point at it and commit, then the old object is
  deleted (a crash leaves an orphan the reconciliation removes).

Before each batch is rewritten, what it would remove is **checked again**,
the index rows locked until that batch commits: a pass can run beside the
purge, and a record seen again since the purge started keeps its line — a
pass that revives one waits for the batch's commit.

Then the index forgets their batch (`payload_key` NULL). It is idempotent: a
second run finds nothing to remove and writes nothing. The pass stays fast;
the purge follows within minutes.

## Not yet

- **A purge that reads only the batches concerned** — each purge reads every
  live batch of the source. Fine today; a source of hundreds of thousands of
  commits will need the index to know every batch a record is in, not only
  the latest (Haitam, review of #89).
- **Checkpoints inside a capability** — a pass that fails half-way through
  a large capability re-reads it from the cursor, not from the page it
  reached; the index makes that re-read cost reads, not writes.
