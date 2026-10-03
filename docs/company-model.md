# The company model — what the company is made of

Resolution says what is **one** thing ([resolution.md](resolution.md),
LEKA-357); enrichment says what those things are **together**
([enrichment.md](enrichment.md), LEKA-359). The company model makes of them
the company's **canonical entities**: typed, checked against their kind's
schema, versioned, with a lifecycle and where every piece of them came from.
LEKA-361. It is the source of truth `leka.context` reads, and what the
screens of the graph read (§ 16).

```
 resolved_entities, resolved_keys     what the last resolution run made
 entity_enrichments,                  what the last enrichment run added
 enriched_relationships
        │  event ingestion.enriched ──▶ model:<workspace>
        ▼
 build()                              leka/knowledge/build.py — pure
        │
        ▼
 entities           one row per real thing; its id is the resolved entity's
 relationships      between them, of the registry's types
 entity_versions    what each said at each of its versions, and what changed
 model_runs         each build: what it read, what it did, or its error
```

Two generic tables and their history, not a table per kind
([ADR 003](adr/003-entity-model.md)): a new kind of thing is an entry in
the registry, not a new table.

---

## 1. The registry — the kinds of things

`leka/knowledge/registry.py`. Each **entity kind** has a version, a category
— how the company is read — the ingestion types it is built from
([normalisation.md § 2](normalisation.md)), and the schema its attributes
are checked against.

