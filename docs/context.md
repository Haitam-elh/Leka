# The context engine — what LEKA assembles to understand a request

A question about the company — "why is billing slow?" — is not answered
from one source's records. It is answered from what the company knows of
billing and what surrounds it: the services it is, what they depend on,
what happened to them this week, the page that says how to recover them —
each piece with where it came from. The context engine (`leka/context`)
reads what an intention asks for — its kind, what it is about, when,
where, and what is missing (LEKA-373) — finds that (LEKA-371), ranks it —
what matters most first, duplicates folded, disagreements said (LEKA-372)
— assembles it, keeps it version by version (LEKA-370), and hands it to
whatever analyses the request.

```
 sources ─▶ … ─▶ company model (leka.knowledge)      records' own text (leka.ingestion)
                   entities, relationships,             extracted titles and bodies,
                   provenance, events                   indexed by their words
                        │                                        │
                        ▼                                        ▼
 an intention ─▶ read (kind, subjects, period, environment, gaps) ─▶ a request (§ 13)
                        │
                        ▼
 a request ─▶ retrievers: graph · search · content · timeline · paths ─▶ fused (relevance)
                        │
                        ▼
              ranking (topic × trust, duplicates folded, barely relevant left out, conflicts)
                        │
                        ▼
              assembly (order, budget, provenance, why) ─▶ a version, kept
                        │
                        ▼
              AssembledContext (contract v1) ─▶ intentions, capabilities (LEKA-384…)
```

It calls no customer API and no language model: by the time a request
arrives, the background loop has built the model and indexed the records
([architecture.md](architecture.md)). It reads the model through
`leka.knowledge` and the records' text through `leka.ingestion` (the
dependency rule: `intentions → context → knowledge → ingestion`).

## 1. A context, its versions, its elements

| | Table | What it holds |
|---|---|---|
| **Context** | `contexts` | what it is for — a title, a `purpose` in the asker's words, a `subject` (an entity today, an intention with LEKA-384, or a bare request) — what it asks for (its **request**), where it stands (`status`), its latest version (`current_version`), who made it, when it was last checked (`refreshed_at`), archived when |
| **Version** | `context_versions` | one assembly, **never changed**: when, why (`trigger`: created or refreshed, and a `reason`), by which strategy and its version, under which contract, the request it answered, **which build of the model** it read (`model_built_at`, `model_version`), how many elements, whether the budget cut (`truncated`, `dropped`), counts (`summary`), **what each retriever did** (`retrieval`), **how it was ranked** (`ranking`: the policy, what was left out and why, what its sources disagree on), a `fingerprint` of what it holds — or why it failed (`error`) |
| **Element** | `context_elements` | one thing a version holds — an entity or a relationship — at its `position`: its id and type in the model, a label, **what it said then** (`content`), **where it came from** (`provenance`), **why it is there** (`reason`: every retriever that found it), **how relevant** it was found (`relevance`, 0 to 1), **how it was ranked** (`ranking`: its score, its place, every signal it was read from) |

**Kept whole, not as ids.** The model moves on: an attribute changes, a
relationship goes, an entity is removed. A version must say, months later,
what LEKA knew when it answered — so each element is a copy of what the
model said, not a pointer to what it says now.

The request a context answers:

| Field | | |
|---|---|---|
| `roots` | 0 to 10 entities | where it starts — the workspace's, or the context is refused (404). None: what its words find |
| `query` | default the purpose | the words searched |
| `depth` | 1 to 3, default 1 | how many steps the graph walks |
| `relationships` | kinds, default all | only through these |
| `environment` | default all | only what is true in this one |
| `limit` | 1 to 500, default 100 | the budget: at most this many elements |
| `window_days`, `until` | 1 to 365, default 14; default now | the window what happened is read in |
| `retrievers` | default all | which to combine |
| `strategy` | `hybrid` (default) or `neighbourhood` | how the elements are gathered (§ 3) |
| `min_relevance` | 0 to 1, default 0.05 | under this score a thing found is left out — never a root (§ 5); 0 keeps all the budget holds |
| `weights` | retriever → 0 to 3, default 1 | each retriever's findings weighed that many times its own weight — an intention's kind sets them (§ 13); 0 does not run it |
| `sources` | source ids, default every one | only what these sources say — never a root (§ 5, `out_of_scope`) |

A request must start somewhere: roots, or words that say something —
"pourquoi ?" alone is refused (422).

## 2. Its life

