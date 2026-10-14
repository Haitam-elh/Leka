# Traceability — from a source to an intention's answer, and back

What links each step of the chain to the next, where each keeps where its
data came from, when and in what state, and the tests that walk the whole
way. LEKA-444. Each stage has its own document; this one is the thread
through them.

```
 source (connector)            sources: status, sync_status, last_synced_at, last_error
   │  a pass                   sync_runs, source_syncs (cursor per capability)
   ▼
 raw_payloads / source_records   source_id, kind, external_id, container, fetched_at, checksum
   │  extraction · parsing · normalisation                      processing_runs (per stage)
   ▼
 normalised_records            entity_key, provenance (the source record's), versions
   │  validation               validated_records: status, issues, scores — quarantined left out
   ▼
 resolved_entities / resolved_keys / resolution_decisions
   │  one thing per real thing: every key per source, every merge with its rule
   ▼
 enriched_relationships / entity_enrichments
   │  stated (the records that said it) or inferred (rule, confidence)
   ▼
 entities / relationships / entity_versions      the company model, versioned
   │  provenance.sources {source_id, key}, provenance.conflicts, first/last_seen_at
   ▼
 contexts / context_versions / context_elements
   │  each element: its provenance — sources, record_id (a relationship's), origin
   ▼
 intention_analyses            context_id + context_version, evidence, explanation
                               (consulted: each source and its state when read)
```

## 1. What links each step to the next

| Step | Made | Linked back by | Where it came from, when, in what state |
|---|---|---|---|
| Pass | `raw_payloads`, `source_records` | `source_id`, `kind` + `external_id` (+ `container`) | `fetched_at`; the pass is the `sync_runs` row whose span holds it ([collection.md § 3](collection.md#3-provenance--where-a-record-came-from)) |
| Extraction, parsing, normalisation | `extracted_records`, `parsed_records`, `normalised_records` | the previous row's `checksum`, each stage's version | the stage's `processing_runs` row ([processing.md § 4](processing.md#4-versions-and-traceability)) |
| Validation | `validated_records` | `normalised_record_id`, `run_id` | `status` (valid, warning, quarantined), `seen_at` ([validation.md § 4](validation.md#4-where-results-are-kept-and-traced)) |
| Resolution | `resolved_entities`, `resolved_keys`, `resolution_decisions` | every canonical key per source | each merge, link or ambiguity with its rule and confidence; disagreements kept as conflicts ([resolution.md](resolution.md)) |
| Enrichment | `enriched_relationships`, `entity_enrichments` | entity ids; a stated relationship's `provenance` → its `normalised_records` | `origin` (stated / inferred), `rule`, `confidence`, `run_id` ([enrichment.md § 9](enrichment.md#9-where-results-are-kept-and-what-reads-them)) |
| Company model | `entities`, `relationships`, `entity_versions` | `provenance.sources` `{source_id, key}` | `first_seen_at`, `last_seen_at`, `provenance.conflicts`, a version per change ([company-model.md § 3](company-model.md#3-what-it-says-and-where-it-came-from)) |
| Context | `context_versions`, `context_elements` | element `ref_id` = the entity or relationship id | each element's provenance; the version kept as it was read ([context.md](context.md)) |
| Analysis | `intention_analyses` | `context_id` + `context_version`; evidence ids → element `ref_id`s | `explanation.consulted`: each source, its state (`read`, `error`, `syncing`, `degraded`, `stale`, `disabled`, `gone`) and `last_synced_at` ([intentions.md § 12 ter](intentions.md)) |

**Back from a proof to the record.** An analysis's evidence names its
sources and the element it is (`ref_id`). Its record at the source is one
call away, on the version the analysis read:
`GET /api/v1/context/{context_id}/elements/{ref_id}/evidence?version=n` —
the source, the kind of record, its id there, its URL, when the source
last showed it, or that it is gone.

**Connected, synced, used** are three things:

| | Said by |
|---|---|
| connected | `sources.status` = `active` |
| synced | `sources.sync_status`, `last_synced_at`, `last_error`; per capability `source_syncs` |
| used for an analysis | `explanation.consulted` — only the sources its context holds elements from |

## 2. The scenarios

`api/tests/test_traceability_e2e.py` runs GitHub's own payloads (a
repository, an issue, the pull request that fixes it, a commit) through
every real stage, each run by hand where the job loop would queue it.

| Scenario | What it shows |
|---|---|
| `test_a_record_reaches_an_answer_and_the_answer_traces_back_to_it` | Each stage asserted on what it made (4 records through, none quarantined, 6 entities — one Sara of her address and her login); « Qui maintient acme/payments ? » answered (Sara K., omar); the source consulted and its state; the repository's proof traced to the source, the context version, and GitHub's record `R_kgDO1` and its URL; who maintains it said as LEKA's inference, never a record's |
| `test_a_change_at_the_source_reaches_the_context_and_the_next_analysis` | The repository's language changed at GitHub: the model changes one entity, the context is made again, the next analysis says Rust; the analysis before still says Python |
| `test_a_failing_then_stale_source_is_never_said_up_to_date` | A pass that fails: the source said `error`, the analysis `partial`, the limit said. Not synced for 20 days: said `stale`, its confidence capped |
| `test_two_sources_of_one_repository_make_one_thing_their_disagreement_said` | Two sources of one repository: one entity, both sources on its proof; their disagreement on its language kept and said, each value with its source; confidence medium. A third source, connected and never read, is not counted as consulted |
| `test_another_workspace_sees_nothing_of_it` | Another workspace's same question finds nothing; the analysis and the record's evidence are 404 to it |

What the stages' own tests already cover, not repeated here: parsing
errors (`test_parsing_job.py`), quarantine and stale records
(`test_validation_job.py`), failed and partial passes (`test_sync.py`),
ambiguous merges (`test_resolution.py`), cross-workspace rows refused by
the database (`test_tenant_isolation.py`).

## 3. Breaks found, and fixed

Each has its test in the same file, now green.

| | Break | Fixed | Test |
|---|---|---|---|
| R1 | A source connected but never read (or still on its first pass) appeared nowhere in the analysis: a limit of coverage unsaid before a conclusion. | The analysis now says it among its limits — `limit.source_unread`: « connected, not read yet: what it holds is not in this answer » (`leka/intentions/processing.py`, `explain.py`). | `test_a_source_connected_but_never_read_is_said_as_a_limit` |
| R2 | An inferred proof (`maintained_by`, `contributes_to`) carried no source: `sources: []`, the proof stopping at the rule. | A rule's inference with no record of its own now names the sources of its two ends — what it was inferred from (`leka/intentions/analysis.py`, `Proofs.tie`). | `test_an_inferred_proof_names_the_sources_it_was_inferred_from` |

Seen, and kept as they are:

- A source `stale` caps the confidence at medium but leaves the analysis
  `complete`; only `error`, `syncing` and `degraded` make it `partial`
  (LEKA-441). Stale data is still the latest the source gave.
- A failing source's `last_synced_at` is its last good pass: what it said
  is said as of then.
- An entity's proof gives its record through the context's evidence route,
  not in the analysis itself (`records` is filled only for a stated
  relationship).

## Not covered

- Real vendors: GitHub is the test's, answering its own payloads.
- The model's synthesis: no model runs in these tests (`synthesis`
  skipped, said).
- Sources other than code: the chain is the same past normalisation; each
  connector's own tests cover its records.
