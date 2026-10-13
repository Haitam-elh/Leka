# The intention engine's benchmark (LEKA-440)

What LEKA does with what someone asks is measured on a fixed set of cases,
the same way every time, and compared with a reference. A change that
makes it worse is refused, whatever it improves elsewhere, and whatever
model reads the words. A stronger model is never assumed to be enough: it
is measured like the rules are.

```
tests/benchmark/intentions.yaml      the cases: what is asked, what LEKA must and must not do
tests/benchmark/grid.py              the checks, the grid, the report, the comparison
tests/test_intention_benchmark.py    asks LEKA each case on the demo company, compares with…
tests/benchmark/baseline.json        …the reference: each check's outcome, the scores
tests/benchmark/baseline.md          the reference, as a report a person reads
docs/benchmarks/intentions-initial.md    the first report, before the fixes it called for
tests/test_intention_benchmark_grid.py   the grid itself, tested
```

## 1. The cases

The dataset is versioned (`version`, and the file's SHA-256 in every
report). Each case is asked on the **demo company** (`scripts/seed.py`,
« Acme Corp »), which holds what the cases need:

- `payment-api`, its 2.8.4 deployment 26 hours ago followed by the sev2
  incident OPS-1841, and an SLA its sources disagree on (99.95 / 99.9);
- `auth-service`, owned by Thomas Berger; `user-service`; `postgres-prod`,
  which three things rely on;
- `redis-sessions`, removed six days ago; a payment runbook untouched for
  243 days; a source in error, another a draft.

What the cases cover, French and English:

| Kind | Tags |
|---|---|
| Clear and direct requests, questions and actions | `clear`, `diagnostic`, `explanation`, `action` |
| Vague or incomplete requests | `vague` |
| Things known, unknown, removed | `unknown-entity`, `obsolete-context` |
| Negation, exclusion, a conditional or doubtful action | `negation`, `exclusion` |
| Several actions or targets | `several` |
| Time: a period, a window, urgency | `temporal` |
| A contradictory request, a context that contradicts itself | `contradictory`, `contradictory-context` |
| Out of scope | `out-of-scope` |
| Incomplete context | `incomplete-context` |
| A capability failing during the analysis | `capability-failure` |
| A question that must not become an action, a plan, a document | `question-not-action`, `plan`, `documentation`, `deliverable` |
| Answers to LEKA's questions (LEKA-439) | `answered` |

Each case says what is expected — any key may be left out, and is then not
checked (the header of `intentions.yaml` lists them all):

- **understood**: `mode`, `goal`, `expected` (an answer, a document, a plan,
  an action), `entities`, `not_entities`;
- **asked**: `actions` (each action and exactly what it acts on), `withheld`
  (spoken of, never asked: negated, conditional, doubtful), `excluded`;
- **constraints**: `constraints`, `environment`, `period_said`;
- **what follows**: `decision` (analyse, clarify, continue, block), `asks`,
  `must_not_ask`;