| Category | Kinds | Schema declares, beyond url, description, state, lifecycle, last activity |
|---|---|---|
| organisation | `person` | address, title, department, location, whether active, the directory; bot; expertise and languages (enrichment's) — § 12 |
| | `team` | team or department, description, slug — § 12 |
| applications | `application` | criticality, stage, environments, point of contact — § 9 |
| | `service` | the same, and its type, languages, escalation policy, links; incidents over 90 days, open incidents, MTTR — § 9 |
| | `repository` | visibility, default branch, language, topics, fork |
| delivery | `project` | — |
| | `release` | its tag, draft, prerelease; when made and published — § 14 |
| | `deployment` | its environment, production or not, its commit and ref, each status with when; when made, started, finished, how long — § 14 |
| | `issue`, `pull_request` | priority, category, labels, components, stale, cycle time; a pull request's opening, merge and closing dates — § 14 |
| | `commit` | category, change type |
| operations | `incident` | priority, severity, urgency, number, customers hit; when opened, detected, acknowledged, resolved; how long to acknowledge and to resolve — § 14 |
| | `change` | its type, risk, environment; when asked, planned, started, finished — § 14 |
| infrastructure | `infra_resource` | provider, account, region, zone, resource group; resource kind and class, the provider's type; environment, exposure, criticality; instance type, engine, version, runtime, endpoint; tags — § 10 |
| | `cloud_account` | an AWS account, an Azure subscription, a Google Cloud project: its type and id, its state, its organisation, tenant or parent; environment, criticality, tags — § 10 |
| | `resource_group` | an Azure resource group: its subscription, region, environment, tags — § 10 |
| | `environment` | — `production`, `staging`, `development`, `test` |
| data | `database` | a cloud instance's, as a resource's (§ 10); a database a source reads: its engine, host, port, name; what it holds — § 11 |
| | `schema` | its database's role that owns it; what it holds — § 11 |
| | `data_object` | a table, a view, a collection: its kind, schema, columns, primary key, size; what each column holds, its classification — § 11 |
| knowledge | `document` | its kind (`page`, `post`, `card`, `file`), where it opens, the tools it is read from; its freshness — enrichment's — whether its tool says it is verified and when it wants it verified again; its version, type, size, path — § 13 |
| | `knowledge_space` | where documents are kept: its kind (`space`, `database`, `topic`, `collection`, `shared_drive`, `document_library`, `onedrive`), its tool's type, its key — § 13 |
| business | `business_capability`, `business_process` | level, criticality, stage; a process's type and step; the data its source names — § 13 |

Each **relationship kind** is built from enrichment's relationships
([enrichment.md § 1–4](enrichment.md)): `part_of`, `child_of`,
`depends_on`, `owned_by`, `maintained_by`, `member_of`, `authored_by`
(and normalisation's `committed_by`), `assigned_to`, `reviewed_by`,
`reported_by` (and `created_by`), `led_by`, `affects`, `resolves`,
`implements`, `merges`, `mentions`, `in_network`, `runs_in` (LEKA-362),
`references` and `reads_from` (LEKA-364), `reports_to` and `contributes_to`
(LEKA-365), `describes`, `edited_by`, `supported_by`, `uses` and `realizes`
(LEKA-366), `deploys`, `deployed_to` and `caused_by` (LEKA-367).
`owns` is kept for what states it later; nothing does yet. Each has a
**contract** — what it means, what each end may be, whether a thing has
one, whether a loop of it is a contradiction, whether it is a dependency —
checked at every build (§ 15, LEKA-368).

`GET /knowledge/registry` serves all of it.

**Versioned.** A kind's `version` is raised when its schema changes what is
kept; every entity says which it was checked against (`schema_version`).
`MODEL_VERSION` is raised when anything changes what a build makes: the
next build remakes every entity — ids, histories and lifecycles kept, and
no version made for what did not change.

**Extensible without breaking.** A schema declares what it knows and lets
the rest through: a connector that learns a new attribute adds it with no
change here, and an entity made before a field was declared still reads. A
declared attribute whose value does not fit — a number where a list is
expected — is **dropped**, never written wrong: named in the entity's
`provenance.dropped` and counted (`attributes_dropped`). A new kind is an
enum value, its CHECK constraint ([ADR 006](adr/006-enum-storage.md)) and
an entry here. What normalisation makes and the model leaves out is said
on purpose (`NOT_MODELLED`: a branch is a short-lived name, not a part of
the company); a type it starts making that is neither fails
`tests/test_company_model.py`.

## 2. Identity

**An entity's id is its resolved entity's.** Resolution keeps ids from one
run to the next ([resolution.md](resolution.md)), so a service is the same
row whatever changes around it — renamed, seen by a new tool, removed and
back. `key` is the key that says it best (`github.com/acme/api`,
`person:email:sara@acme.io`); `provenance.sources` lists every source that
shows it and the key it goes by there (up to 20).

## 3. What it says, and where it came from

| Column | |
|---|---|
| `name` | resolution's choice |
| `attributes` | what its sources say; where they say nothing, what enrichment added — **never enrichment's over a source's**. Checked against its kind's schema |
| `provenance.attributes` | each attribute's origin: `{"origin": "source"}` — `{"origin": "source", "rule": "record"}` for what enrichment carries from the records as they say it, a date, a link, resolution keeping none (LEKA-366, LEKA-367) — or `{"origin": "enrichment", "rule", "confidence"}` |
| `provenance.sources` | `{source_id, key, kind}` per source and key |
| `provenance.conflicts` | what its sources **disagree** on (resolution's conflicts, LEKA-362): `{attribute, chosen, values: [{value, source_id}]}` — every value kept with who said it, the attribute marked `disputed` in `provenance.attributes` |
| `confidence` | how sure the merges that made it are (resolution) |
| `quality` | the best quality of its records (validation, LEKA-358) |
| `first_seen_at`, `last_seen_at` | the earliest and latest a source showed it |
| `occurred_at` | when an event happened (LEKA-367): an incident opened — the earliest of detected and opened — a deployment done, a change made, a release published, a pull request merged — else, for all but a pull request, when a source first showed it. None for what is not an event. Indexed with the workspace and the type: lists and timelines go by it |

A relationship says whether a source **stated** it or a rule **inferred**
it (`origin`, `rule`), how sure it is, whether it joins two tools' things
(`cross_source`), the records that stated it (`provenance`), the
**environments** it is true in (`attributes.environments`, § 9), and when
it first appeared and last changed (`first_seen_at`, `changed_at`, § 15).

## 4. Lifecycle

| State | When |
|---|---|
| `active` | shown by a source, and not one of the below |
| `dormant` | enrichment finds nothing done to it for 180 days ([enrichment.md § 5](enrichment.md)) |
| `archived` | its source says so (`state: archived`), or its catalogue says it is retired (`stage: retired`), or its provider that it is gone (`state: terminated` — a terminated instance, a deleted resource; an account `deleted`) |
| `removed` | **no source shows it any more** |

A removed thing is **kept, never deleted**: its history stays, `removed_at`
says when, and the API leaves it out unless asked (`?lifecycle=removed`).
One that comes back is `active` again — the same id, the next version.
`lifecycle_changed_at` says when it last changed state. The database holds
`removed` and `removed_at` together (a CHECK constraint).

## 5. Versions

What an entity says — its **name, its attributes, its lifecycle** — is
hashed (`content_hash`). A build that finds a different hash raises
`version` and records the new content in `entity_versions`, with **what
changed**: `created`, `name`, `lifecycle`, `attributes.<name>`. One row per
(entity, version), append-only: a second writer of the same version is
refused by the database.

**A change of the thing, not of the clock.** Measures that move with time
alone — last activity, activity over 90 days, incidents over 90 days, open
incidents, MTTR, stale, enrichment's lifecycle word, a table's estimated
rows and size, a person's expertise, a document's freshness — are kept
current but make no version of their own. A thing
whose only news is that a day passed is not a new version of itself.

Relationships are the model's present: made again whole at each build.

## 6. When it builds

A **workspace** stage, after enrichment: `model:<workspace>`,
`leka.knowledge.job.run_model_build`.

- **Told, not called.** An enrichment run that succeeds publishes
  `ingestion.enriched`; `leka/background/routes.py` routes it to
  `run_model_build_for_event`, which queues the build. `leka.ingestion`
  never imports `leka.knowledge` (architecture rule 1).
- It reads what the **latest successful enrichment run** made, and the
  resolution under it; that run's id is what the model was made from. A new
  one, or a new `MODEL_VERSION`, is something to build; otherwise nothing is.
- **One transaction**: a failed build changes nothing — the last model
  stays — and is recorded `failed` with the error's type. A build that sees
  enrichment succeed again while it reads is closed `abandoned` and reads
  again (up to three times); a run left `running` by a dead worker is closed
  by the next.
- **The hourly sweep** (`model-sweep`, :48 — [background.md](background.md))
  queues what no event will: a workspace enriched before the model existed,
  a build that failed, a new `MODEL_VERSION`. It closes the runs a dead
  worker left, and forgets `model_runs` past 90 days — never a workspace's
  last success, which says what its model was made from — and the
  relationships' history past a year (LEKA-368).

`model_runs.counts`: `created`, `changed`, `unchanged`, `removed`,
`still_removed`, `entities`, `relationships`, `type.<kind>`,
`relationships_added`, `relationships_changed`, `relationships_removed`,
`relationships_invalid`, `relationship_warnings` (LEKA-368),
`not_modelled`, `attributes_dropped`, `relationships_not_modelled`,
`relationships_to_unmodelled`.

## 7. The API

Read by every member (`workspace:read`); another workspace's entity is 404.

| Route | |
|---|---|
| `GET /knowledge/model` | whether enrichment made something the last build has not read (`pending`), the last build, how many entities of each type (the removed left out) and lifecycle, how many relationships of each type |
| `GET /knowledge/registry` | the kinds: version, category, declared attributes, what each is built from |
| `GET /knowledge/entities` | the entities by name, paged; `type`, `lifecycle`, `q` (in the name). Without `lifecycle`, every one but the removed |
| `GET /knowledge/entities/{id}` | one: its provenance, its relationships both ways — the surest first, up to 100, and how many — and how many versions |
| `GET /knowledge/entities/{id}/versions` | its history, the latest first: each version's content and what changed |
| `GET /knowledge/entities/{id}/neighbourhood?depth=1..3` | what surrounds it, in either direction, the removed left out: up to 200 entities and the relationships between them |
| `GET /knowledge/services`, `GET /knowledge/applications` | the landscape (§ 9), by name, paged: `criticality`, `stage`, `environment`, `application_id` (services), `team_id`, `lifecycle`, `q` |
| `GET /knowledge/services/{id}`, `GET /knowledge/applications/{id}` | one: its landscape, what it is made of and in which environments, its dependencies both ways, its attributes and provenance. A service's id on the applications' route is 404 |
| `GET /knowledge/entities/{id}/dependencies` | `direction=downstream` (what it depends on) or `upstream` (what depends on it: what its failure reaches), `depth=1..5`, `environment`, `through` (the dependency relationships followed: `depends_on` — the default — `reads_from`, `references`, `supported_by`, `uses`; LEKA-368): each thing reached and how far, the relationships walked — up to 500, `truncated` beyond |
| `GET /knowledge/infrastructure` | the cloud resources and databases (§ 10), by name, paged: `resource_class`, `resource_kind`, `provider`, `account_id` (an account, subscription, project — or resource group: what is in it and in its groups), `region`, `environment`, `state`, `exposure`, `criticality`, `service_id`, `team_id`, `lifecycle`, `q` |
| `GET /knowledge/infrastructure/{id}` | one: its place, environment and who says so, services, team, network, cluster; what it holds — a cluster's nodes, a network's resources — and its dependencies both ways; its attributes and provenance. Anything but a resource is 404 |
| `GET /knowledge/cloud-accounts` | the accounts, subscriptions and projects, by name, paged: `provider`, `environment`, `lifecycle`, `q` — each with how many resources it holds (in its groups too), of which class, in which regions; its environment and team |
| `GET /knowledge/cloud-accounts/{id}` | one — or a resource group — its resource groups and theirs, its attributes and provenance |
| `GET /knowledge/databases` | the databases (§ 11), by name, paged: `engine`, `classification`, `personal_data`, `environment`, `team_id`, `lifecycle`, `q` — each with the instance serving it, how many schemas and objects, what it holds and who says so |
| `GET /knowledge/databases/{id}` | one: its schemas — how many tables, views, collections, what each holds — the databases it serves (an instance), its attributes and provenance |
| `GET /knowledge/data-objects` | the tables, views, collections, by name, paged: `database_id`, `schema_id`, `object_kind`, `classification`, `category`, `personal_data`, `service_id`, `team_id`, `lifecycle`, `q` — each with its database and schema, size, what it holds, how many ties each way |
| `GET /knowledge/data-objects/{id}` | one: its columns — what each holds, the primary key — what it references and reads from, what references and reads from it |
| `GET /knowledge/teams` | the teams and departments (§ 12), by name, paged: `team_type`, `parent_id`, `lifecycle`, `q` — each with its parent, sub-teams, members said and inferred, leads, what it owns by type |
| `GET /knowledge/teams/{id}` | one: its parents up to the top, its sub-teams, its members — each said or inferred, how surely — what it owns, the surest first |
| `GET /knowledge/people` | the people, by name, paged: `team_id`, `department`, `contributors`, `bots` (left out unless asked), `lifecycle`, `q` (name or address) — each with title, department, teams, manager, reports, what they maintain, their first expertise |
| `GET /knowledge/people/{id}` | one: their teams, their managers up to the top, their reports, what they maintain and own, everything their work shows they know with its evidence |
| `GET /knowledge/entities/{id}/responsibility` | who owns a thing — its teams, said or inherited — who leads them, who maintains it, whose work shows they know it, its escalation policy |
| `GET /knowledge/data-objects/{id}/lineage` | `direction=upstream` (what it reads from and references) or `downstream` (what reads from or references it — what a change of it reaches), `depth=1..5`: each reached and how far, the relationships walked |
| `GET /knowledge/documents` | the documents (§ 13), by title, paged: `space_id`, `freshness`, `about_id` (a thing's documentation), `person_id` (written, edited or owned by), `team_id`, `verified`, `lifecycle`, `q` — each with its space, link and tools, freshness, authors, last editor, owners, what it describes |
| `GET /knowledge/documents/{id}` | one: its pages above and below, what it describes, links to and mentions, who links to it, who wrote, edited and owns it — each said or inferred |
| `GET /knowledge/knowledge-spaces` | where documents are kept, by name, paged: `space_kind`, `team_id`, `lifecycle`, `q` — each with how many documents and how fresh, its owners, what it documents, its maintainers |
| `GET /knowledge/knowledge-spaces/{id}` | one: its ties, its ten latest documents and its ten stalest |
| `GET /knowledge/documentation/coverage` | how many documents and spaces, by freshness, how many to verify — and for applications, services, repositories, databases, tables, capabilities, processes: how many, how many documented, how many by a document that is not stale |
| `GET /knowledge/documentation/gaps` | `type` (one of those kinds), `stale` (only stale documents describe it), `criticality`, `team_id`, `lifecycle`, `q`: what is undocumented, paged — how critical, whose |
| `GET /knowledge/business-capabilities`, `GET /knowledge/business-processes` | by name, paged: `parent_id`, `top`, `capability_id` (processes), `team_id`, `application_id` (supported by), `data_id` (using), `lifecycle`, `q` — each with its parent, parts, what supports it, its data, owners, documents |
| `GET /knowledge/business-capabilities/{id}`, `GET /knowledge/business-processes/{id}` | one: its parents, its parts — activities by step, each with what supports it and its data — the processes realizing it, the applications and services supporting it and the services of those applications, its data, owners and documentation |
| `GET /knowledge/entities/{id}/business` | what a technical thing means to the business: the capabilities and processes relying on it — directly, through what holds it (its service, its application) or through what depends on it — each with how, and who says so |
| `GET /knowledge/incidents` | the incidents (§ 14), the latest first (`sort=occurred_at`, or `name`), paged: `state`, `priority`, `service_id` (affecting it), `cause_id` (caused by that change or deployment), `since`, `until`, `lifecycle`, `q` — each with its dates, what it affects, who leads it, its causes said or suspected |
| `GET /knowledge/incidents/{id}` | one: its timeline — the dates its sources give, each state LEKA saw it take — what it affects, who handled it, its causes with origin and rule, what changed on what it affects in the 72 hours before, what it reaches: dependents, applications, the business |
| `GET /knowledge/changes`, `GET /knowledge/deployments` | the latest first, paged: `state`, `change_type` or `environment`, `service_id` (a deployment's own or its repositories'), `repository_id` (deployments), `since`, `until`, `lifecycle`, `q` — each with its dates, what it touched, who made it, how many incidents follow from it |
| `GET /knowledge/changes/{id}`, `GET /knowledge/deployments/{id}` | one: a change's timeline, a deployment's statuses with when; what it affects or shipped, where it went; the incidents said or suspected to follow from it |
| `GET /knowledge/relationships` | the graph's relationships (§ 15), the latest changed first (`sort=changed_at`, or `confidence`), paged: `type`, `entity_id` (either end), `origin`, `rule`, `min_confidence`, `since`, `until` — each with both ends named, its provenance, when it first appeared and last changed |
| `GET /knowledge/relationships/changes` | their history, the latest first: each relationship added, changed or removed at a build, before and after — `type`, `entity_id`, `change`, `since`, `until` |
| `GET /knowledge/relationships/issues` | what the last build found wrong: `wrong_end` (dropped, an error), `cycle_broken` (an inferred link dropped), `cycle`, `several_targets` (kept, warnings) — `type`, `entity_id`, `severity`, `issue` |
| `GET /knowledge/timeline` | what happened between `since` and `until` (a month by default, a year at most), the latest first — incidents opened and resolved, deployments, changes, releases, merges — around `entity_id` (itself, what is part of it two steps down, what affects it, each with `via`) or everywhere; `kinds`, `limit` (500 at most) |
| `GET /knowledge/search` | what was typed (`q`), every word a prefix (§ 16): the entities whose names — then whose other words — match, the best first, each with where it is and the kinds of the sources that show it, and the relationships among them; `type`, `removed`, `limit` (50 at most) |
| `GET /knowledge/graph` | a walk from `root` (up to ten): `depth=1..4`, `direction` (`outgoing`, `incoming`, `both`), `relationship`, `entity_type`, `min_confidence`, `environment`, `limit` (500 at most): each entity reached and how far, the relationships among them all, `truncated` past a bound |
| `GET /knowledge/graph/paths` | the shortest ways `from` one entity `to` another, relationships read either way: `max_depth=1..4`, `relationship`, `min_confidence` — five at most, the surest first; `length` null when none |
| `GET /knowledge/views/{view}` | a landscape — `company`, `domains`, `applications`, `services`, `data`, `infrastructure`, `organisation`, `dependencies`: its rows, boxes, lines, states, coverage and sources |
| `GET /knowledge/coverage` | how well the model knows each kind — how many, with an owner, documented, corroborated, connected — and from which sources |

## 8. What reads it

`leka.context`, through `KnowledgeService.neighbourhood`: an entity and
what surrounds it, as one subgraph — the unit an answer is assembled from.
The traversal is one recursive query, bounded by depth and size
([ADR 001](adr/001-postgresql.md)). What happened is there too
(LEKA-367): `KnowledgeService.timeline` — what happened around a thing
between two dates — and `incident`, `change`, `deployment` — one event with
its causes, what changed before it and what it reaches — for what explains
a change and assesses its impact. And the graph explored (LEKA-369, § 16):
`GraphService.search` — the things a question names, found by their names
— `walk` and `paths` — what surrounds them, and how two of them are tied.

## 9. Applications and services (LEKA-362)

The company's **application landscape**: the applications — groups of
services it names as one — the services, where each runs, whose it is, how
critical, where in its life, what it depends on. Built from the tools that
know it ([normalisation.md](normalisation.md)):

| Tool | What it says |
|---|---|
| PagerDuty | services and their teams; their **technical dependencies**; business services — as **applications** — and the services supporting them |
| the Datadog service catalog | a service's team, application (v3: its system), tier, lifecycle, type, languages, links, dependencies |
| cloud tags (AWS, Azure, Google Cloud) | a resource's service, application, environment, team, criticality |
| a custom source — a CMDB, a Backstage catalogue | services and applications, declared, with the same fields |
| the code itself — GitHub's `components` (LEKA-369) | the services a repository runs — its API, web app, workers — their technology, where they are reached, what deploys them; the databases, caches, stores and services outside they rely on, from their configuration; each link named, with its file and line ([connectors/code-platforms.md](connectors/code-platforms.md)) |
| a code host | the repository of a service's name (enrichment's `same_name`) |

**Canonical.** A service is `service:<name>`, an application
`application:<name>`, whatever tool names it: resolution makes one entity
of them (`Billing API` and `billing-service`; `Billing` and `Billing
platform`), and the model keeps every source it came from.

| On a service or an application | Values | From |
|---|---|---|
| `criticality` | `critical`, `high`, `medium`, `low` — `criticality_raw`, the source's word | a catalogue, a tag; else enrichment: its most critical part ([enrichment.md § 7](enrichment.md)) |
| `stage` | `experimental`, `production`, `deprecated`, `retired` — `stage_raw` | a catalogue's lifecycle; `retired` makes it `archived` (§ 4) |
| `environments` | the canonical environments it runs in | its parts' and its own `runs_in` (enrichment) |
| owners | `owned_by` → a team | its catalogue, its tags; else inherited from its application |
| application | `part_of` → an application | a catalogue, an application tag beside a service tag, a business service |
| dependencies | `depends_on` → a service (an application → an application) | PagerDuty, the Datadog catalog, a custom source |
| where it runs | `runs_in` → an environment | its parts, its catalogue |

**Environment-specific.** An `environment` is an entity — things run *in*
it. A relationship keeps the environments it is true in
(`attributes.environments`): an end that runs in a single environment — a
production instance, a service seen in production only — makes the edge
that environment's; one that runs in several says nothing. So Billing API's
production database and its staging one stay apart, and the dependencies
of a service **in staging** leave out what is known to hold in production
only. Empty: everywhere, or unknown.

**Where known, and who says so.** Nothing is set by default: a service
nobody says is critical has no criticality. Each value says its origin
(`provenance.attributes`) — a source, or enrichment with its rule and
confidence — and where the tools disagree, every value is kept with who
said it (`provenance.conflicts`).

**Queried.** `GET /knowledge/services` and `/applications` list the
landscape; one service's detail says what it is made of in which
environment; `/entities/{id}/dependencies` walks `depends_on` — what a
service needs, or what its failure reaches — in one environment or all.

## 10. Infrastructure and cloud (LEKA-363)

The company's **infrastructure**: what computes, carries the traffic,
stores and holds the data — and what it is in, where, in which environment,
whose, what it serves and depends on. Built from the tools that know it:

| Tool | What it says |
|---|---|
| AWS | an account's instances, databases, buckets, functions, EKS clusters, VPCs, load balancers; the account itself — its alias, its organisation |
| Azure | the same in each subscription of the scope; the subscriptions — name, state, tags — and their **resource groups** |
| Google Cloud | the same in each project; the projects — name, labels, parent folder or organisation |
| a custom source — a CMDB | servers and databases: by the provider's id when it gives one, else its own; their team, service, criticality, environment, dependencies ([custom.md](connectors/custom.md)) |

**Canonical.** A resource is keyed by its provider's own id — `aws:<ARN>`,
`azure:<ARM id>`, `gcp:<full resource name>` — whatever reads it: two AWS
sources on one account, the cloud connector and a CMDB that names the
resource by its ARN, make **one** entity, every source kept in its
provenance, what they disagree on kept with who said it
(`provenance.conflicts`). Its kind (`resource_kind`) and its **class** —
`compute` (instances, functions, clusters), `network` (networks, load
balancers), `storage` (buckets), `database` — whatever the provider calls
it; the provider's own type beside (`resource_type`).

**The hierarchy, kept.** What resources are in is an entity of its own:

```
 AWS            organisation (attribute) ─▶ cloud_account ◀── resource ── region, zone
 Azure          tenant (attribute) ─▶ cloud_account (subscription) ◀── resource_group ◀── resource
 Google Cloud   folder or organisation (attribute) ─▶ cloud_account (project) ◀── resource
```

Each resource is `part_of` its account, project or resource group, and a
group `part_of` its subscription — named from the resource's own id even
before the account is read, and by its own record's name (`acme-prod`,
`Acme Staging`) once the `accounts` capability is ([cloud.md](connectors/cloud.md);
an existing source reads it after its next connection test). A resource
says its `account`, `region` and `zone` as attributes too. An S3 bucket's
ARN names no account: it is the one account its source reads (enrichment,
`source_account`).

| On a resource | Values | From |
|---|---|---|
| `environment` | the canonical four, or the source's word | a tag, a name (0.5), a CMDB; else its nearest container's — its cluster, its group, its account — 0.9 times as sure ([enrichment.md § 7](enrichment.md)) |
| `exposure` | `public`, `internal` | a public flag, a load balancer's scheme |
| `criticality` | `critical`, `high`, `medium`, `low` | a tag, a CMDB's tier |
| `state` | `running`, `starting`, `stopping`, `stopped`, `deleting`, `terminated`, `failed` | its provider; `terminated` makes it `archived` (§ 4) |
| owners | `owned_by` → a team | a tag, a CMDB; else inherited — from its service, else from what it is in, less surely ([enrichment.md § 3](enrichment.md)) |
| service, application | `part_of` | a tag, a CMDB |
| where it runs | `runs_in` → an environment | its environment |
| network | `in_network` → a VPC, a network | the provider |
| cluster | `part_of` → the cluster it is a node of | the tags EKS, GKE and AKS put on nodes |
| dependencies | `depends_on` → a resource | a CMDB: by provider id, or between its own records |

**Environment context.** An account, a subscription, a resource group or a
project says its environment by its tags, else by its name (0.7: named for
it more often than not — a resource's name says it at 0.5); a resource
that says none runs where what it is in runs. So a company that separates
its environments by account is read right without a tag on every
resource; each value says whether a source or enrichment said it
(`provenance.attributes`), and the API says it too (`environment.origin`).

**Lifecycle.** A resource or an account gone from its provider's listing is
`removed` — kept, with its history (§ 4); one its provider says is
terminated or deleted is `archived` meanwhile.

**Queried.** `GET /knowledge/infrastructure` lists the resources — by
class, kind, provider, account, region, environment, state, exposure,
criticality, service, team; one resource's detail says where it is, what it
holds and what depends on it; `GET /knowledge/cloud-accounts` what each
account holds. `/entities/{id}/dependencies` walks a resource's
`depends_on` as a service's.

## 11. Data (LEKA-364)

The company's **data landscape**: the databases, their schemas and data
objects — tables, views, collections — whose they are, what they hold, how
sensitive, and what is made from what. Built from the tools that know it:

| Tool | What it says |
|---|---|
| PostgreSQL, Supabase, MySQL, MariaDB, SQL Server, Oracle, MongoDB | the catalogue — never a row: schemas, tables, views, collections, their columns, keys, comments, sizes, what each view reads ([databases.md](connectors/databases.md)) |
| AWS, Azure | the instance serving a database, and its endpoint (§ 10) |
| a custom source — a data catalogue | a table's owner, service, classification, kinds of data, upstream ([custom.md](connectors/custom.md)) |
| the source's own mapping | a schema's service and team ([scope-and-mapping.md](connectors/scope-and-mapping.md)) |

**Canonical.** What a source reads is keyed by **where** it reads it — the
engine, the host, the port, the database — `db:postgresql://ledger.abc.rds.amazonaws.com:5432/ledger`;
a schema, `…/ledger/billing`; a data object, `…/ledger/billing/invoices`.
Two sources on one database — one scoped to a schema, a Supabase source
and a PostgreSQL one on the same project, a catalogue that says where a
table is — make **one** entity, every source kept. A MySQL, MariaDB or
MongoDB source reads a server: the `database` is the server, its databases
are `schema`s.

**The hierarchy, kept.**

```
 cloud instance (database, § 10) ◀── database ◀── schema ◀── data_object
       endpoint:<host>:<port>         host, port, name                 table, view, collection
```

A data object is `part_of` its schema, a schema of its database, and a
database of the cloud instance a client reaches at its address — an RDS
instance by its endpoint, an Azure flexible server by its name in its
engine's domain: the PostgreSQL source's and AWS's things joined.

| On a data object | Values | From |
|---|---|---|
| `object_kind` | `table`, `partitioned_table`, `view`, `materialized_view`, `foreign_table`, `collection` | the catalogue |
| `columns`, `primary_key`, `estimated_rows`, `size_bytes`, `description` | as the catalogue says them — sizes rounded, and no version of their own (§ 5) | the catalogue |
| `owner_role` | the database's role that owns it — not a team | the catalogue |
| `column_categories`, `data_categories` | what each column holds: `contact`, `identity`, `location`, `financial`, `credential`, `health`, `personal` | its name (0.8), its comment (0.95) — **never a value**; a catalogue ([parsing.md](parsing.md)) |
| `classification` | `restricted` (a credential, a card or an account, health), `confidential` (personal data), `internal`, `public` | the most sensitive of its columns, its documentation, a catalogue |
| `personal_data` | `true` when it holds personal data | its columns, a catalogue |
| owners | `owned_by` → a team | a catalogue, the source's mapping of its schema; else inherited — from its schema, its database, the instance ([enrichment.md § 3](enrichment.md)) |
| service | `part_of` → a service | a catalogue, the source's mapping |
| foreign keys | `references` → the table it points at | the catalogue |
| what it is made from | `reads_from` → a table | a view's definition, a catalogue's upstream |

**Up and down.** What a schema, a database and the instance serving it
hold is what their tables hold — every kind, the most sensitive
classification, said as enrichment's (`objects`); a database and its
schemas run where the instance serving them runs (`container`). Nothing is
guessed: a table no column, comment or catalogue says anything of has no
classification.

**Lineage.** `/data-objects/{id}/lineage` walks `references` and
`reads_from`: upstream, what a view or a table is made from; downstream,
what a change of it reaches. And through the graph (§ 8), a table reaches
its service, its team, its database's instance and its account.

## 12. People and organisation (LEKA-365)

Who works there, how they are organised, who owns and operates what, and
who knows it. **Every piece says where it came from**: a source stated it,
or a rule inferred it from the work — never invented.

**What each source gives.**

| Source | People | Teams | Hierarchy | Ownership, responsibility | Expertise signals |
|---|---|---|---|---|---|
| GitHub | logins; addresses from commits | the organisation's teams: maintainers, members | a team's parent | — | commits, pull requests, reviews, issues |
| GitLab, Bitbucket | usernames, addresses | — | — | — | the same |
| PagerDuty | names, addresses | teams: managers, responders | a team's parent | services' teams; escalation policy | incidents led, assigned |
| Microsoft 365 | the directory: address, title, department, office, active | departments | **who reports to whom** | — | documents |
| Google Workspace | the directory (with delegation): address, title, department, unit, active | departments | **who reports to whom** | — | documents |
| Jira, Linear, Asana, ClickUp, Monday, Trello | accounts, addresses | — | — | — | issues assigned, reported |
| Datadog, a CMDB, cloud tags, a source's mapping | — | teams named | — | a service's, a resource's, a schema's team | — |
| an HR system (custom source) | address, title, department | teams, members, leads | a team's parent, a person's manager | — | — |

**Canonical.** A person is their address, `person:email:sara@acme.io` —
their accounts aliases: a GitHub login, a directory's id — and resolution
makes one of what names them ([resolution.md](resolution.md)): her
commits, her PagerDuty user, her directory entry. A team is its name,
`team:payments`, whichever tool names it; a directory's department is a
team of `team_type: department` — one a tool names too keeps the tool's
word.

| Relationship | From → to | Said by | Inferred by |
|---|---|---|---|
| `member_of` | a person → a team | a team's members, a directory's department, an HR system | `works_with`: most of what they work on is the team's ([enrichment.md § 4](enrichment.md)) |
| `led_by` | a team → a person | GitHub maintainers, PagerDuty managers, an HR system's leads | — |
| `child_of` | a team → its parent | GitHub, PagerDuty, an HR system | — |
| `reports_to` | a person → their manager | a directory, an HR system | — |
| `owned_by` | a thing → a team | a catalogue, a tag, PagerDuty, a CMDB, a mapping | `inherited`: from its container, 0.9 a step — less through an account (§ 10) |
| `maintained_by` | a repository, project, service → a person | — | `most_active`: the most active on what it holds |
| `contributes_to` | a person → a repository, project, service | — | `work`: their items there — with the evidence (§ below) |

**Expertise, attributed.** A person's `expertise` lists the areas their
work shows they know — each with how many items, in which roles, the last
— and `languages`, those of the code: [enrichment.md § 7](enrichment.md).
What a person never touched in a source LEKA reads is not their expertise;
a bot has none, and says it is one (`bot`).

**Queried.** `/knowledge/teams`, `/knowledge/people` and their details;
`/entities/{id}/responsibility` answers "who owns this, who leads them,
who knows it" for anything. Every tie says `origin` (`stated`,
`inferred`), its `rule` and its `confidence`.

**Limits, and coverage.**

- **The org chart is a directory's**: without Microsoft 365, Google
  Workspace (with delegation) or an HR system, there is no `reports_to`.
- **Teams are the tools'**: GitLab groups, Slack user groups, Jira and
  Linear teams, Microsoft Teams are not read as teams.
- **Ownership by code**: `CODEOWNERS` files are not read; a GitHub team's
  repository permissions are not taken for ownership — an admin team on
  every repository would own them all.
- **Who is on call**: PagerDuty's escalation policy is named, its
  schedules and on-call shifts are not read.
- **Departments are words**: a directory's department is a team by its
  name; two departments written differently are two teams.
- **A person without an address** in one tool and an address in another
  meets by name only where resolution is sure ([resolution.md](resolution.md));
  else they are two.
- **LEKA's own users** are not tied to the people of the model yet.

## 13. Documentation and business knowledge (LEKA-366)

Where the company writes down what it knows, how fresh that is, what it
covers — and what the business does, how, and on what technology and data.
**Every piece says where it came from**: a source stated it, or a rule
inferred it, with its confidence — `provenance` on the entity, `origin`,
`rule` and the records on each relationship.

**What each source gives.**

| Source | Knowledge spaces | Documents | People | Links, what it describes |
|---|---|---|---|---|
| Confluence | spaces: key, type, description | pages: version, parent page | author, page owner, last editor | its links: pages, spaces, repositories, issues |
| Notion | databases | pages: in a database, or under a page | creator, last editor | its links and page mentions, the pages it links |
| Slab | topics (the source's scope) | posts | — | its links |
| Guru | collections | cards: verified or not, when to verify again | owner, last editor | its links |
| Google Workspace | shared drives | files: type, size, text | owner, last editor | the links in its text |
| Microsoft 365 | SharePoint libraries — a group's — and OneDrives — a person's | files: type, size, path | creator, last editor | the links in its text |
| Datadog's catalog, a CMDB | — | — | — | a service's documentation and runbook links: `describes` |
| a business system (custom source) | — | — | business owners | capabilities, processes, activities; their applications, services, data, documentation |
| a wiki (custom source) | spaces | documents | author | the services, applications, capabilities it describes |

**Documents and where they are kept.** A document is `part_of` its
**knowledge space** — a Confluence space, a Notion database, a Slab topic,
a Guru collection, a shared drive, a SharePoint library — and `child_of`
its parent page. Its people: `authored_by`, `owned_by` (a person, or the
space's team, inherited), `edited_by` (who last changed it). What it links
to is what the link opens: `references` a document or a space, `mentions`
a repository, an issue, a pull request.

**What it describes.** `describes` → a service, an application, a
repository, a table, a capability, a process — said by a catalogue's
documentation link, a business system, the source's mapping of a space to a
service; inferred from its title (`named_in_title`, 0.6), its space's name
(`same_name`, 0.7), its address in a catalogue's link (`linked`, 0.95)
([enrichment.md](enrichment.md)).

**Freshness and ownership, where available.** A document's `freshness` —
`fresh` (changed within 90 days), `aging` (within a year), `stale` — from
when it last changed (`last_activity_at`), kept current without a version
of its own (§ 5); `verified` and `verification_due_at` where its tool says
(Guru). A space's team: its tool's (a SharePoint library's group), the
source's mapping, else its name's (`same_name`); its maintainers, those
who write and edit it most; its lifecycle, its documents' activity —
`dormant` after 180 days without a change.

**Coverage.** `/documentation/coverage` says, kind by kind, how much of the
company is documented, and by documents that are not stale;
`/documentation/gaps` lists what is not — the critical first to filter by
— or what only stale documents describe.

**Business capabilities and processes.** Keyed by name —
`capability:invoicing`, `process:order-to-cash`, an activity by its path,
`process:order-to-cash/send-invoice` — so a CMDB's application naming a
capability meets the capability's own record.

| Relationship | From → to | Said by | Inferred by |
|---|---|---|---|
| `child_of` | a capability → its parent | a business system | — |
| `part_of` | an activity → its process | a business system | — |
| `realizes` | a process → a capability | a business system | — |
| `supported_by` | a capability, a process → an application, a service | a business system; a catalogue's application or service | — |
| `uses` | a capability, a process → a table, a schema, a database | — | `named`: the data the business system names, found by name |
| `owned_by` | a capability, a process → a team or a person | its business owner, its team | `inherited`: an activity its process's, a sub-capability its parent's |
| `describes` | a document → a capability, a process | its documentation link | `named_in_title` |

**Queried.** `/business-capabilities`, `/business-processes` and their
details; `/entities/{id}/business` answers "what does this table, this
service, this resource mean to the business": the capabilities and
processes relying on it — directly, through its service or application, or
through what depends on it — each with how (`path`, `via`) and who says so.

**Limits, and coverage.**

- **Only what is linked is read as linked**: Confluence's internal links
  by title (`<ac:link>`, no address) are not read; a SharePoint link is
  found by its address only when a catalogue gives it (`linked`).
- **Text is not read for meaning**: what a document describes comes from
  links, titles, names — never a summary of its text; no model reads it.
- **Slab**: a post's topic is read only when the source's scope names the
  topics; its authors are not read.
- **Google Drive's own drive** (`My Drive`) is no space; its files are
  documents in none.
- **Business processes come from a business system**: none of the tools
  LEKA connects to models them; without a custom source on an architecture
  repository or a process catalogue, there are none. A name two
  capabilities share is one capability.
- **Data named by a business system** is found by name only: a table two
  schemas share a name with is not said (`knowledge.data_ambiguous`).
- **Freshness is time**: a page changed yesterday may still be wrong; only
  Guru's verification says more.
- **Where it opens**: documents and spaces keep their link; other kinds
  do not yet — resolution keeps links as provenance.

## 14. Incidents, changes and deployments (LEKA-367)

What happens to the company's systems — what broke, what changed, what was
shipped where — with **when**, as the sources date it, so LEKA can say what
changed and what it reached. Every piece says where it came from: a date its
source gives, a relationship a source states or a rule infers.

**What each source gives.**

| Source | Incidents | Changes | Deployments |
|---|---|---|---|
| PagerDuty | incidents: urgency, priority, number, opened, first acknowledged, resolved; their service | change events (`changes`): what a pipeline or a tool sent it, its services | — |
| Datadog | incidents: severity, customers hit, detected, declared, resolved; their services | an event tagged as a change | an event tagged as a deployment (`event_type:deployment`, `deploy`…) or sent by a delivery tool (Argo CD, Spinnaker, Octopus…): its service, environment, version |
| Kibana | cases: severity, opened, closed | — | — |
| Grafana | — | an annotation tagged as a change | an annotation tagged `deploy`: its region's end, when it finished |
| GitHub, GitLab | — | — | `deployments`: environment, commit, ref, who; GitHub's statuses, GitLab's status, started and finished |
| Jira Service Management | issues of type Incident | change requests (Normal, Standard, Emergency change): type, state | — |
| a change management tool, a CI/CD tool (custom sources) | — | a change: type, risk, plan, what it affects, who made and asked for it | a deployment: service, environment, version, commit, who |

**Canonical.** An incident is `incident:<tool>:<id>` — a Jira one, its
ticket's key. A deployment is its repository's, `github.com/acme/api/deployments/42`,
or its tool's, `deployment:datadog:<id>`. A change is `change:pagerduty:<id>`,
a Jira change its ticket's key. States on LEKA's scales: an incident `open`,
`in_progress`, `closed`; a deployment `pending`, `in_progress`, `succeeded`,
`failed`, `canceled`, `inactive` (replaced by a later one); a change
`requested`, `scheduled`, `in_progress`, `completed`, `failed`, `canceled`
— the source's word kept beside, where it has one.

| Relationship | From → to | Said by | Inferred by |
|---|---|---|---|
| `affects` | an incident, a change → a service, an application, a resource | its tool: the incident's service, the change event's services, a change request's configuration items | `named_in_title`, `component`, `label`: its title, a component, a label names the service (0.6–0.85) |
| `part_of` | a deployment → its repository, its service | its code host, an event's `service:` tag, a CI/CD tool | — |
| `deploys` | a deployment → its commit, the release its ref names | its code host, a CI/CD tool | — |
| `deployed_to` | a deployment → an environment — or a resource | its environment, canonical (a GitLab tier, GitHub's production flag) | — |
| `caused_by` | an incident → a change, a deployment, a ticket | Jira's cause links (`Causes`, `Problem/Incident`) | `preceded`: a deployment of its service — or of a repository of it — a change to it or to the application holding it, done within the day before it opened, in its environment: 0.7 within the hour, 0.6 within six, 0.5 within the day; three at most; none where a source says the cause |
| `assigned_to`, `reported_by`, `led_by` | an incident, a change → a person | its tool | — |
| `reported_by` | a deployment → who made it | its code host, a CI/CD tool | — |

**Historical state, kept.** Each event's own dates, as its sources give
them — an incident opened, detected, acknowledged, resolved; a deployment
made, started, finished, and each of its statuses with when; a change
asked, planned, started, finished; a release published; a pull request
merged — carried by enrichment from the records, their origin the source's.
And each version LEKA made of it (§ 5): the states it saw it take, when it
saw them — an incident's detail and a change's give both, in time order
(`timeline`). How long an incident waited to be acknowledged and lasted, a
deployment ran — enrichment's, from those dates.

**What changed, and what it reached.** An incident's detail lists what
changed on what it affects in the 72 hours before it opened — deployments,
changes, releases, merges — its causes, said or suspected, each with its
rule, and its **impact**: what depends on what it affects (two steps), the
applications holding them, the capabilities and processes relying on them
(§ 13). `/knowledge/timeline` gives what happened around anything — a
service, its repositories and resources, an application and its services —
or everywhere, between two dates.

**Limits, and coverage.**

- **A suspected cause is a suspect**: `preceded` says a change came
  shortly before, on what the incident affects — never that it caused it.
  A change to a database a service reads, a dependency's deployment, are
  not suspected.
- **Existing sources read deployments and change events after a
  re-test**: their capabilities come from the last connection test. A
  GitHub token needs the **Deployments** permission (read).
- **History starts with LEKA**: GitHub's and GitLab's deployments of the
  last 90 days at the first pass, PagerDuty's change events and incidents
  of the last 90 days; a state LEKA did not see — between two passes — is
  known only by the dates the source gives.
- **Bitbucket, Jenkins, Argo CD, Kubernetes** are not read for deployments
  — a CI/CD tool can be, as a custom source; Datadog's and Grafana's events
  are deployments only when tagged so.
- **ServiceNow** is read as a custom source: its change requests and their
  configuration items, by name.
- **Change approvals, maintenance windows, freezes, postmortems** are not
  modelled yet.
- **DORA measures** — deployment frequency, lead time, change failure
  rate — are not computed yet; the deployments and causes they need are
  here.

## 15. Relationships and dependencies (LEKA-368)

The relationships are the graph: what `leka.context` follows to gather an
answer, what a dependency walk follows to know what a failure reaches. Each
kind has a **contract** in the registry (`leka/knowledge/registry.py`,
served by `/knowledge/registry`), versioned with it; each build checks
every relationship against it (`leka/knowledge/contracts.py`).

**Made from processed evidence.** A relationship is **stated** — a record
of a source said it, normalisation read it ([normalisation.md § 5](normalisation.md))
— or **inferred** by a rule of enrichment ([enrichment.md](enrichment.md)),
never invented. Each keeps its `origin`, its `rule`, its `confidence` and
its `provenance`: the records that stated it, or what it was inferred from.

**The contracts.**

| Kind | Means, from → to | From | To | |
|---|---|---|---|---|
| `part_of` | is part of | any | repository, project, service, application, cloud account, resource group, resource, database, schema, knowledge space, business process | no loop |
| `child_of` | is a child of | issue, incident, change, document, team, capability | the same | one; no loop |
| `depends_on` | depends on | service, application, resource, database | the same | dependency |
| `owned_by` | is owned by | any | team, person | |
| `maintained_by` | is maintained by | repository, project, service, application, knowledge space | person | |
| `member_of` | is a member of | person | team | |
| `authored_by`, `assigned_to`, `reviewed_by`, `reported_by`, `led_by` | … by | any | person | |
| `edited_by` | is edited by | document | person | |
| `reports_to` | reports to | person | person | one; no loop |
| `contributes_to` | contributes to | person | repository, project, service, knowledge space | |
| `affects` | affects | incident, change | service, application, resource, database, table, repository | |
| `resolves`, `implements` | resolves, implements | pull request, commit, issue | issue, incident, change | |
| `merges` | merges | commit, pull request | pull request, commit | |
| `caused_by` | is caused by | issue, incident, change | change, deployment, incident, issue, pull request, commit, release | |
| `deploys` | deploys | deployment | commit, release | |
| `deployed_to` | is deployed to | deployment | environment, resource, database | |
| `runs_in` | runs in | any | environment | |
| `in_network` | is in the network | resource, database | resource | |
| `references` | references | table, document | table, document, knowledge space | dependency |
| `reads_from` | reads from | table | table | dependency |
| `describes` | describes | document, knowledge space | any | |
| `supported_by` | is supported by | capability, process | application, service | dependency |
| `uses` | uses | capability, process | table, schema, database | dependency |
| `realizes` | realizes | process | capability | |
| `mentions`, `owns` | mentions, owns | any | any | |

**Validated.** At each build:

| Issue | When | What happens |
|---|---|---|
| `wrong_end` | an end of a kind the contract does not take — a team that reports to someone | **dropped**, an error: never written wrong |
| `cycle_broken` | an inferred link closes a loop of a kind that may have none — A part of B, part of A | the **weakest inferred** link dropped, a warning |
| `cycle` | a loop its sources state — two teams each the other's parent — or a dependency loop | **kept**, a warning: the sources contradict each other, LEKA says so |
| `several_targets` | more than one of what a thing has one — two managers, from an HR system and a directory | **kept**, the surest first, a warning |

`/knowledge/relationships/issues` lists what the last build found;
`model_runs.counts` says how many (`relationships_invalid`,
`relationship_warnings`).

**Their life, kept.** Each relationship says when it first appeared
(`first_seen_at`, the first build it was in) and last changed
(`changed_at`). Each build records in `relationship_changes` what was
`added`, `removed`, or `changed` — its origin, its rule, its environments,
or its confidence by 0.05 at least: an inference drifting with the clock is
no news — before and after, with the build that saw it. Kept a year (the
hourly sweep forgets what is older). `/knowledge/relationships/changes`
serves it to whatever reads the graph.

**Dependencies.** `depends_on`, `reads_from`, `references`, `supported_by`
and `uses` say what a thing needs to work; the dependency walk follows
`depends_on`, or those asked (`through`): upstream, what a failure reaches;
downstream, what a thing relies on — in one environment or all (§ 9).

**Limits.** History starts with the first build after LEKA-368: a
relationship's `first_seen_at` before it is when its last build made it. A
relationship's change of provenance alone — another record stating it — is
not a change. A loop longer than the graph's hierarchy is found whatever
its length; a loop through two kinds (A part of B, B child of A) is not.

## 16. The knowledge graph: search, walks, paths, views (LEKA-369)

The entities and the relationships **are** the graph, in PostgreSQL — no
second store ([ADR 001](adr/001-postgresql.md)): an edge table with an
index for each way (`ix_relationships_from`, `ix_relationships_to`:
workspace, end, type), walked one step — one query a way — at a time,
always bounded. `GraphRepository` reads (`leka/knowledge/repository.py`),
`GraphService` answers (`leka/knowledge/graph.py`): people through the API,
the modules above (`leka.context`) through `leka.knowledge`.

**Search** (`leka/knowledge/search.py`). Each build writes on each entity
what search reads:

- `search_name` — its name, its display name, a repository's own name
  (`payment-api` of `acme/payment-api`): each once, apart;
- `search_text` — its key's words, its description (its first 1,500
  characters), an email, a title, a department, a class, an engine, a
  provider, a region, an environment, a language, its labels, topics, tags.

Both **folded**: lower case, accents off, ligatures opened (`œ` → `oe`),
words split at whatever is not a letter or a digit — of any script. A
word's case changes do not break it — PostgreSQL is `postgresql`, GitHub
`github` — but its pieces are words too, in the text: PaymentApi is found
by `paymentapi`, `payment api` and `api`. PostgreSQL computes their words
(`search_vector`, the `simple` dictionary: no stemming — names are not
prose, and the company speaks French and English), the names weighted A,
the rest B, under a GIN index (`ix_entities_search`).

What is typed: every word a prefix, all of them needed — or, typed
`PaymentApi`, its pieces; nothing typed is tsquery syntax. The best first:
one of its names the very one typed, then a name it starts, then the
words' rank (`ts_rank_cd`, a name's words weigh more), the active before
the dormant and archived. The removed are left out unless asked. Each hit
says where it is — what it is part of, a child or a member of, the surest
— and the relationships among the hits come with them.

Until a build writes them, an entity's texts are its name and its key in
lower case (the migration); `MODEL_VERSION` 9 has the hourly sweep rebuild
every model.

**Walks** — what surrounds one entity or a few (ten at most): 1 to 4
steps, `outgoing`, `incoming` or `both`, through the relationships asked
(every kind when none), reaching only the kinds asked, `min_confidence`,
in one `environment` (a relationship true in every environment counts).
Each step is one query a way, the surest first, 5,000 rows a way at most;
500 entities at most; then the relationships among all of them, whichever
way they point — the direction says how far the walk goes, not which
truths it shows — 2,000 at most. The removed are never walked through; a
root may be one. Past a bound, `truncated`.

**Paths** — the shortest ways between two entities, through relationships
read either way (`relationship` to keep to some kinds), `max_depth` 4 at
most. Two searches, one from each end, meet in the middle — the smaller
frontier steps first — each step reading the relationships' ids and ends
only. Every shortest way is found; five are returned, the surest first (by
their least sure relationship). None within `max_depth`: `length` is null.
5,000 entities visited at most, then `truncated`.

**Views** — the company's landscapes (`leka/knowledge/views.py`):

| View | Rows | Lines |
|---|---|---|
| `company` | users (no source describes them yet: the row says so) · applications (the repositories, where no catalogue names applications) · services · data (databases) · infrastructure (resources, boxed) | `part_of`, `depends_on`, `in_network` |
| `domains` | capabilities · processes · the applications and services tied to them · the data tied to them | `child_of`, `part_of`, `realizes`, `supported_by`, `uses` |
| `applications` | applications · services · code (the repositories tied to either) | `part_of`, `depends_on` |
| `services` | services · data (the databases tied to services) · infrastructure (the resources tied to services or databases, boxed) | `depends_on`, `part_of`, `in_network` |
| `data` | databases · schemas · tables and views | `part_of`, `references`, `reads_from` |
| `infrastructure` | accounts and resource groups · resources, one by one · databases | `part_of`, `in_network`, `depends_on` |
| `organisation` | teams · people | `child_of`, `member_of`, `led_by`, `reports_to` |
| `dependencies` | business · applications · services · data · infrastructure — each only what a dependency ties to another of them | the registry's dependencies (§ 15) |

Each row shows its 60 most connected things and says how many it holds
(`shown`, `total`); a bot — what signs GitHub's merges — is none of the
company's people, on a view nor in its coverage. A boxed row puts the cloud resources together per
provider and region, counted, in their worst state. A line joins two boxes
for a relationship of the view, once, coloured by the worse of its ends.
Each box has its state — the environment screen's rules,
[enrichment.md § 12](enrichment.md) — its environment and its team
(`owned_by` a team, the surest).

**Provenance and coverage.** Each search hit and each thing a walk reaches
says the kinds of the sources that show it (`github`, `pagerduty`…). Each
view — and `/knowledge/coverage`, for every kind — says how well LEKA
knows its kinds, over all of them, not only those drawn: how many, with an
owner, documented (a `describes`), corroborated (said by two sources or
more), connected (tied to anything). A measure that does not apply is
null: a person's owner and documentation, a team's owner. And the sources
it comes from: each, its kind, how many of its entities it shows.

**Access.** Read by every member (`workspace:read`), like the rest of the
model; nothing here writes. Every query carries the workspace: a root, an
end of a path — any entity — of another workspace is 404, and a search
never crosses.

**Performance.** `scripts/bench_knowledge_graph.py` builds a synthetic
company — 20,000 entities, 60,000 relationships, in a build's proportions:
people, repositories, tables, resources, the dependencies between services
and data — and times `GraphService`: the median and the slowest of seven
runs, caches warm; Apple M4, PostgreSQL 16 in Docker, 2026-10-03.

| Question | Median | Slowest |
|---|---:|---:|
| search `pay` (thousands match) | 16 ms | 44 ms |
| search `billing api` | 6 ms | 8 ms |
| walk, a typical service, 1 · 2 · 4 steps | 5 · 10 · 43 ms | 6 · 12 · 67 ms |
| walk, the most connected service, 2 · 4 steps | 31 · 144 ms | 54 · 174 ms |
| walk, the same, 4 steps, dependencies only | 80 ms | 115 ms |
| paths, a typical service → a team | 5 ms | 6 ms |
| paths, the most connected service → a team | 26 ms | 49 ms |
| views `company`, `applications`, `services`, `data` | 126–157 ms | 140–194 ms |
| views `domains`, `infrastructure`, `organisation` | 74–104 ms | 102–119 ms |
| view `dependencies` | 348 ms | 398 ms |
| coverage, every kind | 78 ms | 80 ms |

What to expect: a search, a walk of one or two steps, a path — tens of
milliseconds; four steps from a hub, a view — under 200; the dependency
view, every dependency of the company, about 350. The bench found two
queries slow, rewritten since: a view's tied rows (one condition with an
OR between the two ways: minutes; each way on its own column, once per
view: milliseconds) and the shortest ways from a hub (500 ms; meeting in
the middle: 26). The figures are an order, not a contract: they grow with
the rows a step reads, which the bounds cap. Run the script again after
changing a query, and say what moved.

**On screen.** "Mon environnement" (`/environment`): seven tabs, each a
view — Entreprise, Domaines, Applications, Services, Données,
Infrastructure, Organisation — as a map or a list, its coverage and
sources under it; the figures, events and points of attention still read
enrichment ([enrichment.md § 12](enrichment.md)). "Voir la cartographie
détaillée" (`/environment/graph`): the dependency view; with a thing chosen
(`?entity=`), what surrounds it — 1 to 3 levels, a direction, a family of
relationships — what is picked on the canvas, and the shortest way to
anything searched. Its canvas puts each row's things in rows of their
own by what points to what — a table above the tables its foreign keys
point to, an arrow going down rather than looping along a row — ordered
under what they are tied to (`layered`, `dependency-graph.tsx`). An empty
row of a view says what would fill it there: the domains' applications are
those the business relies on, not "connect GitHub". ⌘K searches the model;
an entity's sheet leads to its graph and names the browser tab.

**Limits.** Search finds entities; a relationship is found through its
ends — those among the hits come with them — or listed by
`/knowledge/relationships` (§ 7). A row shows 60 things, the list view
too; the screens walk 3 steps, the API 4. The detailed map lays things out
in rows — by distance on a walk, by row on a view — not by an auto-layout.
No view is saved or shared yet.

## Not yet

- **The environment screen's figures** ([enrichment.md § 12](enrichment.md))
  — its counts, events and points of attention, and an entity's sheet —
  still read enrichment's tables; its map reads the model's views (§ 16).
- **A person's word**: correcting an entity or a relationship by hand, kept
  across builds.
- **Kinds promised by connectors not built**: Kubernetes workloads — a
  pod, a replica set — a dashboard, an alert — each an entry in the registry
  the day a connector makes it.
- **What a load balancer sends traffic to**: its targets are one more call
  per load balancer at each provider; not read yet.
- **An Azure machine's network**: Azure names it through the machine's
  network interface, not in the resource list; not read yet.
- **A resource known by its address**: a CMDB that names an instance by its
  host name or IP — matched by the provider's id only, today. A database
  source meets an RDS instance and an Azure flexible server at their
  endpoint (§ 11); a Cloud SQL instance, an Azure SQL database, a MongoDB
  Atlas cluster are not matched yet.
- **What the code reads and writes**: which service queries which table —
  from code or query logs — is not read; a table's service comes from a
  catalogue or the source's mapping.
- **A database's own classification**: SQL Server's sensitivity labels,
  Oracle's data redaction policies are not read; columns' names and
  comments, and catalogues, are.
- **Backstage files in repositories** (`catalog-info.yaml`): read today
  through a custom source on Backstage's API; reading the files from the
  code hosts is the next step.
- **Datadog's traced dependencies** (APM service maps, per environment):
  the catalog's declared ones are read; the observed ones are not.
- **The documentation's, the incidents' and the timelines' screens**: their
  API is there (LEKA-366, LEKA-367); the screens of the landscapes are
  (§ 16), theirs are not yet.
