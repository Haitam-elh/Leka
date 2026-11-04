# The model gateway and router (LEKA-394)

Every LEKA feature that needs a language model — Intentions, Mon
environnement, Capacités, the agents, the skills, the workflows — asks
through one gateway, and none depends on a vendor. Architecture rule 7: **one
module calls a model**, `leka.capabilities`; the gateway is
`api/leka/capabilities/gateway/`.

```
a feature asks — a Request: what it is for, its messages, how much it asks
(a tier), the shape of the answer it wants, the tools it offers
    │   and says what it needs — Needs: a structured answer, tools, a
    │   context this long, a quality at least
    ▼
routing.py     the model the LEKA team assigned to the agent, or to LEKA's
               own work (agents/models.yaml, LEKA-530), then the fallbacks
               approved for it — after the company's own model under an
               Enterprise contract; what cannot do what is asked passed over,
               and why; never a model chosen per task
    ▼
service.py     each tried: a temporary failure tried again, then the next
               approved model (three at most); a structured answer checked against its
               model, asked again when it does not match; tools called until
               the model answers; every attempt kept (model_calls)
    ▼
a provider     google.py · openai.py (Mistral, OpenAI or compatible, Azure
               OpenAI) · anthropic.py — plain HTTP, no vendor SDK
```

## 1. The contract

`contract.py`. A provider is **one class**: its `name`, `title`, the URL it
defaults to, what a workspace bringing its own must give (`needs`: key, url,
model), and `complete(call, client) -> Completion`. Registered with
`register_provider(...)`; **nothing else in LEKA changes** to add one.

