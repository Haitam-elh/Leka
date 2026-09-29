# Validation — what a processed record is worth, before it is trusted

Every record normalisation makes ([normalisation.md](normalisation.md)) is
checked before it becomes the company's knowledge: its shape, what it says,
what it contradicts, how complete and how recent it is. LEKA-358. What reads
it next is entity resolution ([resolution.md](resolution.md)) — which
leaves quarantined records out.

```
 normalised_records ──▶ validation (validate:<source>) ──▶ validated_records
                                                     │  valid · warning · quarantined
                                                     ▼
                              entity resolution — quarantined left out,
                              each entity's quality kept
```

## 1. The verdict

| Status | When | What follows |
|---|---|---|
| `valid` | nothing wrong — at most something missing | used |
| `warning` | a doubt: a word off the scale, a date out of order, a duplicate, stale | used, the doubt said |
| `quarantined` | an error: the record cannot be trusted as it is | **kept out of entity resolution, and so of the company model** — the source's other records go on. It comes back by itself when its record is corrected: normalised again (a new pass, a new mapping), then validated again |

Every issue is `{code, severity, field, message, remediation}`: what, where,
and **what a person does about it**. A message never quotes a value of the
record — a title, an address, a date as written.

## 2. The rules

| Code | Severity | When |
|---|---|---|
| `schema` | error | not a NormalisedRecord: a field missing or of another type, a confidence outside 0–1 |
| `bad_key` | error | a key without its type's shape: a person's `person:email:<an address>` or `person:<host>:<account>`; a service's and a team's slug; a commit's sha (4 to 64 hex); an incident's `incident:<tool>:<id>`; a cloud resource's `aws:` / `azure:` / `gcp:`; a space in any key |
| `bad_related_key` | error | the same, for a person, service or team the record names |
| `bad_date` | error | an `…_at` that does not read as a date |
| `person_relationship_to_non_person` | error | `authored_by`, `committed_by`, `assigned_to`, `reviewed_by`, `reported_by`, `created_by`, `led_by` ending anywhere but at a person |
| `unknown_state` | warning | a state off LEKA's scale for its type — `open`, `in_progress`, `closed`, `merged` for issues and pull requests; `open`, `in_progress`, `closed` for incidents; `running` … `failed` for cloud resources |
| `unknown_priority` | warning | a priority off `highest` … `lowest` |
| `future_date` | warning | a date more than a day ahead |
| `ancient_date` | warning | a date before 1990 — a default, not a date |
| `dates_out_of_order` | warning | updated before created |
| `bad_url` | warning | a link that is not `http(s)://` |
| `unknown_relationship` | warning | a relationship type LEKA does not know |
| `self_relationship` | warning | a thing related to itself |
| `duplicate_in_source` | warning | another record of the same source makes the same entity |
| `stale` | warning | a pass has not seen its record for more than 8 days — a weekly full pass sees every record, so the source's passes are failing |
| `incomplete` | info | what a thing of its type is expected to say is missing (§ 3) |
| `vendor_word` | info | normalisation kept something as the vendor wrote it |

## 3. The scores

From 0 to 1, each record:

| Score | How |
|---|---|
| **completeness** | what is present of what its type is expected to say — an issue: link, state, created, updated, author; a pull request: those and its repository; a commit: date, author, repository; an incident: link, state, created, the service it affects; a document: link, updated, author; a cloud resource: state, environment; a person: an address; a repository: link, updated. A type with no expectation is complete |
| **consistency** | 1, less 0.25 for each doubt (warning) but staleness |
| **freshness** | 1 when a pass saw its record within 8 days, down to 0 at 30 |
| **confidence** | the source's confidence in the entity × the parse's quality ([parsing.md](parsing.md)) |
| **quality** | 0.35 completeness + 0.3 consistency + 0.2 freshness + 0.15 confidence — **0 for a quarantined record** |

## 4. Where results are kept, and traced

`validated_records` (`ValidatedRecordRow`): **one row per normalised
record** — its `status`, `issues`, the five scores, `seen_at` (when a pass
last saw its record), its `source_id`, its `normalised_record_id`, and
**`run_id`: the processing run that validated it** (`processing_runs`,
stage `validation`, with the validator's version). Remade when its record
is normalised again or `VALIDATOR_VERSION` changes; gone with its record.

Downstream: entity resolution reads every normalised record **but the
quarantined**, and gives each resolved entity the best `quality` of the
records that are it ([resolution.md](resolution.md)).

## 5. When it runs

The stage after normalisation, one run at a time per source
([processing.md](processing.md)): queued when the normalisation ends, or by
the end of a pass when only it has something to do. It forgets the verdict
of records that failed normalisation since, validates in id order what was
never validated, normalised again since, or validated by another version,
and then hands over — `advance` queues the workspace's resolution.
Incremental and idempotent. `reprocess` with the stage `validation` drops a
source's verdicts and makes them again.

## 6. The API and the screen

`source:read` — every member; another workspace's source is 404.

| | |
|---|---|
| `GET /ingestion/sources/{id}/validation` | valid, warning, quarantined; the mean scores; each issue — how many records, its severity, what to do; the 20 latest quarantined |
| `GET /ingestion/quality` | one line per source: valid, warning, quarantined, mean quality |

The source's page shows it — **Qualité des données**: the counts, the
scores, the issues and what to do, the latest quarantined.

## Not yet

- **Freshness is measured when a record is validated**: a record no pass
  sees again ages without being validated again; the source's own sync
  history says it first. A daily re-measure is the next step.
- **A person's release**: letting an admin trust a quarantined record as
  it is.
- **Rules of one's own**: a workspace's own business rules per type.
