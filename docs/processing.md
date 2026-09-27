# Processing — from collected records to processed data

How the stages after collection are ordered, handed over, recorded,
recovered and versioned. LEKA-360. What each stage makes is its own
contract: [extraction.md](extraction.md), [parsing.md](parsing.md),
[normalisation.md](normalisation.md); what feeds them is
[collection.md](collection.md).

```
 collection ──▶ extraction ──▶ parsing ──▶ normalisation
 (a pass)       extract:<id>   parse:<id>  normalise:<id>
 source_records extracted_      parsed_     normalised_
 raw_payloads   records         records     records
                        each run: processing_runs
```

---

## 1. Stages and their dependencies

`leka/ingestion/pipeline.py` — **one definition**, `STAGES`, in order. Each
stage reads only what the stage before it wrote:

| Stage | Reads | Writes | Job | Key |
|---|---|---|---|---|
| extraction | `source_records` + the stored batches | `extracted_records` | `leka.ingestion.extraction.job.run_extraction` | `extract:<source_id>` |
| parsing | `extracted_records` (extracted) | `parsed_records` | `leka.ingestion.parsing.job.run_parsing` | `parse:<source_id>` |
| normalisation | `parsed_records` (parsed) + their extraction | `normalised_records` | `leka.ingestion.normalisation.job.run_normalisation` | `normalise:<source_id>` |

**Handing over.** A pass, and every stage when it ends, calls `advance`,
which queues the **first later stage that has work** — and only that one.
A later stage never runs beside the one before it for the same source: it
is queued when that one ends, and reads rows that are complete. A later
stage alone has work when only its own version changed; `advance` finds it
all the same.

**Work** is decided the same way at every stage: a row is (re)made when its
input has no row yet, when the input changed (its checksum), or when a
version it was made by is not the current one (§ 4).

## 2. Parallel where safe

- **One run of a stage at a time per source** — its concurrency key. Two
  "sync now" clicks, a pass and a retry, never run one stage twice at once.
- **The stages of one source run in order** (§ 1).
- **Different sources run side by side**, each stage on any worker; and a
  source's collection can run while its previous records are processed —
  the stages compare checksums, so what a pass changes meanwhile is redone
  at the next run.

## 3. Recovery and retry

- Every stage is **incremental and idempotent**: it saves chunk by chunk,
  each chunk committed; a row is replaced only by a complete one, in one
  statement.
- A run that **fails** — an exception, a database gone — is recorded
  `failed` with the exception's type, and raised again: the job runner
  retries it with backoff (`LEKA_JOB_MAX_ATTEMPTS`, three by default). The
  retry starts where the last committed chunk ended: what was saved is not
  redone.
- A failed run **queues nothing**: the next stage is queued only when a run
  ends. Downstream never reads a half-made stage as done.
- A run whose **worker died** stays `running`; the stage's next run for the
  source marks it `abandoned` (one run at a time: it cannot be alive).
- A record that fails *inside* a stage (unsupported, malformed, invalid) is
  a row too, with its diagnostic; the run succeeds, its neighbours go on.

Tested in `tests/test_processing_pipeline.py`: a crash half-way through an
extraction and a parse, their retries, what downstream then sees; a run a
dead worker left behind.

## 4. Versions and traceability

Every processed row says what it was made **from** and **by**:

| Row | From | By |
|---|---|---|
| `extracted_records` | `source_records.checksum` | `extractor`, `extractor_version` |
| `parsed_records` | the extraction's `checksum`, `extractor_version` | `parser_version` |
| `normalised_records` | the parse's `checksum`, extractor and parser versions | `normaliser_version` |

And **which run** made it: a row's `extracted_at` / `parsed_at` /
`normalised_at` falls inside exactly one run of its stage for its source —
`processing_runs.started_at … finished_at` — since only one runs at a time.
From there, the source record (`provenance.external_id`, `checksum`,
`payload_key`) leads back to the stored batch and to the pass that read it
([collection.md § 3](collection.md#3-provenance--where-a-record-came-from)).

`processing_runs`: `stage`, `status` (`running`, `succeeded`, `failed`,
`abandoned`), `started_at`, `finished_at`, `counts` (what the run did:
extracted, parsed, failed, forgotten, passed over…), `versions` (each
extraction strategy's for the source's kind, or the parser's or
normaliser's), `error` (the exception's type — its details are in the
logs: a database error's message may quote a record).

## Not yet

- Inspecting a source's pipeline and resuming it over the API, lifecycle
  policies for processed data, an end-to-end run on representative
  payloads — the next PR.
