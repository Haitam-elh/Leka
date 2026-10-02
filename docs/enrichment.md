# Enrichment — what resolved entities are to one another

Entity resolution says what is **one** thing ([resolution.md](resolution.md),
LEKA-357). Enrichment adds what those things are **together**, and what
follows from it: the relationships between them across tools, who owns and
works on them, how alive they are, what kind of work they are. LEKA-359.
What reads it next is the company model ([company-model.md](company-model.md),
LEKA-361).

```
 resolved_entities, resolved_keys        what the last resolution run made
 normalised_records                      what the sources stated between keys,
        │                                and each entity's dates, links and
        │                                tools — the quarantined left out
        │                                (validation.md)
        ▼
 enrich()                                leka/ingestion/enrichment
        │  1 relationships  2 links  infrastructure, data, knowledge (§ 7)
        │  3 ownership  4 membership  expertise  5 activity  6 category  7 landscape
        ▼
 enriched_relationships   every relationship between two entities: stated or inferred
 entity_enrichments       every attribute added to an entity
 enrichment_runs          each run over the workspace, and the enrichers that failed
```

**Added, never overwritten.** Nothing of a resolved entity changes: what is
enriched is kept beside it, each attribute and each relationship with its
**rule**, its **confidence**, its **evidence** and **what it was made
from**. An attribute a source states is never enriched; a relationship a
source states is never replaced by an inferred one.

**Local rules.** No model, no paid service: every rule below runs in LEKA.

---

## 1. Relationships, stated — across tools

