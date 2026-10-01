# The extraction contract — from a stored record to structured content

What extraction reads, what it hands to parsing, and how it fails. LEKA-354.
What it reads is [collection.md](collection.md); what reads it next is
[parsing](parsing.md) (LEKA-355), then normalisation (LEKA-356).

```
 source_records + raw_payloads          a RawRecord: the vendor's JSON, untouched
        │
        ▼
 extract(record, source_id, source_kind)          leka/ingestion/extraction
        │  one strategy per (source kind, capability)
        ▼
 ExtractedRecord  — or —  ExtractionFailure       one per record, never an exception
```

---

## 1. What comes out

`ExtractedRecord` (`leka/ingestion/extraction/contract.py`): the vendor's
meaning, not its shape. A GitHub pull request, a GitLab merge request and a
Bitbucket pull request come out with the same fields.

| Field | | Promise |
|---|---|---|
| `provenance` | see § 2 | always set |
| `extractor`, `extractor_version` | `github.pull_requests`, `1` | which strategy, which version of it |
| `title` | a name, a subject, a commit's first line | set whenever the vendor has one; a record without what it means nothing without is a failure |
| `url` | where a person opens it | the vendor's web page, not its API |
| `state` | `open`, `merged`, `closed`, `archived`, `active`, … | **lower-cased**, otherwise the vendor's word — mapping `opened` and `open` to one state is normalisation's |
| `created_at`, `updated_at` | | timezone-aware, from the vendor's own dates |
| `content` | `[{role, format, text, truncated}]` | human-written text: `description`, `body`, `message`, `notes`, `comment`. `format` is `markdown` or `text`. Cut at **100 000 characters**, and `truncated` says so |
| `references` | `[{role, kind, external_id, name, email}]` | what the record names: its `author`, `assignee`, `reviewer`, `source_branch`, `head` commit… in the vendor's terms (a login, an account id). Which entity it is, is decided later |
| `metadata` | `number`, `labels`, `visibility`, `sha`, `tag`, `draft`, … | what describes it |
| `signals` | `language`, `topics`, `merge`, … | technical facts |

What the vendor does not say is **left out**: no `None`, no empty list in
`metadata` or `signals`; no empty `content`; no reference that names nothing.

It is plain JSON (`model_dump_json`), and reads back identically
(`model_validate_json`): what parsing receives is exactly what extraction
produced.

## 2. Provenance — enough to find the bytes again

| Field | |
|---|---|
| `source_id`, `source_kind` | the source, and which connector wrote it |
| `capability`, `external_id`, `container` | the record, as `source_records` knows it |
| `fetched_at` | when LEKA read it from the vendor |
| `checksum` | sha256 of the payload read — `source_records.checksum` |
| `payload_key` | the stored batch it was read from, when known |

`checksum` is what makes extraction incremental: a record whose checksum and
`extractor_version` are the ones last extracted has nothing new to say.

## 3. Failures — one record at a time

`ExtractionFailure`: the same `provenance`, the strategy (if any), a `code`
and a `message`.

| `code` | When |
|---|---|
| `unsupported` | no strategy for this (source kind, capability) yet |
| `malformed` | the payload is not the shape the strategy knows: a title missing or not text, a date that is not one, a field of the wrong type |

- `extract` **never raises** for what is in a payload: a failed record is
  data about that record, and its neighbours are extracted.
- The `message` names the field — `missing field 'title'`, `not a date:
  'created_at'` — and **never carries a value from the payload**: a
  customer's ticket text has no place in a diagnostic.
- A vendor that changes a payload's shape shows up as `malformed` failures
  from one strategy, all at once: that is how we find out.

## 4. Strategies

A strategy is a **pure function** of one payload — no database, no network,
no clock — registered for the (source kind, capability) pairs it knows
(`@strategy(name, version, *targets)`). Changing what one extracts means
**raising its version**: what the old one extracted is extracted again.

| Source kind | Capabilities | Module |
|---|---|---|
| GitHub (REST v3) | repositories, commits, pull_requests, issues, releases, branches | `extraction/code.py` |
| GitLab (v4) | the same | `extraction/code.py` |
| Bitbucket (2.0) | repositories, commits, pull_requests, issues, branches | `extraction/code.py` |
| Jira Cloud (REST v3) | projects, issues | `extraction/tickets.py` |
| AWS | instances, db_instances (with the endpoint a client connects to), buckets, functions, clusters, networks, load_balancers — one strategy per service; accounts: the account, its alias and organisation (LEKA-363) | `extraction/cloud.py` |
| Azure | the same seven — one strategy: Resource Manager's list has one shape; accounts: a subscription or a resource group | `extraction/cloud.py` |
| Google Cloud | the same seven — one strategy: an asset around each API's resource; accounts: a project, its number, labels and parent | `extraction/cloud.py` |
| Datadog | alerts (monitors), events, incidents, metrics, logs — `service`, `env`, `host`, `tags` as signals; Datadog's id and timestamp kept | `extraction/observability.py` |
| PagerDuty, Grafana | services, incidents; dashboards, alert rules, annotations | `extraction/observability.py` |
| Splunk, Kibana | alerts (saved searches that alert, alerting rules), fired alerts, cases — Kibana's incidents —, dashboards; tags as signals, the app or space kept | `extraction/observability.py` |
| Linear, Asana, Trello, ClickUp, Monday | projects, and their issues — a task, a card, an item — with the tool's `key`, `status_category` when it has one (Linear's workflow type, ClickUp's status type), priority, labels, people, project, parent | `extraction/projects.py` |
| Confluence, Notion, Slab, Guru | spaces, databases, topics, collections; pages, posts, cards — their **text** read out of Confluence's storage XHTML, Guru's HTML, Notion's blocks, Slab's Quill delta | `extraction/documents.py` |
| Google Workspace, Microsoft 365 | drives; files, with the text the connector read | `extraction/documents.py` |
| PostgreSQL, Supabase, MySQL, MariaDB, SQL Server, Oracle, MongoDB | schemas (a MySQL, MariaDB or MongoDB database, an Oracle user); tables, views, collections — the name as a query writes it, the columns one line each with their type, keys and comment, a view's definition; the tables a foreign key references and a view reads from as references ; where each was read — the server's engine, host, port and database — as signals and metadata (LEKA-364) | `extraction/data.py` |
| A custom API (`custom_rest`, `custom_graphql`, `custom_webhook`) | records — what the source's mapping read: title, url, state, dates, description, author, the metadata named; the resource and the entity it declares as signals ([custom.md](connectors/custom.md)) | `extraction/custom.py` |

