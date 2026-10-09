# Workflows (LEKA-397)

Several of LEKA's capabilities composed into one controlled, multi-step
run: ordered steps, dependencies between them, conditions that choose the
path, failures handled explicitly and retried where it makes sense, every
run and every step kept. Code: `api/leka/capabilities/workflow.py` (pure:
the model, the builder, conditions, order, a run's states),
`workflow_runs.py` (the engine, its executors, the sweep), the workflows
themselves in `api/leka/capabilities/workflows/*.yaml`; LEKA's own analyses
as steps in `api/leka/intentions/workflow_steps.py`; the routes in
`api/leka/api/workflows.py`.

## 1. A workflow

A YAML file in `api/leka/capabilities/workflows/` — content, reviewed in a
pull request like an agent (ADR 004), shipped with the API:

```yaml
key: incident-review                 # kebab-case, unique among capabilities
title: Revue d'incident
summary: Use when an incident must be reviewed end to end — …   # when to use it
category: operations
version: 1.0.0                       # semver
lifecycle: active                    # draft, review, active, deprecated, retired
goals: [explain_cause, investigate]  # what routes to it (LEKA-398)
kinds: [diagnose]
entity_types: [service, application, incident]
inputs:                              # what it takes, as a capability's contract
  - {name: deck, type: boolean, required: false}
steps:
  - id: incidents                    # a word, unique in the workflow
    uses: incidents                  # a capability: LEKA's own rules, or an agent
    retry: {attempts: 2}             # 1 to 3 — a retryable failure tried again
  - id: changes
    uses: changes
    after: [incidents]               # runs once these ended
    when:                            # runs only if this holds
      any:
        - {step: incidents, found: incident.no_cause}
        - {step: incidents, status: failed}
  - id: documentation
    uses: documentation
    after: [incidents]
    on_failure: continue             # stop (the default) or continue
  - id: deck
    uses: application-architecture
    after: [documentation]
    with:                            # what its capability is given
      parcours: {input: parcours}    # one of the workflow's inputs
      perimetre: {value: Digital}    # or a literal
```

**A workflow is a capability** — of kind `workflow`, in the catalogue
([capabilities.md](capabilities.md)): registered, **versioned like any
other** (its steps are fingerprinted: changing them without a new version is
refused, said), its lifecycle, turned on or off by an admin, found by the
router ([capability-router.md](capability-router.md)).

**Checked when the catalogue loads** — the workflow refused, and the
catalogue with it, when: its key, version, category, title or summary
cannot be; two steps share an id; a step uses a capability LEKA does not
have, or one that cannot be a step (a model's synthesis); it gives a
capability what it does not take, or not what it requires; it runs after a
step that does not exist, or the steps wait on each other (a cycle); a
condition reads a step it does not run after, or an input the workflow does
not take; more than 3 attempts; an unknown field. A test loads the
repository's on every CI run.

## 2. Conditions

Structured — never code, nothing evaluated:

| Condition | Holds when |
| --- | --- |
| `{step: x, status: succeeded}` (or a list) | step `x` ended so — `succeeded`, `failed`, `skipped` |
| `{step: x, found: incident.no_cause}` | step `x` found that code (a finding of LEKA's analysis) |
| `{input: deck, equals: true}` | the workflow was given that |
| `{all: […]}` · `{any: […]}` · `{not: {…}}` | each · one of · not |

A step whose condition does not hold is **skipped**
(`reason: condition_false`); what runs after it still runs — a skipped step
has ended.

## 3. A run

```
queued ──▶ running ──▶ succeeded
   │          ├──────▶ failed  ──retry──▶ queued   (from where it failed)
   └──────────┴──────▶ cancelled
```

Each step: `pending → running → succeeded | failed`, or `skipped`, or
`not_reached` (the workflow stopped, was cancelled or abandoned before it).

1. **Asked** — `POST /workflow-runs`: the workflow as the catalogue holds it,
   usable here by this person; what it takes checked; **LEKA's own steps read
   an intention's context**: a workflow using them runs for an intention
   (`needs_intention` otherwise). Kept queued, every step pending, **its
   steps as they are now** (`spec`) — what this run runs, whatever its file
   says later. Committed, then a job on `leka:high`.
2. **Claimed** by one worker (a single UPDATE from `queued`); the person who
   asked must still be in the workspace — their role read now.
3. **Driven** — until nothing is left: the steps in the order of their
   dependencies (as written where they do not depend on each other), one at
   a time; a step runs once every step it runs after has ended, and when its
   condition holds. Each step's capability is checked **as it stands for
   this person** — not usable: the step fails `unavailable`.
4. **A step's attempts** — run by the executor of its capability's kind:
   - **LEKA's own rules** (`leka.intentions.workflow_steps`): the analysis's
     capability on the intention — its understanding, its context, the parts
     it reads — isolated, as the analysis runs it; what it found (its codes)
     is what later conditions read;
   - **an agent** (`agent_step`): a run of its own
     ([agent-runtime.md](agent-runtime.md)), executed then and there; what it
     delivered is the step's (`ref: agent_run:<id>`).

   A failure that says trying again may mend it (a timeout, an error, no
   model answering) is tried again while its attempts last; one that says it
   cannot (`unavailable`, `needs_intention`, `no_material`, refused) is not.
5. **A failure** — `on_failure: stop` (the default): the run fails
   (`error: step_failed`, `failed_step`), what was not run is not reached;
   `continue`: the step stays failed, the run goes on.
6. **Ended** — succeeded when no step that stops it failed.

**Retry** — `POST /workflow-runs/{id}/retry`: a failed run queued again, its
failed and not reached steps pending again, **what succeeded or was skipped
kept** and not run again. Not when what failed it cannot be mended by
trying again (`not_permitted`). **Cancel** — queued, it never runs; running,
it stops between two steps. **The sweep** (`workflow-runs-sweep`, hourly at
44): running past an hour, queued past six — failed `abandoned`, retryable.

## 4. What is kept

- `workflow_runs` — the workflow, its version and steps as asked, who asked,
  for which intention, what it was given, its status, the step that failed
  it, how many retries, when.
- `workflow_run_steps` — each step: its status, attempts, what it found
  (`output`: codes, summary, counts, `ref`), why it was skipped or failed.
- `workflow_run_events` — **append-only** (the database refuses to change
  one): queued, started, step_started, step_retried, step_succeeded,
  step_failed, step_skipped, succeeded, failed, cancelled, retried — each
  with its step, attempt, error, how long.
- Its versions: the catalogue's (`capability_registrations`,
  `capability_events`).

## 5. The API

| Route | | Permission |
| --- | --- | --- |
| `GET /workflows` | every workflow, its steps (conditions structured), whether it can run here and why not | `intention:read` |
| `GET /workflows/{key}` | one — its versions and history: `GET /capabilities/{key}` | `intention:read` |
| `POST /workflow-runs` `{key, inputs, intention_id?}` | 202, queued | `intention:create`, and the workflow's own |
| `GET /workflow-runs?key&status&limit` | the workspace's runs | `intention:read` |
| `GET /workflow-runs/{id}` | one: each step's state, every event | `intention:read` |
| `POST /workflow-runs/{id}/cancel` | by who asked, or who may approve; 409 ended | `intention:create` |
| `POST /workflow-runs/{id}/retry` | a failed run, from where it failed; 409 otherwise | `intention:create` |

Refused, nothing kept: no such workflow (404); the person's role (403); not
usable here — a step it cannot do without not usable (`step_unavailable`;
a conditional or passed step not usable is only noted) — what it takes not
given (`inputs.<name>`), LEKA's own steps without an intention
(`intention_id`) — 422, each reason in `details`.

## 6. In the app

On a workflow's sheet (**Capacités**): its **Étapes** in order — what each
uses, after which, on what condition in words, its attempts, whether its
failure stops the rest; **Lancer le workflow** for an intention chosen; its
**Exécutions** — where each stands, a failure said at which step and
**Reprendre** from there, each step's state and why. Routed to on an
intention (LEKA-398), it is offered there, for that intention.

## 7. The workflows

| Key | Steps |
| --- | --- |
| `incident-review` | incidents (2 attempts) → changes, when nothing explains it → ownership → documentation (its failure does not stop it) |
| `architecture-dossier` | standing → dependencies, documentation → the architect's deck, when asked (`deck`) and there is documentation |

## Not yet

- Steps run one at a time — independent steps in parallel later.
- Workflows written in the app (a builder screen): they are files, reviewed.
- Orchestrating capabilities without a written workflow (LEKA-399).
