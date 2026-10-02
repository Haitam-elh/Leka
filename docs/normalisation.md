# The normalisation contract — from a record to LEKA's structures

What normalisation reads, what it hands to the graph, and the mapping rules
it applies. LEKA-356. It reads an extraction ([extraction.md](extraction.md))
and its parse ([parsing.md](parsing.md)); what reads it next is validation
([validation.md](validation.md)), then entity resolution
([resolution.md](resolution.md)), then enrichment
([enrichment.md](enrichment.md)), then leka.knowledge.

```
 ExtractedRecord + ParsedRecord
        │
        ▼
 normalise(extracted, parsed)                    leka/ingestion/normalisation
        │  a canonical key, canonical attributes, relationships between keys
        ▼
 NormalisedRecord  — or —  NormalisationFailure  one per record, never an exception
```

**Candidates, not rows.** Normalisation says the same thing the same way
whichever source said it; it does not decide that two candidates are one
entity (LEKA-357), and it writes nothing to `entities`.

---

## 1. What comes out

`NormalisedRecord` (`leka/ingestion/normalisation/contract.py`):

| Field | |
|---|---|
| `provenance` | the extraction's, unchanged |
| `extractor_version`, `parser_version`, `normaliser_version` | what it was made from and by |
| `entity` | the record itself, as a `NormalisedEntity` |
| `related` | the entities it names: people, services, teams |
| `relationships` | `NormalisedRelationship`s between canonical keys |
| `diagnostics` | what was kept as the vendor wrote it — an unknown state, a Jira site unknown |