| | |
| --- | --- |
| `Request` | `purpose` (`intention.understanding`, `capability.synthesis`, `agent:<key>`…), `messages` (system, user, assistant — with the tool calls it made — tool results), `tier` (`fast`, `standard`, `deep`), `max_tokens`, `temperature` (none: the model's own), `output` (a JSON schema), `tools`, `tool_choice` (auto, required, none), `ref` (what it is about: `intention:<id>`) |
| `Completion` | the text, or the tool calls (each with the signature its provider needs back); **who answered** — provider, model, and the version it said (Gemini's `modelVersion`, the dated model behind `-latest`); tokens in, out, thinking; latency; finish reason; the provider's request id |
| `ProviderError` | `retryable` — busy, rate-limited, down, a dropped connection, an empty answer — and how long it asks to wait (`Retry-After`); not retryable — a refused key, a bad request, a refused address |

**Structured output**: the schema is a pydantic model's, its references
inlined (`plain_schema`) — Gemini's `responseJsonSchema`, the chat
completions' `response_format: json_schema`, Anthropic's one tool it must
call. The gateway reads the answer against the model (`structured()`): an
answer that does not match is asked again, then of the next model — and kept
as `invalid`, with what it cost.

**Tools**: function declarations (Gemini), functions (chat completions),
tools (Anthropic). `run_tools(request, handlers)` calls the ones asked, gives
the model what they returned — a tool that fails says so to it, one it made
up is said unknown — until it answers, six rounds at most (`rounds`);
`conclude` makes the last round answer — the tools not offered again —
rather than end in `ToolRoundsError`. A shape asked beside the tools
(`request.output`) is how the answer comes back once it stops calling them:
Gemini 3 and the chat-completions APIs take both. **Gemini 3 signs the
calls it makes**: the signature goes back with the call, or it refuses the
conversation.

## 2. The models

`profiles.py` — what each model takes in and gives back, whether it gives a
structured answer and calls tools, how good (1 enough to classify · 2 good
analysis · 3 the best) and how fast (1–3), and **its list price per million
tokens, with the date a published change applies**.

| Provider | Model | Context | Quality | Price in / out ($ per M tokens) |
| --- | --- | --- | --- | --- |
| Google | **Gemini 3.8 Flash** (`gemini-3.8-flash`) — **LEKA's default** | 1 048 576 | 3 | 0.75 / 3.75 until 2026-12-31, then 1.50 / 7.50; read from its cache 0.075, then 0.15 |
| Mistral | Mistral Large (`mistral-large-latest`) | 256 000 | 3 | 0.50 / 1.50 |
| Mistral | Mistral Medium, Small | 128 000 | 2, 1 | not published: not estimated |
| Anthropic | Claude Sonnet 5, Haiku 4.5 | 1 000 000, 200 000 | 3, 2 | 2 / 10, 1 / 5 |
| OpenAI (LEKA-491) | GPT-4.1 (`gpt-4.1`), GPT-4.1 mini | 1 047 576 | 3, 2 | 2 / 8 (cached 0.50), 0.40 / 1.60 (cached 0.10) |

**Images** (`vision`, LEKA-491): Gemini 3.8 Flash, Claude Sonnet 5 and Haiku
4.5, GPT-4.1 and its mini **read** images given to them; Mistral's do not.
None of them is used to **make** an image: reading one is not generating one.
A task that sends images says so (`Needs.vision`), and a model that cannot read
them is passed over (`vision`).

A model the table does not know — a company's Azure deployment, its own
model — is taken cautiously: 128k tokens in, structured output and tools as
its provider's API offers them, quality 2, **no price: its cost is not
guessed**. Gemini 3 is left at its own temperature; how long it thinks is the
tier (`thinkingLevel` low, medium, high), its thinking billed as output —
and counted in `max_tokens`: a task gives it room, or its answer is cut
short, paid for, and useless.

**What a provider read from its cache** is billed less: Gemini caches the
start of a conversation it was sent before — every round of tools sends the
instructions and what was read again — and bills those tokens a tenth
(ai.google.dev/gemini-api/docs/pricing, read 2026-10-09). Read per call —
Gemini's `cachedContentTokenCount`, the chat-completions APIs'
`prompt_tokens_details.cached_tokens`, Anthropic's `cache_read_input_tokens`
— kept (`model_calls.tokens_cached`) and priced at the model's cached price
when it is published, else as any token in: what a call cost is what was
billed.

## 3. Routing: the model assigned to each agent (LEKA-530)

`routing.py`, pure. **No model is chosen per task while it runs**: each agent
runs on the model the LEKA team validated for it, every step of it — and so
does LEKA's own work (reading an intention, its analysis, its answer, the
company model's enrichment, the interface's words). The order is a policy:

1. **the workspace's own model**, under an Enterprise contract that brings it
   (§ 6) and when it is on — its account, its contract, its data residency;
   when it said **"ours only"** (`exclusive`), nothing else, even when it
   fails. A step its own model cannot do (a code change asked of a mid-range
   model) goes to the strongest model of its provider, on its key (route
   `own_stronger`);
2. **the model assigned to the work** — the agent's, from the purpose of the
   call (`agent:<key>` or `agent:<key>:<step>`), or LEKA's own work's — in
   [`agents/models.yaml`](../agents/models.yaml) (route `assigned`);
3. **the fallbacks approved for that same agent**, in their order (route
   `fallback`). **None approved: none tried** — the agent tries its model
   again (§ 4), then says it failed. Never another model LEKA holds a key
   for, never an untested one in its place.

A model that cannot do what a step asks — a structured answer, tools, a
context that long, a quality that high, images — **is not tried, and why is
kept** (`Passed`: structured, tools, context, quality, vision, no_key,
exclusive). That never happens to a validated agent:
`tests/test_model_assignments.py` holds every agent's model, and every
fallback approved for it, to every step it asks (its definition's
`ModelNeed`, [capabilities.md](capabilities.md) § 1, and the hardest steps of
a code change, quality 3). The catalogue says whether the assigned model can
run each capability here; a capability's page says it is ready, on LEKA's
model or the company's — never which one.

### Assigning a model to an agent

`agents/models.yaml`, one line per agent of `agents/registry.yaml` (the test
fails on an agent without one, or a line without its agent), and one for
LEKA's own work:

    operations:
      model: google:gemini-3.8-flash
      fallbacks: []
    agents:
      code-review:
        model: google:gemini-3.8-flash
        fallbacks: [mistral:mistral-large-latest]   # once tested for it

Changing one is **engineering work, by the LEKA team**:

1. **Try the candidate on the agent's real work**, outside production:
   `LEKA_LLM_TRIAL_MODEL=provider:model` puts every agent on it (refused in
   production, `config.py`); run the agent on its usual requests — its
   instructions, its tools, the deliverable it owes.
2. **Compare**: what it delivered (the deliverable checks, the intention
   benchmark, [benchmarks/intentions.md](benchmarks/intentions.md)), how
   reliably (`python -m leka.metering.cli usage --agent <key> --by model`:
   failures, invalid answers), how fast, what it cost
   (`python -m leka.metering.cli compare`).
3. **Write it** in `agents/models.yaml`, the comparison in the pull request.
   A fallback is the same work, for that agent.

LEKA needs the key of each provider the file names (`LEKA_<PROVIDER>_API_KEY`).

## 4. Retry and fallback

`LEKA_LLM_RETRIES` (1): a failure the provider says is temporary is tried
again — after what it asks, else 1 s, 2 s…, never more than 10 s — then the
agent's next approved model, if it has one. **Three models at most** for one
request. A workspace's model
refusing its key is **marked failed**, for its admin to see, and LEKA's
answers instead (unless "ours only"). A `budget` (seconds) bounds it all —
reading an intention while its asker waits: 12 s. **Nothing answers: a
`NoModelError`**, never something made up — the caller says so, or does
without (the rules).

## 5. What is kept

`model_calls` — one row per attempt: purpose, ref, tier, provider, model,
the version that answered, the route (own, own_stronger, assigned,
fallback, trial; `default`, `alternative` and `task` in what was kept before
LEKA-530) and which try, whose model (LEKA's or the workspace's), ok · failed ·
invalid and why, tokens in, out, thinking, tool calls, **whether the
provider said what it used** (`usage_reported`: an answer without it reads 0
tokens — not known, not free; none for the calls kept before LEKA-430),
**the cost at the rate in force** and that rate (`rate_id`; none when the
model has no rate, or its usage was not said), latency, the provider's
request id. What answers « why did LEKA say that? » and « what does it
spend? » — **for the LEKA team only** (LEKA-530):
`python -m leka.metering.cli usage` ([metering.md](metering.md) § 6). No
customer route serves its tokens or its cost
(`tests/test_usage_report.py` walks every route of the API).

The rates are in the database (`model_rates`, LEKA-430): what a model costs
from a day on, seeded with the list prices above — a new price is a new
rate, a rate never rewritten. Routing still reads the list prices here.
[metering.md](metering.md) says how a rate is added.

## 6. A workspace's own model (an Enterprise contract)

`workspace_models` — one per workspace: provider (Google, Mistral, OpenAI or
compatible, Azure OpenAI, Anthropic), the model or the Azure deployment, its
address and API version (Azure), **its key encrypted** (`secret_box`,
rotated with the others by `scripts/rotate_encryption_key.py`), never sent
back — its last four characters are; on or off; "ours only"; whether it
answered when last tested. A customer's address is reached through the
connectors' transport: **public https only**, pinned against DNS rebinding.

**Brought under an Enterprise contract only** (the catalogue's `own_llm`,
LEKA-530): a public plan is refused (`403 plan_required`). A model brought
before that is kept, still answers, is said in Paramètres, and can be
removed — never changed again there. Customers never choose, compare or
switch LEKA's models: `PUT /models/default` and `GET /models/usage` are gone
(a choice kept from before, `workspace_model_defaults`, is never read).

**Microsoft 365 Copilot** is no API a platform can call; a company on Copilot
holds **Azure OpenAI** — that is what it plugs in.

| Route | | Permission |
| --- | --- | --- |
| `GET /models` | whether its contract brings a model of its own, the providers it may bring and what each takes, its own model — never LEKA's models, their prices, an order of answer | `workspace:read` |
| `PUT /models/settings` | bring or change its own, under the contract — a key needed to bring one, and again for another provider; left out, kept | `workspace:update` |
| `DELETE /models/settings` | back to LEKA's, on any plan | `workspace:update` |
| `POST /models/settings/test` | asked a few words: did it answer, how fast, which version — LEKA's never tried in its place | `workspace:update` |

In the app: **Paramètres › Le modèle de votre entreprise**, under the
contract only.

## 7. Who uses it

Through the LLM runtime (LEKA-429, [llm-runtime.md](llm-runtime.md)): a
feature gives it a task — its context, the shape of its answer, its check —
and gets an execution back; it never imports the gateway.

- **An intention, read** (`leka/intentions/reading.py`): the model reads the
  words with the rules — the goal, a question or a request, what is asked in
  a sentence. It settles a goal the rules could not tell (what stopped an
  intention for a question); it never changes the things named, the actions
  asked, nor a request to act — those stay the rules'. Kept in the
  understanding: `restated`, `read_by` (provider, model, version).
- **An analysis, answered** (`leka/intentions/writing.py`): the
  **synthesis** capability, written by a model after LEKA's rules ran, from
  what they found and nothing else; each point cites the findings, causes
  and evidence it rests on — a citation the result does not hold is
  dropped, an answer resting on nothing is not kept. The intention's summary
  is that answer. It runs on LEKA's own work's model, which its needs (a
  structured answer, quality 2) are held to.
- **The agents** (LEKA-395, [agent-runtime.md](agent-runtime.md)) —
  `run_tools`, `deep` tier, on the model assigned to the agent; each call
  kept with its run (`agent_run:<id>`).

No model configured, or none answering: the rules read and analyse, as
before LEKA-394, and the screens say so.

## 8. Configuration

Which model each agent runs on: [`agents/models.yaml`](../agents/models.yaml)
(§ 3), never an environment. `LEKA_LLM_RETRIES`, `LEKA_LLM_PROVIDER` and
`LEKA_LLM_API_URL` (a provider reached at another address), `LEKA_LLM_TRIAL_MODEL`
(a candidate, outside production), `LEKA_GOOGLE_API_KEY`,
`LEKA_MISTRAL_API_KEY`, `LEKA_ANTHROPIC_API_KEY`, `LEKA_OPENAI_API_KEY` —
[configuration.md](configuration.md). The keys are **server-side only**:
never sent to the browser, never logged, rotated every 90 days
(`RotateEvery`). A Google AI Studio key **on a project with billing on**: on
the free tier, Google may use what is sent to improve its products.

### Before turning a provider on in production (LEKA-491)

What each is sent is **the request only**: the task's instructions, the
context LEKA assembled for it (what the company model holds about the things
asked — names, owners, states, extracts of its documents and tickets, within
what the asker may see), the question, the tools' results. **No credential,
no secret, no source's raw dump.** Before setting a provider's key in
production:

| Provider | Its terms for API data | To check |
| --- | --- | --- |
| Google (Gemini API) | not used to train on a paid project; abuse logs kept for a time | billing on for the project |
| Anthropic (Claude API) | API inputs and outputs not used to train by default; kept a limited time for abuse checks | the org's retention and zero-retention option |
| OpenAI (API) | API data not used to train by default; kept up to 30 days for abuse checks | zero data retention if the contract needs it; the project's region |
| Mistral | per its API terms | as above |

Then: set the key (`LEKA_<PROVIDER>_API_KEY`), assign its model to the
agents it was validated for (`agents/models.yaml`, § 3), and read
`python -m leka.metering.cli usage --provider <name> --by agent` on the first
days. A provider without a key is passed over — said `no_key` — and only an
approved fallback answers in its place: never a loop, never billed twice (a
failed attempt is kept as failed, its tokens as said).
