# ADR 002 — A modular monolith, not microservices

**Status:** accepted · **Date:** 2026-09-19 · **Ticket:** LEKA-329

## Context

LEKA has parts with genuinely different shapes. Connectors are IO-bound and
spend their life waiting on rate limits. Ingestion is CPU-bound in bursts.
The API must answer in under a second. Capabilities calls a model and waits
seconds. That variety is the classic argument for splitting into services.

Against it: **two part-time developers**. A distributed system is not only
distributed at runtime; it is distributed across the time you have. Every
boundary between processes is a deployment pipeline, a contract to version, a
network failure to handle, and a debugging session that spans two log streams.

## Decision

**One deployable FastAPI application with hard internal boundaries.**

Two processes run from the same codebase:

- the **API**, serving the interactive loop;
- the **worker** (RQ), running the background loop.

Same code, same models, same migrations. The split is by *when the work
happens*, not by *what the work is about* — the one dimension along which
these two genuinely differ.

Boundaries are enforced inside the codebase:

1. Dependencies point one way: `intentions → context → knowledge → ingestion →
   connectors`.
2. A module is imported only through its `__init__.py`.
3. Every module has the same internal shape: `models` / `schemas` /
   `repository` / `service` / `__init__`.
4. Every database query lives in a `repository.py`.

The point of these rules is that extracting a module later is a refactor
rather than an excavation.

## Alternatives rejected

**Microservices from day one.**
Would give independent scaling and deployment. Would also require, before
writing a single feature: a service mesh or an API gateway, distributed
tracing, per-service pipelines, contract versioning, and an answer to "what
happens when ingestion is down and knowledge is not". Every one of those is a
week we do not have. And splitting early means guessing the boundaries before
we know them — the expensive mistake, since a wrong process boundary is far
harder to move than a wrong module boundary.

**Serverless functions.**
Attractive for connectors: bursty, IO-bound, parallel. Fatal for the rest —
cold starts against a sub-second interactive budget, a connection pool that
does not survive between invocations, and a background loop whose natural unit
of work is "sync this source for the next twenty minutes", not "run for 900
seconds and die".

**One process for everything, API and background work together.**
Simplest of all, and wrong: a heavy sync would compete with a user's request
for the same event loop. The API/worker split is the one process boundary that
pays for itself immediately.

**An unstructured monolith.**
Faster this month, and it removes the only thing that makes the next decision
reversible. Module boundaries are what let us extract a service the day one
genuinely needs to scale apart.

## Consequences

**Good.** One thing to deploy, one to monitor, one to debug. A developer runs
the whole product locally. Refactoring across module boundaries is a normal
change, not a cross-team negotiation. Transactions are real transactions.

**Bad.** Everything scales together — a connector doing heavy work shares a
machine with the API. A crash in shared code takes down both processes. And
the boundaries are enforced by discipline and review, not by the network:
nothing physically stops someone importing `knowledge.repository` from
`connectors`. That is what code review is for, and what the import-graph test
will be for.

**Watch for:** one module needing a different scaling profile badly enough to
hurt; a deploy blocked because two unrelated changes are in it; build or test
time long enough to slow the loop. Those are the signals to extract the first
service — probably `connectors`, the most independent of them.
