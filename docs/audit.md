# The audit trail (LEKA-407)

One record per event that matters — **who** did **what**, to **what**, with
**what outcome**, **when**, from **where** — in one shape whatever produced
it, searched in one place, kept as long as the workspace says, and changed
by no one.

## One record, one shape

`audit_events`, one row per event:

| Field | |
| --- | --- |
| `at` | when |
| `category` | `user` · `team` · `workspace` · `data` · `access` · `governance` · `decision` · `action` · `ai` · `audit` |
| `action` | what, as `kind.verb`: `source.credentials_rotated`, `member.role_changed`, `agent_run.succeeded`… — an access decision keeps its permission or action (`agent:run`, `workspace:read`) |
| `outcome` | `success` · `failure` (it was tried and did not work: a wrong password) · `denied` (refused: a permission, a policy, an AI control) |
| `actor_type`, `actor_id`, `actor_role` | a person, as which role (a role of the workspace's own included) — or `system`: LEKA itself, `detail.for` naming whom it acted for |
| `target_type`, `target_id`, `target_label` | what it was done to: a source, an entity, a run, a person… and a name to read it by |
| `request_id`, `ip`, `user_agent` | where from: the request (the same id as the logs and the error a user quotes), the caller's **network prefix** — /24, /48, never a full address (`identity.truncate_ip`) |
| `detail` | what else matters: the before and after of a change, a reason, a count — **never the data touched**: no secret, no password, no answer of a model, no attribute of an entity |

Written by one function, `governance.audit()` — with the request's
transaction, so a change rolled back leaves no trace of having happened —
or `audit_apart()` for what must outlive a rollback: a refusal, a failed
sign-in. The specialised trails stay where they are, each also writing its
line here: access decisions (LEKA-402), governance changes (LEKA-403), AI
control outcomes (LEKA-406).

## What is recorded

| Category | Events |
| --- | --- |
| `user` | signed in · sign-in failed (an account that exists — an unknown address leaves a log line only, so the trail never says which addresses exist; kept **after** the answer, so its timing does not tell either; its actor is `system`, the account its **target** — anyone may try an address) · signed out, everywhere · password changed (or failed to) · password reset · a device signed out · account closed. Kept in **every workspace the person belongs to**. |
| `team` | invitation sent (its role — never the address invited), revoked · member joined · role changed (before, after) · member removed |
| `workspace` | settings changed · deletion requested |
| `data` | source created, changed, credentials rotated, activated, disabled, deleted, settings saved · entity restricted, restriction lifted · **a restricted entity read** by who may |
| `access` | every access decision kept (LEKA-402): refusals — an entity a person may not see, a route their role refuses, a policy — and writes and runs allowed |
| `governance` | roles, assignments, policies, AI controls created, changed, deleted — before and after |
| `decision` | a decision approved, rejected, modified, changes requested · the approval policy changed |
| `action` | systems authorized, changed, removed · plans created, started, cancelled · a step reported · **each action LEKA executed** on a system, with its outcome |
| `ai` | agents and workflows asked, cancelled, retried — and **ended**, by LEKA, for whom · what the AI controls did: a model refused, a limit reached, an answer redacted, blocked, flagged, a run held, approved, rejected |
| `audit` | the retention changed · events expired · the trail exported |

## Searching it

`GET /governance/audit` — the latest first, a page at a time (`limit` up to
200; `next` reads on; a cursor it did not hand out, 422): filtered by `category` (several), `action` (exact, or
`source.*`), `outcome`, `actor`, `target_type`, `target_id`, `since`,
`until`, `request_id`, and `q` — words in the action, the target, the
detail. `GET /governance/audit/{id}`: one event, and what else its request
did. `GET /governance/audit/export`: the same search as CSV, up to 10 000
events — the export itself recorded, with its filters. A cell that a
spreadsheet would read as a formula (`=`, `+`, `-`, `@`) is quoted: a name
someone chose never runs in the reader's spreadsheet.

In the app: Sécurité & gouvernance → **Journal d'audit** — filters by
category, outcome, person, period and words; each event said in words, who
did it (LEKA, for whom), opened on where it came from and its request.

## Who may

| | Permission | Who |
| --- | --- | --- |
| Search, read, export | `audit:read` | admins and the owner — or a role of the workspace's own granting it (LEKA-403) |
| Change the retention | `audit:manage` | **the owner only** — shortening it erases evidence; no role of the workspace's own may grant it |

A member reads nothing of it. A workspace sees its own trail, never
another's.

## Retention

- **365 days by default**; the owner sets **90 days to seven years**
  (`PUT /governance/audit/settings`), the change itself recorded, before and
  after.
- `audit-sweep`, daily at 04:15: every workspace's events older than its
  retention are deleted, and the sweep **says so in the trail**
  (`audit.expired`, how many, older than when) — one workspace at a time:
  one that fails is logged, the others are swept all the same. Idempotent.
- The workspace's deletion takes its trail with it, at its erasure.
- A person's account deleted: their events stay, the person forgotten
  (`actor_id` empty) — what was done remains, not who it was. Where they
  were the **target** (a role changed, a sign-in), the id stays: an
  identifier that no longer leads to anyone, no name, no address — the
  trail never holds an email or a name of a person.

## Nothing changes a record

- **No route** changes or deletes an event: the API reads, exports, and
  sets the retention — nothing else.
- **The database refuses it**: a trigger rejects every `UPDATE` of
  `audit_events` — but forgetting a person with their account — and every
  `DELETE` but two: the retention sweep, which declares itself in its own
  transaction (`SET LOCAL leka.audit_sweep`), and the workspace's own
  deletion. An attempt fails `restrict_violation`, "append-only".
- The specialised trails are append-only the same way (LEKA-402, 403, 406).

## Not yet

- Reads of ordinary data are not recorded one by one — only reads of
  **restricted** entities, and of those, the entity's own page
  (`GET /knowledge/entities/{id}`): a restricted entity met in a search, the
  graph or a context is not recorded there. Recording every page viewed
  would bury what matters, and the access decisions already keep every
  refusal.
- **Where from** is the address as the rate limiting reads it — the first
  `X-Forwarded-For` hop, which the deployment's proxy sets; a client
  reaching the API around that proxy could choose it.
- No signature chaining the records to one another: the guarantee is the
  database's, for those with no direct access to it. Exporting the trail
  regularly to the customer's own storage is the step after.
- The specialised trails (`access_decisions`, `governance_events`,
  `ai_control_events`) keep their own retention: as long as the workspace.
