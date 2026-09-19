# ADR 006 — Text with a CHECK constraint, not PostgreSQL ENUM types

**Status:** accepted · **Date:** 2026-09-19 · **Ticket:** LEKA-329
**Supersedes:** the enum choice made in migration 001

## Context

Five columns hold a closed set of values: `sources.kind`, `sources.status`,
`entities.type`, `relationships.type`, `memberships.role`.

Migration 001 made all five native PostgreSQL `ENUM` types. The reasoning was
integrity at the database level, which is sound. What that reasoning left out
is how often these particular lists change.

They change constantly, and by design. Every connector we add brings source
kinds and entity types with it: the backlog already anticipates roughly
eighteen source kinds against the six we shipped. `entity_type` will grow the
same way — Kubernetes clusters, dashboards, alerts, pull requests, feature
flags. A closed set that is closed on paper and open in practice is the worst
of both.

Two properties of PostgreSQL enums make that expensive, and both were
measured on PostgreSQL 16 rather than assumed:

**A value can never be removed.** There is no `DROP VALUE`. A typo, or a
source kind we stop supporting, is in the type permanently. The only way out
is recreating the type and rewriting every column that uses it.

**A value cannot be added and used in the same transaction.** Adding one
inside a transaction works:

```sql
BEGIN; ALTER TYPE k ADD VALUE 'slack'; COMMIT;   -- fine
```

but using it there does not:

```sql
BEGIN;
  ALTER TYPE k ADD VALUE 'aws';
  INSERT INTO s VALUES (1, 'aws');
  -- ERROR: unsafe use of new value "aws" of enum type k
  -- HINT:  New enum values must be committed before they can be used.
COMMIT;
```

Alembic wraps every migration in a transaction. So any migration that adds a
value *and* backfills rows with it — the normal shape of a migration that
introduces a type — has to be split into two migrations, forever, for a
reason that has nothing to do with the change being made.

## Decision

Store these five columns as `VARCHAR(50)` with a `CHECK` constraint listing
the allowed values. Migration 002 converts them.

The Python `StrEnum` classes stay exactly as they were: SQLAlchemy's
`Enum(..., native_enum=False)` keeps the typing in the application and emits
the constraint in the database. Nothing changes for code that reads or writes
these columns.

Adding a value is now one ordinary, transactional statement:

```sql
ALTER TABLE sources DROP CONSTRAINT ck_sources_kind;
ALTER TABLE sources ADD CONSTRAINT ck_sources_kind CHECK (kind IN (...));
```

Removing one is the same statement.

## Alternatives rejected

**Keeping the enums and splitting migrations when needed.**
Workable, and it pushes a recurring tax onto every future connector — paid by
whoever forgets, in the form of a migration that fails halfway. The tables are
empty today; this is the cheapest moment this decision will ever have.

**A reference table with a foreign key.**
Most flexible: values become rows, addable without any DDL, and joinable to
labels or metadata. Rejected for now because it turns every read into a join,
or into a denormalised copy, for lists of six to eighteen short strings that
are part of the domain rather than data. If entity types ever need attributes
of their own — a display name, an icon, per-type settings — this becomes the
right answer and the CHECK constraint becomes the migration path to it.

**A plain column with no constraint, validated only in Python.**
Cheapest to change, and it gives up the thing native enums were chosen for.
The background loop writes to these columns from several code paths; the
database is the one place that sees all of them.

## Consequences

**Good.** Adding or removing a value is one transactional statement. No
migration has to be split for a reason unrelated to its content. Application
typing is unchanged.

**Bad.** Slightly more storage per row — irrelevant at our scale. No ordering
between values, which we did not use. And a `CHECK` constraint is easier to
drop by accident than a type is, so a migration that removes one without
putting it back must be caught in review.

**Watch for:** a list growing past twenty or so values, or wanting attributes
of its own. Either is the signal to move to a reference table.
