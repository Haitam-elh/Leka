# The company model — what the company is made of

Resolution says what is **one** thing ([resolution.md](resolution.md),
LEKA-357); enrichment says what those things are **together**
([enrichment.md](enrichment.md), LEKA-359). The company model makes of them
the company's **canonical entities**: typed, checked against their kind's
schema, versioned, with a lifecycle and where every piece of them came from.
LEKA-361. It is the source of truth `leka.context` reads, and what the
screens of the graph will read.

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
| organisation | `person`, `team` | — |
| applications | `application` | criticality, stage, environments, point of contact — § 9 |
| | `service` | the same, and its type, languages, escalation policy, links; incidents over 90 days, open incidents, MTTR — § 9 |
| | `repository` | visibility, default branch, language, topics, fork |
| delivery | `project`, `release`, `deployment` | — |
| | `issue`, `pull_request` | priority, category, labels, components, stale, cycle time |
| | `commit` | category, change type |
| operations | `incident` | priority, duration |
| infrastructure | `infra_resource` | provider, account, region, zone, resource group; resource kind and class, the provider's type; environment, exposure, criticality; instance type, engine, version, runtime, endpoint; tags — § 10 |
| | `cloud_account` | an AWS account, an Azure subscription, a Google Cloud project: its type and id, its state, its organisation, tenant or parent; environment, criticality, tags — § 10 |
| | `resource_group` | an Azure resource group: its subscription, region, environment, tags — § 10 |
| | `environment` | — `production`, `staging`, `development`, `test` |
| data | `database` | a cloud instance's, as a resource's (§ 10); a database a source reads: its engine, host, port, name; what it holds — § 11 |
| | `schema` | its database's role that owns it; what it holds — § 11 |
| | `data_object` | a table, a view, a collection: its kind, schema, columns, primary key, size; what each column holds, its classification — § 11 |
| knowledge | `document` | — |

Each **relationship kind** is built from enrichment's relationships
([enrichment.md § 1–4](enrichment.md)): `part_of`, `child_of`,
`depends_on`, `owned_by`, `maintained_by`, `member_of`, `authored_by`
(and normalisation's `committed_by`), `assigned_to`, `reviewed_by`,
`reported_by` (and `created_by`), `led_by`, `affects`, `resolves`,
`implements`, `merges`, `mentions`, `in_network`, `runs_in` (LEKA-362),
`references` and `reads_from` (LEKA-364).
`owns`, `deployed_to` and `caused_by` are kept for what states them later;
nothing does yet.

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
| `provenance.attributes` | each attribute's origin: `{"origin": "source"}`, or `{"origin": "enrichment", "rule", "confidence"}` |
| `provenance.sources` | `{source_id, key, kind}` per source and key |
| `provenance.conflicts` | what its sources **disagree** on (resolution's conflicts, LEKA-362): `{attribute, chosen, values: [{value, source_id}]}` — every value kept with who said it, the attribute marked `disputed` in `provenance.attributes` |
| `confidence` | how sure the merges that made it are (resolution) |
| `quality` | the best quality of its records (validation, LEKA-358) |
| `first_seen_at`, `last_seen_at` | the earliest and latest a source showed it |

A relationship says whether a source **stated** it or a rule **inferred**
it (`origin`, `rule`), how sure it is, whether it joins two tools' things
(`cross_source`), the records that stated it (`provenance`), and the
**environments** it is true in (`attributes.environments`, § 9).

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
rows and size — are kept current but make no version of their own. A thing
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
  last success, which says what its model was made from.

`model_runs.counts`: `created`, `changed`, `unchanged`, `removed`,
`still_removed`, `entities`, `relationships`, `type.<kind>`,
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
| `GET /knowledge/entities/{id}/dependencies` | `direction=downstream` (what it depends on) or `upstream` (what depends on it: what its failure reaches), `depth=1..5`, `environment`: each thing reached and how far, the `depends_on` walked — up to 500, `truncated` beyond |
| `GET /knowledge/infrastructure` | the cloud resources and databases (§ 10), by name, paged: `resource_class`, `resource_kind`, `provider`, `account_id` (an account, subscription, project — or resource group: what is in it and in its groups), `region`, `environment`, `state`, `exposure`, `criticality`, `service_id`, `team_id`, `lifecycle`, `q` |
| `GET /knowledge/infrastructure/{id}` | one: its place, environment and who says so, services, team, network, cluster; what it holds — a cluster's nodes, a network's resources — and its dependencies both ways; its attributes and provenance. Anything but a resource is 404 |
| `GET /knowledge/cloud-accounts` | the accounts, subscriptions and projects, by name, paged: `provider`, `environment`, `lifecycle`, `q` — each with how many resources it holds (in its groups too), of which class, in which regions; its environment and team |
| `GET /knowledge/cloud-accounts/{id}` | one — or a resource group — its resource groups and theirs, its attributes and provenance |
| `GET /knowledge/databases` | the databases (§ 11), by name, paged: `engine`, `classification`, `personal_data`, `environment`, `team_id`, `lifecycle`, `q` — each with the instance serving it, how many schemas and objects, what it holds and who says so |
| `GET /knowledge/databases/{id}` | one: its schemas — how many tables, views, collections, what each holds — the databases it serves (an instance), its attributes and provenance |
| `GET /knowledge/data-objects` | the tables, views, collections, by name, paged: `database_id`, `schema_id`, `object_kind`, `classification`, `category`, `personal_data`, `service_id`, `team_id`, `lifecycle`, `q` — each with its database and schema, size, what it holds, how many ties each way |
| `GET /knowledge/data-objects/{id}` | one: its columns — what each holds, the primary key — what it references and reads from, what references and reads from it |
| `GET /knowledge/data-objects/{id}/lineage` | `direction=upstream` (what it reads from and references) or `downstream` (what reads from or references it — what a change of it reaches), `depth=1..5`: each reached and how far, the relationships walked |

## 8. What reads it

`leka.context`, through `KnowledgeService.neighbourhood`: an entity and
what surrounds it, as one subgraph — the unit an answer is assembled from.
The traversal is one recursive query, bounded by depth and size
([ADR 001](adr/001-postgresql.md)).

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

## Not yet

- **The environment screens** ([enrichment.md § 12](enrichment.md)) still
  read enrichment's tables; they move to the model's entities and
  lifecycles next.
- **Relationships' history**: a relationship is current only; when it
  appeared and went is not kept yet.
- **A person's word**: correcting an entity or a relationship by hand, kept
  across builds.
- **Kinds promised by connectors not built**: Kubernetes workloads — a
  deployment, a pod — a dashboard, an alert — each an entry in the registry
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
- **The landscape on a screen**: the API is there; the views are
  LEKA-369's.
