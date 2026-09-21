# ADR 011 — API conventions

**Status:** accepted
**Date:** 2026-09-21
**Ticket:** LEKA-333

## Context

Five tickets had built routes without anyone deciding how routes should
behave. The result was not chaos, but it was inconsistent in ways that get
expensive:

- **Three error shapes reached clients.** Whatever an author chose for an
  `HTTPException`, Pydantic's own shape for a validation failure, and a bare
  500. `web/lib/api.ts` carried a function whose only purpose was to unpick
  the second, plus branches for the other two. That code existed because the
  API had three shapes.
- **No request identifier**, so a report of "it failed this afternoon" had
  nothing to search for.
- **No pagination**, no sorting, no filtering. The first large collection
  would have invented its own.
- **Rate limiting existed in one module**, called by hand at seven call
  sites. A route that forgot the call was unlimited and nothing said so.
- **The schema was published in production**, which on a B2B product hands
  anyone who asks a current map of the attack surface.
- **Nothing made authorisation unforgettable.** `Principal` and
  `require_permission` were correct and entirely optional.

## Decisions

### One error contract, imposed by handlers

Three handlers registered on the application normalise everything into one
body: a machine code, a sentence, optional per-field details, and the
request id. Registered on the app rather than a router, because a 404 for an
unmatched path never reaches a router.

The body is wrapped in `error`. A single resource is returned unwrapped, so
a flat error body would collide the day a resource has a field called
`code`. The wrapper makes the discriminator structural.

**A fourth shape turned up during implementation.** The CSRF middleware
builds its own response and never reaches a handler — middleware runs
outside the chain that converts exceptions. It lives in `leka.identity`,
which sits below `leka.api` and may not import from it. So the *shape* lives
in `leka.core.errors`, reachable from every layer, and the framework wiring
stays in `leka.api.errors`.

The codes are one enumeration, because clients branch on them. The nine
introduced by LEKA-330 keep their exact spelling; renaming them would have
been a breaking change for nothing.

**A 500 never carries internals**, in any environment. A rule with an
exception is a rule somebody misconfigures.

### A request identifier, end to end

A middleware stamps every request, honours an upstream `X-Request-ID` when
one arrives and passes a narrow check, binds it for structlog, and returns
it in a header and in every error body.

It is also written to `request.state`, and that is not redundancy. An
unhandled exception propagates *out* through the middleware before
Starlette's outermost handler builds the 500 — by then the context variable
has been reset, and the one response where the id matters most would have
gone out without one. This was found by a test, not by reasoning.

### Cursor pagination, never offset

`OFFSET 20` means "skip whatever the first twenty are right now". Rows
arriving while somebody reads make page two repeat an item or lose one. On a
continuously fed screen that is the normal case, not an edge case.

A cursor names a position instead of a count. It carries the sort key **and
the row id**: without the tiebreaker, two rows sharing a timestamp on a page
boundary silently lose one for ever.

**Opaque and signed.** Opaque so the encoding can change; signed with the
application secret so a modified cursor is refused before its contents are
trusted at all. Validation alone would have made a forged cursor harmless;
signing makes it impossible, and costs a few lines.

It never carries a workspace. The workspace comes from the principal, and a
test signs a cursor containing a foreign workspace id to prove the server
ignores it.

Rotating the signing key invalidates cursors in flight. A cursor lives for
seconds; that is the price and it is written down.

### Sorting and filtering are whitelists

Each resource declares what it allows. A query parameter never reaches the
ORM — that is how a client ends up sorting by a column nobody meant to
expose, or by one with no index that the first large tenant turns into an
outage.

Each sortable field records what supports it. **Three fields are exposed
today with no index of their own**, and that is a deliberate exception:
those queries are already bounded by an indexed column and return tens of
rows, so the sort happens in memory and costs nothing. The rule matters for
the tables that grow without bound, and those already carry the composite
indexes their sorts need. Revisit if any of these collections stops being
small.

Filters are typed parameters rather than a query language. Adding one is a
deliberate act.

### The envelope

A list returns `{"data": [...], "next_cursor": ...}`. A single resource is
returned unwrapped. The inconsistency of choosing per route costs more than
either choice.

### Rate limiting on every route

A middleware, so a route added next year is covered without its author
knowing the file exists. The strict per-route limits on authentication stay
on top; a request passes through both.

**Keyed by caller, not by workspace**, and this is a departure from what the
ticket asked. Keying by workspace means resolving a session to a membership
on every request — a database read before deciding whether to serve, *
including for the requests about to be refused*. A limiter that costs a
query per refusal amplifies an attack instead of absorbing it. The
consequence is honest: two people in one workspace get a bucket each. Per
tenant quota is a billing concern and belongs in a mechanism that counts
after the work, not before it.

Health checks are exempt. A rate-limited probe would make this mechanism
invent the outage it exists to survive.

### The schema is not published in production

`/docs` and `/openapi.json` are served everywhere else. In production they
are not routes at all. The schema is still generated — CI still checks the
frontend's generated types against it — so what changes is network exposure,
not the artefact.

### What `/v1` promises

Additive changes happen without warning: a new field, a new enumeration
value in a response, a new optional parameter, a new route, a new error
code. Clients must tolerate all of them.

Removals, renames, type changes, semantic changes and newly-required
parameters need `/v2`.

Deprecation uses `Deprecation` and `Sunset` headers. Nothing emits them yet;
the rule is written now so the first deprecation follows one.

### Authorisation must be unforgettable

The most valuable thing in this ticket is a test that enumerates every
mounted route and requires each to be either protected or listed as public
with a written reason. A route added without authentication fails CI, named.

Making it possible required a change: **five routes enforced their session
inside the handler body**. That works and it is invisible — no check can
distinguish a route that forgot from one deliberately open. Those guards
moved into a dependency.

The test was proved to bite by adding a genuinely unprotected route,
watching it fail, and removing it.

## Consequences

**Good.** One error shape deleted a parser from the frontend. The request id
makes a report actionable. One paginator exists before the first large
collection needs one. An unprotected route cannot reach production quietly.

**Bad, and accepted.** Every list route changed shape, and the sessions,
members and workspaces routes are breaking changes — made now, while nothing
consumes them, because they will never be this cheap again.

**Bad, and deferred.** Rate limiting is per caller rather than per tenant.
Three sortable fields have no index. Both are written down above rather than
left to be discovered.

## Alternatives considered

**Leaving error shapes as they were and normalising in clients.** Every
client would carry the adapter our frontend already had, for ever, and each
would get it subtly wrong.

**Offset pagination**, because it is simpler and every list is currently
small. Rejected: the first screen that needs pagination is the one fed
continuously, which is exactly where offset misbehaves, and by then there
would be two implementations.

**An unsigned cursor**, validated on the way in. Enough to prevent harm, and
it leaves "what happens if somebody edits this?" as a question answered by
reading code rather than by the design.

**A general filter syntax.** Flexible, and a standing invitation to query
something nobody intended to expose.

**A separate gateway** for rate limiting and request ids. Another component
to operate, for two middlewares totalling a few hundred lines.
