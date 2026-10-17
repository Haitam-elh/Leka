# LEKA agents

An agent is a **markdown file with YAML front matter**. Not a Python class.

Because an agent is a file in Git, it is versioned, reviewed in a pull
request, reverted like anything else — and adding one requires no
deployment. The reasoning is in
[docs/adr/004-agents-as-markdown.md](../docs/adr/004-agents-as-markdown.md).

**This directory holds content.** The loader that reads, validates and
registers it lives in `api/leka/capabilities/`. The two never mix
(architecture rule 8).

---

## The two rules

### 1. Security

**An agent is text that becomes an instruction executed by a model with
access to a customer's production data.** Treat every agent file as code
running with those privileges, because that is what it is.

- **Anything placed in `vendor/` is reviewed line by line in a pull request
  before it is activated.** Not skimmed. Read, sentence by sentence, by
  someone asking what each one would make a model do.
- **Agents run read-only.**
- **No action is ever executed without explicit human approval that carries
  a name and a timestamp.**

An agent that says "ignore the above and…", that asks for credentials, that
requests data outside its `entity_types`, or that tries to widen its own
scope is rejected. There is no benefit of the doubt on this.

### 2. Mode

An agent in `proposes_action` mode **proposes**. It never executes.

Execution goes through `api/leka/intentions/`, after approval. `mode:
proposes_action` is not permission to act — it is permission to suggest.

### How it runs

The agent runtime (LEKA-395) gives it the context of what it is asked —
only the things of its `entity_types` — and read-only tools, offered by the
permissions of whoever asked; its rules come before the agent's
instructions, and the context and what tools return reach the model as data,
never as instructions. Every run and every step is kept. See
[docs/agent-runtime.md](../docs/agent-runtime.md).

---

## The format

````markdown
---
name: correlate-deploy-with-latency
description: Use when a service's latency degrades and a deployment may explain it.
version: 0.1.0
entity_types: [service, deployment, incident]
requires: [datadog, github]
mode: read_only
risk: low
outputs: finding
origin: internal
---

The agent's instructions, in markdown.
````

| Field | Required | What it is |
| --- | --- | --- |
| `name` | yes | unique, kebab-case |
| `description` | yes | **one sentence saying WHEN to use this agent** |
| `version` | yes | semver |
| `entity_types` | yes | the entity types it operates on |
| `requires` | no | connectors that must be connected for it to run |
| `mode` | yes | `read_only` or `proposes_action` |
| `risk` | yes | `low`, `medium`, `high` |
| `outputs` | yes | the kind of finding it produces |
| `origin` | yes | `internal` or `vendor:<owner>/<repo>` |
| `category` | yes | what it is about, for the catalogue: architecture, development, infrastructure, operations, security, compliance, data, documentation, project_management, business, knowledge |
| `title` | no | how people call it; its `name` otherwise |
| `inputs` | no | what it takes: `{name, type: text·number·boolean·choice·entity, required, description, choices}` |
| `deliverables` | no | the formats it delivers: `pptx`, `pdf`, `markdown`… |
| `goals`, `kinds` | no | the intentions it answers (LEKA-385, LEKA-373) — what routes to it |
| `examples` | no | how people ask for it |
| `permission` | no | what a person needs to use it — `intention:create` by default |
| `tools` | no | the runtime's tools it may be offered — `search_entities`, `read_entity`, `dependencies`, `what_happened` (LEKA-400); every read-only one when it declares none. Least privilege: declare what it needs |
| `skills` | no | the skills of LEKA's library it may be offered, by key — `delivery-metrics`, `blast-radius`… (LEKA-401, [docs/skills.md](../docs/skills.md) § 9); none unless named, each only when it reads nothing beyond `entity_types` |
| `method` | no | the library of guides it works by, read while it runs: a directory under [`_library/`](_library/README.md), e.g. `_library/emilkowalski-skills` — named with the tool `read_method` in `tools`, and only with it. A library is never an agent: the loader skips every directory named `_…` |
| `renders` | no | what LEKA makes of what it delivers — `architecture_deck`: the editable PowerPoint and its PDF on the application architecture template ([docs/agent-runtime.md](../docs/agent-runtime.md) § 6 bis); its `pptx` and `pdf` are then not pending — `code_change`: the change it proposes, diffed, for a person to accept as a pull request (§ 6 ter); its `diff` is then not pending. The code tools `list_files` and `read_file` are offered only to an agent that names them in `tools` |

`requires` names source kinds; alternatives in one entry, `"confluence|microsoft_365"`.

**Its lifecycle is `registry.yaml`'s `status`** (draft, review, active,
deprecated, retired): an agent not indexed is a draft. The capability
catalogue keeps every version; changing an agent without bumping its
`version` is refused, and said — see
[docs/capabilities.md](../docs/capabilities.md).

### `description` is the field that matters

It is what decides whether the agent triggers at all. Everything else
describes an agent that has already been selected; this is the selection.

Write **when to use it**, not what it is.

- ✅ `Use when a service's latency degrades and a recent deployment may explain it.`
- ❌ `Analyses latency.` — triggers on everything, or on nothing.
- ❌ `A powerful agent for incident response.` — says nothing a model can act on.

An unknown field is rejected rather than ignored. A typo in a field that
decides how an agent may behave must not pass silently.

---

## Adding an agent

1. `cp -r _template <category>/<your-agent-name>`
2. Fill in the front matter. Spend your time on `description`.
3. Write the body.
4. Add the row to [`registry.yaml`](registry.yaml).
5. Open a pull request. An agent is reviewed like code, because it is.

Categories today: `architecture/`, `codebase/`, `data/`, `development/`,
`documentation/`, `drift/`, `frontend/`, `incident/`, `infrastructure/`,
`operations/`, `security/` — the library of LEKA-400 ([docs/agent-library.md](../docs/agent-library.md)).
Add one when a new theme genuinely appears — not for a single file.

What an agent works by but is too long for its instructions — a method of
several guides — goes in [`_library/`](_library/README.md), read a guide at a
time with `read_method`. Imported from outside, a library is held to the
same rules as `vendor/`.

---

## Importing a third-party skill

1. Copy it into `vendor/<owner>-<repo>/<skill-name>/`.
2. Keep the upstream `LICENSE` and every copyright header.
3. Set `origin: vendor:<owner>/<repo>`.
4. Add the row to
   [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md) — source, licence,
   what was taken, **what was changed**, date. Apache 2.0 requires stating
   modifications; MIT requires keeping the notice. Neither can be satisfied
   retroactively.
5. Do not reformat the file in the commit that imports it. The diff has to
   show what we changed and nothing else.
6. Get the line-by-line review.

See [`vendor/README.md`](vendor/README.md).
