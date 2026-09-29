# Entity resolution — which candidates are one real thing

What LEKA decides, across a workspace's sources, is **one** thing — a
person, a service, a ticket — how sure it is, and why. LEKA-357. It reads
what normalisation made ([normalisation.md](normalisation.md)); what reads
it next is the company model (leka.knowledge).

```
 normalised_records, every source of the workspace — but the quarantined
        │  (validation, LEKA-358: docs/validation.md)
        │  each record's entity, and the people, services, teams it names —
        │  a canonical key and aliases each
        ▼
 resolve()                                   leka/ingestion/resolution
        │  1. deterministic merges   2. semantic signals   3. decisions
        ▼
 resolved_entities   one row per real thing — its key, name, attributes, conflicts
 resolved_keys       every key it goes by, per source: its provenance, and the lookup
 resolution_decisions  every merge, link and ambiguity: rule, confidence, evidence
 resolution_runs     each run over the workspace
```

**Merged, linked, or ambiguous — never guessed.** A merge makes one entity
of several candidates. A link says two entities are probably one, and
keeps them apart for what reads them to weigh. An ambiguity says what it
would not decide. Nothing is overwritten: where the sources of one thing
disagree, every value is kept beside the one chosen.

---

## 1. Deterministic — what keys themselves say

| Rule | When | Confidence |
|---|---|---|
| `same_key` | one canonical key, seen by several sources — **a duplicate across sources**, found and said | 1.0 |
| `alias` | a key and an alias a source gives it: a person's address and their login (`person:email:sara@acme.io` ~ `person:github.com:sara`); a Jira issue and `ticket:PAY-42` | 1.0 |
| `github_noreply`, `gitlab_noreply` | an address that says its account: `12345+sara@users.noreply.github.com` is GitHub's `sara` | 0.99 |
| `plus_address` | `sara+jira@acme.io` is `sara@acme.io`'s mailbox | 0.95 |

An account links every address it was seen with — one person with a work
and a personal address is one person — **unless** it was seen with more
than 5: then it is a shared account (`shared_account`, ambiguous), and
links none.

A short ticket key (`ticket:ENG-42`) joins the one ticket that has it as an
alias. **Two tools with the same key** — `ENG-42` in Jira and in Linear —
make it ambiguous (`ambiguous_alias`): neither is assumed, and a lookup of
`ticket:ENG-42` answers both.

## 2. Semantic — what names mean

Between what step 1 left apart, for **people, services and teams** —
computed locally, by LEKA itself: no model, no paid service.

**People** — two families of signals, scored:

| Family | Signal | Score |
|---|---|---|
| what they are called | the same full name, in any order ("Martin Sara" is "Sara Martin") | 0.8 |
| | a handle whose words are the name: `sara.martin`, `martin_sara` | 0.85 |
| | a handle that is the name joined: `saramartin` | 0.8 |
| | an initial and a surname: `smartin` (Sam Martin is `smartin` too) | 0.55 |
| how they sign in | the same handle in two tools — a login, an address's local part | 0.75 |

The best of each family counts; two families agreeing are worth more than
either (1 − (1 − a)(1 − b)), up to 0.95 — never the 1.0 of a fact.

**Services and teams** — the core of a name: the words that say "a
service" or "a team" (`api`, `service`, `svc`, `app`, `server`; `team`,
`squad`, `group`, `engineering`…) and a plural set aside.

| Signal | Example | Score |
|---|---|---|
| `same_name` | `Billing API`, `billing-service`, `billing` | 0.9 |
| `environment_variant` | `billing` and `billing-staging` | 0.7 |
| `similar_spelling` | `notification` and `notifcation` — a typo, not a digit | 0.65 |

## 3. Decided

| Score | Decision |
|---|---|
| ≥ 0.9 | **merged**: one entity |
| 0.6 to 0.9 | **linked**: probably one — kept apart, the link carries its rule and evidence |
| below 0.6 | nothing |

What is **never** merged — the false positives this is built against:

- **Two people with an address each** are never merged by their names:
  two "Alex Kim" are two until someone says otherwise. Linked at most
  (0.89).
- **A tie**: a candidate matching two others that are not one another is
  merged with neither (`tied_match`, ambiguous).