```mermaid
stateDiagram-v2
    [*] --> assembling: created
    assembling --> assembled: version 1
    assembling --> failed: every retriever failed
    assembled --> assembled: refreshed — a new version if what it holds changed
    assembled --> failed: refreshed — a root is gone, or every retriever failed
    failed --> assembled: refreshed — it is back
    assembled --> archived
    failed --> archived
    archived --> [*]: read, never reassembled
```

- **Created**: the request is settled, gathered and assembled; version 1 is
  written with its elements in the same transaction. A root that is not the
  workspace's refuses the whole thing — nothing is kept.
- **Refreshed**: assembled again from the model as it is now. If the result
  holds the same things, said the same way — **the same fingerprint** — no
  version is made: `refreshed_at` says it looked, and the latest version
  holds. Otherwise version N+1. Two refreshes at once wait for each other
  (the context row is locked), so they cannot both make N+1.
- **Failed**: a version that holds nothing and says why — a root gone, a
  strategy, kind of relationship or retriever LEKA no longer knows, or every
  retriever that ran failed (§ 4). The last version that held something is
  still what is read by default. Failing again the same way is no news.
- **Archived**: still read — every version — never reassembled (409).

## 3. How it is gathered: retrievers, combined

`leka/context/retrieval.py`, `strategies.py`.

| Retriever | Finds | On what (`detail`) | Weight |
|---|---|---|---:|
| `graph` | what surrounds the roots — or, none asked, what the words found best — `depth` steps, through the kinds asked, removed things never walked through | its steps: `1` | 1.0 |
| `search` | the request's words, and what they also mean, in the **company model's own words** — names, descriptions, labels, keys, folded, each a prefix (`GraphService.matching()`) | the words it holds | 1.0 |
| `content` | the same words in **what the records themselves say** — a page's body, a ticket's description, a pull request's — read back to the things they are about (`ContentRepository.matching()`) | — (the run says the words) | 0.8 |
| `timeline` | what happened in the window around them and what is one step from them — incidents opened and resolved, deployments, changes, releases, merges (`GraphService.events()`) | the event and when: `deployment 2026-09-28T11:30:00+00:00` | 0.8 |
| `paths` | what is on the shortest ways between two roots (up to 6 pairs, 4 steps) | the way's length | 1.2 |

**The order they run in.** The search and the content first. When no root
was asked, the three things they found best are the **anchors**: where the
graph walks from and the timeline reads around. The timeline also reads
around what the graph found one step from them: an incident has no
deployment of its own, the service it affects has. A retriever with
nothing to start from is skipped, and the version says so.

**The words** (`leka/context/language.py`, pure). A request comes as a
sentence, in French or English, about systems named in English. Its words
are folded (accents and case off), the words that say nothing — French and
English stopwords — left out, and each is given what it also means: a
small vocabulary of what an IT question is made of (`facturation` →
billing, invoice; `lent` → slow, latency; `panne` → outage, incident;
`déploiement` → deploy, release; `reprise` → recovery, retry…), a plural or
feminine read as its word. The records' text keeps its accents — the
`simple` dictionary, no stemming — so it is searched by the words as
written and folded both. This is what retrieval reads without paying a
model; an embedding of the sentence would come beside it (§ Not yet).

**The records' text, indexed.** `ix_extracted_records_words`: a GIN index
on each extracted record's title and texts as PostgreSQL's full-text search
reads them — `'simple'`, the first 100 000 characters — the extracted ones
only (migration `20261004_2300_context_retrieval`). A record is read back
to its entity by the key normalisation gave it and the entity resolution
made of that key from that source; a record gone at its source is left
out. No excerpt of a record is kept in a context: what was found is the
entity, and the words.

**Combined** (`fuse()`): reciprocal rank fusion. A thing at rank r of a
retriever adds weight / (10 + r); its **relevance** is the sum over the
retrievers that found it, scaled from 0 to 1 by the most any thing could
have had — found first by every retriever that ran, it is 1. A thing found
high by several is surer than a thing found high by one. **Equally near is
equally ranked** (LEKA-372): what the graph found one step away is all at
rank 1, what it found two steps away all after them — not first to tenth by
name, which made two things equally near unequally relevant. Each element keeps
**every way it was found** (`reason.retrievers`: the retriever, its rank,
what it added, on what), the surest first. A root's relevance is 1.

| Strategy | Version | |
|---|---|---|
| `hybrid` | 1 | the retrievers combined — the default |
| `neighbourhood` | 1 | the graph from the roots, alone (LEKA-370); its versions say no relevance |

