# The LLM runtime (LEKA-429)

One way for every LEKA feature — Intentions, Mon environnement, Capacités, the
agents, the skills, the workflows — to have a language model do a piece of
work, without knowing which model, or whose. It sits above the model gateway
([model-gateway.md](model-gateway.md), LEKA-394), which knows the vendors,
and below every feature, which knows none.

Code: `api/leka/capabilities/llm.py` — `LLMRuntime`, `Task`, `ContextPack`,
`Execution`, `RuntimeTool`.

```
a Task          what it is for (purpose), its instructions, what is asked,
                the LEKA context that grounds it, the answer's shape and its
                own check, what it needs of a model, its time budget, the
                tools it may read through
   │
   ▼
LLMRuntime.run  its instructions, then LEKA's own rules (GUARDRAILS), then
                the task and its context — apart, as JSON, each context item
                with its id
   │            through the gateway: the model chosen by what the task
   │            needs; retries; fallback; the workspace's own model first
   ▼
checked         its shape (a pydantic model), then the task's check — what
                it cites is in its context… — an answer failing either is
                asked again, then of the next model, and never handed on
   ▼
an Execution    succeeded · invalid · no_model · timed_out · failed — never
                an exception the feature must guess at; who answered
                (provider, model, version), tokens, latency, how many calls
                — kept in llm_runs, its calls in model_calls (run_id)
```

## A task's LEKA context

`ContextPack`: what LEKA knows that grounds the answer, each item with an id
the answer cites, and where it came from.

- `ContextPack.of_context(context)` — a context the Context Engine assembled
  (LEKA-370): its elements as it ranked them, each in the one line it writes
  for a model (`ContextElementRead.text`), with its sources; cut to size
  (24 000 characters by default), what was left out counted.
- `ContextPack.of(items)` — anything else LEKA holds: the things an intention
  names, a service's facts in the company model.

`cites(value)` reads every id an answer cites; a task's `check` compares them
with `context.ids`.

## What it never does: act

A model reads; it never acts.

- A tool given to a model is a `RuntimeTool` whose `effect` is `read`. One that
  would change something raises `SensitiveToolError`: it cannot be offered.
- LEKA's rules, said to every model: use only what is given, cite it, never
  invent; never act on anyone's systems — propose, a person decides.
- What a model says should be done is, at most, said. Only LEKA's intention
  flow carries an action out: a person's decision under the workspace's
  policy (LEKA-390), through the systems it authorized (LEKA-391). The model
  may not make a question a request, add an action, or turn a goal into
  `act` (`intentions/reading.py`); `tests/test_intention_model.py` asks a
  question the model reads as « restart it in production » — no action, no
  decision, no plan.

## Errors and time

| Status | When | What the feature does |
| --- | --- | --- |
| `succeeded` | an answer, in its shape, its check held | uses `value` (structured) or `text` |
| `invalid` | every answer failed its shape or its check | does without: the rules' reading, no written answer |
| `no_model` | no model this workspace can reach does what is needed | does without, says so |
| `timed_out` | its budget spent — tools or not | does without |
| `failed` | every model refused or failed — the last one's error said; tools in rounds without end (`tool_rounds`) | does without |

## Who uses it

| Feature | Purpose | Context | Output | Check |
| --- | --- | --- | --- | --- |
| An intention, read (`intentions/reading.py`) | `intention.understanding` | the things it names | `Reading`: goal, question or request, what is asked in a sentence | its shape; the merge keeps the rules' things, actions and requests |
| An intention, answered — **LEKA's analyst** (`intentions/analyst.py`), the synthesis capability | `capability.synthesis` | what the rules found, a part of the context the Context Engine assembled, the sources — and what it reads through LEKA's nine tools | `Written`: the answer, its points and what each cites | it rests on something it read or was given; what it cites, the analysis's evidence |
| …or, when it cannot, the analysis said in words (`intentions/writing.py`) | `capability.synthesis` | **the context the Context Engine assembled for the intention** | `Written` | it rests on something the analysis or its context holds |
| A description proposed for À valider (`intelligence/enrichment.py`) | `enrichment.summary` | **the company model's facts** about each thing | `Descriptions` | one at least cites a fact it was given |
| An agent (LEKA-395, `capabilities/runs.py`) | `agent:<key>` | the agent's own conversation (ADR 004) | its deliverable | — |

A task can bring its own conversation (`Task.messages`) — an agent's rules
and instructions, as written: the runtime keeps it, and everything else
(routing, tools, budget, statuses, what is kept). The agent runs of LEKA-395
call the gateway from `capabilities/runs.py`; moving them onto
`LLMRuntime.run` is that one call.

**No feature reaches a vendor, nor the gateway:** `tests/test_llm_boundaries.py`
fails a vendor's address or SDK outside `capabilities/gateway/`, and an import
of the gateway outside `leka.capabilities` (and the API of its settings).

## Tools, and a last round that answers

A task with tools (`Task.tools`, read only) may say how many rounds
(`rounds`, 6) and that the last one answers with what was read
(`conclude`) — LEKA's analyst does (intentions.md § 12) — rather than end
`failed`, `tool_rounds`. Its shape (`output`) is asked beside the tools:
once it stops calling them, its answer comes back in it, then checked.

## Never paid for twice

`model_asks`: what a model was already asked about one thing, for one
purpose, and the digest of the facts it was asked on —
`LLMRuntime.asked(purpose, keys)`, `.remember(purpose, digests,
answered=…)`. A background task asks again only once a thing's facts
changed: the descriptions proposed for À valider were asked every hour, the
same things left out for saying too little asked again each time, and paid
for; no longer (intelligence.md § 13).

## What is kept

`llm_runs`: purpose, ref (`intention:<id>`…), status, provider, model,
version, calls, tokens in and out, cost at list price, latency, the context's
reference and how many items it held, the error, when. `model_calls.run_id`
ties each call to it. `GET /models/usage` counts them by status and lists the
latest — and what an intention costs, measured: every call made for it
(`ref` `intention:<id>`), understanding and answer, summed, averaged
(`per_intention_usd`, `intentions`); the share of tokens read from the
provider's cache. Paramètres › Modèle de langage says « Exécutions : 9
réussie(s) · 1 hors délai », « Une intention coûte en moyenne 1,1 ¢, mesuré
sur 12 intention(s) : environ 900 intentions pour 10 $ », and what each use
cost.

## Tested

- `tests/test_llm_runtime.py`:
  - a task done with its context, checked and kept;
  - an answer checked before it is used, and asked again;
  - every ending as a status: no model, every model refused, its budget spent, tools in rounds;
  - a tool that would act refused; a read-only tool called and its answer given back;
  - an agent's own conversation kept;
  - a context given as it was ranked, and cut to size.
- `tests/test_llm_boundaries.py`: no vendor outside the gateway, no feature at the gateway.
- `tests/test_intention_model.py`, end to end on the API, Gemini scripted:
  - an intention read and answered;
  - a request to act kept as the rules read it;
  - an ungrounded answer not kept;
  - a model saying to act sets nothing in motion.
- `web/e2e/llm-runtime.spec.ts`, in a browser:
  - an intention read and answered by the model;
  - the synthesis capability run by the model its needs chose;
  - both counted in Paramètres.

  The browser tests run against a stand-in for Gemini (`web/e2e/model-stub.mjs`). LEKA's default model is pointed at it (`LEKA_LLM_API_URL`), so the real gateway, runtime and checks run without a key, a cost or a network.

The real Gemini 3.8 Flash was checked by hand through the same gateway (2026-10-08): text, then a structured answer, both kept with their cost.