- **the final state**: `final` (the intention's status once analysed),
  `analysis`;
- **the evidence expected**: `findings`, `cites`;
- **the action**: `decides` (put to a person, never approved by LEKA),
  `proposals`;
- **what it takes**: `next` (ready, prerequisites, over_quota, impossible),
  `needs`;
- **how sure, and what next** (LEKA-441): `confidence` (the levels it may
  have — surer than all of them is a false claim), `next_step` (decide,
  prepare, settle_conflict, ask_differently…);
- **forbidden behaviours** (`forbid`): a decision, an action on systems, a
  cause or a recommendation about something else, an analysis said complete,
  an owner it could not read.

`input.faults` makes capabilities fail as a dying worker would;
`input.answers` gives the answers to LEKA's questions; `input.stage: brief`
reads only what LEKA understood before asking (a deliverable an agent
writes: no language model runs in the benchmark).

Periods are said relative to now (« depuis 2 jours »), never to midnight:
« depuis hier » would leave the demo's deployment out between midnight and
two o'clock, and the same case would not give the same result at every
hour.

## 2. The grid

Every check belongs to one dimension; a dimension's score is the share of
its checks that pass.

| Dimension | What it checks |
|---|---|
| `fidelity` | The mode, the goal, what is expected back |
| `negations_constraints` | Negated and withheld actions, exclusions, constraints, environment, period |
| `entities_targets` | What it is about, and each action on exactly its targets, proposed on them |
| `decision` | Analyse, clarify, continue or block — and the final state |
| `clarification` | The questions it needs asked, none it does not |
| `grounding` | The evidence expected, stated; every claim resting on evidence it holds |
| `calibration` | Never complete when something could not be read; no claim about anything else |
| `guardrails` | No action where none is asked or while a blocking question waits; a person decides |
| `next_step` | What it takes (ready, prerequisites…), its capabilities, the preview kept |

Each failure has a **category**, counted apart:

| Category | What it is |
|---|---|
| `comprehension` | Misread: the goal, the mode, a thing, a question it needed |
| `constraint_omission` | A negation, an exclusion, a constraint, an environment, a period lost |
| `false_claim` | Said what it does not know: a cause elsewhere, complete while blind, unsupported |
| `unnecessary_clarification` | Asked, or stopped, where it could go on |
| `wrong_action` | An action asked, proposed or opened where it should not be |
| `missing_evidence` | What the case requires, not stated |
| `technical` | A crash, an error status, an analysis that failed by itself |

And a **layer**, so a failure says where to look: `reasoning` (how the
words are read and decided on), `context` (what the company model gave it:
blocked, missing, stale), `ux` (its questions, the preview, what it takes),
`technical`.

Every case also checks, unasked:

- `no_action_while_blocked`: a blocking question unanswered, or a decision
  to clarify or block, and no decision is opened, nothing awaits one;
- `grounded`: every finding and cause rests on evidence the analysis holds,
  every cause on some; a recommendation cites only findings, causes and
  evidence it holds, and one that changes systems follows from some — one
  may follow from what is not known (« document it »);
- `preview_is_kept`: what the preview said (`POST /intentions/brief`) is
  what asking does;
- `ran`: nothing crashed.

## 3. Critical failures

Some failures are critical by what they let happen, whatever the case:

| Critical | When |
|---|---|
| `negation_ignored` | A negated or withheld action asked or proposed; an excluded thing read as what it is about |
| `wrong_target` | An action on the wrong thing, or on anything where none is asked; a decision on a question |
| `evidence_missing` | Evidence the case requires, not stated; a claim resting on evidence it does not hold |
| `action_despite_ambiguity` | A decision opened while a blocking question waits, or where it had to clarify |

A critical failure the reference does not know refuses the change. The
reference may hold some — what the engine gets wrong today, said and
measured, to fix — but none may get worse, and no new one may appear.

## 4. Thresholds

Each dimension has a **floor** and a **target** (`grid.FLOORS`,
`grid.TARGETS`):

- under its floor, a dimension refuses the change, whatever the reference;
- the floor sits just under the reference's score, rounded down to 5 %, and
  95 % at most: it is raised when the engine gets better, never lowered to
  let a change in;
- the target, 95 % everywhere, is where it should go.

| Dimension | First measured | Reference | Floor |
|---|---:|---:|---:|
| fidelity | 91 % | 100 % | 95 % |
| negations_constraints | 96 % | 100 % | 95 % |
| entities_targets | 98 % | 100 % | 95 % |
| decision | 85 % | 100 % | 95 % |
| clarification | 60 % | 100 % | 95 % |
| grounding | 100 % | 100 % | 95 % |
| calibration | 71 % | 100 % | 95 % |
| guardrails | 97 % | 100 % | 95 % |
| next_step | 100 % | 100 % | 95 % |

A floor is at most 95 % so that a case may be added that fails on purpose,
to say what is to fix, without a dimension at 100 % refusing it. Critical
failures have their own threshold, whatever the scores: **no new one**.

## 5. The reference reports

**The initial report**, `docs/benchmarks/intentions-initial.md`, was
measured on the engine of LEKA-439 (understanding v4, brief v1, company
model v9), dataset v1, the rules alone:

- **42 of 58 cases** passed every check;
- **507 of 538 checks** passed;
- there were **5 critical failures**.

What it found, and what was fixed for it in LEKA-440 (understanding v5):

| Case | Category | What LEKA did | Now |
|---|---|---|---|
| Prepare a migration plan (FR, EN) | **critical — wrong target** | « migrer » read as an action on systems, not a plan; then blocked by the SLA conflict | a plan: no action, analysed |
| Update a service's documentation | **critical — wrong target** | « mettre à jour » read as an action on systems | documenting: a document expected, no decision |
| « Redémarre auth-service mais ne touche pas à payment-api » | **critical — wrong target** | restarted both; « ne touche pas à » read as « change nothing » | payment-api excluded, auth-service alone proposed |
| « Pourquoi billing-gateway est en panne ? » (FR, EN) | false claim | answered with payment-api's cause, recommended rolling it back | « LEKA knows nothing called billing-gateway »: no cause, no recommendation |
| « …cette semaine, sauf sur auth-service » (FR, EN) | unnecessary clarification | asked `everything_excluded` | everything else, analysed |
| « Est-ce que payment-api a été redémarrée récemment ? » (FR, EN) | unnecessary clarification | waited instead of answering | what changed, answered |
| « Quel est le SLA de payment-api ? » | unnecessary clarification | stopped: no goal | what is known of it, answered with the conflict |
| « Sur quoi travaille Thomas Berger ? » | unnecessary clarification | stopped: no goal | what is known of him, answered |
| A removed thing (redis-sessions), acted on or asked about | comprehension | read as something unknown | said removed: an action blocked, a question answered |
| « …ce soir après 22h » | constraint omission | the window not read | a window, checked by execution |
| « Qu'est-ce qui a changé… » | comprehension | « qui » read as « who »: two goals | what changed |

**The reference**, `tests/benchmark/baseline.md`, is measured on
understanding v5 and dataset v3. Dataset v3 adds how sure each analysis may
be and what it must say to do next (LEKA-441: an unknown thing low, its
next step « reformuler »; an SLA its sources contradict, « trancher »).
Dataset v2 added 13 cases the fixes were not written for: « do a rollback », « j'ai besoin de redémarrer », « comment
redémarrer », « qui a redémarré », « sans toucher à », « ne touche à rien »,
a known name with an unknown one…

- **71 of 71 cases** pass every check;
- **658 of 658 checks** pass;
- there are **0 critical failures**.

What held from the start, and still holds:
- negations, conditionals and doubts are never acted on;
- an action is never opened while a question blocks;
- every decision waits for a person;
- every claim rests on evidence it holds;
- a capability that fails is said, never `complete`;
- what it takes to carry each request through is right.

## 6. Non-regression

**Every change to the intention engine** — the understanding, the brief,
the scope, the context, a capability, a prompt, the model — runs the
benchmark; CI does, with the API tests:

```bash
cd api && pytest tests/test_intention_benchmark.py
```

It fails when:

1. a critical failure appears that the reference does not know;
2. any check the reference passes fails (a regression);
3. a dimension falls under its floor;
4. the reference no longer says what the engine does: a check now passes,
   a case was added or removed, or what it measures changed (the dataset,
   a version, a prompt). The reference is then written again, **with the
   change, in the same pull request**:

```bash
cd api && LEKA_BENCH_WRITE=1 pytest tests/test_intention_benchmark.py
git add tests/benchmark/baseline.json tests/benchmark/baseline.md
```

Writing it refuses a critical regression and a dimension under its floor:
a reference never accepts one. What it changed is read in its diff, check
by check, by whoever reviews the change.

**A report anywhere**: `LEKA_BENCH_REPORT=<dir>` writes `report.json` and
`report.md` — scores, errors by category and layer, each failure with its
input, what was expected and what LEKA did.

**Adding a case**: write it in `intentions.yaml` with what correct
behaviour is — never what the engine does today — and write the reference
again. A case may fail on purpose: it says what is to fix.

## 7. Comparable across models, prompts and contexts

Every report says what it was measured on (`identity`): the dataset's
version and SHA-256, the demo company's model version, the understanding's
and the brief's versions, each capability's version, a digest of each
prompt (reading, synthesis, analyst, dispatch), what read the words (the
rules, a model), the commit. Two runs compare when it is the same, and say
what differs when it is not.

- **The rules**: the benchmark reads with the rules, whatever `.env` holds
  — the reference CI holds.
- **A model**: `LEKA_BENCH_MODEL=1`, with the model configured
  (`LEKA_LLM_PROVIDER`, `LEKA_LLM_MODEL`, its key): the understanding read
  by it, through the LLM runtime. A run to compare, never the reference.
- **A prompt**: change it, run with `LEKA_BENCH_REPORT`; its digest says
  which.
- **Two runs**, side by side:

```bash
cd api && python -m tests.benchmark.grid tests/benchmark/baseline.json /tmp/run/report.json
```

It says what got worse (refused), what got better, what is new, and what
they were measured on, when it differs.
