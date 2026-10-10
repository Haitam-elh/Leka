# Usage and cost metering

LEKA-430. What each execution took and cost LEKA — derived from what was
kept where the work was done, never told twice — and what an intention cost,
end to end. The code is `api/leka/metering`; the rates are the model
gateway's (`api/leka/capabilities/gateway/rates.py`).

## 1. What a call keeps

Every call to a model is kept by the gateway (`model_calls`, see
[model-gateway.md](model-gateway.md) § 5). Two things were added:

- `usage_reported` — whether the provider said what the call used. An answer
  without it reads 0 tokens: not known, not free. `false` then, and the call
  has no cost; `true` when it said; none for the calls kept before LEKA-430
  (taken as said when they have tokens).
- `rate_id` — the rate the call was priced with, so that its cost can be
  read again.

`cost_usd` keeps its meaning — the call's cost at the rate in force, none
when it is not known — and the AI controls' usage limits (LEKA-406) and
`GET /models/usage` read it as before.

## 2. The rates

`model_rates`: what a model costs LEKA from a day on, per million tokens in,
out and read from the provider's cache, in US dollars, with where the price
was read. Seeded with the list prices of `profiles.py`; a test fails when a
list price there has no rate here.

A rate is never rewritten — the database refuses it. A new price is a new
rate, from its day:

    python -m leka.metering.cli rates
    python -m leka.metering.cli rates add google gemini-3.8-flash 2027-06-01 1.2 6.0 \
        --cached 0.12 --source "contract 2027"

A model with no rate — a workspace's own deployment — has no cost: unknown,
never 0. Giving it a rate gives it one, from that day.

## 3. The ledger

`usage_records`: one row per execution, written again whole from its calls
and its run each time it is metered — so a call retried, a sweep run twice, a
backfill over a metered month count once (unique on workspace and
execution).

| Execution | What it is | Its calls |
| --- | --- | --- |
| `agent_run:<id>` | an agent run — its key, version, status, who asked, its intention | `ref = agent_run:<id>`: its analysis and, for the agents that make one, its deck or its change (`agent:<key>`, `agent:<key>:deck`) |
| `workflow_run:<id>` | a workflow run | `ref = workflow_run:<id>` (its agent steps are agent runs of their own) |
| `intention:<id>` | the work done for an intention outside a run: its analysis, its answer | `ref = intention:<id>` |
| `llm_run:<id>` | a run of the LLM runtime about nothing above — reading an intention is one, tied to it by `understanding.read_by.run_id` | `run_id = <id>` |
| `work:<purpose>:<day>` | the rest of a day's work for one purpose | neither |

Each row says: the subject and its version, who it was for, how it ended,
when, how long; calls, failed, invalid, tries past a model's first,
fallbacks, tool calls, answered calls whose usage was not said; tokens in,
out, thinking, cached — **measured** (every answer said them), **partial**,
**unknown**, or **none** (no answer); the cost — LEKA's, and a workspace's own
model's apart — **estimated** (measured tokens at the rate in force),
**partial**, **unknown**, or **none**; the models and the rates; and, by
purpose, what each step took and cost, the cost of answers that were not
what was asked and of tries past the first apart.

A call that failed was not answered: counted, never priced — providers do not
bill it. What LEKA does not measure is said rather than left out:
embeddings `not_applicable` (context is retrieved in the database: no
embedding model is paid), tools and infrastructure `unavailable`.

Nothing is kept that is not already kept elsewhere: no prompt, no answer, no
error text — keys, purposes, counts and amounts.

The schedule meters every execution a call was made for, or a run ended, in
the last six hours — every quarter of an hour (`metering-sweep`). A backfill:

    python -m leka.metering.cli sweep --since 2026-10-01

## 4. An intention, end to end

    python -m leka.metering.cli intention <workspace id> <intention id>

Its executions metered again, then summed: reading it, analysing it, the
agents and workflows it ran (`intention_id`), every try — calls, tokens,
cost, by step, with the same statuses.
