# The enterprise agent library (LEKA-400)

LEKA's first set of specialised agents: what people ask — investigate an
incident, review a change, explain an architecture — goes to the one that
does it, without anyone choosing an agent. Each is a file in `agents/`
(ADR 004, [agents/README.md](../agents/README.md)), active in
`agents/registry.yaml`, run by the agent runtime
([agent-runtime.md](agent-runtime.md)), reached through the capability
router ([capability-router.md](capability-router.md)).

## 1. The agents

| Agent | Key | Reads (`entity_types`) | Needs connected | Tools | Skills (LEKA-401) | Routed by |
| --- | --- | --- | --- | --- | --- | --- |
| Analyse d'architecture | `architecture-analysis` | application, service, database, infra resource, business process, team, repository, business capability, person | — | search, read, dependencies | `blast-radius` | map dependencies, assess impact · dependency |
| Revue de code | `code-review` | repository, pull request, commit, service, person, team, change, deployment, release, application, incident, business capability, business process | GitHub, GitLab or Bitbucket | search, read, what happened | `change-review`, `repository-profile` | investigate, assess impact · change |
| Revue de sécurité | `security-review` | application, service, infra resource, cloud account, database, data object, repository, team | — | search, read, dependencies | `security-posture` | check compliance, assess impact · compliance |
| Analyse des tests | `test-analysis` | repository, service, pull request, commit, release, incident, application, database, infra resource, business capability, business process | GitHub, GitLab or Bitbucket | search, read, what happened, dependencies | `test-scope` | assess impact, investigate · change |
| Aide au débogage | `debug-assistant` | service, incident, deployment, change, commit, infra resource, database, application, team, person | — | all four | `incident-history` | explain cause, investigate · diagnose |
| Assistant de documentation | `documentation-assistant` | document, knowledge space, service, application, team, person, repository, database, business capability, business process | Confluence, Microsoft 365, Notion, Google Workspace, Guru, Slab or GitHub | search, read; the code (`list_files`, `read_file`) when GitHub is connected | `documentation-coverage` | find knowledge · knowledge |
| Investigation d'incident | `incident-investigation` | incident, service, deployment, change, release, team, person, application, database, infra resource, repository, business capability, business process | — | all four | `incident-history`, `blast-radius` | explain cause, investigate · diagnose |
| Analyse d'infrastructure | `infrastructure-analysis` | infra resource, cloud account, resource group, environment, service, database, application, team | AWS, Azure or GCP | search, read, dependencies | `infrastructure-inventory` | map dependencies, assess impact · dependency |
| Analyse des données | `data-analysis` | database, schema, data object, application, service, team, infra resource | a database source | search, read, dependencies | `data-landscape` | map dependencies, find owner · dependency, ownership |
| Analyse de release | `release-analysis` | release, deployment, change, commit, pull request, service, incident, application, repository, business capability, business process | GitHub, GitLab or Bitbucket | all four | `delivery-metrics`, `change-review` | find change, assess impact · change |
| Réparation de build | `build-fixer` | repository, commit, pull request, service, change | GitHub, GitLab or Bitbucket | search, read, what happened | — | investigate, explain cause · diagnose — **a request to act only** |

Beside them, the application architect (`application-architecture`, the
deck, LEKA-393) and three drafts kept from LEKA-329.

## 2. Their contract

Every agent of the library:

- **is the runtime's** — an agent (`kind: agent`), run by a model through the
  gateway, its instructions after the runtime's rules; version 1.1.0 since
  it was given the skills of its domain (LEKA-401), 1.0.0 for the build
  fixer;
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

**And the skills of their domain** (LEKA-401, [skills.md](skills.md) §§ 9
and 10), each named in the file (`skills:`, the table above): an assessment
an expert would make — the delivery metrics of a service, its incident
history, the blast radius of a failure, what to test, a change reviewed, a
repository profiled, the security posture, the documentation coverage, the
infrastructure inventory, the data landscape. Offered under its key, beside
the tools, only when it reads nothing beyond the agent's `entity_types`
(theirs grew to cover them); each call kept as a tool step of the run and as
a skill run about it. Each says what it concluded as signals, which the
agent weighs and cites.

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

`tests/test_agent_library.py`: every agent to the contract above — and,
but the build fixer, offered every skill it names, none withheld (LEKA-401);
six realistic requests routed to the right one; a question about a broken
build never to the fixer. `tests/test_agent_library_api.py`, on Acme's
model: an incident routed to the investigator and investigated — what
depends on Billing API, what happened around it — its post-mortem
delivered, every step kept; an architecture read through its dependencies;
a thing the debugging agent is not about refused; the documentation
assistant offered only the two tools it declares, and its skill.
`tests/test_skill_library_api.py`: the investigator calling
`incident-history` and `blast-radius` on Acme's operations, each call kept
about its run.

## Not yet

- Reading sources live (a diff, build logs, metrics): tools to come, each
  read-only, each with its permission.
- Files beyond markdown (a post-mortem as a document): with the architect's.
