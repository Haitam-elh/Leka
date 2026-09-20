# ADR 008 — Opaque server-side sessions, not JWT

**Status:** accepted · **Date:** 2026-09-20 · **Ticket:** LEKA-330

## Context

LEKA needs to know who is making a request. Two families of answer exist: a
signed token the client carries and the server verifies without storing
anything (JWT), or an opaque random identifier the server looks up.

Two requirements already on the table decide this before any preference does:

**LEKA-331 promises immediate revocation.** Removing someone's membership
cuts their access on their next request. That promise is tested, and it is
the difference between a revocation and a delay.

**LEKA-330 requires sessions "created, maintained and invalidated securely".**
Invalidation is the word that matters.

## Decision

**A random 256-bit token in an httpOnly cookie, and a `sessions` row holding
its SHA-256 hash.**

- The token is generated with `secrets.token_urlsafe(32)`.
- Only its hash is stored, for the same reason passwords are hashed: a leaked
  backup is not a set of usable sessions.
- SHA-256 rather than argon2, deliberately. Argon2 is slow on purpose, to
  make guessing a low-entropy secret expensive. A 256-bit random token has
  nothing to guess, and this lookup runs on *every authenticated request* —
  slowing it would buy nothing and cost everything.
- Two expiry limits, not one: an absolute maximum (30 days) and an idle
  timeout (7 days). The first bounds how long a stolen cookie is useful; the
  second closes the laptop someone left in a cafe.
- A new token is issued at every sign-in. Reusing one that existed before
  authentication is session fixation.
- Expired sessions are deleted by a sweep, not merely ignored.

## Alternatives rejected

**JWT with a short lifetime.**
The usual answer, and the reason it fails here is arithmetic: a JWT is valid
until it expires, whatever happens in between. A fifteen-minute token means a
fifteen-minute window in which someone removed from a workspace still has
access. We would have to add a revocation list — which is a database lookup
on every request, which is exactly what the JWT was supposed to avoid. At
that point it is a session with extra steps and a larger cookie.

**JWT plus a refresh token.**
Moves the problem rather than solving it: the access token is still
irrevocable for its lifetime, and now there are two token types, two
lifetimes and a rotation protocol to get wrong.

**Signed cookies carrying the user id (itsdangerous, Flask-style).**
No database lookup, and no revocation either. Same problem as a JWT with
fewer standards behind it.

**Redis-backed sessions.**
Genuinely faster, and it splits the source of truth. A session pointing at a
user who no longer exists, or surviving a database restore, are both states
that have to be reasoned about. PostgreSQL gives us a foreign key and
`ON DELETE CASCADE` instead: deleting a person deletes their sessions,
provably. Revisit if session lookups ever show up in a latency profile.

## Consequences

**Good.** Revocation is immediate and total — one row, and the next request
is refused. "Your signed-in devices" is a table we can show and a row we can
delete. A leaked database yields hashes. The cookie is small.

**Bad.** One indexed lookup per authenticated request, on a unique index.
Sessions are state we have to sweep, hence the purge job. Horizontal scaling
now needs a shared database, which we already have.

**Watch for:** the session lookup appearing in latency profiles, which would
be the moment to cache it for the life of a request — never longer, since
"never longer" is the whole point.