- **Bots** (`dependabot[bot]`, `github-actions`, `renovate`…) are never
  matched by their names; **generic or short handles** (`admin`, `dev`,
  anything under four letters) say nothing.
- **A crowd**: a name or a handle more than 5 people hold says nothing.
- **Things of different types** — a service, a team, a repository called
  `billing` — are never one.
- **Services that only look alike**: `payment-api` and `payout-api`,
  `payment-v1` and `payment-v2` (a digit is never a typo),
  `billing-backend` and `billing-frontend`.

## 4. What an entity is made of

| | Rule |
|---|---|
| `key` | the one that says it best: the key the thing's own records give; a person's working address before a login or a no-reply address; a ticket on its site before `ticket:…`; then the most said, the shortest |
| `name` | a real name before a handle; what the thing's own records say before what others call it; the surest, then the latest. `names` keeps every other |
| `attributes` | from the thing's own records (else from what names it): where they agree, their value; where they disagree, the most recent, then the surest |
| `conflicts` | **every disagreement, every value kept**: `{attribute, chosen, values: [{value, source_id, key, observed_at}]}`. A name is in conflict when two are not the same name — "Sara Martin" and "Sarah Johnson" under one address; not "Sara Martin" and "Sara Martin-Dupont", nor a handle beside a name |
| `confidence` | the lowest of the merges that made it — 1.0 for one key or keys that say they are one another |
| `quality` | the best quality validation gave the records that are it ([validation.md](validation.md)); none for an entity only named by others |

Where a candidate came from — `url`, `source_kind`, `quality`, any `*_at`,
`*_raw` or `*_confidence` — is never compared or chosen between: it is
provenance, in `resolved_keys` and in the records.

**Provenance** — `resolved_keys`: for every key an entity goes by, per
source that gave it: `key` (the source's own), `alias` (one it asserted),
or `derived` (one its address says); the name that source uses; how many of
its records **are** the thing and how many **name** it; when first and last
seen; an example `normalised_records` row.

## 5. When it runs

A **workspace** stage, where extraction, parsing and normalisation are a
source's ([processing.md](processing.md)): what is one thing is decided
across sources.

- `advance`, finding nothing left to do for a source, queues
  `leka.ingestion.resolution.job.run_resolution` (key
  `resolve:<workspace>`) when normalisation made something since the last
  successful run — the count of the workspace's normalised and validated
  rows and the latest of each, its **fingerprint** — or `RESOLVER_VERSION`
  changed. A quarantined record is not read; one not validated yet is.
- One run at a time per workspace; a run that saw normalisation move while
  it ran runs again (up to three times); a run left `running` by a dead
  worker is closed `abandoned` by the next.
- **Made again whole, in one transaction, the ids kept**: an entity keeps
  the id most of its keys had, so what reads an entity by its id reads the
  same thing after the next run; a new entity's id is derived from its key.
  A failed run changes nothing, and is recorded `failed` with the error's
  type.
- A source removed takes its candidates, and its keys, with it; the next
  run resolves without them.

## 6. The API

`source:read` — every member. Another workspace's entity is 404.

| | |
|---|---|
| `GET /ingestion/resolution` | pending?, the last run, and counts: entities, conflicted, merges, links, ambiguous |
| `GET /ingestion/resolution/entities` | paginated, by name — `type=person`, `only=merged`, `conflicted`, `linked`, `ambiguous` |
| `GET /ingestion/resolution/entities/{id}` | one entity, its keys per source, and every decision about it |
| `GET /ingestion/resolution/lookup?key=…` | the entity a key names — several when ambiguous, none when no source shows it |

## Not yet

- **Semantic matching by embeddings**: names are compared by what they
  mean in words (§ 2), locally. An embeddings model would compare
  descriptions and titles — the hook is the engine's second step; it would
  cost a model to host or an API to pay.
- **A person's word**: confirming a link or splitting a merge by hand, kept
  across runs.
- **Incidents from two tools about one outage**, **a repository and the
  service it builds**: related, not the same thing — the company model's
  relationships, not resolution's.
- **A screen**: the routes are there.
- **Incremental runs**: a run reads the whole workspace; fine at today's
  volumes, to be made incremental — by the keys a run's changes touch —
  when a workspace's candidates reach the millions.
