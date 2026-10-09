# The enterprise agent library (LEKA-400)

LEKA's first set of specialised agents: what people ask — investigate an
incident, review a change, explain an architecture — goes to the one that
does it, without anyone choosing an agent. Each is a file in `agents/`
(ADR 004, [agents/README.md](../agents/README.md)), active in
`agents/registry.yaml`, run by the agent runtime
([agent-runtime.md](agent-runtime.md)), reached through the capability
router ([capability-router.md](capability-router.md)).

## 1. The agents

| Agent | Key | Reads (`entity_types`) | Needs connected | Tools | Routed by |
| --- | --- | --- | --- | --- | --- |
| Analyse d'architecture | `architecture-analysis` | application, service, database, infra resource, business process, team | — | search, read, dependencies | map dependencies, assess impact · dependency |
| Revue de code | `code-review` | repository, pull request, commit, service, person, team | GitHub, GitLab or Bitbucket | search, read, what happened | investigate, assess impact · change |
| Revue de sécurité | `security-review` | application, service, infra resource, cloud account, database, data object, repository | — | search, read, dependencies | check compliance, assess impact · compliance |
| Analyse des tests | `test-analysis` | repository, service, pull request, commit, release, incident | GitHub, GitLab or Bitbucket | search, read, what happened, dependencies | assess impact, investigate · change |
| Aide au débogage | `debug-assistant` | service, incident, deployment, change, commit, infra resource, database | — | all four | explain cause, investigate · diagnose |
| Assistant de documentation | `documentation-assistant` | document, knowledge space, service, application, team, person | Confluence, Microsoft 365, Notion, Google Workspace, Guru or Slab | search, read | find knowledge · knowledge |
| Investigation d'incident | `incident-investigation` | incident, service, deployment, change, release, team, person | — | all four | explain cause, investigate · diagnose |
| Analyse d'infrastructure | `infrastructure-analysis` | infra resource, cloud account, resource group, environment, service, database | AWS, Azure or GCP | search, read, dependencies | map dependencies, assess impact · dependency |
| Analyse des données | `data-analysis` | database, schema, data object, application, service, team | a database source | search, read, dependencies | map dependencies, find owner · dependency, ownership |
| Analyse de release | `release-analysis` | release, deployment, change, commit, pull request, service, incident | GitHub, GitLab or Bitbucket | all four | find change, assess impact · change |
| Réparation de build | `build-fixer` | repository, commit, pull request, service, change | GitHub, GitLab or Bitbucket | search, read, what happened | investigate, explain cause · diagnose — **a request to act only** |

Beside them, the application architect (`application-architecture`, the
deck, LEKA-393) and three drafts kept from LEKA-329.

## 2. Their contract

Every agent of the library:

- **is the runtime's** — an agent (`kind: agent`), version 1.0.0, run by a
  model through the gateway, its instructions after the runtime's rules;
- **reads only what it is about** — its context, injected by the runtime
  (LEKA-395), holds only things of its `entity_types`; its tools read only
  them;
- **declares its tools** (`tools:` — least privilege): it is offered only
  those, and only when the person who asked holds their permission; an
  unknown tool refuses the catalogue;
- **takes optional inputs** (`sujet`, `incident`, `changement`…): routed from
  an intention, it runs on what was asked and its context; given, they say
  what to look at;
- **delivers markdown** in the language of the request, in sections its file
  names, each statement citing what it rests on;
- **never acts** — read-only; the build fixer is `proposes_action`: it
  proposes a fix, a person decides (LEKA-390), and **a question never goes to
  it** (the router's policy) — only a request to act does;
- **is traceable** — every run, every tool call and what came of it, the
  model that answered, why it failed (`agent_runs`, `agent_run_events`).

## 3. The tools

The runtime's four read-only tools ([agent-runtime.md](agent-runtime.md)
§ 4): `search_entities`, `read_entity`, and, with the library,

- `dependencies` — what a thing depends on (`depends_on`) or what depends on
  it (`used_by`), 1 to 3 steps away; what the agent may not read is counted
  (`left_out`), never shown;
- `what_happened` — incidents opened or resolved, deployments, changes,
  releases, merges around a thing over the last 1 to 30 days, the latest
  first.

## 4. Their limits

Said in each file, and to whoever reads what they deliver:

- They read **LEKA's company model**, as built from the sources — never a
  source live: not a diff line by line (code review), not a vulnerability
  scan (security), not test coverage, not build logs, not live metrics or
  costs, not a table's rows.
- What the model does not hold, they **say missing**, never fill.
- An agent needing a source runs only once one is connected (the catalogue
  says which); one needing a model, once one is reachable.

## 5. Validated

`tests/test_agent_library.py`: every agent to the contract above; six
realistic requests routed to the right one; a question about a broken build
never to the fixer. `tests/test_agent_library_api.py`, on Acme's model: an
incident routed to the investigator and investigated — what depends on
Billing API, what happened around it — its post-mortem delivered, every step
kept; an architecture read through its dependencies, a thing it is not about
refused; the documentation assistant offered only the two tools it declares.

## Not yet

- Reading sources live (a diff, build logs, metrics): tools to come, each
  read-only, each with its permission.
- Files beyond markdown (a post-mortem as a document): with the architect's.
