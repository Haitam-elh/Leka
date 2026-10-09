# Capabilities — what LEKA can do (LEKA-393, LEKA-394, LEKA-395)

One model for everything LEKA can do — its own rules over the company model
(LEKA-388) and the agents written as markdown (ADR 004) — so that what routes
an intention to them (LEKA-398) and what runs them (LEKA-395) read the same
thing. Code: `api/leka/capabilities/` — `definition.py` (pure: the model, its
lifecycle, availability, discovery), `registry.py` (where definitions come
from), `catalogue.py` (their history, and the catalogue for a workspace), the
routes in `api/leka/api/capabilities.py`; the model gateway and router in
`gateway/` ([model-gateway.md](model-gateway.md)); what runs the agents in
`runtime.py`, `tools.py`, `runs.py` ([agent-runtime.md](agent-runtime.md));
the router that sends an intention to them in `router.py`
([capability-router.md](capability-router.md)); workflows, composing them,
in `workflow.py`, `workflow_runs.py` ([workflows.md](workflows.md)).

## 1. A capability

| Field | |
| --- | --- |
| `key` | unique, kebab-case — an agent's `name`, an analysis's name |
| `title`, `summary` | what people call it; **when to use it** — what routing reads first |
| `category` | architecture, development, infrastructure, operations, security, compliance, data, documentation, project_management, business, knowledge |
| `kind` | `rules` (LEKA's own, run in the analysis), `model` (LEKA's own, written by a language model through the gateway — the synthesis, LEKA-394), `agent` (instructions a model follows — LEKA-395) or `workflow` (several of the others composed into one controlled run — LEKA-397, [workflows.md](workflows.md)) |
| `version` | semver |
| `lifecycle` | `draft` → `review` → `active` ⇄ `deprecated` → `retired`; only active and deprecated run; **retired is final** |
| contract | `inputs` (name, type text·number·boolean·choice·entity, required, choices), `output` (finding, analysis, document, proposal), `formats` (json, markdown, pptx, pdf, docx, xlsx, csv) |
| needs | `sources` — each a source kind, or alternatives (`confluence|microsoft_365`); `model` — run by a language model, and `model_needs` — what that model must do: a structured answer, tools, a context this long, a quality at least: **the router picks the model by them** ([model-gateway.md](model-gateway.md) § 3) |
| who | `permission` (default `intention:create`), `mode` (`read_only`, `proposes_action`), `risk` |
| discovery | `goals` (LEKA-385), `kinds` (LEKA-373), `entity_types`, `examples` (how people ask for it) |

Checked when the catalogue loads — a key, a version, a category, a contract
that cannot be, an entity type, a source kind or a permission LEKA does not
know: **the catalogue refuses to load** (a test loads the repository's on
every CI run). Two capabilities never share a key.

## 2. Where they come from

- **Agents** — `agents/**/SKILL.md` (ADR 004, [agents/README.md](../agents/README.md)):
  the front matter says the fields above; the body is the instructions.
  **Its lifecycle is `agents/registry.yaml`'s `status`** — an agent missing
  from the index is a draft: going live is a line there, reviewed in a pull
  request. The index's version must be the file's.
- **LEKA's own** — the analysis's nine capabilities (LEKA-388) and its
  synthesis (LEKA-394), declared by
  `leka.intentions` with `provide(…)` when it is imported, as every module
  declares its tables for `leka/schema.py`: `capabilities` sits below
  `intentions` and never imports it.

**In the image**: `agents/` is at the repository's root, outside the API's
build context; `cd.yml` gives it by name (`build-contexts: agents=agents`),
`api/Dockerfile` copies it to `/app/agents` (`LEKA_AGENTS_DIR`). By hand:
`docker buildx build --build-context agents=agents api`.

## 3. Its history

LEKA's catalogue, no customer's (`capability_registrations`,
`capability_events`, no `workspace_id`):

