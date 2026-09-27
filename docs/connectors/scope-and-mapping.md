# Scope and mapping — what a source contributes, and how it is read

What an administrator decides about each source: which of what it can read
LEKA keeps, and how its records map into the company model. LEKA-351.
Contract: `leka/connectors/settings.py`.

Two layers, one after the other:

| | Where | What it decides |
|---|---|---|
| **Connector config** | `sources.config` — per connector: an organisation, a list of repositories, Jira projects, AWS regions, Azure subscriptions, Google Cloud projects | what the connector **reads**. Changing it sends the source back to a test and an activation ([framework.md](framework.md)) |
| **Settings** — scope rules and mapping | `source_settings`, versioned | what LEKA **keeps** of what was read, and how it is **mapped** — the same way for every connector |

---

## 1. Scope rules

`scope.include` and `scope.exclude`: glob patterns (`*`, `?`, `[…]`),
case-insensitive, matched against each record's **scope key** — its
container:

| Connector | Scope key | Example rules |
|---|---|---|
| GitHub, Bitbucket | the repository: `acme/api` — a repository record is its own container | `include: ["acme/*"]`, `exclude: ["acme/legacy-*", "*/sandbox"]` |
| GitLab | the project's path: `acme/platform/api` | `include: ["acme/platform/*"]` |
| Jira | the project key: `PAY` — a project record is its own container | `include: ["PAY", "OPS"]` |
| AWS | the region: `eu-west-3` | `exclude: ["us-*"]` |
| Azure | the subscription id | |
| Google Cloud | the project id: `acme-prod` | `include: ["*-prod"]` |

A record is **kept** unless an exclude rule matches it, and — when there are
include rules — unless none of them does. **Exclude wins.** A record with no
container (S3's global bucket list) is not subject to the rules.

Applied in the **sync**, to every record, before anything is stored: an
excluded record is neither stored nor indexed. The pass reports how many it
left out, per capability (`excluded`).

## 2. Mapping

How the source's records are read into the model — its own words, where
they differ from what LEKA reads by default:

| Field | What it does | Example |
|---|---|---|
| `entity_types` | a capability's records become this entity type | `{"issues": "incident"}` — a GitHub repository of incidents |
| `services` | containers → the service they are, first match wins | `[{"match": "acme/pay*", "service": "billing"}]` |
| `owners` | containers → the team that owns them | `[{"match": "acme/*", "team": "platform"}]` |
| `tag_keys` | this company's tag keys, beside `env`, `service`, `team`… | `{"environment": ["stage"], "owner": ["squad"]}` |
| `states` | a vendor state → LEKA's | `{"QA Review": "in_progress"}` |
| `priorities` | → `highest`, `high`, `medium`, `low`, `lowest` | `{"P0": "highest"}` |
| `environments` | → `production`, `staging`, `development`, `test` | `{"prd": "production"}` |

The mapping is stored, validated and versioned here; normalisation applies
it ([normalisation.md](../normalisation.md)).

## 3. What is refused, what is said

`POST /sources/{id}/settings/check` answers every **finding** without saving;
`PUT` refuses the settings if any is an error (422, each one named in
`details`), saves them with their warnings otherwise.

| Level | When |
|---|---|
| error | a pattern empty, too long or broken (`acme/[api`) |
| error | the same pattern both included and excluded |
| error | an entity type for a capability the source does not read, or not one of LEKA's types |
| error | a state, priority or environment mapped to a value LEKA does not have |
| error | one tag key under two facets; one pattern mapped to two services or teams |
| warning | a rule that matches **nothing the credentials can see** — asked of the vendor, like the scope options: a typo, or a repository not created yet |
| warning | include and exclude rules that leave nothing |
| warning | the credentials' containers could not be listed: the rules were not checked against them |

## 4. Versions and audit

Settings are **never edited**: each change is a new version in
`source_settings` — the scope, the mapping, who made it, when. The current
settings are the highest version; a source never set has the defaults
(version 0). Saving the same settings again makes no version.

Each version also writes a `settings_changed` event on the source (its
version, what changed: `scope`, `mapping`), beside its test, activation and
health events.

## 5. Changing them safely

- **Before activation**: allowed; the first pass reads with them.
- **The scope of an active source changes**: a **full pass** follows —
  published in the same transaction as the version (`source.scope_changed`),
  so it never runs with the old rules. It reads what came in from the start
  (an incremental pass from the old cursor would miss its history) and, not
  seeing what went out, sweeps it: marked deleted, purged from the stored
  batches, and what was processed of it removed
  ([collection.md](../collection.md), [processing.md](../processing.md)).
  The pass's trigger is `settings`.
- **Only the mapping changes**: no pass — nothing to read again.

## 6. The API

| Route | Permission | |
|---|---|---|
| `GET /sources/{id}/settings` | `source:read` | `{version, settings: {scope, mapping}}` |
| `POST /sources/{id}/settings/check` | `source:manage` | `{findings}` — asks the vendor what the credentials can see |
| `PUT /sources/{id}/settings` | `source:manage` | `{version, changed, findings, full_sync_queued}` |
| `GET /sources/{id}/settings/versions` | `source:read` | every version, newest first |
