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
| named by a record | `person`, `service`, `team` |

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
| service, team | `service:billing-api`, `team:payments` — a slug of the tag's value |

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
| `state` (issues, pull requests) | `open`, `in_progress`, `closed`, `merged` — GitLab `opened` → open, Bitbucket `declined` → closed; **Jira's status category** (`new`, `indeterminate`, `done`) wins over its status name |
| `state` (cloud resources) | `running`, `starting`, `stopping`, `stopped`, `deleting`, `failed` — EC2 `running`, RDS `available`, Azure `Succeeded`, GCE `RUNNING` → running |
| `state_raw` | the vendor's word, always kept |
| `priority`, `priority_raw` | `highest`, `high`, `medium`, `low`, `lowest` — `blocker`/`critical` → highest, `major` → high, `normal` → medium, `minor` → low, `trivial` → lowest |
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
| `part_of` | an item → its repository; a Jira issue → its project; a resource → its service | the container; a `service` tag |
| `child_of` | a Jira issue → its parent | the extraction's `parent` |
| `authored_by`, `committed_by`, `assigned_to`, `reviewed_by`, `reported_by`, `created_by`, `led_by` | an item → a person | the extraction's references |
| `resolves`, `mentions`, `implements`, `merges` | an item → an item | parsing's references: "Fixes #41", a link, a branch name, a merge commit |
| `mentions` | an item → a person | `@handle` on a code host |
| `owned_by` | a resource → a team | a `team` / `owner` tag |
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

## Not yet

- **Where results are kept, and when they are made**: after the parsing,
  incremental on the parse and `NORMALISER_VERSION` — the next PR.
- **Writing the graph**: entity resolution (LEKA-357) and leka.knowledge.
- **A Jira link's site**: a link to `acme.atlassian.net/browse/PAY-7` found in
  GitHub comes out as `ticket:PAY-7` — parsing keeps the key, not the site.
