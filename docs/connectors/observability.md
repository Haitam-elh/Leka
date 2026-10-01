# Observability and operations — what LEKA asks for, and what it reads

Datadog, PagerDuty, Grafana, Splunk and Kibana, through
[the connector framework](framework.md). LEKA-348. **LEKA only reads**: every call is a GET, with keys that can only
read. What each source contributes then goes through extraction
([extraction.md](../extraction.md)), parsing and normalisation like any
other.

What observability data is, for LEKA: **alerts** (monitors and their
state), **events** (the stream of what happened: an alert that fired, a
deploy, a change), **incidents**, **metrics** (their definitions, not
their points), **logs** (a chosen few), and the **services** an incident
tool or a service catalog knows — with their team, application, tier,
lifecycle and what they depend on (LEKA-362). Every record keeps the vendor's
own **identifier** — its `external_id` — and its own **timestamp** — its
`updated_at`, and in the payload as the vendor wrote it.

---

## Datadog

| | |
|---|---|
| Endpoint | `https://api.<site>` — the site is the organisation's, one of Datadog's |
| Credentials | `application_key` (first, so the stored hint is its own), `api_key` — both write-only |
| Config | `site`, `logs_query`, `services` |
| Category | `observability` |
| Capabilities | `alerts`, `events`, `incidents`, `metrics`, `logs`, `services` |

### What to create at Datadog

1. **A service account** (Organization Settings → Service Accounts) with
   the **Datadog Read Only Role** — a person's account works too, but a
   service account outlives people.
2. **An application key** for it, **scoped** to exactly what LEKA reads:

   | Permission | For |
   |---|---|
   | `monitors_read` | `alerts` |
   | `events_read` | `events` |
   | `incident_read` | `incidents` |
   | `metrics_read` | `metrics` |
   | `logs_read_data` | `logs` |
   | `apm_service_catalog_read` | `services` — the service catalog — and the services offered as scope |

   A permission left out is a capability left out — the connection test
   says which it could read — never a failure.
3. **An API key** of the organisation (Organization Settings → API Keys).
4. In LEKA, **Sources → Add → Datadog**: the site, the two keys. Test,
   choose the services, activate.

### The site

`site` is the organisation's Datadog site: `datadoghq.com` (US1),
`us3.datadoghq.com`, `us5.datadoghq.com`, `datadoghq.eu`,
`ap1.datadoghq.com`, `ap2.datadoghq.com`, `uk1.datadoghq.com`,
`ddog-gov.com`, `us2.ddog-gov.com`. The form takes it typed, or the address
of the organisation's Datadog pasted (`https://app.datadoghq.eu/…`), and
keeps the site. Anything else is refused when the source is saved: the
keys go to `api.<site>` and nowhere else.

### Scope

- `services` — the services to read, as Datadog names them (`checkout`,
  kept in small letters; `service:checkout` is accepted). Absent, every
  service. Monitors and incidents are kept when one of their services is
  in scope (a monitor's `service:` tag, an incident's *services* field);
  events and logs are asked of Datadog with `service:(a OR b)`; metrics
  with `filter[tags]`. The choices come from
  `GET /sources/{id}/scope/options`: the service catalog, and the
  `service:` tags of the monitors.
- `logs_query` — which logs, in Datadog's log search syntax. By default
  `status:error`: logs are the largest thing Datadog holds, and errors are
  what an investigation starts from.
- Beyond the connector, the source's **scope rules**
  ([scope-and-mapping.md](scope-and-mapping.md)) apply to each record's
  container — its service.

### The connection test

1. `GET /api/v1/validate` — the API key. Refused: `AUTH_INVALID`, naming
   the API key (or the site: a key of another site is refused too).
2. `GET /api/v2/current_user` — whose the application key is: the
   account. Refused: `AUTH_INVALID`, naming the application key.
3. One small read of each capability, at once — a monitor, an hour of
   events, an incident, a metric, a quarter of an hour of logs matching
   `logs_query`, a catalog definition. A refusal leaves that capability out; none readable is a
   pass with a warning listing the permissions to give.

### What is read