- each version of each capability **registered once**, with what it is — its
  fingerprint (everything but its lifecycle; `model_needs` at its default
  left out, so what was registered before LEKA-394 stands) and what the catalogue says of
  it (an agent's instructions never: hashed only); a new version supersedes
  the last;
- a move its lifecycle allows, kept; **a move it forbids** (retired → active),
  **a change without a new version**, **an older version** — refused, once,
  said why (`refused`): what was registered stands, and the capability is not
  used;
- every event (registered, lifecycle changed, superseded, refused) is kept —
  **the database refuses to change one**.

Synced when the API starts, and every hour (`capability-registry-sync`), one
process at a time (an advisory lock).

## 4. For a workspace and a person

Whether it can be used here, now — **every reason it cannot**, not the first:

| Reason | |
| --- | --- |
| `refused` | the catalogue refused this version (§ 3) |
| `lifecycle` | draft, in review, retired |
| `disabled` | turned off in the workspace — an admin, saying why |
| `missing_source` | none of the sources it needs is connected (active or degraded) |
| `no_model` | it is run by a model, and **no model this workspace can reach does what it needs** (LEKA-394: asked of the router, per workspace — its own model, LEKA's) |
| `no_runtime` | an agent, where agents cannot run — none since the runtime ([agent-runtime.md](agent-runtime.md), LEKA-395) |
| `not_permitted` | the person's role lacks its permission |

Deprecated: used, and said (`notes`). Turned off, **the analyses no longer
run it** (`select(…, disabled=…)`: the choice says `disabled`).

## 5. Discovered

`discover(definitions, query, availabilities)` — what the catalogue answers
(`POST /capabilities/discover`): by the intention's goal (3), its kind (2), what it acts on (1 each, at most
2), the words it is asked in (1 each, at most 3); each match with its
reasons; never retired; the unavailable left out when asked
(`available_only`). `check_input(contract, given)` says what is wrong with
what a capability is given — what the runtime refuses (LEKA-395). Routing
an intention — its context read, policies applied, a fallback — is the
router's ([capability-router.md](capability-router.md), LEKA-398).

## 6. The API

| Route | | Permission |
| --- | --- | --- |
| `GET /capabilities?view=all|mine&category&kind&lifecycle&available&q&sort` | the catalogue — what runs, unless every lifecycle is asked; most used first | `workspace:read` |
| `GET /capabilities/summary` | available of how many, added this month, by category, this week's runs against the last, the analysis time, by day, the most used, the latest added | `workspace:read` |
| `POST /capabilities/discover` | ranked, each with why | `workspace:read` |
| `GET /capabilities/{key}` | one — its versions, its history, its week | `workspace:read` |
| `PUT /capabilities/{key}/settings` `{enabled, reason}` | on, or off saying why (422 without) | `workspace:update` |
| `PUT` · `DELETE /capabilities/{key}/favourite` | kept at hand — « Mes capacités » | `workspace:read` |

**An agent's instructions are never sent.** Usage is read from what the
workspace's analyses ran (`intention_analyses.steps`: what ran, failed,
how long).

## 7. In the app

**Capacités** (mockup 13): the figures — available of how many, categories,
runs this week against the last, the analysis time; by category, searched,
sorted; each capability in words (LEKA's own in French, an agent as its file
says it) with its category, its runs, and whether it can be used — and why
not, in words: « Source à connecter : Confluence ou Microsoft 365 », « Aucun
modèle de langage ne peut l'exécuter ici »; the week's use by category, the most used,
the latest added; « Demander une capacité » asks LEKA (a new intention).
**Mes capacités**: the starred. **Configuration**: every capability, turned
on or off by an admin, saying why. A capability's sheet: what it takes and
delivers, what it needs and whether it is there — **the model that would run
it here, chosen by what it needs** (« Gemini 3.8 Flash (LEKA), choisi selon ses
besoins ») — who may use it, its versions and history, its week.

## 8. The first agent

`agents/architecture/application-architecture` — **Architecte applicatif**:
the application architecture of a business journey on a perimeter, as a deck
(business layer in ArchiMate 3.0.1, application layer as sequence diagrams,
business rules, RACI, points to confirm, sources), built only from the
documentation (Confluence or SharePoint), never invented. Version 18.0.0 —
the prompt's v18, kept as written. Takes `parcours`, `perimetre`,
`vue_applicative`; delivers `pptx` and `pdf`. Registered and active; run by
the agent runtime (LEKA-395, [agent-runtime.md](agent-runtime.md)) through the
model gateway (LEKA-394) — its deck delivered as markdown, its PPTX and PDF
said pending.

## Not yet

- **What an agent delivers as files** (an architecture deck as PPTX and PDF):
  rendered from what the runtime delivers; each agent declares its own
  (`formats`).
