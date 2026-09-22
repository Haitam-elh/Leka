# Working with the LEKA API

Everything a client needs that the OpenAPI schema does not say. The schema
lists the routes; this explains how they behave.

Base path is `/api/v1`. Interactive documentation is served at
`/api/v1/docs` in every environment except production, where it is not
served at all — see ADR 011.

---

## Where the workspace comes from

Never from the client. Not a header, not a body field, not a path segment.
The server reads it from the session.

The single exception is the route that switches workspace, which is a
request to move rather than a statement about where you already are. Any
other route accepting a workspace identifier is a bug, and a test in
`tests/test_tenant_isolation.py` fails if one appears.

---

## Errors

Every failure returns the same shape, whatever caused it — a malformed body,
a rule that said no, a path matching nothing, or a bug on our side.

```json
{
  "error": {
    "code": "validation_failed",
    "message": "The request is not valid.",
    "details": [
      { "field": "email", "message": "value is not a valid email address" }
    ],
    "request_id": "01M32MTTPZN073Q1RT7DNHNBB4"
  }
}
```

`code` is what a client should branch on. `message` is one sentence fit to
show a person. `details` appears only when particular fields were at fault.
`request_id` matches the `X-Request-ID` response header and our log lines.

The body is wrapped in `error` deliberately. A single resource is returned
unwrapped, so a flat error body would collide the day some resource has a
field called `code`. Detect a failure with `"error" in body` rather than by
reading the status.

### Codes

The full list lives in `leka/core/errors.py` and is published in the schema
as `ErrorCode`. Generate your types from the schema rather than copying the
list: `npm run gen:api` does exactly that for the frontend, and CI fails if
the generated file drifts.

Codes group into three families. Platform codes cover the ordinary
outcomes — validation, permission, absence, conflict, throttling, and our
own failures. Request-pattern codes cover a cursor, a sort field or a filter
the API would not accept. Authentication codes were introduced with
LEKA-330 and keep the exact spelling they shipped with, because the frontend
already switches on them.

### What a 500 says

That something failed, and the request id. Nothing else — no exception type,
no query, no table name, no stack. Those go to our logs, where the same
request id ties them to your response.

This is the same in every environment. A rule with an exception is a rule
someone eventually misconfigures, and one mislabelled environment would be
enough.

---

## The request id

Every response carries `X-Request-ID`, and every error body repeats it.

If you already stamp requests upstream, send the header and we use your
value rather than inventing a second one. It has to be short and printable;
anything else is replaced, because the value ends up in our logs and in a
response header.

When something goes wrong, the request id is the one thing worth quoting.
It turns "a page failed yesterday afternoon" into a single log line.

---

## Lists

Every list route returns the rows and a cursor:

```json
{
  "data": [ { "id": "…" } ],
  "next_cursor": "eyJzIjoibmFtZSIsImQiOiJkZXNjIn0.Yk9…"
}
```

A single resource is returned on its own, without a wrapper. A list needs
somewhere to put the cursor; one object does not need a wrapper to carry
nothing.

### Paging

Ask for the next page by passing the previous `next_cursor` back as
`?cursor=`. When `next_cursor` is `null` you have reached the end.

The cursor is opaque. Do not parse it, do not build one, do not edit one. It
is signed, so a modified cursor is refused rather than misinterpreted, and
its encoding may change without notice.

There is no page number and no offset, on purpose — see ADR 011.

A cursor is refused when it was not issued by us, when it was issued for a
different ordering than the one you are now asking for, or when the signing
key has since been rotated. All three answer `invalid_cursor` with a 400,
never a 500. Start again from the first page.

### Sorting and filtering

`?sort=` accepts only the fields a resource declares. Asking for anything
else is refused with `invalid_sort`, and the refusal names what is allowed.
`?order=` takes `asc` or `desc`.

Filters are declared per resource as typed parameters — members can be
filtered by role, workspaces by status. A value outside the accepted set is
refused before the request reaches any query. There is no general-purpose
filter syntax, and that is deliberate: a query parameter that reaches the
database is how a client ends up sorting by a column nobody meant to
expose.

`?limit=` defaults to 50 and is capped at 200.

---

## Job history

What ran in the background for your workspace, and how it went. Read-only, and for admins and
owners only (`job:read`, see [permissions.md](permissions.md)).

```
GET /api/v1/jobs            a page of runs, newest first
GET /api/v1/jobs/{id}       one run
```

A run has a `status` — `queued` (waiting for a worker), `running`, `retrying` (an attempt failed
and another is due at `next_run_at`), and the final `succeeded` and `failed` — with its
`attempts`, when it `created_at` / `started_at` / `finished_at`, and the `request_id` of what
caused it. Quote that id when you write to us: it is the one that ties a run to our logs.

`?status=` filters, and `?sort=` accepts `created_at` only. Everything else about paging is as
described under Lists above.

**What it never shows.** An error message: an exception text names hosts, paths and queries, and
this API does not say what went wrong inside (see What a 500 says). A run that belongs to nobody —
the platform's own housekeeping — and one that belongs to another workspace. Both answer **404**,
not 403, so that neither can be told apart from a run that never existed.

---

## Rate limiting

Every response carries `RateLimit-Limit`, `RateLimit-Remaining` and
`RateLimit-Reset`. Watch them and slow down before you are refused; a client
that only reacts to a refusal has already been refused.

When you exceed the limit the answer is 429 with `rate_limited`, and
`Retry-After` says how long to wait.

There are two layers. A generous backstop applies to every route, keyed to
the caller. Sign-in, registration and password recovery have their own much
stricter limits on top, tuned to the attacks they attract. Health checks are
never limited — a busy probe must not make the service look down.

---

## Versioning

The path carries the version: `/api/v1`.

**These can change inside v1 without warning.** A new field appearing in a
response. A new value appearing in an enumeration that a response can
contain. A new optional query parameter. A new route. A new error code.

Write clients that tolerate all of these. Ignore fields you do not know
rather than rejecting the response, and treat an unrecognised code as a
generic failure of its status class rather than crashing.

**These require v2.** Removing or renaming a response field. Changing a
field's type. Changing what an existing value means. Removing a route, or
changing what it does. Making an optional parameter required.

**Deprecation.** A route on the way out answers with a `Deprecation` header
carrying the date the decision was taken, and a `Sunset` header carrying the
date it stops working. Nothing uses them yet. They are written down now so
that the first deprecation follows a rule rather than inventing one.

---

## Reading the schema

`/api/v1/openapi.json` outside production. It describes the error shape as
well as the routes, so generated clients type failures correctly rather than
against a body that never arrives.

In production neither the schema nor the documentation page is served. The
schema is still generated internally and CI still checks the frontend's
generated types against it; what changes is who can fetch it over the
network.