A new retriever is a class with `name`, `version`, `weight` and
`retrieve()`, given to `Hybrid.retrievers()`; LEKA-373 chooses the
retrievers and their weights per kind of intention.

## 4. When a retriever fails

**It fails alone.** Each retriever runs in a savepoint with a statement
timeout (`ContextRepository.isolated()`, 5 s): an error in the database or
a query that takes too long is undone — the transaction goes on — and the
others' findings make the context. Each run is reported in the version's
`retrieval`:

| `status` | | `error` |
|---|---|---|
| `ok` | found `found` things in `ms` | — |
| `failed` | it raised | `ProgrammingError: the retriever failed.` — the kind, never a query or a value |
| `timeout` | stopped by the statement timeout | `Took longer than 5000 ms.` |
| `skipped` | nothing to start from | `No words to search.`, `Fewer than two roots…`, `Nothing to start from…` |

**Observable.** A failure is logged (`context_retriever_failed`:
retriever, status, error kind, ms) and every assembly is
(`context_assembled`: context, version, status, strategy, elements, each
retriever's status); the screen shows the report under the figures, a
failed retriever in orange with why. When **every** retriever that ran
failed, the version is `failed` with "Every retriever failed" — the next
refresh, the database back, makes a version that holds something.

## 5. How it is ranked: relevance, trust, what is left out

`leka/context/ranking.py`, pure — no database, no clock: the time it is is
given. Each entity gathered is read on **two axes**, signal by signal, and
every signal is kept with what it was read from (`detail`) and in words
(`said`):

| Axis | Signal | Read from | Weight |
|---|---|---|---:|
| **topic** — how much it is about the request | `asked` | a root: 1, whatever else | — |
| | `retrieval` | how high, and by how many retrievers, it was found (§ 3) | 1 |
| | `proximity` | 1 / (1 + steps) from the nearest root or anchor; 0 when tied to none | bonus 0.25 |
| **trust** — how far it can be relied on | `confidence` | how sure entity resolution was of it | 0.25 |
| | `quality` | how good its records were (validation, LEKA-358) | 0.15 |
| | `freshness` | how lately a source showed it: halved every 30 days | 0.15 |
| | `sources` | how its best source is doing: active and healthy 1, active 0.8, degraded 0.6, failing or disabled 0.3, deleted 0.2 | 0.15 |
| | `corroboration` | how many sources say it: one 0.6, two 0.85, three or more 1 | 0.10 |
| | `lifecycle` | active 1, dormant 0.6, archived 0.3, removed 0.1 | 0.10 |
| | `consistency` | nothing disputed 1, once 0.6, more 0.4 | 0.10 |

```
topic = retrieval + (1 − retrieval) × 0.25 × proximity        (a root: 1)
trust = the weighted mean of the trust signals something measures
score = topic × (0.6 + 0.4 × trust)
```

**Trust moves a score by up to 40 %.** Of two things found as high, the
better sourced comes first; nothing becomes relevant for being well
sourced — a thing found much higher keeps its place over a thing found low
from a perfect source. Being near the roots is a bonus on what retrieval
left, never a cost: a thing tied to nothing keeps what retrieval said. A
neighbourhood, with no retriever, is ranked on nearness alone. **A signal
nothing measures** — a quality never computed, a source whose state was
never read, a thing never seen — is said unknown and left out of the mean,
never guessed.

**What is left out, and why** — never a root, nor an anchor:

| `reason` | |
|---|---|
| `duplicate` | entity resolution linked it to another as probably the same thing — a link of 0.6 or more ([resolution.md](resolution.md)): the surer is kept — the more trusted, then the better scored — the other folded into it, said on both (`ranking.duplicates`, `duplicate_of`). A root is never folded away |
| `low_relevance` | its score is under the request's `min_relevance` (0.05 by default: low enough that a thing found once, not first, still stays) |
| `out_of_scope` | none of the sources the request reads says it (`sources`, LEKA-373) |
| `budget` | beyond the limit, after the order below |

Each is in the version's ranking report — counted by why (`left_out`, and
`ties`: relationships that went with an end), the best 100 listed with
their score and why (`left`). A strategy reads more than the budget holds
(twice, at most a hundred more), so what is folded or left out leaves room
for the next best, not a hole.

**Conflicts are said, not merged** (`conflicts`, each with every side and
who says so — a source by name, or a rule):

