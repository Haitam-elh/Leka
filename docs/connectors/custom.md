# Custom sources — a system LEKA has no connector for

A company's own tools — an in-house ticketing system, an asset inventory, a
vendor LEKA does not know — read through their API, **without a line of
LEKA's code**: the admin declares what to read and what it means, and the
[connector framework](framework.md) does the rest as for any source. LEKA-350.

| | |
|---|---|
| Kind | `custom_rest` — shown as **API REST**, in the **Custom** category |
| Server | any JSON API over https, on a public address |
| Credentials | `secret` (first, so the stored hint is the secret's), `username` for basic — write-only |
| Config | `base_url`, `auth`, `auth_name`, `definition` |
| Capabilities | `records` — every resource's; a record's container is its resource |
| Code | `leka/connectors/custom/` (the connector and its definition), `leka/ingestion/extraction/custom.py`, and normalisation's `_custom` |

Everything that is not the API's is the framework's, unchanged: the secret
encrypted at rest and never returned, the connection test, the health
checks, the sync and its history, the scope rules, the retention, the
diagnostics.

---

## Configuring one

**Sources → Add → API REST**, then:

| Field | |
|---|---|
| `base_url` | The API's address, https and public: `https://helpdesk.acme.com/api/v2`. Each resource's path is added to it |
| `auth` | How the secret is sent: `none`; `bearer` — `Authorization: Bearer <secret>`; `header` — a header of its own, named in `auth_name` (`X-API-Key`); `query` — a query parameter, named in `auth_name` (`api_key`); `basic` — `username` and the secret as password |
| `auth_name` | For `header` and `query` only. `Authorization`, `Host`, `Cookie` and the transport's own headers are refused |
| `definition` | What to read and what it means, as JSON (below) |
| `secret` | The token, the API key, or the password. Empty for `none` |

Then **Test**: LEKA reads the first page of each resource and tries the
mapping on its first record. The test fails, naming the resource and the
path, when that record has no id or no title where the mapping says; a
mapped field it lacks is a warning. The scope then offers the resources:
keep them all, or some.

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
| `entity` | | What its records are in LEKA's model: `issue`, `incident`, `service`, `project`, `document`. Without it, they are extracted and stay out of the model |
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
  systems' ids apart — except a `service`, keyed by its name, so it meets
  the same service from PagerDuty or a tag; its author related by
  `authored_by`. The source's own mapping of states and priorities
  ([scope-and-mapping.md](scope-and-mapping.md)) applies.
- **Keeps** its payloads 90 days, as the other structured sources'.

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

- JSON over https only: no XML, no SOAP, no plain http.
- A secret that is sent as is: no OAuth dance, no signed requests.
- Every pass reads whole: an API of millions of records is to be narrowed
  with `params`.
- The mapping reads values, it does not compute: no concatenation, no
  conversion beyond dates.
- GraphQL APIs and webhooks come next in LEKA-350.