What normalisation read between keys ([normalisation.md § 5](normalisation.md#5-relationships))
— a container, an author, "Fixes PAY-42" — becomes a relationship between
the **entities** those keys are. A pull request names Sara by her GitHub
login; she is one entity with her address: the edge ends at her. A GitHub
pull request resolving `ticket:PAY-42` ends at the Jira issue.

| | |
|---|---|
| `origin` | `stated` |
| `confidence` | the surest statement of it |
| `provenance` | the first five records stating it: `{source_id, record_id, evidence}` — the evidence is where normalisation read it (`container`, `references`, `parsing`, `tags`, `mapping.services`…) |
| `sources` | how many sources state it |
| `cross_source` | its two ends are shown by **different sources**: two tools' things joined — the GitHub pull request and the Jira issue |

A key **no entity** goes by — a ticket in a tool not connected, a
quarantined record — or **several** do — `ENG-42` in Jira and in Linear —
joins nothing: counted (`relationships.unresolved`, `relationships.ambiguous`),
not guessed. Two keys of one thing are resolution's merge, not a
relationship (`relationships.within`).

## 2. Links, inferred

What names a service without saying so. `origin: inferred`; its evidence
says which name, and in what.

| Rule | Relationship | When | Confidence |
|---|---|---|---|
| `same_name` | repository `part_of` service | the repository's name and the service's have one core (`acme/billing-api` and `Billing`: [resolution.md § 2](resolution.md#2-semantic--what-names-mean)) — one service only, no environment word | 0.8 |
| `component` | issue `part_of` service | a Jira component names the service | 0.85 |
| `label` | issue, pull request `part_of` service | a label names it | 0.7 |
| `named_in_title` | issue, pull request, incident `mentions` service; a document **`describes`** it (LEKA-366) | its title holds the service's name, as whole words — a name of five letters or more, held by one service | 0.6 |
| `named_in_title` | document `describes` application, business capability, business process (LEKA-366) | its title holds the name — an application's without `platform`, `system`, `app`… — held by one of that kind | 0.6 |

Never made: where a source already places the item in a service; where two
services share the name; for a name in more than 20 titles and a fifth of
them — a word, not a service (`links.too_common`); for an item a source
already relates to that service (an incident that `affects` it is not also
"mentioned").

## 3. Ownership

**The team**, where no source says one: the nearest container's — an item's
repository or project, a repository's service, a cloud resource's service —
through `part_of` and `child_of`, three steps at most. `owned_by`, rule
`inherited`, its provenance the container it is inherited from; confidence:
the steps' confidences × the owner's × **0.9 a step** — a pull request of a
repository of a service owned by `payments`: 1.0 × 0.8 × 0.9² = 0.65. Two
teams equally near: neither (`ownership.tied`). Below 0.5: nothing.

An **application**'s team is inherited the same way by its services
(LEKA-362): a service a catalogue names as the application's, with no team
of its own, is the application's team's.

A team inherited through **what resources are in** — an account, a
subscription, a resource group, a project (LEKA-363) — is **0.8 times** as
sure: billing groups resources, a service says whose they are. A resource
of Billing API (owned by Payments) in an account owned by Platform is
Payments'; one no service holds is Platform's.

**The maintainers** of a repository, a project, a service: the three people
most active on what it holds (a service: what is part of it and of its
repositories), with a share of the work of 20 % or more and two items or
more. `maintained_by`, rule `most_active`, confidence 0.4 + 0.6 × the share,
at most 0.9; its provenance, five of the items they worked on. Work is
weighed: author, assignee, lead 1; committer, reviewer 0.5; creator,
reporter 0.3; who last edited a document 0.5 (LEKA-366) — the last 180
days in full, before that 0.3. Bots are never maintainers.

A **knowledge space** — a Confluence space, a Notion database, a drive —
is a container too (LEKA-366): its maintainers are those who write and
edit its documents most; its documents inherit its team.

## 4. Membership

**The team a person works with**: of the items they work on that have a
team, 60 % or more are one team's — three items at least. `member_of`, rule
`works_with`, confidence 0.35 + 0.5 × the share, at most 0.85. Not an org
chart: an inference, with its share in its evidence. Never for a bot, nor
where a source says the person's team.

## 5. Activity

Measured when the run is made, from the entities' dates — as their own
records give them: the earliest creation, the latest of every other date
(resolution keeps no dates: they are provenance). A date in the future is
not activity.

| Attribute | Of | Rule | Confidence |
|---|---|---|---|
| `last_activity_at` | repository, project, service, application, knowledge space, person, team | `activity`: the latest date of it and what it holds (a person: what they work on; a team: what it owns) | 1.0 |
| `last_activity_at` | anything else with a date — a ticket, a pull request, an incident, a resource | `activity`: its own latest date — what the screens' events are made of | 1.0 |
| `activity_90d` | the same | `activity`: how many of those changed in the last 90 days | 1.0 |
| `lifecycle` | repository, project, service, application, knowledge space — not archived | `activity`: `active` within 30 days, `quiet` within 180, else `dormant` | 0.9 |
| `cycle_time_hours` | issue, pull request, closed or merged | `dates`: from its creation to its merge, closing or resolution | 1.0 |
| `stale` | issue, pull request, open | `inactivity`: unchanged for more than 30 days | 0.8 |
| `duration_minutes` | incident | `dates`: from its creation to its resolution | 1.0 |
| `incidents_90d`, `open_incidents`, `mttr_minutes` | service | `incidents`: those that `affect` it — created in 90 days; not resolved; the median time to resolve those of 90 days | 1.0 |

## 6. Category

The kind of work — `bug`, `security`, `feature`, `docs`, `maintenance` —
of an issue, a pull request, a commit **where parsing found none** (a
vendor's type, a label and a Conventional Commits title come first:
[parsing.md](parsing.md)): the words of its title, in English and French
("fix", "crash", "corrige", "plantage"…). One kind clearly ahead, or
nothing — "Fix typo in docs" is a tie. `category`, rule `title_words`,
confidence 0.6.

## 7. Landscape — where services and applications run, how critical

What a service or an application **is made of** says what no catalogue
said of it (LEKA-362). Services first — an application reads its services'.

| Attribute or relationship | Of | Rule | Confidence |
|---|---|---|---|
| `runs_in` → an environment | service, application | `parts`: one of its parts runs there — a resource by its `environment`, anything by its own `runs_in`; an application's services by what this rule found for them | the surest part's: the `part_of`'s and its environment's, the lower |
| `environments` | service, application | `parts`: every environment above, and those its sources state, in the order production, staging, development, test | the surest of them |
| `criticality` | service, application | `parts`: as critical as its most critical part — a resource's `criticality` tag, a service's catalogue | its part's, the `part_of`'s, **0.8 at most** |

A `runs_in` is made to the environment's **own entity** — normalisation
names `environment:production` wherever a record runs in production — and
only where the entity has one holder. An attribute its sources state is
never enriched: a catalogue's `criticality` stands, and it is what an
application's is read from. Nothing known of its parts: nothing said.

### Infrastructure — where a resource is (LEKA-363)

What a cloud resource is in says what its own tags do not. Run before
ownership and the landscape, which read what it adds.

| Attribute or relationship | Of | Rule | Confidence |
|---|---|---|---|
| `part_of` → an account, and `account` | a resource whose record names no account — an S3 bucket's ARN names none | `source_account`: the one account of its provider its sources read — none where they read several | 0.9 |
| `environment`, and `runs_in` → it | a resource, a resource group, a database, a schema, with no environment of its own | `container`: its nearest container's — a schema's database, a database's instance (LEKA-364), a node's cluster, a resource's group, else its account — that runs in one environment | the container's × the `part_of`'s × **0.9**; below 0.5, nothing |

### Expertise — what someone's work shows they know (LEKA-365)

| Relationship or attribute | Of | Rule | Confidence |
|---|---|---|---|
| `contributes_to` → a repository, a project, a service, a knowledge space | a person, not a bot | `work`: the items they work on — authored, assigned, led, committed, reviewed, created, reported, edited — are part of it: a pull request of its repository and of that repository's service, an issue of its project, an incident of the services it affects, a document of its space and of what it describes (LEKA-366). Two items at least; the ten areas with the most work; weighed as maintainers are (§ 3: role, the last 180 days in full) | 0.4 + 0.5 × its share of the person's work, 0.9 at most |
| `expertise` | the same | `work`: each of those areas with its **evidence** — how many items, how many in each role, the last one | 0.9 |
| `languages` | the same | `work`: the languages of the repositories among them, the most worked first, three at most | 0.8 |
| `bot` | a person | `name`: a bot's address, handle or name (`[bot]`, `dependabot`, `noreply`…) — and then no expertise | 0.9 |

**Sourced, not invented.** Expertise is what a person did, where: never a
skill they were said to have, never a guess from a title. Each area says
its numbers; each `contributes_to` says the items it was read from
(`provenance`). Someone whose work LEKA does not read has none.

### Data — what a database holds (LEKA-364)

| Attribute | Of | Rule | Confidence |
|---|---|---|---|
| `data_categories` | a schema, a database, the instance serving it | `objects`: every kind of data its tables — its schemas, its databases — hold | 0.8 |
| `classification` | the same | `objects`: the most sensitive of what it holds — `restricted`, `confidential`, `internal`, `public` — even where its own word is milder | 0.8 |
| `personal_data` | the same | `objects`: one of them holds personal data | 0.8 |

What a source says of it is never enriched; what goes up is the most
sensitive, so a schema documented `internal` that holds a table of
password hashes makes its database `restricted`.

A company that keeps production in an account of its own — `acme-prod`,
the subscription `Production`, the project labelled `env=prod` — says it
once, there: every resource in it runs in production, said as enrichment's,
with its rule. The nearest container decides: a node of a staging cluster in
a production account runs in staging. Groups and clusters first, so what
they hold reads what they inherited.

### Knowledge — documentation and the business (LEKA-366)

Run before ownership, which hands a space's team down to its documents.
Resolution keeps no link and no tool on an entity (they are provenance):
this reads them from the records.

| Attribute or relationship | Of | Rule | Confidence |
|---|---|---|---|
| `url`, `tools` | a document, a knowledge space | `record`: where its record opens it — the first record's — and the kinds of the tools it is read from | 1.0 |
| `freshness` | a document | `freshness`: from when it last changed — `fresh` within 90 days, `aging` within a year, else `stale`. A measure: no version of its own ([company-model.md § 5](company-model.md)) | 1.0 |
| `verification_due_at` | a document | `dates`: when its tool wants it verified again (Guru) | 1.0 |
| `owned_by` → a team | a knowledge space no source says the owner of | `same_name`: it is named for the team — `Payments`, `Payments team wiki` — the documentation words aside (`docs`, `wiki`, `space`, `kb`, `handbook`…); one team only | 0.7 |
| `describes` → a service, an application | a knowledge space | `same_name`: it is named for it — `Billing API docs` — one only | 0.7 |
| `describes` → a service, an application, a capability, a process | a document or a space | `linked`: its `docs_url` or `runbook_url` — a catalogue's — is the document's own address (no scheme, query nor fragment; the path decoded): what normalisation could not read from the address — a SharePoint file's — found here | 0.95 |
| `uses` → a table, a schema, a database | a business capability or process | `named`: the data its business system names (`data_names`) — `billing.invoices`, or a table's name alone; never a name two tables share (`knowledge.data_ambiguous`), nor one no table has (`knowledge.data_unfound`) | 0.9 qualified, 0.75 a name alone |

## 8. What fails, fails alone

- **An enricher that raises** is recorded in the run's `failures`
  (`{enricher, error}` — the error's type) and what it made is dropped; the
  others go on with what exists. The run succeeds.
- **What an enricher makes is checked** before it is kept: both ends of a
  relationship exist and differ, its type is a word; an attribute's entity
  exists, its name is a word, **its sources do not state it**, its value is
  JSON; a confidence is from 0 to 1. What fails is dropped and counted
  (`rejected`).
- **A run that fails** — a database gone — changes nothing: what the last
  run made is replaced in one transaction, or not at all. It is recorded
  `failed` with the error's type, and retried.
- **The base is never written**: resolved entities, their keys and
  decisions are resolution's alone.

## 9. Where results are kept, and what reads them

| Table | One row per | Holds |
|---|---|---|
| `enriched_relationships` | relationship between two entities (`from_entity_id`, `to_entity_id`, `type`) | `origin`, `rule`, `confidence`, `evidence`, `provenance`, `sources`, `cross_source`, `run_id` |
| `entity_enrichments` | attribute of an entity (`entity_id`, `attribute`) | `value`, `confidence`, `rule`, `evidence`, `inputs` (the keys it was made from), `run_id` |
| `enrichment_runs` | run over a workspace | `status`, `resolution_run_id` (what it read), `enricher_version`, `counts`, `failures`, `error` |

**Made again whole** at each run. No foreign key to `resolved_entities`:
resolution makes those again at each of its runs, ids kept — the last
enrichment stays readable meanwhile, and what reads it joins the entities
(a relationship whose end resolution no longer has is left out, and gone at
the next run). `run_id` leads to the run, the run to the resolution run it
read; a stated relationship's provenance to its records
(`normalised_records`), and from there to the source record
([processing.md § 4](processing.md#4-versions-and-traceability)).

**The company model** reads, per resolved entity: its `attributes` (what
its sources say), its `entity_enrichments` (what enrichment adds — never
the same names), and its `enriched_relationships` both ways — each with a
confidence to weigh. `GET /ingestion/enrichment/entities/{id}` is that
read.

## 10. When it runs

A **workspace** stage, after resolution
([processing.md](processing.md)): `enrich:<workspace>`,
`leka.ingestion.enrichment.job.run_enrichment`.

- **Queued by a resolution run that succeeded.** It reads what the latest
  successful resolution run made; that run's id is what it was made from.
- **Queued by `advance`**, when nothing is left to resolve but enrichment
  has something to do: a new `ENRICHER_VERSION` (5 since LEKA-365's expertise,
  4 since LEKA-364's data, 3 since LEKA-363's infrastructure, 2 since
  LEKA-362's landscape), a run that used up its
  retries.
- One run at a time per workspace; a run that sees resolution succeed again
  while it reads is closed `abandoned` and reads again (up to three times);
  a run left `running` by a dead worker is closed `abandoned` by the next.
- `enrichment_runs` is kept 90 days ([data-lifecycle.md](data-lifecycle.md)).
- **A run that succeeds publishes `ingestion.enriched`**, in the
  transaction that records its success (the outbox,
  [ADR 013](adr/013-events-and-job-runs.md)): the company model is built
  from it ([company-model.md § 6](company-model.md#6-when-it-builds)).

## 11. The API

`source:read` — every member. Another workspace's entity is 404.

| | |
|---|---|
| `GET /ingestion/enrichment` | pending?, the last run and its failed enrichers; counts — relationships, stated, inferred, cross-source, attributes; how many per `type:rule` and per attribute |
| `GET /ingestion/enrichment/entities/{id}` | one entity as the company model reads it: its attributes, what was added, its relationships both ways (100 each way, by type and the surest first, and how many) |
| `GET /ingestion/enrichment/relationships` | paginated, the surest first — `type=`, `origin=stated\|inferred`, `rule=`, `cross_source=true`, `entity_id=` |
| `GET /ingestion/enrichment/environment` | the "Mon environnement" screen (§ 12) |
| `GET /ingestion/enrichment/environment/{id}` | one entity's sheet (§ 12) |

## 12. The "Mon environnement" screens

`/environment` and `/environment/<type>/<id>` in the application, laid out
as mockups 10 and 11 (`docs/product/mockups/`), read from
`leka/ingestion/enrichment/screens.py` — what resolution and enrichment
made, put together by `view.py`'s rules. **Every figure is the sources';
what no source says is said missing, never invented.**

**States** — mockup 10's legend:

| Thing | State | When |
|---|---|---|
| service | incident | an open incident `affects` it |
| | attention | an incident affecting it moved in the last 7 days |
| | operational | a monitoring source — PagerDuty, Datadog, Grafana, Splunk, Kibana (connector category `observability`) — shows it, and nothing above |
| | unmonitored | no monitoring source shows it |
| database, cloud resource | operational · attention · incident | `running` · `starting`, `stopping`, `stopped`, `deleting` · `failed` — a `terminated` one has none: it is gone |
| incident | incident · operational | open or in progress · closed |
| repository, team | none | no state of its own |

**The screen** (`GET /ingestion/enrichment/environment`):

- **the map**, one row per layer: users (no source describes them yet —
  said), applications (the repositories), services, data (the databases),
  infrastructure (the cloud resources boxed per provider and region, in
  their worst state); a line per `part_of`, `depends_on`, `owned_by` or
  `in_network` between two boxes, coloured by the worse of their states;
  each row the surest-troubled first, the others ordered under their
  services;
- **the figures**: services, and how many are operational; open incidents,
  and how many services they affect; changes (pull requests, commits,
  releases, deployments) in the last 24 hours; the environments things say
  they are in — the "Vue globale" filter;
- **points of attention**, the most urgent first: each open incident and
  what it affects; resources failed; resources stopped; work waiting
  (`stale`); services nothing watches; dormant repositories;
- **recent events**: the six latest things that moved (by
  `last_activity_at`), what each is now — an open incident, a resolved one,
  work waiting, a change, news — and the service, repository or project it
  belongs to. Databases and cloud resources are not events: their last
  change is a state read again.

**A sheet** (`GET /ingestion/enrichment/environment/{id}`): the entity as
the company model reads it (§ 9), its state; its **owner** — its surest
maintainer — and its **team** — owned_by, stated first, and how many work
with it (`member_of`); its incidents, the open first; the eight latest
events around it (what is part of it or affects it — for a service, also
what is part of its repositories); its dependencies — repositories,
services, databases, resources, projects related to it, each way, with the
relationship's origin, confidence and whether it joins two tools; the
documents that name it or describe it (LEKA-366); what needs attention.

In their place, and saying what they wait for: the users and the business
domains (the company model, LEKA-361 on), the metrics — latency, errors,
requests, availability — and their chart (a metrics source's metrics read),
the deployments, logs and configuration tabs, LEKA's insights and analysis
(its analysis engine, sprint 4).

## Not yet

- **Measured daily**: activity is measured at each run, which follows
  resolution; a workspace nothing changes in ages without being measured
  again. A daily run is the next step.
- **Semantic enrichment by embeddings**: titles and descriptions compared
  by meaning — the hook is a seventh enricher; it would cost a model to host
  or an API to pay.
- **Ownership files**: a repository's `CODEOWNERS` is not read yet — the
  surest owner there is.
- **A person's word**: confirming or rejecting an inference by hand, kept
  across runs.
- **The users, the business domains, the metrics** on the screens: they
  wait for sources and models that read them (§ 12).