| Capability | What (Datadog API) | Incremental | Id, timestamp |
|---|---|---|---|
| `alerts` | every monitor: name, type, query, message, tags, `overall_state`, priority, creator (`GET /api/v1/monitor`) | whole each pass — a monitor deleted leaves at the next pass | monitor id, `modified` |
| `events` | the event stream: title, message, tags, status, service, host, monitor (`GET /api/v2/events`) | from the last pass less 5 minutes; an initial pass reads 30 days; newest first, at most 50 000 a pass | event id, `timestamp` |
| `incidents` | every incident: title, state, severity, services, customer impact, dates, commander and creator (`GET /api/v2/incidents`) | whole each pass | incident id, `modified` |
| `metrics` | metric definitions: name, type, configured tags (`GET /api/v2/metrics`) — not their points | whole each pass, at most 20 000; swept by the weekly full pass | metric name, `modified_at` |
| `logs` | logs matching `logs_query`: message, status, service, host, tags (`GET /api/v2/logs/events`) | from the last pass less 5 minutes; an initial pass reads 1 day; newest first, at most 10 000 a pass | log id, `timestamp` |
| `services` | the service catalog: each definition as its team wrote it — schemas v2 to v2.2 (`dd-service`, `team`, `application`, `tier`, `lifecycle`, `type`, `languages`, links) and v3 (`metadata`, `spec.dependsOn`, `spec.componentOf`) (`GET /api/v2/services/definitions`) | whole each pass | the service's name, in small letters; `last-modified-time` |

The 5-minute margin is Datadog's indexing: an event or a log becomes
searchable a moment after it happened. Read twice is a write, never a
duplicate. When a stream has more than its cap in one pass, the newest are
kept: narrow `logs_query` or the services when that is too few.

Each record's **container** is its service (none when it has no
`service:` tag). Monitors, incidents and logs carry `web_url`, the link to
open them in Datadog. An incident carries its commander and creator,
resolved from Datadog's `included` users.

Not read: metric points (time series), traces and spans, dashboards,
SLOs, synthetics, RUM, security signals.

### Downstream

