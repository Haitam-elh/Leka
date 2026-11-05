# ADR 016: LEKA ADMIN reads every customer, behind its own identity

**Status:** accepted
**Date:** 2026-11-05
**Ticket:** LEKA-544 (with the groundwork of LEKA-545 and LEKA-546)

## Context

Everything in LEKA CORE was built so that a request sees exactly one
workspace: the principal carries it, the session guard refuses any query
without it, and `system_scope()` (every tenant at once) is reserved for
workers and scripts, "never for serving a request"
(`leka/db/repository.py`). `tests/test_tenant_isolation.py` holds that line
for every route.

LEKA ADMIN, the LEKA team's back office (Android first, the web later), needs
the opposite on purpose: every organisation, every person, every intention,
across customers.

## Decisions

### A separate identity, not a role of the customers'

LEKA's team signs in to `admin_accounts`, apart from `users`. No customer
account, whatever its role in its workspace, can become an admin, and no
admin route accepts a customer's cookie: `get_admin` reads a bearer token
only. A bearer suits the Android app (no cookie jar, no CSRF to manage), and
the CSRF middleware, which acts only when a session cookie is present, stays
out of the way.

### The one place a request runs in `system_scope()`

`leka/admin/dependencies.py` resolves the token to an active admin, then runs
the handler in `system_scope()`. Writes to one organisation narrow it again
with `workspace_scope(id)`. No other request path opens `system_scope()`.

What keeps this from leaking:
- `tests/test_admin_access.py` calls every admin route with no token, a bad
  one, a Basic header and a signed-in customer owner: all refused.
- `tests/test_route_protection.py` counts `get_admin` as authentication, and
  the sign-in route as the one public admin route.
- `tests/test_tenant_isolation.py` still calls every readable route as a
  customer and looks for another's data.
- Only admin routes may name an organisation in their path
  (`{organisation_id}`), and a test says so.

### Permissions, refused by default, on the server

Four roles (Super Admin, Operations, Support, Finance) map to permissions per
module and action (`leka/admin/access.py`). A route asks for a permission. A
role nobody knows grants nothing. What a customer wrote is its own permission
(`intentions:content`), apart from knowing an intention exists.

### A trail of its own, append-only

`admin_audit_events` keeps sign-ins (failed ones with their reason),
refusals, sensitive readings and every change, with the request id and the
address prefix. A trigger refuses any update except a foreign key forgetting
who. Refusals and failed sign-ins are committed apart from the request they
end. It is independent of the customers' audit retention.

### Reuse, never rewrite

The reads come from the modules that keep the data; the writes call those
modules' rules (`WorkspaceService.suspend`, `add_pack`). Nothing is copied
but the activity journal, and that is minimal and derived.

### The activity journal is derived, not instrumented in every module

Adoption, activation and retention need history the product does not keep in
one place (sessions are purged, sign-ins follow each workspace's retention).
Rather than make seven modules publish analytics events, a sweep reads each
table that already says what happened and writes each fact once, by its
`dedupe_key`. No write path changes, the history is filled from the first
run, a new kind is one function, and replaying is harmless. The sweep reads
up to the database's clock, with a ten-minute overlap for late commits.

### Sensitive operations are idempotent

Each takes an `Idempotency-Key`. The answer is kept under it: a retry gets
the same answer and does nothing, and the same key with another request is a
409. A placeholder row taken at once serialises two concurrent requests with
one key on the unique index.

## Consequences

- An admin token opens every customer: sessions end after 12 hours or 2 idle,
  five wrong passwords lock the account, sign-in is rate-limited, and LEKA-546
  adds the rest (renewal, device storage, retention of the trail).
- What models cost is visible through the Admin API. LEKA-530 keeps it from
  customers; `tests/test_usage_report.py` still holds that for every other
  route.
- Since LEKA-545 a Super Admin invites, changes and disables admins and sets
  what each role may do through the Admin API (the server's command stays
  for the first account). What a role grants is read from the database at
  every request, so a change applies without signing in again.