| `kind` | When |
|---|---|
| `attribute` | its sources give different values — resolution chose one and kept every one |
| `duplicates` | two things probably the same, one folded into the other, give different values: said, not lost with the one folded |
| `competing` | two of a kind a thing has one of — owners (`owned_by`, `owns`), a manager (`reports_to`), a lead (`led_by`), a parent (`child_of`). Two owners folded into one are no competition |
| `gone` | a source still states a tie to a thing gone from every source |

What a conflict involves carries its id (`ranking.conflicts`) and a lower
consistency: disputed is not wrong, but it is less sure. A conflict about
a thing left out is that thing's, not the context's. The line a model reads
says it: `service "payment-api" … [from acme-eu, acme/backend] — disputed:
sla: 99.95 by acme/backend, 99.9 by acme-eu`.

**A relationship** is as relevant as its weaker end, and as sure as its
own trust: its confidence (0.5), said by a source or inferred by a rule
(1 or 0.7, weight 0.3), by how many sources (0.2).

**Traceable.** Every element says its `ranking`: its score, its place among
the entities (`rank`, from 1), both axes and every signal; the version, the
policy it was ranked under (`version`, `min_relevance`, `trust_share`,
`weights`). A version made before LEKA-372 says no ranking rather than one
made up.

## 6. How it is assembled: order and budget

`leka/context/assembly.py`, pure — no database, no clock.

**The order is the budget's.** The roots first, as asked — or, none asked,
the anchors; then the **best scored** (§ 5), the nearest, the surest, by
name. Each entity taken brings, right after it, the relationships between
it and those already taken — a source's word before a rule's, the surest
first. So a context cut short holds what matters most and how it is tied,
and **never a relationship whose end it lacks**. What does not fit is
dropped deliberately, counted (`dropped`), said (`truncated`) and listed
with why (§ 5) — also when a retriever itself stopped short.

**Why each is there** (`reason`):

| `role` | Means | Also |
|---|---|---|
| `root` | asked for | `depth` 0 |
| `reached` | tied to a root or an anchor | `depth`, the `root` (or anchor), and `via` — the relationship it was reached through, the surest way first |
| `found` | found — by its words, its time, on a way — and tied to none of the rest | `depth` none, or 0 for an anchor |
| `tie` | a relationship between two elements | `depth`: its farther end's |

And every one says `retrievers`: each way it was found. Every element also
carries `text`: itself in one line, for a model to read —
`service "Billing API" (service:billing-api) — tier: 1 [from Catalogue]`,
`"Checkout" depends_on "Billing API" — stated by Catalogue, confidence 0.90`.

## 7. Provenance: where each element came from

Copied from the model when the version is made:

| | Entity | Relationship |
|---|---|---|
| `origin` | `stated`: its sources show it | `stated` by a source's record, or `inferred` by an enrichment rule |
| `rule`, `confidence` | — , its confidence | the rule that inferred it, its confidence |
| `sources` | every source it goes by, with **its key there**; a source deleted since keeps its id and kind, no name | each source whose **record** stated it (`record_id`) |
| `evidence` | — | what the records said (`dependsOn`, `file:line — VAR`…) |
| `inferred_from` | — | the entities a rule read |
| `attributes` | each attribute's origin: a source, or an enrichment rule, its confidence and evidence | — |
| `conflicts` | what its sources disagree on, every value with who said it — and said at the context's level too (§ 5) | — |
| `first_seen_at`, `last_seen_at`, `changed_at` | first and last seen | first seen, last changed |