`NormalisedEntity` (`leka/ingestion/schemas.py`): `type`, **`key`** (canonical),
`external_id` (the vendor's id for the record itself, else the key),
`source_id`, `name`, `attributes`, **`aliases`** (its other canonical keys),
`confidence`, `observed_at`.

`NormalisedRelationship`: `type`, `from_key`, `to_key`, `source_id`,
`confidence`, `evidence` (the field it was read in). A key may name
something no source has shown yet — a ticket in a tool not connected.

## 2. Types

| Capability | Entity `type` |
|---|---|
| repositories, pull_requests, issues, commits, branches, releases, projects | `repository`, `pull_request`, `issue`, `commit`, `branch`, `release`, `project` |
| db_instances | `database` |
| instances, buckets, functions, clusters, networks, load_balancers | `infra_resource`, with `attributes.resource_kind`: `instance`, `bucket`, `function`, `cluster`, `network`, `load_balancer` — and its `resource_class`: `compute` (instance, function, cluster), `network` (network, load balancer), `storage` (bucket); a database's is `database` (LEKA-363) |
| accounts (AWS, Azure, Google Cloud) | `cloud_account` — an AWS account, an Azure subscription, a Google Cloud project — or `resource_group`, an Azure resource group (LEKA-363) |
| schemas, tables (PostgreSQL, Supabase, MySQL, MariaDB, SQL Server, Oracle, MongoDB) | `schema` — a MySQL or MongoDB database too — and `data_object`, with `attributes.object_kind`: `table`, `partitioned_table`, `view`, `materialized_view`, `foreign_table`, `collection`; the database they were read on, named: `database` (LEKA-364) |
| projects, issues of Linear, Asana, Trello, ClickUp, Monday | `project`, `issue` — a task, a card, an item is an `issue` |
| pages, files (Confluence, Notion, Slab, Guru, Google Workspace, Microsoft 365) | `document` — `attributes.document_kind`: `page`, `post`, `card`, `file` |
| spaces, databases, drives (Confluence, Notion, Slab, Guru, Google Workspace, Microsoft 365) | `knowledge_space` — where documents are kept; `attributes.space_kind`: `space`, `database` (Notion's), `topic`, `collection`, `shared_drive`, `document_library`, `onedrive` (LEKA-366) |
| incidents (Datadog, PagerDuty; Kibana's cases) | `incident` |
| services (PagerDuty, the Datadog service catalog) | `service` — a PagerDuty **business service** is an `application` (LEKA-362) |
| records of a custom API (`custom_rest`, `custom_graphql`, `custom_webhook`) | the `entity` their resource declares: `issue`, `incident`, `service`, `application`, `project`, `document`, `infra_resource`, `database`, `data_object`, `person`, `team`, `business_capability`, `business_process`, `knowledge_space` — keyed by the source, a service, an application, a capability, a process by its name, a resource by its provider's id when the record gives it, a catalogue's table by where it is ([custom.md](connectors/custom.md)) |
| teams (GitHub, PagerDuty) | `team` — `attributes.team_type`: `team` (LEKA-365) |
| people (Microsoft 365, Google Workspace) | `person` — and their department, a `team` with `team_type: department` |
| named by a record | `person`, `service`, `application`, `team`, `environment`; what a resource is in — `cloud_account`, `resource_group` — and a node's cluster; a business system's `business_capability` and `business_process` |

Alerts, events, metrics, logs and dashboards (Datadog, Grafana, Splunk, Kibana) are
extracted and parsed, but are not entities: they are the evidence about
incidents and services, not things of the company model: they stay
`unsupported`. And so do a custom API's records whose resource declares no
`entity`: extracted, not modelled.

A GitLab merge request is a `pull_request`; a Jira issue and a GitHub issue
are both `issue`. The strings are ingestion's; leka.knowledge maps them onto
its own types.

## 3. Canonical keys

One thing, one key — built from what every mention of it carries
(`normalisation/identifiers.py`):

| Thing | Key |
|---|---|
| repository | `github.com/acme/api` — host and path, lower-cased, no `.git` |
| issue or pull request on GitHub | `github.com/acme/api#41` — GitHub numbers both in one sequence |
| issue on GitLab, Bitbucket | `gitlab.com/acme/api#3` |
| merge / pull request on GitLab, Bitbucket | `gitlab.com/acme/api!12` |
| commit | `github.com/acme/api@9f2c…` — the sha lower-cased |
| branch, release | `github.com/acme/api:main`, `github.com/acme/api/releases/v1.2.0` |
| Jira issue, project | `acme.atlassian.net/PAY-42`, `acme.atlassian.net/PAY` — the key upper-cased; **alias `ticket:PAY-42`** |
| a ticket named where its site is unknown | `ticket:PAY-42` |
| person | `person:email:sara@acme.io` when an email is known, **alias** `person:github.com:sara`; else the account: `person:github.com:sara`, `person:acme.atlassian.net:<account id>` |
| cloud resource | `aws:<ARN>`, `azure:<ARM id, lower-cased>`, `gcp:<full resource name>` — a CMDB's resource that gives one, the same key |
| what resources are in | `aws:account:123456789012`; an Azure subscription by its ARM id, `azure:/subscriptions/<id>`, a resource group too, `azure:/subscriptions/<id>/resourcegroups/<name>`; `gcp:project:acme-prod`, **alias** `gcp:project:<number>` — from a resource's ARN, ARM id or project, and from the account's own record: they meet |
| a GKE cluster | its full resource name, **alias** `gcp:cluster:<project>/<location>/<name>` — what its nodes' labels say of it; an EKS or AKS cluster's ARN or ARM id is built from its node's tags |
| a database a source reads | `db:<engine>://<host>:<port>/<database>` — `db:postgresql://ledger.abc.rds.amazonaws.com:5432/ledger`; a MySQL, MariaDB or MongoDB server without its database: `db:mysql://shop.acme.io:3306` |
| a schema, a data object | `<database>/<schema>`, `<database>/<schema>/<name>` — `…/ledger/billing/invoices`: whichever source reads it |
| where a client connects to a database | `endpoint:<host>:<port>` — an **alias** of the RDS instance at that endpoint, of an Azure flexible server at `<name>.postgres.database.azure.com:5432` (or MySQL's); what a database is `part_of` |
| service, team | `service:billing-api`, `team:payments` — a slug of the tag's value, or of a PagerDuty or Datadog service's name, of a GitHub or PagerDuty team's, of a directory's department: the same service, the same team meets on one key; a GitHub team's slug is an **alias** (`team:platform-eng`) |
| a directory's person | `person:email:<address>` — **alias** their account at the directory, `person:microsoft_365:<id>`, `person:google_workspace:<id>` (LEKA-365) |
| application | `application:billing` — a slug of an `application` / `system` / `product` tag, a catalog's application, a PagerDuty business service's name |
| environment | `environment:production` — one of the four canonical names only (§ 4): `prd-eu-2` is a name, not an environment |
| incident | `incident:pagerduty:Q1ABC…`, `incident:datadog:<uuid>`, `incident:kibana:<case id>` — the tool and its own id, not its per-account number |
| Linear issue | `linear.app/acme/ENG-42` — its workspace and identifier; **alias `ticket:ENG-42`**, so `ENG-42` in a pull request finds it |
| another tool's project, issue | `asana:project:1204…`, `trello:issue:5f1e…`, `clickup:issue:86…`, `monday:issue:123…` — the tool, what it is, its id |
| document | `acme.atlassian.net/wiki/pages/1001` (Confluence's ids are its site's), `microsoft_365:document:<drive>/<item>`, `notion:document:<id>`, `slab:…`, `guru:…` — **alias** `guru:card:<slug>`, what its link says — `google_workspace:…` |
| knowledge space | `acme.atlassian.net/wiki/spaces/ENG` — the space's key on its site, its pages' container — `notion:space:<id>` (**alias** `notion:document:<id>`: a link to a database reads as one to a page), `slab:space:<topic>`, `guru:space:<collection>`, `google_workspace:space:<drive>`, `microsoft_365:space:<drive>` (LEKA-366). Google's own drive (`user`) is no space |
| business capability, process | `capability:invoicing`; `process:order-to-cash`, an activity by its path under its process: `process:order-to-cash/send-invoice` — two processes may each have an `Approve` (LEKA-366) |

The host is the record's link's (a self-hosted GitLab keeps its own), else
the vendor's public host. **Aliases** are what entity resolution joins on:
`PAY-42` in a GitHub pull request (`ticket:PAY-42`) and the Jira issue
(`acme.atlassian.net/PAY-42`, alias `ticket:PAY-42`); a commit's author by
email and the same person's pull request by login.

## 4. Canonical attributes

Every entity carries the extraction's `metadata` and `signals`, plus:

| Attribute | Rule |
|---|---|
| `created_at`, `updated_at`, any `*_at` | ISO 8601 **in UTC**, to the second: `2026-09-20T08:00:00Z` |
| `state` (issues, pull requests) | `open`, `in_progress`, `closed`, `merged` — GitLab `opened` → open, Bitbucket `declined` → closed; a **tool's own class of state** wins over its status name: Jira's category (`new`, `indeterminate`, `done`), Linear's workflow type (`backlog`, `unstarted`, `started`, `completed`, `canceled`), ClickUp's status type (`open`, `custom`, `closed`); Monday's `Working on it` and `Stuck` → in_progress |
| `state` (cloud resources) | `running`, `starting`, `stopping`, `stopped`, `deleting`, `terminated`, `failed` — EC2 `running`, RDS `available`, Azure `Succeeded`, GCE `RUNNING` → running; EC2 `terminated`, a `deleted` resource → terminated: gone at the provider, still listed a while |
| `state` (accounts) | `active`, `disabled`, `deleted` — Azure `Enabled`, `Warned`, `PastDue` → active (billing's words: it still runs); Google `DELETE_REQUESTED` → deleted |
| `state` (incidents) | `open`, `in_progress`, `closed` — PagerDuty `triggered` and Datadog `active` → open, `acknowledged` and `stable` → in_progress, `resolved` → closed |
| `state_raw` | the vendor's word, always kept |
| `priority`, `priority_raw` | `highest`, `high`, `medium`, `low`, `lowest` — `blocker`/`critical` → highest, `major` → high, `normal` → medium, `minor` → low, `trivial` → lowest; an incident's priority (PagerDuty `P1`…`P5`) or severity (Datadog `SEV-0`…`SEV-5`): P1, SEV-0 and SEV-1 → highest, P2 and SEV-2 → high, and so on |
| `change_type`, `scope`, `category`, `breaking` | the surest fact of each (parsing), with `<name>_confidence` |
| `environment`, `exposure`, `criticality` (cloud) | the surest fact, with its confidence — a tag's 0.95, a name's 0.5 |
| `criticality`, `criticality_raw` (services, applications) | `critical`, `high`, `medium`, `low` — a tier is a number, 1 (or 0) the most critical: `tier-1` → critical, `2` → high, `3` → medium, `4` → low; `mission-critical` → critical. A catalogue's `tier` or `criticality`. The source's word kept beside |
| `stage`, `stage_raw` (services, applications) | where it is in its life: `experimental` (alpha, beta, pilot), `production` (GA, live, stable), `deprecated` (sunset, legacy), `retired` (decommissioned, EOL). A catalogue's `lifecycle` |
| `service_type`, `languages`, `display_name`, `runbook_url`, `repository_url`, `dashboard_url`, `docs_url` (Datadog catalog) | what its team wrote: `web`, `grpc`; `["python"]`; the first link of each kind |
| `tags` (cloud) | a `{key: value}` object |
| `resource_kind`, `resource_class` (cloud) | § 2 |
| `account`, `region`, `zone` (cloud) | the account, subscription or project id it is in; its region — a Google zone (`europe-west1-b`) is a `zone`, its region `europe-west1` |
| `resource_group` (Azure) | the group it is in |
| `job_title`, `department`, `location`, `active`, `user_type`, `directory` (a directory's person) | what the directory says: `location` an office, or Google's organisational unit; `active` whether their account is on (LEKA-365) |
| `team_type`, `description`, `slug`, `privacy` (a team) | `team`, or `department` for one a directory names |
| `account_type`, `account_id` (accounts) | `aws_account`, `azure_subscription`, `gcp_project`; the provider's id. An AWS account's `organization`, an Azure subscription's `tenant`, a project's `parent` folder or organisation |
| `endpoint`, `port` (RDS) | where a client connects |
| `engine`, `host`, `port`, `database_name` (a database) | where a source reads it (LEKA-364) |
| `object_kind`, `schema_name`, `columns`, `primary_key`, `estimated_rows`, `size_bytes`, `owner_role`, `description` (a data object) | what the catalogue says; `owner_role` is the database's role, not a team |
| `data_categories`, `column_categories`, `personal_data`, `classification` (a data object) | what each column holds, by its name and its comment ([parsing.md](parsing.md)): `contact`, `identity`, `location`, `financial`, `credential`, `health`, `personal`; `restricted` for a credential, a card or an account, health, `confidential` for personal data — or what the table's documentation, a catalogue says, the most sensitive |
| `url`, `source_kind`, `quality` | the link, the connector, the parse's quality score |

A state, a priority, a criticality or a stage no table knows is **kept**,
lower-cased, and said in `diagnostics` — not a failure. What a catalogue
said and normalisation turned into relationships or scales — its
`application`, `depends_on`, `tier`, `lifecycle` — is not kept twice as an
attribute: the raw word is in `*_raw`. A `name` has its spaces collapsed, at most
500 characters.

## 5. Relationships

| `type` | From → to | Read from |
|---|---|---|
| `part_of` | an item → its repository; a Jira issue, a tool's issue → its project; a resource → its service; a service → its application — or a resource, tagged with an application alone | the container (a Linear issue: its project); a `service` tag; an `application` tag beside it; a catalog's application or system; a PagerDuty business service's supporting services |
| `depends_on` | a service → a service; an application → an application | PagerDuty's technical dependencies and a business service's supporting business services; the Datadog catalog's `dependsOn` (v3); a custom source's `depends_on` |
| `runs_in` | a resource, a service, an application → an environment | a resource's canonical environment; a custom source's `environments` |
| `child_of` | a Jira issue → its parent; a tool's issue → its parent issue; a document → its parent page | the extraction's `parent` |
| `authored_by`, `committed_by`, `assigned_to`, `reviewed_by`, `reported_by`, `created_by`, `led_by` | an item → a person — an incident's commander leads it | the extraction's references |
| `affects` | an incident → a service | PagerDuty's service, Datadog's *services* field |
| `resolves`, `mentions`, `implements`, `merges` | an item → an item | parsing's references: "Fixes #41", a link, a branch name, a merge commit |
| `mentions` | an item → a person | `@handle` on a code host |
| `owned_by` | a resource → a team; a service, an application → its teams | a `team` / `owner` tag; a PagerDuty service's teams, a business service's team, a catalog's team or owner |
| `in_network` | a resource → its VPC or network, by that record's own key | the extraction's `network` |
| `part_of` | a resource → its account or project; an Azure resource → its resource group → its subscription; a node → its cluster; a CMDB's resource → its service, its application (LEKA-363) | the resource's ARN, ARM id or project; a resource group's own record; the tags a Kubernetes service puts on its nodes |
| `depends_on` | a CMDB's resource → a resource | its `depends_on`: a provider id, or another record's id |
| `part_of` | a data object → its schema → its database → the instance at its endpoint (LEKA-364) | where it was read; a catalogue's schema |
| `references` | a table → the table a foreign key points at | the catalogue's constraints |
| `reads_from` | a view → what it reads; a catalogue's dataset → its upstream | the view's definition; a catalogue's `reads_from` |
| `member_of` | a person → a team (LEKA-365) | a team's members and leads; a directory's department; an HR system's teams |
| `led_by` | a team → a person | a GitHub team's maintainers, a PagerDuty team's managers, an HR system's leads |
| `child_of` | a team → its parent team | GitHub's and PagerDuty's parent team, an HR system's `parent` |
| `reports_to` | a person → their manager | a directory's manager, an HR system's `manager` |
| `part_of` | a document → its knowledge space (LEKA-366) | its container: a Confluence space's key, a Slab topic, a Guru collection, a drive; a Notion page's parent database |
| `authored_by`, `owned_by`, `edited_by` | a document → a person; a space → a team or a person | its author — Notion's creator too — its owner (Confluence's page owner), who last changed it (Confluence's last version, Notion's, Guru's, a file's); a SharePoint library's group, a OneDrive's person |
| `references` | a document → the document or space it links to | its links — its markup's anchors (Confluence, Guru), its runs' (Notion, Slab), its text's — at an address that says which: a Confluence page or space, a Notion page or database, a Google document or folder, a Slab post or topic, a Guru card |
| `mentions` | a document → a repository, an issue, a pull request, a commit | a link to a repository on a code host, or to an item |
| `describes` | a document → a service, an application, a capability, a process | a catalogue's or a business system's documentation link — `docs_url`, `runbook_url`, `documentation` — at an address that says which document; the source's mapping of a container to a service (a document, a space, is not *part of* its service: it describes it) |
| `child_of` | a business capability → its parent | a business system's `parent` |
| `part_of` | an activity → its process | its `parent`: the process's name, or its path |
| `realizes` | a process → a capability | a process's `capabilities`, a capability's `processes` |
| `supported_by` | a capability, a process → an application, a service | its `applications`, `services`; an application's or a service's `capabilities`, `processes` (a catalogue) |
| `owned_by` | a capability, a process → a team or a person | its `business_owner` / `owner` — a person by address — and its `team` |

Confidence is the fact's: 1.0 for what the vendor said, the parse's
confidence for what was read in text or tags.

## 6. Failures — one record at a time

| `code` | When |
|---|---|
| `unsupported` | no mapping for this kind of record (a connector with no rules yet) |
| `invalid` | it cannot be an entity: no name, a pull request with no number, a commit with no sha |
| `malformed` | the stored extraction or parse does not read, or the parse is of another record |

The `message` names what is missing — `no number: the extraction has no
metadata.number` — never a value. Its neighbours are normalised.

## 7. Versions

`NORMALISER_VERSION` (`normalisation/engine.py`) is raised when a rule
changes: what the old rules normalised is normalised again. 4: applications,
environments, dependencies, criticality and stage (LEKA-362). 5: what
resources are in, their class, a node's cluster, a CMDB's servers and
databases, a terminated resource (LEKA-363). 6: databases, schemas and data
objects, foreign keys and what views read, what columns hold (LEKA-364). 7:
teams, a directory's people, an HR system's (LEKA-365). 8: knowledge
spaces, documents' owners, last editors and links, a catalogue's
documentation, a business system's capabilities and processes (LEKA-366).

## 8. Where results are kept, and when they are made

`normalised_records` (`NormalisedRecordRow`): **one row per parsed
`parsed_records` row** — `status` (`normalised` or `failed`), the
NormalisedRecord as JSON (`result`) or `failure_code` and `message`, what it
was made from and by (the parse's `checksum`, extractor and parser versions,
`normaliser_version`), and the record's own **`entity_type` and
`entity_key`**, indexed per workspace: every record naming one key, found
without reading the JSON — what entity resolution (LEKA-357) starts from.
A parse that failed has no candidates; a record gone takes them along
(cascade).

The job, `leka.ingestion.normalisation.job.run_normalisation` (key
`normalise:<source_id>`), is **queued by the parsing job** when it ends
with something to normalise, and **by the end of a pass** when only
normalisation has something to do (a new `NORMALISER_VERSION`). It forgets
the candidates of parses that failed since, then normalises, in id order,
every parse never normalised or normalised from another checksum or
version, with its extraction. Everything it reads is in the database.
Incremental and idempotent.

```
 pass ──▶ extraction ──▶ parsing ──▶ normalisation
   └────── only a later stage to do ─────▲
```

`GET /ingestion/sources/{id}/normalisation` (`source:read`): how many were
normalised and failed (`unsupported`, `invalid`, `malformed`), the records'
entities and their relationships by type, how many kept something as the
vendor wrote it, when last, and the 20 latest failures.

## 9. A source's own mapping

An administrator's mapping for the source (LEKA-351,
[scope-and-mapping.md](connectors/scope-and-mapping.md)) is applied over
these rules: the entity type of a capability, the service and team of a
container (confidence 1.0), the company's tag keys (0.95) — for the
environment, the service, the application, the team and how critical —
its own words for states, priorities and environments — which win over the
tables of § 4.
`normalised_records.settings_version` is the version it was applied with; a
new mapping makes the source's rows stale, and they are made again.

## Not yet

- **Writing the graph**: leka.knowledge, from what entity resolution and
  enrichment make ([resolution.md](resolution.md),
  [enrichment.md](enrichment.md)).
- **A Jira link's site**: a link to `acme.atlassian.net/browse/PAY-7` found in
  GitHub comes out as `ticket:PAY-7` — parsing keeps the key, not the site.
- **A screen**: the route is there; the Sources screen does not show it yet.
