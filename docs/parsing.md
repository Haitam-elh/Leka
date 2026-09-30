# The parsing contract — from an extracted record to what it means

What parsing reads, what it hands to normalisation, how sure it is, and how
it fails. LEKA-355. What it reads is [extraction.md](extraction.md); what
reads it next is [normalisation](normalisation.md) (LEKA-356).

```
 ExtractedRecord (extracted_records.result)
        │
        ▼
 parse(record)                                   leka/ingestion/parsing
        │  its texts read for references and people, then the rules of its kind
        ▼
 ParsedRecord  — or —  ParseFailure              one per record, never an exception
```

Parsing works on the extraction's **unified** fields: a rule for pull
requests holds for GitHub, GitLab and Bitbucket; a rule for instances holds
for AWS, Azure and Google Cloud.

---

## 1. What comes out

`ParsedRecord` (`leka/ingestion/parsing/contract.py`):

| Field | |
|---|---|
| `provenance` | the extraction's, unchanged — source, capability, vendor id, checksum, batch |
| `extractor`, `extractor_version` | which extraction it was parsed from |
| `parser_version` | which parsing (§ 5) |
| `facts` | what the record means — § 2 |
| `structure` | the shape of its text: `words`, `headings`, `code_blocks`, `code_languages`, `tasks_total`, `tasks_done`, `links` |
| `quality` | `score` from 0 to 1 and the `notes` that lowered it — § 4 |

It is plain JSON and reads back identically.

## 2. Facts — each with its confidence and its evidence

A `Fact` is a `type`, a `value` and/or a `target` (`kind`, `key`, `system`),
a **`confidence`** from 0 to 1, and its **`evidence`**: the `field` it was
read in (`title`, `content.body`, `metadata.labels`, `signals.tags`,
`references.source_branch`…) and an `excerpt` of at most 120 characters.
One fact per (type, target) — or (type, value) — the surest kept.

| `type` | `value` | `target` | Read from | Confidence |
|---|---|---|---|---|
| `references` | `closes` | an issue: `#41`, `acme/api#41`, `PAY-42` | "Fixes / Closes / Resolves …" in text | 0.95 |
| `references` | `mentions` | an issue, pull request, commit | a link to it (GitHub, GitLab, Bitbucket, Jira) | 0.9 |
| `references` | `mentions` | `#41`, `acme/api!12`, `PAY-42` | the bare reference in text | 0.7 |
| `references` | `merges` | a pull request | GitHub's merge commit title | 0.95 |
| `references` | `implements` | a ticket | the branch name: `feature/pay-42-retry` → `PAY-42` | 0.8 |
| `mentions` | | a person, by handle | `@omar-b` in text | 0.8 |
| `links_to` | the host | the URL | any other link | 1.0 |
| `change_type` | `feat`, `fix`, `chore`, … | | a Conventional Commits title | 0.95 |
| `scope` | `payments` | | `fix(payments): …` | 0.9 |
| `breaking` | `true` | | `feat!:` or `BREAKING CHANGE:` | 0.95 |
| `category` | `bug`, `feature`, `task`, `epic`, `incident` | | the vendor's issue type | 0.95 |
| `category` | `bug`, `incident`, `security`, `feature`, `docs`, `maintenance` | | a label | 0.85 |
| `category` | from the change type | | `feat` → feature, `fix` → bug, `docs`, else maintenance | 0.8 |
| `environment` | `production`, `staging`, `development`, `test` | | an `env` / `environment` / `stage` tag | 0.95 (0.8 for a value it does not know) |
| `environment` | same | | a `tier` tag that says an environment: `tier=prod` | 0.9 |
| `environment` | same | | a word of the resource's name: `api-prod-1` | **0.5** — a guess |
| `service` | the tag's value | | a `service` / `app` / `component` tag | 0.9 |
| `application` | the tag's value | | an `application` / `system` / `product` tag — a group of services (LEKA-362) | 0.9 |
| `criticality` | `critical`, `high`, `medium`, `low` | | a `criticality` / `business-criticality` / `service-tier` tag: a tier number — 1 (or 0) the most critical — or a level word | 0.95 (0.8 for a value it does not know) |
| `criticality` | same | | a `tier` tag that says a level: `tier=1`, `tier=T3`, `tier=low` — one that says neither an environment nor a level says nothing | 0.9 |
| `owner` | the tag's value | | a `team` / `owner` / `squad` / `maintainer` tag | 0.9 |
| `exposure` | `public`, `internal` | | `public` flag, a load balancer's scheme | 0.95 |

What is **not** read, deliberately:

- **Code.** Fenced blocks and inline code are skipped: `#1` in a snippet is
  not an issue, `@Override` is not a person.
- **Look-alikes.** `UTF-8`, `SHA-256`, `ISO-8601`, `CVE-…`: not ticket keys.
  `release-2026`, `hotfix-3`: not tickets in a branch. An email is not a
  mention.
- **A bare `#41` outside a code host.** In Jira it means nothing certain.
- **A link's own path.** Read once, as a link — not again as `#12`.

Targets are **as written**: `#41` in a GitHub pull request is GitHub's, of
that repository (the provenance's container). Deciding which entity a
target is, is normalisation's.

## 3. Failures — one record at a time

`ParseFailure`: `code` `malformed`, a `message`, the `provenance` when there
is one.

- There is **no `unsupported`**: every record's text is read, whatever its
  kind; the rules add to it where they know more.
- A stored result that is not an ExtractedRecord (`parse_stored`) fails
  with the fields that are wrong — `not an extracted record: provenance
  (missing)` — never a value.
- A rule that chokes on a record fails that record; its neighbours are
  parsed.

## 4. Quality

1.0, less 0.3 without a title, 0.2 for a pull request, an issue or a project
without a description, 0.2 when a text was cut at 100 000 characters. The
`notes` say which. A commit, a branch or a resource is not expected to be
described.

## 5. Versions

`PARSER_VERSION` (`parsing/engine.py`; 2 since LEKA-362's application and
criticality tags) is raised when what parsing finds
changes: what the old version parsed is parsed again.

## 6. Where results are kept, and when they are made

`parsed_records` (`ParsedRecordRow`): **one row per extracted
`extracted_records` row** — `status` (`parsed` or `failed`), the
ParsedRecord as JSON (`result`) or `failure_code` and `message`, and what it
was parsed from and by: the extraction's `checksum` and `extractor_version`,
and `parser_version`. An extraction that failed has no parse; a record gone
takes its extraction and its parse along (cascade).

The job, `leka.ingestion.parsing.job.run_parsing` (key `parse:<source_id>`,
one at a time per source), is **queued by the extraction job** when it ends
with something to parse, and **by the end of a pass** when only parsing has
something to do (a new `PARSER_VERSION`). It forgets the parse of
extractions that failed since, then parses, in id order, every extraction
never parsed or parsed from another checksum or version. Everything it reads
is in the database. Incremental and idempotent: a second run reads nothing.

```
 pass ──▶ extraction (extract:<id>) ──▶ parsing (parse:<id>)
   └──────────── only parsing to do ──────────▲
```

`GET /ingestion/sources/{id}/parsing` (`source:read`): how many were parsed
and failed, how many facts of each type, the average quality, when last,
and the 20 latest failures with their record's vendor id.

## Not yet

- **Configuration files, code** — no connector reads repository contents yet.
- **Semantic reading** (what a ticket is about, beyond its words): with the
  AI gateway (LEKA-394).
- **A screen**: the route is there; the Sources screen does not show it yet.