**What an element is, across builds.** An entity keeps its id from build
to build (resolution's). A relationship does not: each build remakes the
relationships, their ids with them. So a relationship **is** its ends and
its kind (`assembly.identity()`): the fingerprint, the comparison of two
versions and `reason.via` are read through that, never through an id of
the day. And what changes with nothing said differently — being seen
again (`last_seen_at`, `changed_at`), a source renamed, **a rank or a
score** — is left out of the fingerprint: the hourly model sweep does not
make a version, nor something else being found.

## 8. History: every version, as made

- **By number**: `GET /context/{id}/assembled?version=2`.
- **As it stood at a date**: `?at=2026-10-04T09:00:00Z` — the latest
  version that held something, made then or before. What LEKA knew when an
  incident started is one call.
- **What changed**: `GET /context/{id}/diff?from=1&to=2` — the elements
  added, the elements gone, and those said differently with **what** of
  them: `name`, `lifecycle`, `attributes.<name>`, `provenance.sources`,
  `reason`…

A version is never updated — refreshing writes a new one — so reading an
old one reads what it was, whatever the model became.

## 9. The contract downstream services read

`AssembledContext`, **contract version 1** (`CONTRACT_VERSION` in
`leka/context/schemas.py`): one version whole.

| Field | |
|---|---|
| `contract_version`, `context_id`, `version`, `status`, `error` | which, and whether it holds anything |
| `title`, `purpose`, `subject`, `request`, `strategy` | what it is for, what it asked, how it was gathered |
| `elements` | in order — each `{position, kind, ref_id, ref_type, label, entity \| relationship, provenance, reason, relevance, ranking, text}`; `ranking` is `{score, rank, topic, trust, signals: [{name, axis, value, weight, detail, said}], conflicts, duplicates}` |
| `sources` | the sources its elements came from, and how many each |
| `summary` | entities, relationships, stated and inferred, by type, by source kind, by retriever |
| `retrieval` | what each retriever did: `{retriever, version, status, found, ms, detail, error, weight}` — `weight`, what its findings counted for (LEKA-373) |
| `truncated`, `dropped` | what the budget left out |
| `ranking` | how it was ranked: `version`, `min_relevance`, `trust_share`, `weights`; what was left out, by why (`left_out`) and listed (`left`) — none before LEKA-372 |
| `conflicts` | what its sources disagree on: `{id, kind, subject, label, about, chosen, values: [{value, ref_id, by}], refs, said}` |
| `intent` | the intention it was assembled for, as read (§ 13): `IntentPlan`, its `gaps` with this version's — none for a context asked for directly |
| `model_built_at`, `model_version`, `assembled_at` | from which build of the model, when |

In Python (intentions, capabilities):

```python
service = ContextService(ContextRepository(session, workspace_id),
                         GraphService(GraphRepository(session, workspace_id)),
                         content=ContentRepository(session, workspace_id))
made = await service.create(ContextCreate(title=..., purpose="why is billing slow?",
                                          subject=ContextSubject(type="intention", id=...)),
                            by=user_id)              # None: a root is not the workspace's
again = await service.assembled(made.context_id)     # the latest that holds something
then = await service.assembled(made.context_id, at=incident_started)
```

**The contract's rules.** A field added is no new contract — LEKA-371 added
`retrieval`, `relevance`, `reason.retrievers`, `summary.by_retriever` and the
request's `query`, `window_days`, `until`, `retrievers` under version 1;
LEKA-372 added `ranking` and `conflicts`, each element's `ranking` and the
request's `min_relevance` — `relevance` keeps its meaning, how it was
found; the order follows `ranking.score`; a
field that changes meaning or goes raises `CONTRACT_VERSION`, and each
version keeps the one it was made under. What a version stored is read back
leniently — strings, not the registry's enums; fields a later contract adds
ignored; fields an older one lacked read empty — so a snapshot stays
readable after a kind is renamed.

## 10. The API and the screen

| Route | Permission | |
|---|---|---|
| `POST /context` | `intention:create` | a context assembled: version 1, whole (201); a root not the workspace's: 404; nothing to start from: 422 |
| `POST /context/intents/plan` | `intention:read` | what an intention asks for, read from its words and scope (§ 13): `IntentPlan` — nothing kept |
| `POST /context/intents` | `intention:create` | that context, assembled and kept with its plan (201); nothing named and no word to search: 422 |
| `GET /context` | `intention:read` | the contexts, the latest changed first, paged — `status`, `subject_type`, `subject_id` |
| `GET /context/{id}` | `intention:read` | one, and its latest version |
| `POST /context/{id}/refresh` | `intention:create` | `{changed, version}`; archived: 409 |
| `POST /context/{id}/archive` | `intention:create` | archived; twice changes nothing |
| `GET /context/{id}/versions` | `intention:read` | its versions, the latest first, paged — each with its retrieval report |
| `GET /context/{id}/assembled` | `intention:read` | one version whole: `?version=`, or `?at=`, or the latest that holds something; both: 400 |
| `GET /context/{id}/diff?from=&to=` | `intention:read` | what changed |

A member reads and makes contexts; a suspended workspace reads only
(`intention:create` is a write). The workspace is the session's; another
workspace's context is 404, and its entities cannot be roots. Fine-grained
access to contexts is LEKA-376.

**The screen**: an entity's sheet, tab **Contexte**
(`web/components/environment/entity-context.tsx`). With none yet, it
assembles one around the entity — why (its words guide the search), how
far, over what period. Then: what it is for, its state and version, the
figures, how it was searched — each retriever and what it found, a failed
one in orange — the elements in order, each with its relevance and why it
is there — its score, a conflict, what was folded into it — and, opened,
**why that rank** (each signal, its value, what it was read from, in
words), its provenance, every way it was found and what LEKA reads of it;
beside them the versions, any one shown again, two compared; **the
conflicts**, every side with who says so; **what was left out**, counted
by why and listed on asking; reassemble, archive, a new context. The
figures say why things were left out, and a disagreement is said among
what is uncertain. Sized for a 13-inch screen: the list scrolls, the page
does not.

## 11. How well it retrieves

`tests/test_context_retrieval.py`, on Acme's operations through the whole
pipeline (GitHub, PagerDuty, Jira, a catalogue, a business system, a
Confluence page whose body only says what it is about). Five
representative requests, each with the evidence it must find:

| Request | Must find |
|---|---|
| « Pourquoi la facturation est lente ? » — no root, the week before 29 Sep | Billing API, its incident Q1, its production deployment, the change before it |
| « Qu'est-ce qui a changé avant l'incident « Invoices fail to send » ? » | the incident, the change and the deployment before it, Billing API |
| « Où est la procédure de reprise des paiements ? » | the Confluence page, named nowhere but in its body |
| « Comment Checkout est-il relié à la facturation ? » — roots Checkout and Invoicing | Billing API and the Billing platform, on the way between them |
| « Qui a déployé Billing API ? » — 2 steps | the deployment, and Sara |

Each configuration on each request: the share of the evidence found within
the budget (recall), and how high the first of it comes among what is not a
root (mean reciprocal rank). The test fails if the hybrid finds less than
all of it, ranks it lower than 0.5, or does not beat every retriever alone.

| Retrievers | Recall | MRR |
|---|---:|---:|
| **hybrid** | **1.00** | **0.74** |
| search alone | 0.85 | 0.63 |
| content alone | 0.20 | 0.20 |
| graph alone | 0.20 | 0.20 |
| paths alone | 0.20 | 0.20 |
| timeline alone | 0.00 | 0.00 |

The graph and the timeline alone have nothing to start from when no root
is asked — that is why they run after the words. The table is printed by
`pytest tests/test_context_retrieval.py -k quality -s`. Ranked (LEKA-372),
the hybrid still finds all of it, as high: ranking left nothing out of
these five that the budget held.

**How well it ranks** — `tests/test_context_ranking.py`, representative
cases on Acme around Billing API, and `test_context_engine.py` through the
API:

| Case | What must hold |
|---|---|
| Two found as high, one only by a failing source, seen 120 days ago | the better sourced first; each signal says why |
| A dormant thing found high from a poor source, a solid one found low | the one found high first: trust moves a score by 40 % at most |
| Tied to the anchor, or tied to nothing, found as high | the tied one first; the other keeps what retrieval said |
| A thing never measured, never seen, its source unknown | said unknown, left out of the mean |
| Found barely (0.04) | left out, said why; 0 keeps it; a root never |
| Resolution linked a service to another (0.75) | folded into the surer, said on both; their different tier said as a conflict; a link of 0.4 folds nothing; a root never folded away |
| Two Nadia accounts, both owners, linked | one owner, not a competition; their emails said |
| Sources disagree on a tier; two owners; a tie to a thing removed | each said with every side and who says so; the line a model reads says the dispute |
| The budget | what does not fit listed, the ties it took counted, each kept entity at its place |

## 12. Storage, size, speed

- Indexes: contexts by `(workspace, updated_at)` for the list and by
  `(workspace, subject_type, subject_id)` for a subject's; versions unique
  by `(context, version)`; elements by `(version, position)` to read a
  version in order, and by `(workspace, ref_id)` — which contexts used a
  thing, what LEKA-374 will refresh when it changes; the records' words
  (`ix_extracted_records_words`, GIN, § 3).
- **Tenancy is structural**: versions are tied to their context, elements
  to their version, by composite foreign keys on `(workspace_id, id)` — a
  row can never point into another workspace. The content search reads its
  workspace's records only.
- Size: an element is its content and provenance as JSON — on LEKA's own
  model, a context of 31 elements weighs ~40 KB, of 74 ~90 KB. A version is
  written only when something changed. Its ranking (LEKA-372) adds about 1 KB: on the demo, 0.9 KB
  for an element's 1.2 KB.

- Speed — `scripts/bench_knowledge_graph.py`, 20 000 entities and 60 000
  relationships, PostgreSQL 16 on a laptop, median of 7:

| | ms |
|---|---:|
| neighbourhood of a typical service, 1 step — ranked, assembled and kept | 18 |
| neighbourhood of the busiest service, 2 steps, 500 elements (600 read, ranked) | 351 |
| a version of 500 elements, read back with their rankings | 58 |
| hybrid, from words only — search, content, graph and timeline from what they found | 63 |
| hybrid, the busiest service and its words | 61 |
| refreshed, nothing changed (500 elements) | 120 |

  Ranking (LEKA-372) costs where it reads more and keeps more: a strategy
  reads up to twice the budget, so that what is folded or left out leaves
  room for the next best; each element keeps its ranking, signal by signal,
  and reads it back (13 ms before, for 500 elements).

- Kept as long as the workspace, like the model's own history
  ([data-lifecycle.md](data-lifecycle.md)); deleting the workspace deletes
  them.

## 13. What an intention asks for (LEKA-373)

`leka/context/intent.py`, pure; `ContextService.plan_intent()` and
`assemble_intent()`. An intention comes as a sentence — « Pourquoi l'API
de paiement est-elle plus lente depuis hier ? » — and, from the new
intention's form, a scope: an environment, a period, services, sources.
LEKA reads from them the context request it makes, and says what it read
and from which words, so that what it understood can be checked — and
corrected by asking differently, or by choosing the scope.

**Its kind**, from its words (`kind_of()`, French and English): the kind
with the most of its words, the first on a tie.

| Kind | Said by | Facets | Steps | Days | Retrievers weighed | Ties | Its sources must read |
|---|---|---|---:|---:|---|---|---|
| `diagnose` | pourquoi, lent, panne, erreur, échoue, incident, timeout… | technical, temporal, organizational | 2 | 7 | timeline ×1.5 | all | incidents, alerts, events, metrics, logs, deployments, changes |
| `change` | changé, déploiement, release, version, merge… | technical, temporal | 1 | 14 | timeline ×2 | all | deployments, changes, releases, commits, pull requests |
| `migration` | migrer, remplacer, plan, upgrade… | technical, business, organizational | 2 | 30 | graph ×1.3, paths ×1.3 | all | what runs: components, services, instances, clusters, databases… |
| `compliance` | conformité, sécurité, RGPD, audit, règles, risque… | business, technical, organizational | 2 | 90 | content ×1.5, search ×1.2 | all | what is written: pages, spaces, files, records |
| `dependency` | dépend, relié, connecté, architecture, utilise, impact… | technical, business | 2 | 30 | graph ×1.3, paths ×1.5, timeline ×0.5 | depends_on, uses, reads_from, deployed_to, runs_in, part_of, implements, realizes, supported_by, in_network, child_of | what runs |
| `ownership` | qui, responsable, propriétaire, équipe, astreinte… | organizational, technical | 2 | 30 | graph ×1.5, search ×1.2, timeline ×0.5 | owns, owned_by, member_of, maintained_by, led_by, reports_to, contributes_to, authored_by | teams, people, components, repositories |
| `knowledge` | procédure, runbook, documentation, comment, reprise… | technical | 1 | 90 | content ×2, search ×1.3, timeline ×0.5 | all | what is written |
| `general` | none of these | technical, temporal | 1 | 14 | — | all | — |

**What it is about** (`subjects`, the context's roots, first):

| `how` | |
|---|---|
| `asked` | the services the asker chose |
| `named` | what its words name (`named()`): a thing's name or key as written — confidence 1 — or every word of its name, in either language (« l'API de paiement » names payment-api) — 0.8; half the words is a guess, never a root, offered when nothing is named. A word a name takes as written names nothing else: « Billing API » is not also the Invoicing its « billing » could mean |
| `business` | for a kind with a business facet: the applications, capabilities and processes the technical things named belong to, two steps away at most — so the context holds both sides and the ways between them |

**When** (`period`, with its `origin`): asked; else read from the words
(`period_of()`) — « hier », « aujourd'hui », « cette semaine », « la
semaine dernière », « ce mois », « depuis 3 jours », « 24h », « depuis
lundi », « le 3 octobre », 2026-10-03; « depuis le déploiement » is read
from the model: since the latest deployment of what it is about (`model`);
else the kind's last days (`kind`). The request reads the window in whole
days up to the period's end.

**Where** (`environment`): asked — the form's, unless "every one"; else
read from the words — « en prod » is the production the model knows, an
environment the model knows by name is itself — never a word of a thing's
name (« postgres-prod » is a database). An environment the model does not
know is not applied, and said.

**Under what constraints** (`constraints`, each with its origin): the
period, the environment, the services and the sources asked, the ties and
the retrievers' weights of its kind. The sources asked hold the context to
what they say (`out_of_scope`, § 5). What a source can read is what it was
found able to read when tested, or — never tested — what its connector
says it can.

**What is missing, said** (`gaps`, each `critical` or a `warning`, with
what it was read from):

| `kind` | When | |
|---|---|---|
| `no_subject` | a kind that is about something names nothing in the model: the context is what its words find; what was tried, and what it may have meant | critical |
| `ambiguous_subject` | the same words name several things: each is read | warning |
| `unknown_service` | a thing asked for is not in the model | critical |
| `unknown_environment` | an environment the model does not know: read everywhere | warning |
| `no_source_for` | none of the sources read can read what its kind needs | critical for what happened (diagnose, change), else a warning |
| `no_event_anchor` | « since the deploy », and no deployment found: the kind's window | warning |
| `model_not_built`, `model_stale` | the version read a model never built, or built more than a day before | critical, warning |
| `nothing_happened` | the timeline found nothing in the period, when what happened is the question | critical for a change, else a warning |
| `retriever_failed` | a retriever failed or timed out | warning |
| `no_business` | a business facet, and nothing of the business side in the context | warning |
| `disputed_subject` | the sources disagree on what it is about (§ 5) | warning |

The first five are read before anything is assembled and kept with the
plan; the rest are read from each version when it is read — a refresh
says its own.

**Kept and traceable.** `assemble_intent()` makes the context — its
subject the intention (`intention_id`) when there is one, else the request
— and keeps the plan with it (`contexts.intent`); `AssembledContext.intent`
gives it back with this version's gaps. Its elements say their sources
(§ 7), its retrievers what they counted for (`weight`). Nothing named and
no word to search: refused (422), nothing kept.

**Tested** — `tests/test_context_intent.py`, on Acme's operations through
the whole pipeline, the week before 29 September:

| Intention | Read as | About | Its context holds |
|---|---|---|---|
| « Pourquoi la facturation est lente ? » | diagnose | Invoicing | Billing API, incident Q1, the deployment, the change |
| « Qu'est-ce qui a changé sur Billing API ? » | change | Billing API | the deployment, the change, the incident |
| « Comment Checkout est-il relié à la facturation ? » | dependency | Checkout, Invoicing | Billing API, the Billing platform |
| « Qui est responsable de Billing API ? » | ownership | Billing API | Sara |
| « Où est la procédure de reprise des paiements ? » | knowledge | — | the Confluence page |

none with a critical gap — and the missing cases: nothing named, a thing
asked for not in the model, sources unable to read what happens, nothing
happened in the period, nothing to start from. The reading itself —
kinds, periods, environments, names, gaps — is
`tests/test_context_intent_reading.py`.

**The screen**: step 2 of a new intention
(`web/components/intentions/intent-context.tsx`, mockup 03): the question
and a way back to it; what is missing, the critical first; the scope LEKA
read — its kind and the words that said it, what it is about and how it
knows, the period and where it comes from, the environment, the sources;
the context gathered, by kind of thing, every element on asking; the
sources it came from. The findings and recommendations come with the
analysis engine (LEKA-388).

## Not yet

- **Meaning, not only words.** The search reads words and a vocabulary of
  what they also mean. An embedding of the request and of each thing —
  pgvector, in the same database ([ADR 001](adr/001-postgresql.md)) — would
  find "the payments are failing" in a page that says "transactions are
  rejected". It needs a model to embed: a local one is a new dependency of
  the API, a hosted one a paid service — a decision to take. It would be a
  sixth retriever beside the others, never instead of them: they say why a
  thing was found, in words.
- **Relevance learned from use.** The weights are set by hand (§ 5),
  explained signal by signal and held by representative cases; learning
  them from what analyses actually used needs the intentions to say what
  they used (LEKA-384, LEKA-388) — the signals and their values are kept
  with every element for that.
- **Intentions kept, and their context with them** (LEKA-384, LEKA-387):
  a context is assembled for an intention's words and scope today; the
  intention itself is kept with LEKA-384, and its quality signals come
  with LEKA-375.
- **Refreshing on its own** when the model changes (LEKA-374) — today a
  refresh is asked; `refreshed_at` and the elements' `ref_id` index are
  there for it.
- **A context's quality and confidence** as a whole (LEKA-375).
- **Fine-grained access and the full inspection API** (LEKA-376).
- **Intentions** as subjects (LEKA-384): a context takes an
  `intention_id` as its subject today; nothing keeps the intention yet.
- A retention for contexts nobody reads: decided with LEKA-374, when
  contexts are made without being asked.
