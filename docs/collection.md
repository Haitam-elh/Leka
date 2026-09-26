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

## 4. Guarantees

| | |
|---|---|
| **No loss** | The cursor (`source_syncs.since`) is the start of the last *successful* pass; a failed pass does not move it, so what it did not reach is read by the next. A weekly full pass, per source, reads everything regardless. |
| **At-least-once** | A record can be stored more than once: a retried pass re-reads from the same cursor, an incremental read overlaps the previous one by design, a full pass re-reads everything. |
| **Bounded duplication** | A retry re-reads at most what the failed pass had stored; the full pass, one copy per week. Nothing grows without a pass to cause it, and retention removes old payloads. |
| **Per-record deduplication** | **Not yet.** It needs an index of what was seen per `(source, kind, external_id)` — also what detects deletions and scope removals. Pending a design decision (see *Not yet*). |
| **Ordering** | None across payloads. Within a capability, records come in the vendor's order. |

## 5. Reading it — for the extraction (LEKA-354)

1. Take a source's live payloads (`raw_payloads`, `deleted_at IS NULL`),
   in `fetched_at` order, from where the extraction last stopped.
2. Read each object line by line; each line is a `RawRecord`.
3. **Keep the latest version of each `(kind, external_id)`**: the greatest
   `updated_at`, then the greatest `fetched_at`. That one rule is what makes
   at-least-once harmless.
4. Verify the SHA-256 if the payload is to be trusted for an answer — the
   row has what the store measured.

## 6. Backpressure and failures

In [sync.md](sync.md): the 10 % quota reserve on bulk reads, the cap of
passes under way (20, 3 per workspace), the three kinds of failure and who
handles each, an abandoned pass found by the next.

## Not yet

- **Per-record index** — deduplication, deleted objects, objects out of
  scope. Where it lives (LEKA-352, 353, or on `entities`) is an open question.
- **Checkpoints inside a capability** — a pass that fails half-way through
  a large capability re-reads it from the cursor, not from the page it
  reached. Bounded (above); worth it once passes of hours are common.