Every capability has an extraction strategy (`extraction/observability.py`):
a title, a state (`alert`, `ok`, `warn`, `no data`; an incident's
`active`, `stable`, `resolved`; a log's status), dates, the message as
text, and the signals an operations question needs — `service`, `env`,
`team`, `host`, `tags`, an incident's `severity` and `services`. Parsing
reads their text like any other. Normalisation
([normalisation.md](../normalisation.md)) makes Datadog's and PagerDuty's
incidents `incident` entities — state and priority on LEKA's scales, the
commander as a person, the services they affect — and PagerDuty's and the
catalog's services `service` entities, on the same key as Datadog's
`service:` tags: their team, their application, what they depend on, their
tier as a criticality and their lifecycle as a stage. Alerts,
events, metrics, logs and dashboards stay evidence, not entities.

### Retention

Datadog's raw payloads are kept **30 days** — observability is enormous
and stale in days ([data-lifecycle.md](../data-lifecycle.md)). A source may
keep less — its own retention, in its settings
([scope-and-mapping.md § 2 bis](scope-and-mapping.md#2-bis-retention)); a
contract can move the policy without a deploy
(`LEKA_RAW_PAYLOAD_RETENTION_DAYS`).

### Limits

- **Quota**: Datadog's, per organisation and per endpoint, in
  `X-RateLimit-*` — whose `Reset` is in **seconds from now**, not a moment
  since the epoch, which the shared HTTP client now tells apart. A bulk
  read stops before the last tenth of a quota; a 429 is `RATE_LIMITED`
  with the seconds to wait. Health turns `degraded` under a tenth left.
- **Pagination**: monitors by page, incidents by offset, events, logs and
  metrics by cursor. A cursor Datadog repeats ends the pass with
  `PROVIDER_ERROR` rather than loop.
- **Incidents** are an API Datadog calls public beta.

### Diagnostics

| Datadog answers | Diagnostic |
|---|---|
| 401 or 403 at `/api/v1/validate` | `AUTH_INVALID` — the API key, or the site |
| 401 or 403 at `/api/v2/current_user` | `AUTH_INVALID` — the application key |
| 403 elsewhere | `PERMISSION_DENIED`, naming the permission (`incident_read`, …) |
| 404 | `NOT_FOUND` |
| 429 | `RATE_LIMITED`, with `retry_after` |
| 5xx | `PROVIDER_ERROR` |

Both keys are removed from every detail.

## PagerDuty

| | |
|---|---|
| Endpoint | `https://api.pagerduty.com`, or `https://api.eu.pagerduty.com` for an account in PagerDuty's EU region |
| Credentials | `api_key`, a **read-only** REST API key (write-only here), sent as `Token token=…` |
| Config | `region` (`us`, `eu`), `services` |
| Category | `observability` |
| Capabilities | `services`, `incidents` |

### What to create at PagerDuty

An account admin, in **Integrations → API Access Keys → Create New API
Key**: a description (`LEKA`), and **Read-only API Key** ticked. That is
the boundary — the key cannot acknowledge, resolve or change anything.
Then, in LEKA, **Sources → Add → PagerDuty**: the key, and `eu` as region
if the account's address ends in `eu.pagerduty.com`.

### Scope

`services` takes service ids (`PXXXXXX`), typed or pasted as the link to
the service; kept in capitals. Absent, every service. The choices come from
`GET /sources/{id}/scope/options`: every service of the account. The
connection test fails with `NOT_FOUND`, naming them, when the key does not
see a service in scope.

### The connection test

1. `GET /abilities` — the key reads the account. Refused: `AUTH_INVALID`
   (the key, or the region).
2. `GET /services` — every service; those in scope must be there.
3. One page of incidents: `incidents` if PagerDuty answers.

### What is read

| Capability | What (PagerDuty API) | Incremental | Id, timestamp |
|---|---|---|---|
| `services` | each service: name, description, status, teams, escalation policy, last incident (`GET /services`) — and the services it depends on (`GET /service_dependencies/technical_services/{id}`, one call a service, the first 2 000 a pass); each **business service** — what an application is to PagerDuty — with its team, point of contact and the services supporting it (`GET /business_services`, `GET /service_dependencies/business_services/{id}`) | whole each pass | service id, `updated_at` |
| `incidents` | each incident: title, status, urgency, priority, service, assignees, escalation policy, teams, number, link (`GET /incidents`) | every pass reads the incidents **created in the last 90 days** again — PagerDuty lists by creation, not by change | incident id, `updated_at` |

An incident's **container** is its service; the sync reads services
before the incidents about them. A plan or a key that does not show
dependencies or business services (403, 404) is read without them — never
a failure. With `services` in scope, a business service is read when one
of its supporting services is in scope. Incidents older than 90 days stay as they
were last read, until their retention ends. Not read: log entries, notes,
alerts inside an incident, on-call schedules.

Extraction (`extraction/observability.py`): an incident's title, status,
urgency, priority, number, its assignees as people and its service as a
reference; a service's name, status, teams, last incident and the services
it depends on; a business service's name, team, point of contact, the
services supporting it — as an application.

### Retention

Kept **90 days**, like tickets: incidents are small, and what a
post-mortem reads weeks later.

### Limits

- **Quota**: 960 requests a minute per key, in `ratelimit-*` headers
  (their reset in seconds). A bulk read stops before the last tenth; a 429
  is `RATE_LIMITED` with the seconds to wait; health turns `degraded`
  under a tenth left.
- **Pagination**: PagerDuty's offsets, while it says `more`.
- **Errors**: 401 → `AUTH_INVALID`, 403 → `PERMISSION_DENIED`, 404 →
  `NOT_FOUND`, 5xx → `PROVIDER_ERROR`. The key is removed from every
  detail.

## Grafana

| | |
|---|---|
| Endpoint | the Grafana's address — Grafana Cloud (`https://acme.grafana.net`) or one of the customer's own |
| Credentials | `token`, a service account's token (`glsa_…`, write-only), as Bearer |
| Config | `base_url` |
| Category | `observability` |
| Capabilities | `dashboards`, `alerts` (alert rules and their state), `events` (annotations) |

### What to create at Grafana

In Grafana, **Administration → Users and access → Service accounts → Add
service account**, with the **Viewer** role — nothing more — then **Add
service account token**, with an expiry date. What a Viewer cannot see,
LEKA cannot. In LEKA, **Sources → Add → Grafana**: the address and the
token. Test, activate.

### The address

`base_url` is typed by the admin, and LEKA's server calls it. So it must
be **https**, and lead to a **public address**: checked when the source is
saved (plain `http`, `127.0.0.1`, `10.x`, `169.254.169.254`… are refused
at once) and again **when connecting** — the name is resolved, every
address must be public, and the connection goes to the address checked
(`leka/connectors/network.py`, every connector's transport). A Grafana only
reachable inside the customer's network cannot be read from LEKA's
server.

### Scope

Grafana has no scope to choose in the form: the service account's role is
the boundary. The source's **scope rules**
([scope-and-mapping.md](scope-and-mapping.md)) apply to each record's
container — a dashboard's or an alert rule's folder, an annotation's
dashboard.

### The connection test

1. `GET /api/org` — the organisation's name is the account.
2. One small read of each capability, at once — a dashboard, the alert
   rules, an annotation. A refusal leaves that capability out; none
   readable is a pass with a warning naming the role to give.

### What is read

| Capability | What (Grafana HTTP API) | Incremental | Id, timestamp |
|---|---|---|---|
| `dashboards` | each dashboard: title, tags, folder, link (`GET /api/search?type=dash-db`) | whole each pass | dashboard uid, — |
| `alerts` | each Grafana-managed alert rule with its **state** (`firing`, `pending`, `inactive`), health, query, labels, summary, group, folder (`GET /api/prometheus/grafana/api/v1/rules`) | whole each pass | rule uid (else folder/group/name), last evaluation |
| `events` | annotations — deploys, alert state changes, notes: text, tags, dashboard, panel, time and end (`GET /api/annotations`) | from the last pass less 5 minutes; an initial pass reads 30 days; newest first, at most 10 000 a pass | annotation id, `updated` (else `time`) |

Grafana's times in annotations are milliseconds since the epoch; they are
kept so in the payload and read as dates. Recording rules are not alerts,
and are left out. Not read: panels' queries and their data, data
sources, alert notification history beyond annotations, OnCall and
Incident (Grafana IRM).

Extraction (`extraction/observability.py`): a dashboard's title, folder,
tags; an alert rule's name, state, health, query, summary, and its labels
as tags, `service`, `env`, `team`, `severity`; an annotation's first line,
text, time and dashboard.

### Retention

Kept **30 days**, like Datadog.

### Limits

- **Quota**: Grafana Cloud limits by organisation; a 429 is
  `RATE_LIMITED` with `Retry-After`. Grafana sends no quota headers, so
  health is `healthy` or failed.
- **Errors**: 401 → `AUTH_INVALID`, 403 → `PERMISSION_DENIED` naming the
  Viewer role, 404 → `NOT_FOUND` (often: the address is not a Grafana),
  an address refused by the transport → `CONFIG_INVALID`. The token is
  removed from every detail.

## Splunk

| | |
|---|---|
| Endpoint | Splunk's REST API, on its **management port** — Splunk Cloud Platform (`https://acme.splunkcloud.com:8089`) or a Splunk Enterprise of the customer's own |
| Credentials | `token`, an authentication token (write-only), as Bearer |
| Config | `base_url` |
| Category | `observability` |
| Capabilities | `alerts` (the saved searches that alert), `events` (the alerts that fired), `dashboards` |

### What to create at Splunk

1. **A role** that sees the apps whose alerts and dashboards LEKA should
   read — Splunk's `user` role, or a copy of it limited to those apps.
   Nothing that writes.
2. **A user** with that role, then, as an admin, **Settings → Tokens →
   New Token** for that user, with an expiry date. Token authentication
   must be on (Settings → Tokens → Token Settings).
3. **Splunk Cloud Platform**: the REST API is reached only from allowed
   addresses — add LEKA's server's to the allow list (Settings → Server
   settings → IP allow list, *Search head API access*).
4. In LEKA, **Sources → Add → Splunk**: the address with its port, and the
   token. Test, activate.

### The address

As every address an admin types: **https** and **public**, checked when
saved and again when connecting (`leka/connectors/network.py`). The
certificate must be one a known authority signed: Splunk Enterprise ships
its management port with a self-signed one, which LEKA refuses — install a
real one, or put the port behind a proxy that has one.

### Scope

The token's role is the boundary. The source's **scope rules**
([scope-and-mapping.md](scope-and-mapping.md)) apply to each record's
container: its **app**.

### The connection test

1. `GET /services/authentication/current-context` — whose token it is: the
   user's name is the account, its roles are kept.
2. One small read of each capability, at once. A refusal leaves that
   capability out; none readable is a pass with a warning naming what the
   role must see.

### What is read

| Capability | What (Splunk REST API, `output_mode=json`) | Incremental | Id, timestamp |
|---|---|---|---|
| `alerts` | each saved search that **alerts** — scheduled, with a triggering condition or a tracked alert, not a report: its search, schedule, condition, severity, actions, app, owner, author (`GET /servicesNS/-/-/saved/searches`) | whole each pass | its place, `owner/app/saved/searches/name`; `updated` |
| `events` | each alert that **fired**: its search, trigger time, severity, search id, app (`GET /services/alerts/fired_alerts/-`) — what Splunk keeps, each alert's own expiry (24 hours by default) | every pass reads what Splunk keeps, at most 10 000 | search id; trigger time |
| `dashboards` | each dashboard — label, description, app, author; not its source (`GET /servicesNS/-/-/data/ui/views`, its fields chosen) | whole each pass | its place; `updated` |

Pages of 100, by Splunk's `count` and `offset`, until its `paging.total`.
A view that is not a dashboard (the search page itself) is left out.
Not read: search results, indexes' events, reports, lookups, users.

Extraction (`extraction/observability.py`): an alert's name, whether it is
on, its search, schedule, condition, severity in words (`info` to
`fatal`), actions, app, author; a fired alert's search, time, severity; a
dashboard's label, description, app. Alerts, fired alerts and dashboards
are evidence, not entities of the company model.

### Retention

Kept **30 days**, like Datadog and Grafana.

### Limits

- **Errors**: 401 → `AUTH_INVALID`, 403 → `PERMISSION_DENIED` naming the
  role, 404 → `NOT_FOUND` (often: not the management port), 429 →
  `RATE_LIMITED`. The token is removed from every detail.

## Kibana

| | |
|---|---|
| Endpoint | the Kibana's address — Elastic Cloud (`https://acme.kb.europe-west1.gcp.cloud.es.io`) or one of the customer's own |
| Credentials | `api_key`, an Elastic API key in its **encoded** form (write-only), sent as `ApiKey` |
| Config | `base_url` |
| Category | `observability` |
| Capabilities | `alerts` (alerting rules), `incidents` (cases), `dashboards` |

### What to create at Kibana

**Stack Management → Security → API keys → Create API key**, with an
expiry date and, under *Control security privileges*, the Kibana features
**read** in the spaces to read: *Alerts and Insights → Rules*, *Cases*
(in the solution that holds them: Management, Observability, Security),
*Analytics → Dashboard*. Copy the **Encoded** value. In LEKA, **Sources →
Add → Kibana**: the address and the key. Test, activate.

### Scope

Every space the key sees is read (`GET /api/spaces/space`; a Kibana with
no spaces is its default space). The source's **scope rules** apply to
each record's container: its **space**.

### The connection test

1. `GET /api/status` — the Kibana's name is the account, its version kept.
2. One small read of each capability in the default space. A refusal
   leaves that capability out; none readable is a pass with a warning.

### What is read

| Capability | What (Kibana API) | Incremental | Id, timestamp |
|---|---|---|---|
| `alerts` | each alerting rule: name, type, tags, enabled, interval, how its last run went, author (`GET /api/alerting/rules/_find`) | whole each pass | `space/rule id`; `updated_at` |
| `incidents` | each **case**: title, description, status (`open`, `in-progress`, `closed`), severity, tags, the solution it belongs to, who opened it, comments count, dates (`GET /api/cases/_find`, newest first) | whole each pass | `space/case id`; `updated_at` (else `created_at`) |
| `dashboards` | each dashboard's title and description (`GET /api/saved_objects/_find?type=dashboard`) | whole each pass | `space/dashboard id`; `updated_at` |

Every record carries its space and the link to open it — a case in its
solution's app. Requests carry `elastic-api-version: 2023-10-31`, which
serverless projects ask for. Not read: the alerts a rule raised (they
live in Elasticsearch), connectors, data views, documents.

Extraction (`extraction/observability.py`): a rule's name, state, type,
interval, its tags with `service`, `env`, `team`; a case's title, status,
severity, description, author, its `service:` tags as the services it
affects. Normalisation ([normalisation.md](../normalisation.md)) makes a
case an **incident** — `incident:kibana:<id>`, its status and severity on
LEKA's scales, its author a person, the services it affects — as
PagerDuty's and Datadog's.

### Retention

Kept **90 days**, like PagerDuty: its cases are incidents.

### Limits

- **Errors**: 401 → `AUTH_INVALID`, 403 → `PERMISSION_DENIED` naming the
  features to grant, 404 → `NOT_FOUND`, 429 → `RATE_LIMITED`. The key is
  removed from every detail.