A test fails if one of these connectors reads a capability no strategy
extracts. Every connector has its strategies now; a connector added later
without them has its records `unsupported`: counted, not blocking.

Markup is **read, never run**: `fields.markup_text` takes the text out of
HTML and XHTML by expressions — scripts and styles dropped, HTML's own
entities unescaped, nothing else expanded, nothing fetched.

A strategy reads the payload (`@strategy`), or the whole record when it
needs what the connector put beside it (`@record_strategy`): an AWS
resource's region is its record's `container`, not in its payload.

### Code hosts, field by field

| | GitHub | GitLab | Bitbucket |
|---|---|---|---|
| repository `title` | `full_name` | `path_with_namespace` | `full_name` |
| pull request `state` | `merged` if `merged_at`, else `state` | `state` (`opened`, `merged`, …) | `state` (`merged`, `declined`, …) |
| pull request `number` | `number` | `iid` | `id` |
| commit author | login, name, email | name, email | account uuid and name, or Git's `Name <email>` |
| commit `signals.merge` | more than one parent | more than one parent | more than one parent |

### Jira

| | |
|---|---|
| `title`, `url` | `summary` (a project: `name`), `https://<site>/browse/<KEY>` from the API's `self` link |
| `state` | the status's name, lower-cased (`in progress`); `metadata.status_category` is Jira's own `new` / `indeterminate` / `done` |
| `content` | the description, then the **50 latest comments** — Atlassian Document Format flattened to text: a line per block, a mention by its name |
| `references` | `assignee`, `reporter`, `creator` (account id, display name), `project`, `parent` |
| `metadata` | `key`, `type`, `priority`, `labels`, `components`, `fix_versions`, `resolution`, `resolved_at`, `due` |

### Cloud resources

The same signals whatever the provider — what lets normalisation compare an
EC2 instance with an Azure VM:

| Signal | AWS | Azure | Google Cloud |
|---|---|---|---|
| `provider` | `aws` | `azure` | `gcp` |
| `resource_type` | `ec2:instance`, `rds:db`, `s3:bucket`, `lambda:function`, `eks:cluster`, `ec2:vpc`, `elbv2:loadbalancer` | ARM `type`, lower-cased | `assetType`, lower-cased |
| `region` | the record's region (none for S3's global list) | `location` | `resource.location` |
| `tags` | `Tags` / `TagList` / `tags` | `tags` | `labels` |

Then what each kind has: `instance_type`, `engine`, `version`, `runtime`,
`storage_class`, `scheme`, `multi_az`, `public`, `encrypted`, … `title` is
the name a person gave it — AWS's `Name` tag, the resource's name — else its
id; `metadata.id` is always the provider's id; a VPC or network is a
`network` reference.

## 5. Where results are kept, and when they are made

`extracted_records` (`ExtractedRecordRow`): **one row per `source_records`
row** — `status` (`extracted` or `failed`), the strategy and its version,
the `checksum` extracted from, the ExtractedRecord as JSON (`result`) or the
`failure_code` and `message`. A result exactly when extracted, a failure code
exactly when not: the database checks it.

The job, `leka.ingestion.extraction.job.run_extraction` (key
`extract:<source_id>`, one at a time per source), is **queued at the end of
a pass** that left something to extract — succeeded or not: what a failed
pass stored is worth extracting. It:

1. forgets what was extracted from records marked deleted;
2. reads, **in id order**, the live records that need it: no row yet, a
   checksum that moved, or a strategy version that is not the current one
   (a capability that gains a strategy is extracted then; one that loses it
   is extracted again, as `unsupported`);
3. reads each batch once, finds each record's line by its identity **and**
   its checksum, extracts it, and saves the rows batch by batch.

| | |
|---|---|
| **Incremental, idempotent** | A record extracted from the index's checksum by the current version is not read again: a second run reads nothing |
| **Beside a pass** | A record changed since is found with its old checksum, or not at all: its row does not match the index, and the next run extracts it again |
| **Beside a purge** | A batch rewritten since is not found: its records are passed over (`passed_over`), and read from their new batch at the next run |
| **Isolated failures** | A failure is a row; the batch, the run and the next records go on |

`GET /ingestion/sources/{id}/extraction` (`source:read`): how many records
were extracted and failed — `unsupported`, `malformed` — per strategy, when
last, and the 20 latest failures with their record's vendor id. A vendor
changing a payload's shape shows here as one strategy failing at once.

## Not yet

- **Retention of extracted text**: it follows its record, not the raw
  payload — decided in LEKA-360 ([processing.md](processing.md#6-lifecycle-policies)).
- **A screen**: the route is there; the Sources screen does not show it yet.
- **Code itself** (files, READMEs): no connector reads repository contents
  yet.
