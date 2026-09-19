# ADR 001 — PostgreSQL 16 with pgvector as the only datastore

**Status:** accepted · **Date:** 2026-09-19 · **Ticket:** LEKA-329

## Context

LEKA stores four kinds of data that are usually given four different homes:

- **Relational** — workspaces, users, memberships, sources. Ordinary rows with
  foreign keys and transactions.
- **Semi-structured** — an entity's attributes differ wildly between a GitHub
  repository, a Datadog monitor and a Jira incident. Modelling each in columns
  means a migration every time a connector learns something new.
- **Graph** — entities connected by typed, directed edges, walked in both
  directions: "what does payment-api depend on" and "who depends on
  payment-api".
- **Vector** — semantic retrieval over documents and incidents, so that
  `context` can find evidence a keyword search would miss.

The team is two part-time developers. Every datastore added is a thing to
back up, monitor, upgrade, and debug at an inconvenient hour.

## Decision

**One PostgreSQL 16 instance, with the `vector` extension, for all four.**

- Relational: what PostgreSQL has always been good at.
- Semi-structured: `JSONB` with GIN indexes.
- Graph: `relationships` as an edge table, with a composite index for each
  traversal direction. Recursive CTEs for multi-hop walks.
- Vector: pgvector, in the same transaction as the row it describes.

The extension is created by **Alembic migration 001**, not by a Docker init
script, so a database created on RDS goes through the same path as one created
by `docker compose up`.

## Alternatives rejected

**Neo4j (or any dedicated graph database) for the graph.**
The pitch is real: better traversal ergonomics, better performance on deep
walks. But our graph is narrow — scoped to one workspace, rarely more than a
few hops. The cost is not the query language, it is the second source of
truth: two stores to keep consistent, no transaction spanning both, an entity
written to one and not the other after a crash. We would be trading a problem
we do not have for one we would have every week. Revisit if traversals
routinely exceed four hops or a workspace passes a few million edges.

**Elasticsearch for search.**
Excellent at what it does, and a full operational domain of its own: cluster
sizing, shard allocation, index lifecycle. PostgreSQL full-text search plus
pgvector covers what `context` needs today. Two part-time developers do not
run an Elasticsearch cluster on the side.

**A separate vector database (Pinecone, Qdrant, Weaviate).**
Faster at very large scale. But an embedding that lives elsewhere cannot be
written in the same transaction as the entity it describes, which means
reconciliation code and a class of "the vector says one thing, the row says
another" bug. pgvector keeps them atomic. Revisit when a single workspace's
vectors stop fitting comfortably in memory.

**MongoDB for the semi-structured half.**
`JSONB` gives us document storage *with* foreign keys and transactions. Giving
up referential integrity is exactly the wrong trade for multi-tenant data
where a dangling reference can mean one customer seeing another's row.

## Consequences

**Good.** One thing to back up, monitor and upgrade. Transactions span
everything. `docker compose up` gives a developer the entire data layer. One
query language.

**Bad.** Deep graph traversals will be less elegant than Cypher, and slower
past a certain size. pgvector is behind dedicated engines at very large scale.
PostgreSQL becomes the single point of failure — which is an argument for
replication, not for a second datastore.

**Watch for:** recursive CTEs appearing in `knowledge/repository.py` with more
than four levels; vector search latency above ~200 ms on a realistic
workspace; `attributes` queries that GIN cannot serve.
