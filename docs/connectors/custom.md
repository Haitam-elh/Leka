# Custom sources — a system LEKA has no connector for

A company's own tools — an in-house ticketing system, an asset inventory, a
vendor LEKA does not know — read through their REST or GraphQL API, or
sending LEKA their changes by webhook, **without a line of LEKA's code**:
the admin declares what to read and what it means, and the
[connector framework](framework.md) does the rest as for any source.
LEKA-350.

| | |
|---|---|
| Kinds | `custom_rest` — **API REST** — `custom_graphql` — **API GraphQL** ([below](#graphql)) — and `custom_webhook` — **Webhook entrant** ([below](#webhooks)) — in the **Custom** category |
| Server | any JSON API over https, on a public address |
| Credentials | `secret` (first, so the stored hint is the secret's), `username` for basic — write-only |
| Config | `base_url` (REST) or `endpoint` (GraphQL), `auth`, `auth_name`, `definition` |
| Capabilities | `records` — every resource's; a record's container is its resource |
| Code | `leka/connectors/custom/` — `common.py` what both share, `rest.py`, `graphql_api.py`, `definition.py` — `leka/ingestion/extraction/custom.py`, and normalisation's `_custom` |

Everything that is not the API's is the framework's, unchanged: the secret
encrypted at rest and never returned, the connection test, the health
checks, the sync and its history, the scope rules, the retention, the
diagnostics.

---

## From the Sources page

What an admin does, start to finish (LEKA-426) — no LEKA code, no ticket to
LEKA's team:

1. **Sources → Connecteur sur mesure** (or, in **Ajouter une source**, the
   card at the bottom of the catalogue: *Votre outil n'est pas dans la
   liste ?*). The native catalogue lists LEKA's connectors only; the custom
   ones have this way in.
2. **The method**: *API REST*, *API GraphQL* or *Webhook entrant*, each
   with what it needs — and, beneath, [what none of them can do
   today](#what-is-not-supported), so a tool that needs one of those is
   known before anything is typed.
3. **The connection**: a name, the address, how the secret is sent, the
   secret, the definition. The form shows only what the choices make
   useful — a header's name only for a key sent in one, a user only for
   Basic, no secret without authentication, no signature header for
   Standard Webhooks — and sends nothing a choice made pointless.
   **Partir d'un exemple** fills an empty definition with one that works —
   this page's examples — to edit rather than to write. Saving creates the
   source in draft; a definition the API refuses is shown on its field,
   with where it is wrong.
4. **The test**, with **what the mapping read**: for each resource, how
   many records its first page held and, field by field — title, state,
   author, each metadata — the value read in its first record, and what
   the mapping names that it lacks. Shown there and then, **stored
   nowhere** (not with the source, not in its history): it is the
   system's own data. A failure says why, as every source's test does; what
   LEKA cannot do says **Pas pris en charge aujourd'hui**, not "failed". A
   webhook reads nothing to test: its test gives the address to copy into
   the tool.
5. **Activate** — or later, from the source's page.

Then it is a source like the others: in the list — its *Type* reads **Sur
mesure**, where a native reads its category, and its page and panel say
so beside its status — with its health, its sync state and history, its
last error and what to do about it, its scope and mapping (the source's
*Périmètre et mapping*, LEKA-351), and for a webhook its **Réception**.
It is disabled, activated again, changed (**Modifier**) or deleted as any
source; one whose secret was refused, or in error, offers **Reconnecter**:
the same form, a new secret, the test, the activation.

**No secret in what every member reads.** The configuration is shown to
every member of the workspace; the secret field is write-only, encrypted,
never returned. So when saved, an address with a user or a password in it
(`https://ops:…@host`), and a parameter or a variable named as a
credential (`api_key`, `token`, `access_token`, `client_secret`,
`password`, `signature`…) are refused, saying where the secret goes:
authentication *Clé dans l'URL* or *Clé dans un en-tête*, with that name.
Pagination's own tokens (`pageToken`, `next_token`) are not credentials.

### What is not supported

Said as such — `UNSUPPORTED`, **Pas pris en charge aujourd'hui** — by the
method step before anything is typed, and by the test when it meets one:

| What the system asks | What the test says |
|---|---|
| A person's sign-in: OAuth, SSO, SAML | a redirect to a sign-in page names its host; a web page answered instead of the API says to check the address, and that a sign-in page is not supported |
| An answer other than JSON: XML, SOAP, CSV, YAML, a file | the format it answered in |
| Windows (Kerberos, NTLM) or Digest authentication | the challenge it sent |
| A certificate that is not public — self-signed, an internal authority — or a client certificate (mutual TLS) | which of the two |
| An address that is not public, or plain http | refused when saved, or when connecting ([framework.md](framework.md)) |
| Signed requests (AWS SigV4, per-request HMAC), writing to the tool | — LEKA sends a secret as is, and only reads |

The remediation says what to try instead — an API token, where the system
offers one — and where to ask for it: support@leka-core.com.

---

## Configuring one

**Sources → Connecteur sur mesure → API REST**, then:

| Field | |
|---|---|
| `base_url` | The API's address, https and public: `https://helpdesk.acme.com/api/v2`. Each resource's path is added to it |
| `auth` | How the secret is sent: `none`; `bearer` — `Authorization: Bearer <secret>`; `header` — a header of its own, named in `auth_name` (`X-API-Key`); `query` — a query parameter, named in `auth_name` (`api_key`); `basic` — `username` and the secret as password |
| `auth_name` | For `header` and `query` only. `Authorization`, `Host`, `Cookie` and the transport's own headers are refused |
| `definition` | What to read and what it means, as JSON (below) |
| `secret` | The token, the API key, or the password. Empty for `none` |

Then **Test**: LEKA reads the first page of each resource and tries the
mapping on its first record — and shows what it read (above). The test
fails, naming the resource and the path, when that record has no id or no
title where the mapping says; a mapped field it lacks is a warning. The
scope then offers the resources: keep them all, or some.

---

## The definition

```json
{
  "version": 1,
  "resources": [
    {
      "name": "tickets",
      "entity": "issue",
      "path": "/tickets",
      "params": {"status": "open"},
      "items": "data",
      "pagination": {"type": "cursor", "next": "meta.next_cursor", "param": "cursor",
                     "size_param": "limit", "size": 100},
      "mapping": {
        "id": "id",
        "title": "subject",
        "url": "html_url",
        "state": "status",
        "created_at": "created_at",
        "updated_at": "updated_at",
        "description": "description",
        "author": "requester.email",
        "metadata": {"priority": "priority", "tags": "tags"}
      }
    }
  ]
}
```

At most 20 resources. Anything else in the document — a key LEKA does not
know — is refused, so a typo is found when saved, not at the first sync.

### A resource

| Key | | |
|---|---|---|
| `name` | required | `tickets` — lower case, digits, `_`. What LEKA shows, what the scope keeps or leaves |
| `entity` | | What its records are in LEKA's model: `issue`, `incident`, `service`, `application`, `project`, `document`, `infra_resource`, `database`, `data_object`, `person`, `team`. Without it, they are extracted and stay out of the model |
| `path` | required | From `base_url`: `/tickets`. No scheme, no host, no query, no `..` |
| `params` | | The query, as a map: `{"status": "open"}`. Not secret — the secret goes in the credentials |
| `items` | | Where the records are in a page: `data`, `result.items`. Absent: the page is the list |
| `pagination` | | Below. Absent: one page |
| `mapping` | required | Below |

### Pagination

| `type` | How the next page is found | Needs |
|---|---|---|
| `none` | there is none | |
| `link` | the `Link` header's `rel="next"` | |
| `next_url` | a field of the page holds the next page's URL | `next`: that field |
| `cursor` | a field holds a token, sent back as a parameter; an empty token, or the same one again, ends it | `next`, `param` |
| `page` | a page number from `start` (1), until a page comes back short — or empty, without `size_param` | `param` |
| `offset` | an offset from `start` (0), the same way | `param` |

`size_param` and `size` (1 to 1 000, 100 by default): the page size, when
the API takes one. A next page — a link, a URL — on another host than
`base_url`'s is refused: the secret goes nowhere else.

### The mapping

A path is a dotted path into a record: `requester.email`, `labels.0.name`
— a number indexes a list. What is at the path is read as is: the mapping
never runs anything.

| Key | | Becomes |
|---|---|---|
| `id` | required | the record's id — text or a number. A record without one is not stored: nothing tells it apart (a warning in the logs, the count, not the values) |
| `title` | required | its name |
| `url` | | where a person opens it |
| `state` | | its state, lower-cased — then on LEKA's scale for an `issue` or an `incident` |
| `created_at`, `updated_at` | | ISO 8601 — without a zone, read as UTC — or seconds, or milliseconds, since the epoch |
| `description` | | its text |
| `author` | | a person — by address when the value is one, by name else |
| `metadata` | | `{"name": "path"}`, at most 30: text, numbers, yes/no, lists of them. `priority` is on LEKA's scale for an `issue` or an `incident`. An object is left out: point inside it |

Each record is stored as `{"resource", "entity", "fields", "record"}`: what
the mapping read, and the record itself, untouched. Changing the mapping
changes `fields` — and so, at the next pass, what is extracted.

---

## What LEKA does with it

- **Reads only**: `GET`, and nothing else — `Accept: application/json`, the
  secret as chosen. To `base_url`'s host only, public and over https,
  checked when saved and when connecting ([framework.md](framework.md)).
- **Reads whole each pass**: an API's own "changed since" is too various to
  trust from a declaration. The sync writes only what changed, and marks
  gone what is no longer listed.
- **Bounded**: 2 000 pages a resource, 50 000 records a pass, 20 MB a page.
  Beyond, the pass fails and says so (`CONFIG_INVALID`) — a listing read
  whole and cut would mark the rest gone. Restrict it with `params`, or the
  scope.
- **Spares the quota**: an answer that says the quota is nearly spent
  (`x-ratelimit-*`, `ratelimit-*`) pauses the read until it resets, as for
  every connector.
- **Extracts** (`extraction/custom.py`): the mapped fields, into the
  extraction contract ([extraction.md](../extraction.md)); the resource and
  the entity as signals.
- **Normalises** a resource that declares an `entity` into that entity
  ([normalisation.md](../normalisation.md)): keyed by the source —
  `custom-<source id>:issue:tickets:101`, since nothing tells two unknown
  systems' ids apart — except a `service` or an `application`, keyed by its
  name, so it meets the same one from PagerDuty, Datadog or a tag; its
  author related by `authored_by`. The source's own mapping of states and
  priorities ([scope-and-mapping.md](scope-and-mapping.md)) applies.
- **Reads a catalogue** — a CMDB, a Backstage catalogue behind its API —
  from a `service` or an `application` resource's `metadata`, by these
  names (LEKA-362): `team` / `owner` → its teams; `application` / `system` /
  `product` → the application a service is part of; `services` → an
  application's services; `depends_on` / `dependencies` → what it depends
  on; `criticality` / `tier` → how critical, on LEKA's scale; `lifecycle` /
  `stage` → where in its life; `environments` / `environment` → where it
  runs. A list, or words between commas: `"prod, staging"`.
- **Reads a CMDB's servers and databases** — an `infra_resource` or a
  `database` resource (LEKA-363). One that gives the **provider's own id**
  — an ARN, an Azure ARM id, a Google full resource name — in `resource_id`
  / `arn` / `cloud_id` / `provider_id`, or as the record's id, is **keyed by
  it**, as the AWS, Azure or Google Cloud connector keys it: the two are one
  entity, every source kept, what they disagree on kept with who said it.
  One that does not — a server of its own — is keyed by the source. From
  its `metadata`: `resource_kind` / `kind` / `type` → what kind (`server`,
  `vm` → instance; `db` → database; `lb` → load balancer…); `team` /
  `owner` → its team; `service` / `services` → the service it is part of;
  `application` → its application; `criticality` / `tier`; `environments` /
  `environment`; `depends_on` / `dependencies` → what it depends on: a
  provider id, or the id of another record of the same resource.
- **Reads a data catalogue's tables** — a `data_object` resource
  (LEKA-364). One that says **where it is** — `engine` (`postgres`, `mysql`,
  `sqlserver`…), `host`, `port`, `database`, `schema`, and `table` or its
  title — is **keyed by it**, as the database source reading that table
  keys it: one entity, every source kept. One that does not is the
  catalogue's own. From its `metadata`: `team` / `owner` → its team;
  `service`; `application`; `classification` / `sensitivity` → on LEKA's
  scale (`restricted`, `confidential`, `internal`, `public`, in English or
  French); `data_categories`; `reads_from` / `upstream` → the tables it is
  made from, `schema.table`.
- **Reads an HR system's people and teams** — a `person` or a `team`
  resource (LEKA-365). A person is keyed by their address (`email` /
  `mail`), so they meet the one GitHub, PagerDuty or a directory knows;
  without one, by the system's own id. From its `metadata`: `job_title` /
  `position`; `department` → a team of its own kind they are a member of;
  `team` / `teams` → their teams; `manager` / `reports_to` → who they report
  to, by address or id. A team is keyed by its name: `parent` → the team
  it is part of; `members`; `lead` / `leads` / `managers` → who leads it.
- **Keeps** its payloads 90 days, as the other structured sources'.

## GraphQL

**Sources → Connecteur sur mesure → API GraphQL**: the `endpoint` (`https://api.acme.com/graphql`,
no query), the same `auth`, and a definition whose resources are queries.
Everything above holds — the mapping, `entity`, `items`, the bounds, the
scope, extraction, normalisation — except how a page is asked for:

```json
{
  "resources": [
    {
      "name": "issues",
      "entity": "issue",
      "query": "query Issues($first: Int!, $after: String) { issues(first: $first, after: $after) { nodes { id title url updatedAt state { name } } pageInfo { endCursor hasNextPage } } }",
      "variables": {"project": "PLAT"},
      "items": "data.issues.nodes",
      "pagination": {"type": "cursor", "next": "data.issues.pageInfo.endCursor",
                     "has_next": "data.issues.pageInfo.hasNextPage",
                     "variable": "after", "size_variable": "first", "size": 100},
      "mapping": {"id": "id", "title": "title", "url": "url", "state": "state.name",
                  "updated_at": "updatedAt"}
    }
  ]
}
```

| Key | | |
|---|---|---|
| `query` | required | The document, 20 000 characters at most. **A `query` only**: a `mutation` or a `subscription` — even in a comment — is refused when the definition is saved |
| `variables` | | Its variables, JSON values: `{"project": "PLAT"}` |
| `items` | required | Where the records are in the answer, from its root: `data.issues.nodes` |
| `pagination` | | `none`, or `cursor`: the end cursor's path (`next`), sent back as the variable `variable`; `has_next`, the path that says there is more, when the API gives one — else a cursor empty, or given again, ends the listing. `size_variable` and `size`: the page size, as the query takes it (`first`) |

Each query is POSTed to the endpoint's path — the one POST LEKA sends, and
only there — as `{"query", "variables"}`, JSON in and out. A GraphQL API
refuses in two ways, both read: an HTTP status, as REST's; or a 200 whose
body carries `errors`, read by their `extensions.code` —
`UNAUTHENTICATED` is `AUTH_INVALID`, `FORBIDDEN` `PERMISSION_DENIED`,
`GRAPHQL_VALIDATION_FAILED` and `BAD_USER_INPUT` `CONFIG_INVALID` (the
query or its variables to fix), `RATE_LIMITED` `RATE_LIMITED`, anything
else `PROVIDER_ERROR` — the server's words in the detail, the secret
cleaned out. `errors` beside partial `data` fail the call all the same: a
page read in part would mark the rest gone.

## Webhooks

**Sources → Connecteur sur mesure → Webhook entrant**. The other way round: LEKA reads
nothing, the system SENDS each change, as it happens, to the source's own
address — shown on the source's page, to copy into the system's settings:

    POST https://api.leka-core.com/api/v1/webhooks/sources/<source id>

| Field | |
|---|---|
| `signature` | How the system signs what it sends, with the secret: `hmac_sha256` (the default), `standard_webhooks`, `token` — below |
| `signature_header` | For `hmac_sha256` and `token`: the header that carries it — `X-Hub-Signature-256` for GitHub. Empty: `X-Leka-Signature`, or `X-Leka-Token` |
| `definition` | What a delivery may be, as JSON (below) |
| `secret` | The same on both sides, 16 characters at least — for `standard_webhooks`, the `whsec_…` the system gives. `openssl rand -hex 32` makes one |

**Test** calls nothing — there is nothing to call: it checks the secret's
form and lists the resources the definition recognises. Then **Activate**:
until then, deliveries are refused (409).

### The definition

```json
{
  "resources": [
    {
      "name": "tickets",
      "entity": "issue",
      "match": {"path": "event", "equals": ["ticket.created", "ticket.updated", "ticket.deleted"]},
      "deleted": {"path": "event", "equals": "ticket.deleted"},
      "items": "ticket",
      "mapping": {"id": "id", "title": "subject", "url": "html_url", "state": "status",
                  "updated_at": "updated_at", "author": "requester.email",
                  "metadata": {"priority": "priority"}}
    },
    {
      "name": "assets",
      "entity": "service",
      "match": {"path": "type", "equals": "asset.batch"},
      "items": "assets",
      "mapping": {"id": "serial", "title": "model"}
    }
  ]
}
```

`name`, `entity`, `items` and `mapping` are the REST definition's
([above](#the-definition)), read in the delivery rather than a page. Two
keys are the webhook's:

| Key | |
|---|---|
| `match` | Which deliveries are this resource's: the value at `path` is `equals` — or one of them, a list. Like with like: `true` is not `1`, nor `"true"`. The **first** resource whose `match` a delivery meets is its resource; one without `match` takes every delivery, so it comes last, and alone. A delivery no resource matches is **ignored** — acknowledged (202), logged, not stored: systems send events nobody asked LEKA to keep |
| `deleted` | The condition that says the delivery's records were **deleted**: they are marked gone — as a sweep marks them, and purged the same way — rather than stored. A deletion needs an id, not a title |

`items` absent: the delivery is the record — or the list of them.

### Signatures

| `signature` | What is checked | Systems |
|---|---|---|
| `hmac_sha256` | HMAC-SHA256 of the **body as sent**, keyed with the secret, in the header: hex — after `sha256=` or not — or base64 | GitHub (`X-Hub-Signature-256`), Shopify (`X-Shopify-Hmac-Sha256`), most in-house tools |
| `standard_webhooks` | [Standard Webhooks](https://www.standardwebhooks.com): `webhook-id`, `webhook-timestamp`, `webhook-signature` — `v1,<base64>` of `{id}.{timestamp}.{body}`, keyed with the `whsec_` secret's bytes; one of several matching is enough, while the system rotates its secret. **Signed more than five minutes from now: refused** — a replay | Svix and the systems that send through it |
| `token` | The secret itself, in the header | GitLab (`X-Gitlab-Token`) |

Compared in constant time. The secret is in no answer and no log. With
`hmac_sha256` and `token`, a delivery captured on the way can be sent again
— the signature carries no time; `standard_webhooks` is the one that
refuses a replay.

### What the address answers

A delivery is read at the door as the pass will read it, so what could not
be stored is refused while the sender still listens, with the reason:

| | Answer | Written |
|---|---|---|
| no webhook source at this address | **404** | nothing |
| not signed, or signed otherwise; `standard_webhooks` signed too long ago | **401** | nothing — a line in the logs (`webhook_refused`), not a row: the address is public |
| the source not switched on | **409** | nothing |
| more than 1 200 a minute to this source, or 1 000 deliveries — 50 MB — waiting | **429**, `Retry-After` | nothing: the sender retries |
| more than 1 MB | **413** | nothing |
| not JSON; `items` not a record nor a list; more than 1 000 records | **400** | the delivery, `rejected`, with why — not its body |
| a record without an id, or without a title | **422** — `record 3: no id at « id »`; the whole delivery is refused | the same |
| none of the resources is it | **202** `ignored` | the delivery, `ignored` |
| the rest | **202** `pending` — kept, not yet stored | the delivery, **with its body** |

The API's own limit — 300 requests a minute per sending address — holds
too.

### Kept, then stored

The address answers in milliseconds, whatever the pipeline is doing: the
delivery is kept (`webhook_deliveries`), and a pass is queued — the
source's key, one pass at a time, as for every source. The pass stores
what the deliveries hold **in the order they came** — an update then a
deletion: gone; a deletion then a creation: back — through the same index
as a record read: a delivery sent twice is written once, extraction and
normalisation follow, nothing of their own. It lets each body go as it
stores it. **Never a sweep**: what was not sent was not deleted. A delivery
that came while a pass was ending waits for the next one — the next
delivery's, or the schedule's, within the hour.

### What the admin sees

The source's page, **Réception**: the address, how it signs, and the latest
deliveries — received, waiting, stored, ignored, refused and why. Over the
API, `GET /ingestion/sources/{id}/deliveries`, never a body. The passes
deliveries started are in its history, *Une livraison*. Both are kept 30
days; a pending delivery, until it is stored
([data-lifecycle.md](../data-lifecycle.md)).

## Errors

| What | Diagnostic |
|---|---|
| The secret refused (401) | `AUTH_INVALID` |
| A reading refused (403) | `PERMISSION_DENIED`, naming the path |
| A path unknown (404) | `NOT_FOUND`, naming the path |
| The quota spent (429), or nearly | `RATE_LIMITED`, with when to come back |
| An answer that is not JSON; `items` that is not a list; the first record without an id or a title; a secret or a user missing; too many pages or records | `CONFIG_INVALID`, naming the resource |
| A next page on another host; the API's own failure (5xx) | `PROVIDER_ERROR` |
| Too slow (10 s a call) | `TIMEOUT` |
| An address that is not public | `CONFIG_INVALID` |

The secret is never in a diagnostic — not even where the API echoes it
back, nor in a path, whose query a diagnostic leaves out.

## Limits

- JSON over https only: no XML, no SOAP, no plain http — [said as
  such](#what-is-not-supported) when met.
- A secret that is sent as is: no OAuth dance, no signed requests.
- Every pass reads whole: an API of millions of records is to be narrowed
  with `params`.
- The mapping reads values, it does not compute: no concatenation, no
  conversion beyond dates.
- A webhook delivery is one kind of event: `match` and `deleted` are read on
  the delivery, not on each record of a list.
- A webhook's secret is the same for the source's whole life, until rotated
  — as every source's credentials: rotating sends it back to draft.
