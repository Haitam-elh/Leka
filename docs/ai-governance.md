# AI governance (LEKA-406)

What a workspace allows its models to do, and for whom: which models may
answer, how much may be asked, what an answer may not carry, which agents
wait for someone to approve them. Decided where a model is called and where
an agent is asked to run; every outcome kept.

Permissions and policies ([permissions.md](permissions.md)) decide **who may
ask**. AI controls decide **what the AI may then do**: a person allowed to
run an agent still gets no answer from a model the workspace refuses.

## Four kinds of control

| Kind | What it says | Settings |
| --- | --- | --- |
| `model_access` | which models may answer this work | `providers` (none: any), `owners` — `leka` (LEKA's account), `workspace` (its own); or `block`: none at all |
| `usage_limit` | how much this work may take | `period` (`day`, `month` — the last 24 h, the last 30 days), `per` (`workspace`, `person`), `max_calls`, `max_tokens`, `max_cost_usd` — at least one |
| `output_check` | what an answer may not carry | `detect` (`secrets`, `personal_data`), `on_finding` (`redact`, `block`, `flag`) |
| `approval` | an agent that waits before it runs | `risk_at_least` (`low`, `medium`, `high`) |

### Which work, for whom

Every control covers what it names, and only that:

- **`purposes`** — the work a model is asked to do, as patterns (`*`, `?`):
  `agent:*` every agent, `agent:security-review` one, `intention.*` the
  reading and answering of intentions. None: all of it. A model call's
  purpose is what the gateway keeps on it (`model_calls.purpose`).
- **`roles`** — `member`, `admin`, `owner`, or a role of the workspace's own
  ([LEKA-403](permissions.md#roles-and-policies-of-the-workspaces-own-leka-403)).
  None: everyone. Work done for nobody in particular — LEKA's own, a
  scheduled job — is covered only by controls naming no role.

**Who the work is for** is set where it is known: the request's person
(`get_current_principal`), and the person a worker acts for — an agent run,
a workflow, an analysis (`hidden_on_behalf`). The gateway reads it on every
call (`governance.current_actor`).

### Several controls

- **Model access**: every control covering the work must allow the model.
  Routing's choices that one refuses are dropped; the others still answer.
  None left: refused.
- **Usage**: every limit covering the work is checked before each call; the
  first one reached refuses it.
- **Output**: every check covering the work looks at **the answer as the
  model gave it** — a redaction never hides from a block what it would find.
  A **block wins**; what the redactions found is taken out, once; a flag
  keeps the answer as it is and says so. A structured answer redacted is read
  and held to what its caller expects again; no longer valid, blocked.
- **Approval**: the first control covering the agent at or above its risk
  holds it.

## Where it is enforced

| Control point | What happens |
| --- | --- |
| The model gateway, **before** a call (`gateway/controls.py`, `Guard.before`) | Model access and usage limits. Refused: `NoModelError(reason="refused" \| "limited")`, no model asked. |
| The model gateway, **after** an answer (`Guard.after`) | Output checks. Blocked: `NoModelError(reason="blocked")`, the answer withheld. Redacted: the caller gets the redacted text (a structured answer is read again from it; no longer valid, blocked). |
| `POST /agent-runs` | Approval: a run covered waits (`awaiting_approval`), nothing queued. |
| A workflow's agent step | Approval: **a workflow does not wait** — the step fails `approval_required`, the control named. |

Every model call goes through the gateway — intentions, agents, workflows,
skills, the LLM runtime — so model access, usage and output checks hold for
all of them, in a request or in a worker. An agent run that a control
refused fails `no_model`, its step saying why (`reason`: refused, limited,
blocked).

## Approval

1. An agent at or above an approval control's risk, asked by someone it
   covers, is kept **`awaiting_approval`** — 202 still, nothing queued; the
   worker leaves it (`not_queued`).
2. Someone who may approve (`intention:approve`) — **never who asked it** —
   approves it (`POST /agent-runs/{id}/approve`): it is queued, and runs as
   any run, its policies checked again when it does. Or rejects it
   (`/reject`): cancelled, never run. A note may say why.
3. Who asked may cancel it while it waits.

Each step is in the run's events (`held`, `approved`, `rejected`) and in the
AI log.

## What is kept, for audit

- **`ai_control_events`** — every outcome: `refused`, `limited`, `redacted`,
  `blocked`, `flagged`, `held`, `approved`, `rejected`; which control (its
  name kept when it is removed), what work (purpose, ref, run), for whom,
  which provider and model, what was found (`aws_key`, `email`…) — **never
  the text itself**. Append-only: the database refuses to change one; the
  person is forgotten with their account.
- **`model_calls.user_id`** — every model call says whom it was for (none:
  LEKA's own work), with what it already kept: purpose, model, version,
  tokens, cost, latency, outcome.
- **`governance_events`** (`subject_type = 'ai_control'`) — every control
  created, changed, deleted: who, when, before and after.

## API

| | | |
| --- | --- | --- |
| `GET /governance/ai/controls` | every control, on or off | any member |
| `POST /governance/ai/controls` · `PUT /{id}` · `DELETE /{id}` | created, changed (its kind kept), removed | `policy:manage` |
| `GET /governance/ai/events?outcome&run_id` | what the controls did | `access:read` |
| `GET /governance/ai/calls?user_id&run_id` | the model calls, whom each was for | `access:read` |
| `GET /governance/history?subject_type=ai_control` | the controls, changed | `access:read` |
| `GET /agent-runs?status=awaiting_approval` | the runs waiting | `intention:read` |
| `POST /agent-runs/{id}/approve` · `/reject` | decided | `intention:approve`, not who asked |

A control that cannot be kept is refused (422) naming the field: a kind it
is not, a model access allowing nothing and blocking nothing, a limit
limiting nothing, an unknown role, a purpose with a space.

## In the app

Sécurité & gouvernance: **Contrôles de l'IA** (each said in words; created,
turned off, removed by who may manage policies), **Exécutions à approuver**
(approve, refuse — never one's own), **Journal de l'IA** (what each control
did, for whom). An agent run says it waits for approval.

## Limits, deliberately

- **Detection is by pattern**: well-known key formats, `password=`-style
  assignments, private keys, JWTs; emails, phone numbers, IBANs, card
  numbers (Luhn-checked). It catches what is shaped like a secret, not what
  a model paraphrases. It is a guard rail, not data loss prevention.
- **Usage is counted from the calls kept** (`model_calls`), answered or
  billed; a call refused by a control is not one. Windows roll: the last 24
  hours, the last 30 days.
- **Approval is for agents.** A workflow does not pause: its agent step
  fails `approval_required`. Run the agent on its own, approved, instead.
  An agent step a control refused (`refused`, `limited`, `blocked`) is not
  tried again: the outcome would not change.
- **A run waiting for approval does not expire**: it waits for a person, who
  approves, rejects, or — who asked — cancels it. Approved, it is queued
  from then: the wait is not counted against it.
- **Only answers are checked**, not the arguments of the tools a model calls:
  an agent's tools are LEKA's own, read-only, and never leave the workspace.
- **A limit `per: workspace` counts all the work it covers**, whoever asked;
  its roles say who is refused once it is reached, not whose calls count.
  To give a role its own budget, count `per: person`.
- **Usage is counted on each call** (one query per limit covering the work,
  indexed on the workspace): fine at today's volumes; a running counter per
  period is the step after.
- The controls are read once per gateway — once per request or job: a
  control changed applies from the next one.
