# ADR 007 — Shared tables with a scope guard, not row-level security

**Status:** accepted · **Date:** 2026-09-20 · **Ticket:** LEKA-331

## Context

Every LEKA customer's data lives in the same tables, told apart by
`workspace_id`. One customer reading another's incidents is the failure this
product does not survive — not a bug to fix in the next release, an end to
the trust the product is sold on.

Migration 001 made cross-tenant *writes* impossible: composite foreign keys
mean a row cannot reference another workspace's row, and PostgreSQL rejects
the attempt. What remained unsolved was *reads*. Architecture rule 4 said
every query lives in a repository; nothing said those queries had to filter,
and nothing stopped anyone using the session directly.

"Every future query will remember to filter" is not a guarantee. It is a hope
about forty developers-months of code that has not been written yet.

## Decision

**Four layers, each catching what the one above it misses.**

**1. The schema.** `workspace_id NOT NULL` on every business table, with
composite foreign keys so a row can never point at another tenant's row.
Enforced by PostgreSQL; no application code can bypass it.

**2. `WorkspaceScopedRepository`.** The workspace is a constructor argument,
never a method parameter — a method parameter is something a caller can
forget or get from the wrong place. Reads come back pre-filtered; writes with
a foreign workspace raise. Constructing one without a workspace raises.

**3. The session guard.** A SQLAlchemy `do_orm_execute` listener intercepts
every ORM statement touching a workspace-scoped table and either scopes it or
refuses it. **Fail-closed**: no declared workspace, no rows — and an
exception, not an empty result. A silent empty list is how "my dashboard is
blank" becomes a three-day investigation.

This layer is what the repository alone cannot provide. A base class cannot
stop someone writing `select(Entity)` against the session; the guard can. It
also covers lazy loads, which no repository method ever sees.

**4. The request principal.** Every protected route runs inside
`workspace_scope(...)`, entered by the dependency that resolves the
principal. Routes inherit correct scoping whether or not their author thought
about it.

### Work that legitimately crosses tenants

Seed scripts, data migrations, workers sweeping every customer. They declare
it with `system_scope()` — one visible line, in a diff, that a reviewer can
question. When the guard was first switched on it found exactly two such
places in the whole codebase, and both were genuine.

### The workspace comes from the session, and switching is a request

The active workspace is read from the server-side session, never from a URL,
a header or a body. `POST /workspaces/{id}/switch` is the single exception
and is not really one: it verifies a membership and then writes the id into
the server's own session. A client may **ask** to move; it can never
**assert** where it already is. `X-Workspace-Id` as a trusted header is
forbidden — it is precisely how one ends up reading the neighbour's data.

### The role is resolved on every request

Not cached in the session at sign-in. Removing someone from a workspace takes
effect on their next request rather than at their next login — a delay is not
a revocation. The cost is one indexed lookup on `(workspace_id, user_id)`,
which is a unique constraint and therefore already an index.

## Alternatives rejected

**PostgreSQL row-level security.** The strongest isolation available, and
wrong for us *today*. RLS needs a session variable set per transaction
(`SET LOCAL`), and we run SQLAlchemy async over a connection pool. A
transaction that ends without resetting it leaves the setting on a pooled
connection, which the next request — another customer's — reuses. The
failure mode of the mechanism is the exact bug the mechanism exists to
prevent, and it fails silently and intermittently.

It is worth adding as a fourth net later, deliberately, with the pooling
question solved first.

**Revisit when:** we run a dedicated connection-per-transaction pool, or
SQLAlchemy's async pooling gives a reliable per-transaction hook; or a
customer's security review requires database-level isolation as a control
they can audit; or we take on data we cannot afford to lose to a single
application bug. Any of those makes the work worth doing properly.

**A database per tenant.** Perfect isolation, and it moves the problem to
running N databases: N migration runs, N backups, N connection pools, and a
cross-tenant query — "how many customers use GitHub?" — becoming an
application-level fan-out. At two part-time developers, the operational cost
exceeds the risk it removes. Worth revisiting for a single very large
customer who pays for it.

**A schema per tenant.** The same trade in a smaller package, and the same
`search_path`-on-a-pooled-connection problem as RLS, with worse tooling.

**Trusting repositories to filter.** What we had before this ticket. It
depends on every future author remembering, in code none of us has read yet.
The guard costs a few dozen lines and removes the question.

## Consequences

**Good.** A developer who forgets to filter gets an exception, not a leak. A
developer who bypasses the repository gets the same. Cross-tenant work is
visible in diffs. Removing someone's access is immediate. `alembic`, the
seed script and the workers all still function, having said what they are.

**Bad.** The guard is global: every ORM read of a scoped table now requires a
declared scope, which is a real constraint on code that legitimately spans
tenants and an error message a newcomer will meet at least once. It relies on
a ContextVar, so code spawning tasks outside the request context has to carry
the scope deliberately. And it covers the ORM only — raw SQL through
`session.execute(text(...))` is not filtered, which is why raw SQL in
application code stays a review-stopping event.

**Watch for:** `system_scope()` appearing in a request path, where it never
belongs; raw SQL creeping into services; the principal lookup showing up in
latency profiles, which would be the moment to cache it for the life of a
request — but never longer.
