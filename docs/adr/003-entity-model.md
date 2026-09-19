# ADR 003 — Two generic tables for the graph, not one table per object type

**Status:** accepted · **Date:** 2026-09-19 · **Ticket:** LEKA-329

## Context

LEKA maps a customer's information system. It does not know in advance what
it will find there: services, repositories, incidents, deployments, people,
documents, infrastructure resources, databases — and, as soon as a connector
is added, Kubernetes clusters, dashboards, alerts, pull requests, feature
flags.

The modelling question is whether each of those gets its own table.

The honest constraint: **we cannot enumerate the list.** LEKA's value grows
with the number of things it can see, so the list of types is guaranteed to
grow, and to grow in directions we have not thought of yet.

## Decision

**Two tables.**

```
entities        id, workspace_id, type, external_id, source_id, name,
                attributes (JSONB), confidence, last_seen_at
relationships   id, workspace_id, from_entity_id, to_entity_id, type,
                confidence, source_id
```

`type` is a PostgreSQL enum. Specifics live in `attributes`. Adding
"kubernetes cluster" is one new enum value in a migration — not a table, a
model, a repository, a schema and a set of routes.

Three design points that are not obvious from the shape:

**Identity is `(workspace_id, source_id, external_id)`, enforced as a unique
constraint.** The background loop runs continuously; a second pass over the
same source must update rows, never duplicate the graph. The database makes
that guarantee, not the code that happens to be calling it.

**`confidence` and `last_seen_at` are first-class columns.** LEKA infers
relationships that nobody documented. An answer built on a shaky inference
has to be able to say so, and an entity nobody has seen for three weeks is
evidence in itself.

**Both traversal directions are indexed.** "What does payment-api depend on"
and "who depends on payment-api" are both everyday questions, so
`(workspace_id, from_entity_id, type)` and `(workspace_id, to_entity_id,
type)` both exist.

## Alternatives rejected

**One table per object type — `services`, `repositories`, `incidents`, …**
Gives real column types, real constraints, and a schema that documents itself.
It also means every new kind of object is a migration plus five files, and
every cross-type query is a union over N tables that grows each time. The
killer is the graph: a relationship would need a polymorphic reference to "any
of these fifteen tables", which PostgreSQL cannot express as a foreign key.
We would lose referential integrity on the most important table in the system.

**A single table with every column nullable.**
Avoids the union, at the price of a table with eighty columns of which six are
populated per row. No constraint can express "this column is required when
type is 'incident'". JSONB is the same flexibility, honestly labelled.

**Entity–attribute–value (one row per attribute).**
Maximum flexibility, minimum usability: every read becomes a pivot, no
attribute can be typed or indexed usefully, and query plans are unpredictable.
JSONB with GIN is EAV's flexibility with an index that works.

**A graph database.** Covered in [ADR 001](001-postgresql.md).

## Consequences

**Good.** A new object type costs one enum value. Cross-type queries are one
query. The graph has real foreign keys — including the composite ones that
make a cross-tenant edge impossible to write. One repository, one set of
indexes to tune.

**Bad, and it matters.** **The database cannot validate what is inside
`attributes`.** A typo in an attribute name is accepted silently and surfaces
as a missing field somewhere downstream. That validation has to live
somewhere, and we have chosen: the normalisation step in `ingestion`, plus
Pydantic schemas per entity type in `knowledge/schemas.py`. If that discipline
slips, this decision turns into a data-quality problem, not a modelling one.

Secondary costs: `attributes` cannot be joined against; queries into it are
more verbose than a column; and a type enum can gain values but never lose
one.

**Watch for:** an entity type whose attributes are queried so often and so
structurally that it wants real columns — a promoted column alongside JSONB is
a legitimate escape hatch; `attributes` shapes drifting between connectors for
the same type; GIN indexes no longer serving the common filters.
