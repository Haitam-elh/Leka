# Usage and cost metering

LEKA-430. What each execution took and cost LEKA — derived from what was
kept where the work was done, never told twice — what an intention cost,
end to end; and each workspace's AI credits — its plan's, what it used, the
limit. The code is `api/leka/metering`; the rates are the model
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

## 5. Plans and AI credits

A workspace's **AI credits** are what its plan lets its work cost LEKA on
LEKA's models each month — apart from what that work costs LEKA, which stays
LEKA's to read (§ 3). **1 credit = `LEKA_CREDIT_USD` (0.01 $) of LEKA's model
cost** at the rates in force: a workspace uses, in credits, what its calls to
LEKA's models cost. A call that failed is not billed; a workspace's own model
(Enterprise, its account) uses none — and is still metered (§ 3).

| Plan | Credits a month (`LEKA_PLAN_CREDITS`) |
| --- | --- |
| Free — every workspace until LEKA puts it on another | 200 |
| Starter | 2 000 |
| Growth | 10 000 |
| Business | 40 000 |
| Enterprise — or its contract's (`--credits`) | 100 000 |

The month is the calendar month (UTC). A **pack** adds credits to the month it
is added in, gone when it ends.

**The limit.** Once a month's credits are spent — its plan's and its packs' —
LEKA's models are refused the workspace until the month ends, a pack is added
or its plan changes (`LEKA_CREDITS_ENFORCED`, on). **Never billed past it.** The
refusal is the AI controls' (LEKA-406, `capabilities/gateway/controls.py`):
the run ends `no_model`, reason `limited`, said why. A workspace's own model
still answers.

**Warnings.** Each share of the month's credits passed (`LEKA_CREDIT_WARNINGS`:
80 %, 100 %) is told by email to its owners and admins, once a month
(`credit_warnings`, the `credit-watch` schedule every quarter of an hour).

**Facturation** shows the plan, the credits used and left, until when, the
packs, and — near or past the limit — what to do (`GET /billing/credits`).

**No payment yet**: plans and packs are LEKA's to give, by the server command,
the operator named; each is kept (`workspace_plans`, every plan it was on;
`credit_packs`) and in the workspace's audit trail (`workspace.plan_changed`,
`workspace.credits_added`).

    python -m leka.metering.cli plan <workspace id> growth --by bilal --reason "pilot"
    python -m leka.metering.cli plan <workspace id> enterprise --credits 50000 --by bilal --reason "contract"
    python -m leka.metering.cli pack <workspace id> 1000 --by bilal --reason "asked by mail"
    python -m leka.metering.cli plans <workspace id>
    python -m leka.metering.cli credits <workspace id>

## 6. LEKA's internal reports

What LEKA's AI costs it, across workspaces — LEKA's to read, **by the server
command or SQL, never over HTTP**. Every cost is LEKA's, in US dollars, at the
rates in force; what is not known is said (`cost_not_known`), never averaged
as 0. They read SQL views over the ledger (migration `0a074280012e`):

| View | What |
| --- | --- |
| `metering_executions` | each execution, its workspace, the plan it was on when it ran, its month |
| `metering_steps` | each execution's steps by purpose |
| `metering_agents` | by month and agent: runs, succeeded, calls, retries, invalid answers, cost — total, avg, P50, P90, P95 |
| `metering_intentions` · `metering_intention_months` | each intention's cost end to end; by month, avg, P50, P90, P95 |
| `metering_workspace_months` | by month and workspace: its plan, executions, LEKA's cost, its own model's |
| `metering_waste` | by month and purpose: the cost of answers not asked for and of tries past the first, their share |
| `metering_context` | by month and purpose: tokens in a call — avg, P95 — the share read from the provider's cache, the context items given |

    python -m leka.metering.cli report agents --month 2026-10            # CSV
    python -m leka.metering.cli report intentions --format json
    python -m leka.metering.cli report workspaces --month 2026-10
    python -m leka.metering.cli report plans --month 2026-10
    python -m leka.metering.cli report waste --month 2026-10
    python -m leka.metering.cli report context --month 2026-10
    python -m leka.metering.cli compare --before 2026-10-01:2026-10-15 --after 2026-10-15:2026-11-01
    python -m leka.metering.cli workspaces

**Margins** (`report plans`): by month and plan, the workspaces on it, what
they cost LEKA, the credits they used, and — given the plan's price a month
(`LEKA_PLAN_PRICES_USD`, `LEKA_PLAN_PROMO_PRICES_USD`) — the revenue and the
margin, `(revenue − cost) / revenue`, at the list and at the promotional
price. A plan without a price has no margin.

**Before and after** (`compare`): each agent and purpose in two periods
`[start, end)`: what an execution cost, its calls, tokens in, retry and
invalid rates — and the change, in parts of one (−0.25: a quarter less).

On the server: `docker compose -f docker-compose.production.yml --env-file
production.env run --rm migrate python -m leka.metering.cli …`.
