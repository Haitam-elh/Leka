# The normalisation contract — from a record to LEKA's structures

What normalisation reads, what it hands to the graph, and the mapping rules
it applies. LEKA-356. It reads an extraction ([extraction.md](extraction.md))
and its parse ([parsing.md](parsing.md)); what reads it next is entity
resolution (LEKA-357), then leka.knowledge.

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
| instances, buckets, functions, clusters, networks, load_balancers | `infra_resource`, with `attributes.resource_kind`: `instance`, `bucket`, `function`, `cluster`, `network`, `load_balancer` |
| projects, issues of Linear, Asana, Trello, ClickUp, Monday | `project`, `issue` — a task, a card, an item is an `issue` |
| pages, files (Confluence, Notion, Slab, Guru, Google Workspace, Microsoft 365) | `document` |
| incidents (Datadog, PagerDuty) | `incident` |
| services (PagerDuty) | `service` |
| named by a record | `person`, `service`, `team` |

Alerts, events, metrics, logs and dashboards (Datadog, Grafana) are
extracted and parsed, but are not entities: they are the evidence about
incidents and services, not things of the company model. Nor are the
containers of documents — spaces, Notion databases, topics, collections,
drives: a document names what it is part of. Both stay `unsupported`.

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
| cloud resource | `aws:<ARN>`, `azure:<ARM id, lower-cased>`, `gcp:<full resource name>` |
| service, team | `service:billing-api`, `team:payments` — a slug of the tag's value, or of a PagerDuty service's name: the same service meets on one key |
| incident | `incident:pagerduty:Q1ABC…`, `incident:datadog:<uuid>` — the tool and its own id, not its per-account number |
| Linear issue | `linear.app/acme/ENG-42` — its workspace and identifier; **alias `ticket:ENG-42`**, so `ENG-42` in a pull request finds it |
| another tool's project, issue | `asana:project:1204…`, `trello:issue:5f1e…`, `clickup:issue:86…`, `monday:issue:123…` — the tool, what it is, its id |
| document | `acme.atlassian.net/wiki/pages/1001` (Confluence's ids are its site's), `microsoft_365:document:<drive>/<item>`, `notion:document:<id>`, `slab:…`, `guru:…`, `google_workspace:…` |

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
| `state` (cloud resources) | `running`, `starting`, `stopping`, `stopped`, `deleting`, `failed` — EC2 `running`, RDS `available`, Azure `Succeeded`, GCE `RUNNING` → running |
| `state` (incidents) | `open`, `in_progress`, `closed` — PagerDuty `triggered` and Datadog `active` → open, `acknowledged` and `stable` → in_progress, `resolved` → closed |
| `state_raw` | the vendor's word, always kept |
| `priority`, `priority_raw` | `highest`, `high`, `medium`, `low`, `lowest` — `blocker`/`critical` → highest, `major` → high, `normal` → medium, `minor` → low, `trivial` → lowest; an incident's priority (PagerDuty `P1`…`P5`) or severity (Datadog `SEV-0`…`SEV-5`): P1, SEV-0 and SEV-1 → highest, P2 and SEV-2 → high, and so on |
| `change_type`, `scope`, `category`, `breaking` | the surest fact of each (parsing), with `<name>_confidence` |
| `environment`, `exposure` (cloud) | the surest fact, with its confidence — a tag's 0.95, a name's 0.5 |
| `tags` (cloud) | a `{key: value}` object |
| `resource_kind` (cloud) | § 2 |
| `url`, `source_kind`, `quality` | the link, the connector, the parse's quality score |

A state or a priority no table knows is **kept**, lower-cased, and said in
`diagnostics` — not a failure. A `name` has its spaces collapsed, at most
500 characters.

## 5. Relationships

| `type` | From → to | Read from |
|---|---|---|
| `part_of` | an item → its repository; a Jira issue, a tool's issue → its project; a resource → its service | the container (a Linear issue: its project); a `service` tag |
| `child_of` | a Jira issue → its parent; a tool's issue → its parent issue; a document → its parent page | the extraction's `parent` |
| `authored_by`, `committed_by`, `assigned_to`, `reviewed_by`, `reported_by`, `created_by`, `led_by` | an item → a person — an incident's commander leads it | the extraction's references |
| `affects` | an incident → a service | PagerDuty's service, Datadog's *services* field |
| `resolves`, `mentions`, `implements`, `merges` | an item → an item | parsing's references: "Fixes #41", a link, a branch name, a merge commit |
| `mentions` | an item → a person | `@handle` on a code host |
| `owned_by` | a resource → a team; a PagerDuty service → its teams | a `team` / `owner` tag; the service's teams |
| `in_network` | a resource → its VPC or network, by that record's own key | the extraction's `network` |

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
changes: what the old rules normalised is normalised again.

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
container (confidence 1.0), the company's tag keys (0.95), its own words for
states, priorities and environments — which win over the tables of § 4.
`normalised_records.settings_version` is the version it was applied with; a
new mapping makes the source's rows stale, and they are made again.

## Not yet

- **Writing the graph**: entity resolution (LEKA-357) and leka.knowledge.
- **A Jira link's site**: a link to `acme.atlassian.net/browse/PAY-7` found in
  GitHub comes out as `ticket:PAY-7` — parsing keeps the key, not the site.
- **A screen**: the route is there; the Sources screen does not show it yet.
