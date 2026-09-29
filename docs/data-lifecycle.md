# Data lifecycle

What LEKA holds, how long it holds it, who deletes it, and what happens when
a customer leaves.

This document is the answer to two different questions that get asked by two
different people. An engineer asks "where does this go and when does it go
away?". A customer's data protection officer asks "prove that deleting our
account actually deleted our data." Both answers are below, and they are the
same answer.

## Every class of data

| Data | Where | Kept for | Deleted by |
|---|---|---|---|
| **Raw payloads** (bytes) | object store | 30–90 days by source kind — **or until the vendor object is gone** | `leka.ingestion.tasks.sweep_expired_payloads`; a record deleted at the vendor, restricted or out of scope is removed within minutes of the full pass that finds it, by `leka.ingestion.purge` ([collection.md](collection.md#8-purging-what-was-deleted)) |
| **Raw payloads** (metadata) | `raw_payloads` | same, same row | the same sweep, row first |
| **Sessions** | `sessions` | absolute expiry, or revoked | `leka.identity.tasks.purge_expired` |
| **Email tokens** | `email_tokens` | single use, time limited | the same purge |
| **Invitations** | `invitations` | `INVITATION_LIFETIME` | expire in place; removed with the workspace |
| **Entities, relationships** | `entities`, `relationships` | as long as the workspace | cascade from `workspaces` |
| **Sources and their credentials** | `sources` | as long as the workspace | cascade; credentials are Fernet-encrypted at rest (ADR 005) |
| **Sync state** — how far each source has been read, the last diagnostic | `source_syncs` | as long as its source | cascade from `sources`; holds no payload, and its diagnostics are cleaned of secrets |
| **Sync history** — one row per pass: trigger, times, counts, outcome | `sync_runs` | as long as its source | cascade from `sources`; no payload, diagnostics cleaned of secrets. Not pruned yet: ~9 000 rows per source a year |
| **Record index** — per vendor object: checksum, first and last seen, the batch holding it, when it was found gone | `source_records` | as long as its source | cascade from `sources`; no payload — ids, a hash, a key. A deleted record's row stays, so a return is recognised |
| **Extracted records** — per indexed record: what extraction made of it (title, texts capped at 100 000 characters, people, metadata), or why it could not | `extracted_records` | as long as its record is live | removed at the next extraction once its record is marked deleted; cascade from `source_records` and `sources`. **Holds customer text, and follows its record, not the raw payload's retention** — decided in LEKA-360: it is the working data the model is built from, and it goes when the record does ([processing.md](processing.md#6-lifecycle-policies)) |
| **Parsed records** — per extraction: facts with their confidence and a 120-character excerpt of where each was read, the text's shape, a quality score | `parsed_records` | as long as its extraction | cascade from `extracted_records` and `sources`; removed when its extraction fails. Its excerpts are customer text: they follow the record, like the extracted text (LEKA-360) |
| **Normalised records** — per parse: the record's candidate entity under its canonical key, the people, services and teams it names (names, emails, logins), relationships between keys | `normalised_records` | as long as its parse | cascade from `parsed_records` and `sources`; removed when its parse fails. Holds personal data (names, emails) as the vendors gave them; follows the record, like the extracted text (LEKA-360) |
| **Processing history** — one row per run of a processing stage: stage, times, counts, versions, outcome | `processing_runs` | 90 days | `leka.ingestion.lifecycle.sweep_processing`, daily; cascade from `sources`. No payload — counts, versions and an exception's type |
| **Source settings** — versions of a source's scope rules and mapping, with their author | `source_settings` | as long as its source | cascade from `sources`; append-only, never a secret — patterns and mapping choices |
| **Memberships, users** | `memberships`, `users` | as long as the account | cascade from `workspaces`; a user row survives, since a person may belong to several workspaces |

### Raw payload retention, by source kind

Declared in one place, `leka/ingestion/retention.py`. Not in the writer, not
in the sweep, not in a third file — a retention rule spread across three
files is three different rules within a year, and the one nobody updated is
the one still holding data past what was promised.

| Source | Days | Why |
|---|---|---|
| GitHub, GitLab, Bitbucket, Jira, Confluence, Linear, Notion, Asana, Trello, ClickUp, Monday, Slab, Guru, Google Workspace (`google_workspace`), Microsoft 365 (`microsoft_365`), PagerDuty, PostgreSQL, Supabase, MySQL, MariaDB, SQL Server (`sqlserver`), Oracle, MongoDB, a custom API (`custom_rest`) | 90 | Describe structure. Small, slow-moving, and how "when did this change?" gets answered |
| Slack, AWS, Azure, Google Cloud (`gcp`), Datadog, Grafana | 30 | Observability and chatter. Enormous, and worthless within days |

A source kind nobody has thought about falls back to **30 days**, the
shortest policy, because keeping too little means a resync and keeping too
much means a broken promise. A test fails the day a connector is added
without that decision being made.

Overridable without a deploy, for a contract or a regulator:

```
LEKA_RAW_PAYLOAD_RETENTION_DAYS={"datadog": 14, "github": 180}
```

A value outside `[1, 3650]` stops the process at startup. `0` reads as
"disabled" to whoever typed it and means "delete on arrival" to the sweep.

A source may keep **less** than its kind's policy — its own retention, in
its settings, set by an admin on its page
([scope-and-mapping.md § 2 bis](connectors/scope-and-mapping.md#2-bis-retention)).
Never more: asking for more gets the policy. LEKA-348.

The expiry is computed **once, at write time**, and stored as a column. Two
things follow. The sweep is an indexed range scan rather than a walk of every
row through a Python function. And changing the policy does not retroactively
delete what was collected under the old one — which is the behaviour you want
when a customer asks what happened to data they still expected to find.

## When a customer leaves

### What happens, in order

```
1.  DELETE /api/v1/workspaces/current      the owner asks
        -> status PENDING_DELETION, deletion_requested_at set
        -> access stops IMMEDIATELY. The data stays.

2.  DELETION_GRACE_PERIOD passes           a change of mind costs nothing

3.  erase_workspaces_past_grace()          runs on the background loop
        -> DELETE FROM workspaces          every table cascades
        -> commit
        -> purge objects under {workspace_id}/

4.  reconcile_orphaned_objects()           the net, on its own schedule
        -> anything in the store no row speaks for, gone
```

### Why the rows go before the objects

Interrupted after step 3's commit, we have objects nobody claims.
Reconciliation finds them and removes them.

Interrupted the other way round, we would have rows pointing at bytes that no
longer exist. Nothing can repair that: the metadata is all that is left, and
it describes something gone.

So the invariant is: **the only inconsistency we ever allow is an orphaned
object**, because it is the only one with a fix.

### Why two mechanisms and not one

`ON DELETE CASCADE` removes the customer's **rows**. It cannot remove their
**objects** — nothing in PostgreSQL reaches a bucket. So deletion needs
something explicit, and anything explicit can fail: a queue can drop a
message, a worker can be killed between two objects, Redis can be down at
exactly the wrong minute.

The prefix purge is the answer for the ordinary case: fast, and it carries
the intent. The reconciliation sweep is what makes the guarantee **true**
rather than likely. "Usually deleted" is not something you can tell a
regulator.

A deletion therefore goes through even when the queue is unreachable. The
attempt is logged as an error; the account is still deleted; reconciliation
collects the objects later. Refusing to delete an account because Redis
hiccuped would be the worse failure by a long way.

### The GDPR answer, stated plainly

> When a workspace is erased, every row belonging to it is removed by
> cascading foreign keys, and every stored object under its key prefix is
> deleted. A reconciliation sweep independently removes any object no
> database row accounts for, so an interruption at any point in the deletion
> does not leave customer data behind. Deletion is preceded by a grace period
> during which access has already stopped.

What survives, and why:

- **The `users` row** of a person who was a member. A person may belong to
  several workspaces; deleting one of them must not delete them from the
  others. Deleting the *person* is a separate action.
- **Backups taken before the deletion**, until they age out. See
  `docs/runbook.md` for the window. A restore of such a backup reinstates
  rows that were deleted — which is why a restore is followed by re-running
  the erasure sweep, and why the runbook says so.

## Running the sweeps

These run on their own. `rq cron leka.background.cron_config` puts each on the
queue at the interval below; the worker runs it; and each run is recorded (its
attempts, its error, when it finished) in `job_runs`, where a sweep that is still
going is not started a second time. See [background.md](background.md).

Every task is also a plain function with a synchronous entry point, so it can still
be run by hand:

```bash
# Retention: delete what has outlived its policy, row then object
python -m leka.ingestion.tasks

# End the grace period on requested deletions, and purge their objects
python -m leka.platform.tasks

# Sessions and one-time email tokens
python -m leka.identity.tasks
```

Every one of them is safe to run twice: running a sweep again finds nothing
left to do rather than doing damage. That is deliberate, and it is what lets a
schedule that fires while the last run is still going simply be refused.

**Reconciliation should be run with `dry_run=True` the first time against any
real bucket.** The scheduled one does this for you: it only REPORTS, and deletes
nothing until `LEKA_RECONCILE_DELETES=true` is set. Its failure mode is deleting live data, so seeing the number
before trusting it is cheap:

```python
from leka.ingestion.tasks import run_reconcile
run_reconcile(dry_run=True)
```

It ignores anything written in the last two days. An object is stored
**before** its row is committed — it has to be, since the row records the size
and checksum the store measured — so for a moment a perfectly good payload
has no row. Without that grace period, reconciliation would delete data that
was arriving correctly, and nothing would ever say so.

## The schedule

Nothing here is time-critical to the minute. These are the intervals the
sweeps were written for, and the ones in `leka.background.schedule`.

| Task | Interval | Why that one |
|---|---|---|
| `sweep_expired_payloads` | hourly | Bounded per run, so it catches up rather than falling behind |
| `erase_workspaces_past_grace` | hourly | A deletion should complete within an hour of its grace period ending |
| `purge_expired` (identity) | hourly | Expired sessions are credentials; the smallest set we can hold is the right one |
| `reconcile_orphaned_objects` | weekly | Walks the whole store. It is a net, not a hot path. Dry unless `LEKA_RECONCILE_DELETES=true` |
| `prune_events` | daily | The outbox does not grow for ever |
