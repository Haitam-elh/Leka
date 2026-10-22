# Skills (LEKA-396, LEKA-401)

A **skill** is one operation LEKA's capabilities are made of: one read of the
company model, one lookup, one assessment. It is defined once, with its
contract, and run one way by whoever needs it:
- LEKA's analyst ([intentions.md](intentions.md) § 12);
- the agents, through the skills their file names (§ 10);
- the workflows, through their steps (§ 11).

A **capability** is what a person asks LEKA for and sees in Capacités
([capabilities.md](capabilities.md)). A skill is what a capability uses: it
is not in Capacités.

Code:
- `api/leka/capabilities/skills.py`: the model, the registry, the runtime and
  the runs; skills to an agent.
- `api/leka/intentions/skills.py`: LEKA's reads, as skills (§ 6).
- `api/leka/intelligence/library.py`: the enterprise skill library (§ 9).
- `api/leka/api/skills.py`: the routes.

```
a module registers its skills when it is imported (register)
    │  each checked: key, semver, category, permission, contract — it reads
    │  a version is its contract: the same version said otherwise is refused
    ▼
SkillRuntime.run(key, inputs, version?) — for one caller, with what it may do
    1. which      the version asked, or the latest that runs
    2. may they   the skill's permission, among the caller's
    3. given      checked against what it takes          ── refused, each error said
    4. run        its own session, the transaction READ ONLY, within its time
    5. gave       checked against what it promised       ── failed, said so
    6. kept       skill_runs, whatever came of it
```

## 1. A skill

| Field | |
| --- | --- |
| `key` | kebab-case, 64 characters at most. It is the tool's name when a model calls it. |
| `version` | semver |
| `title`, `summary` | what people call it; what it does and when to use it. The summary is what a model reads to choose it. |
| `category` | one of the catalogue's: architecture, operations, knowledge… |
| `input`, `output` | **its contract**: pydantic models. What it takes and what it gives, as JSON schemas over the API. |
| `permission` | a governance permission (`workspace:read` by default, `source:read` for `sources`) |
| `effect` | `read`. It is the only effect. A skill that would change something is refused at registration: an action is a person's decision (LEKA-390), carried out through the systems they authorized (LEKA-391). |
| `lifecycle` | `draft` → `review` → `active` ⇄ `deprecated` → `retired`, as a capability's |
| `timeout` | seconds, 120 at most; 20 by default |
| `origin` | `internal`, or where it was imported from |
| `limitations` | what it cannot do |
| `reads` | the kinds of things it reads (LEKA-401). An agent is offered it only when it may read them all. None said: it reads anything, and no agent is offered it. |
| `sources` | what must be connected for it to be of use: one source kind of each group, e.g. `("github", "gitlab", "bitbucket")` (LEKA-401) |

**Checked when registered** (`SkillError`, every problem said):
- a key, a version or a category that cannot be;
- an effect other than `read`;
- a permission LEKA does not know;
- an input or output that is not a pydantic model, or whose schema cannot be
  said.

**What it read, citable.** An output may say what it read (`Citing.cited`):
each thing, event, source or finding, with the id an answer cites
(`entity:…`, `event:…`, `source:…`, `finding:…`), what it is, and where it
came from. A model is given the output without it: the ids are in what it
reads. The caller keeps the rest: LEKA's analyst turns what its answer cites
into the analysis's evidence (the Preuves tab).

**A thing it does not know.** A skill raises `UnknownThingError` when what
it was given names nothing LEKA knows: it is refused (`unknown`), said so.

## 2. Versions

A version is its contract. Its fingerprint hashes everything but its
lifecycle: title, summary, category, both schemas, permission, effect,
timeout, origin, limitations.
- Registering the **same version with a different fingerprint** is refused:
  a new contract is a new version.
- The same skill again (a module imported twice), or the same moved in its
  lifecycle, stands in for it.
- Every version is kept side by side (`versions`).

**Which version runs:**
- asked exactly (`1.2.0`): that one;
- asked by its start (`1`, `1.2`): the latest of them that runs;
- not asked: the latest **active**, else the latest **deprecated**.

Draft, review and retired never run: asked, they are refused
(`not_runnable`). A deprecated version runs, and that is said (`deprecated`
on the run).

Each run keeps the version that ran and its fingerprint: what ran is known
exactly, even after a new version.

## 3. Permissions

A skill runs with what its caller may do:

| Caller | Permissions |
| --- | --- |
| a person, over the API | their role's, as the request reads it |
| LEKA's analyst, on an intention | the role **now** of whoever asked the intention (`permitted`): none if they no longer have a seat; LEKA's own (a member's) for an intention no one asked |

A permission the caller lacks: refused (`not_permitted`), « Running it takes
the permission … ». Over the API, every skill says whether this person may
run it (`usable`).

Members hold `workspace:read` and `source:read`, so they may run all of
LEKA's reads and all of its library.

**Prerequisites** (LEKA-401). A skill that needs a source runs only when one
of each of its groups is connected (a source `active` or `degraded`, as the
catalogue reads it). Otherwise it is refused (`unavailable`): « It needs a
source connected: github or gitlab or bitbucket. », each group in its
errors. Over the API, every skill says what it needs (`sources`) and what is
missing here (`missing_sources`); `usable` is false while something is.

## 4. A run

| Status | `reason` | |
| --- | --- | --- |
| `succeeded` | — | what it gave, checked against its output |
| `refused` | `not_found` | no such skill, or no such version |
| | `not_runnable` | that version is draft, review or retired |
| | `not_permitted` | the caller lacks its permission |
| | `unavailable` | a source it needs is not connected, each group said |
| | `invalid_input` | what it was given is not what it takes, each error said: field, code, message |
| | `unknown` | what it was given names nothing LEKA knows |
| `failed` | `invalid_output` | it gave something other than what it promised, each error said |
| | `error` | it failed: the exception's name, never its text |
| `timed_out` | `timed_out` | no answer in its time |

**Read only, as the database holds it.** Each run has its own session, in
the workspace's scope. Its transaction is `READ ONLY`: Postgres refuses a
write (`tests/test_skills.py` tries an UPDATE).

**Kept, whatever came of it** (`skill_runs`, in the caller's session):
- the key, the version and its fingerprint;
- the status and the reason;
- `caller`: `analyst`, `api` or an agent;
- `ref`, what it is about: `intention:<id>`;
- `run_by`, for whom;
- `inputs`, what it was given (up to 4,000 characters, else its size);
- `output`, what it gave, without what it cited (up to 50,000 characters,
  else its size);
- `detail`: its message, its errors, how many things it read, its size,
  whether the version is deprecated;
- `latency_ms` and `at`.

A refusal is kept too: someone tried.

## 5. To a model

`SkillRuntime.tool(key, fill=…, cited=…)` gives a `RuntimeTool` for the LLM
runtime ([llm-runtime.md](llm-runtime.md)):
- its name is the skill's key, its description the summary;
- its parameters are what the skill takes. A value it may leave out is said
  not required, rather than « or null », which not every provider reads.

Each call goes through `run()`, so it is checked and kept like any other
run:
- `fill` gives what the caller knows that the model may leave out. The
  analyst fills in the period the question names and its environment.
- What the skill read goes to `cited`, not to the model.
- What went wrong goes back to the model, each error said, so it can ask
  again.

A tool that is not `read` cannot be given to a model (`RuntimeTool`), and a
skill cannot be anything else.

## 6. LEKA's reads

`api/leka/intentions/skills.py`, version 1.0.0, all `read`:

| Skill | Permission | What it reads |
| --- | --- | --- |
| `find` | `workspace:read` | things by name or words |
| `describe` | `workspace:read` | one thing: what it is, its state, who answers for it, what it is tied to, its sources |
| `dependencies` | `workspace:read` | what it depends on, or what depends on it, two steps, in one environment or all |
| `happened` | `workspace:read` | deployments, merges, releases, changes, incidents in a period: everywhere, in one environment, or around one thing; a week by default |
| `incident` | `workspace:read` | one incident: what it affected, its causes said or suspected, what changed in the 72 hours before |
| `learned` | `workspace:read` | what LEKA's model gained, changed, lost in a period |
| `sources` | `source:read` | what LEKA reads, each source's state, when it was last read |
| `insights` | `workspace:read` | what LEKA concluded and is still open, everywhere or about one thing |
| `overview` | `workspace:read` | how many things of each kind, the environments, the last build |

Each gives a short answer: 25 things at most, 300 characters of any text.

**LEKA's analyst reads through them**, and through the library (§ 9). Every read its model asks for is a
skill run, about the intention, for whoever asked it. `GET
/skills/runs?ref=intention:<id>` lists what LEKA read to answer.

## 7. API

| Route | |
| --- | --- |
| `GET /skills` | every skill as a caller gets it: its contract as JSON schemas, its permission, whether this person may run it, where it stands, its versions |
| `GET /skills/{key}` | one |
| `POST /skills/{key}/run` | `{inputs, version?}`: the run and what it gave. Refused: 404 (no such skill or version, a thing it does not know), 403 (permission), 422 (does not run, or what it was given, each error in `details`). A failure or a timeout is said in its `status`. |
| `GET /skills/runs?key&ref&limit` | the workspace's runs, latest first |

Reading takes `workspace:read`. Running takes the skill's own permission.
The workspace is the session's.

## 8. Adding a skill

1. Two pydantic models: what it takes (each field described: a model reads
   it) and what it gives. Inherit `Citing` when it says what it read.
2. An `async def run(given, call)`. `call` holds the workspace, a read-only
   session, the moment, for whom and the caller. Raise `UnknownThingError`
   for a thing LEKA does not know.
3. A `Skill(...)` in the module that has what it reads (the layering holds:
   a skill reading the knowledge graph sits above it), registered with
   `register(...)` when the module is imported.
4. A test that runs it through the runtime.

To change what it takes or gives, register a new version. Move the old one
to `deprecated`, then `retired`.

## 9. The library (LEKA-401)

`api/leka/intelligence/library.py`: one skill per domain, version 1.0.0, all
`read`, all `workspace:read`. Each computes from what the connected sources
gave LEKA, never a live read of a tool. Each gives what it read, citable
(`cited`), and what it concluded, as **signals**: a code, a level (`info`,
`warning`, `critical`), a sentence, the values it rests on. A workflow's
condition reads the codes; an agent and the analyst weigh them.

Each skill is a read (it takes a session) and a judgement (`judge_*`, pure,
tested without a database).

| Domain | Skill | Takes | Gives | Needs connected |
| --- | --- | --- | --- | --- |
| Repository analysis | `repository-profile` | a repository; days (30) | languages, visibility, default branch, topics, archived; owners and maintainers; the services and applications it builds; merges, releases, deployments in the period; LEKA's open points on it | a code host |
| Code review | `change-review` | a pull request, a change request, a deployment or a release | what it touched and which of that is critical; its reach (dependents, applications, business); the incidents it caused, or that followed it within 72 hours on what it touched | — |
| Testing | `test-scope` | a service, application, repository, database or resource; an environment | what depends on it, two steps, the most critical first, each with its incidents in 30 days; the applications and business it carries | — |
| Security | `security-posture` | a service (none: everywhere); an environment | resources reachable from the internet (the critical and the unowned first); public repositories; databases holding personal data or secrets | — |
| Documentation | `documentation-coverage` | a kind of thing (none: every kind); critical only | documents, spaces, freshness; coverage by kind; what no document describes, or only stale ones, the most critical first | a documentation tool |
| Architecture | `blast-radius` | anything | what depends on it directly and indirectly (three steps); the applications and business capabilities and processes it carries; who answers for it; how many things it depends on | — |
| Incident investigation | `incident-history` | a thing (none: everywhere); days (90) | how many incidents, by severity, how many open, the median time to resolve, the longest, the causes that recur, the latest | — |
| Infrastructure | `infrastructure-inventory` | an account or resource group, a service, an environment | resources by provider, kind, region and state; how many public and unowned; the notable ones | a cloud |
| Data analysis | `data-landscape` | a database (none: all) | each database's engine, schemas and objects, classification, data categories, owners, services; the tables, views and collections holding personal data or secrets | a database |
| Database review | `schema-health` | a database | its tables and how many LEKA read the structure of; the largest; those without a primary key; the foreign keys no index starts with; indexes on the same columns; money in a floating type; dates without their time zone (PostgreSQL) — from the catalogue's columns' types, keys and indexes, never a row (2026-10-22) | a database |
| Release and deployment | `delivery-metrics` | a service or repository (none: all); an environment (production); days (30) | DORA's metrics: deployments and per week, failed, followed by an incident, change failure rate, median time to recover, the last deployment; each tier | — |

A code host: GitHub, GitLab or Bitbucket. A documentation tool: Confluence,
Notion, Microsoft 365, Google Workspace, Guru or Slab. A cloud: AWS, Azure or
Google Cloud. A database: PostgreSQL, MySQL, MariaDB, SQL Server, Oracle,
MongoDB or Supabase.

**Severities.** An incident's severity is read from its tool's own words,
into one scale: `sev1`, `P1`, `critical`, `highest` are critical; `sev2`,
`P2`, `high`, `major`, `urgent` are high; and so on down to low.

**DORA's tiers.** Deployment frequency: elite from 7 a week, high from 1,
medium from one a month. Change failure rate: elite up to 5 %, high 10 %,
medium 15 %, low beyond. Time to recover: elite under an hour, high under a
day, medium under a week. A deployment counts as a failure when it failed,
or when its source ties an incident to it.

**The signals.**

| Skill | Signal | Level | When |
| --- | --- | --- | --- |
| `repository-profile` | `repository.public` | warning | anyone reads it |
| | `repository.unowned` | warning | no owner, no maintainer |
| | `repository.inactive` | info | nothing merged or released in the period |
| | `repository.archived` | info | archived |
| | `repository.open_findings` | info | LEKA has open points on it |
| `change-review` | `change.followed_by_incident` | critical | an incident it caused, or that followed it |
| | `change.failed` | warning | it failed |
| | `change.critical_target` | warning | it touched what is critical or high |
| | `change.wide_reach` | warning | five dependents or more, or the business reached |
| | `change.production` | info | it went to production |
| `test-scope` | `test.critical_dependents` | warning | a dependent is critical or high |
| | `test.fragile_dependents` | warning | a dependent had incidents in 30 days |
| | `test.business_flows` | info | it carries business |
| | `test.isolated` | info | nothing depends on it |
| `security-posture` | `security.public_critical` | critical | public and critical |
| | `security.unowned_exposed` | critical | public and no one answers for it |
| | `security.public_resources` | warning | resources reachable from the internet |
| | `security.public_repositories` | warning | public repositories |
| | `security.secrets_stored` | warning | a database holds secrets or credentials |
| | `security.personal_data` | info | a database holds personal data |
| | `security.nothing_exposed` | info | none of that |
| `documentation-coverage` | `docs.critical_undocumented` | warning | something critical has no document |
| | `docs.low_coverage` | warning | less than half of a kind documented |
| | `docs.gaps` | info | things no document describes |
| | `docs.mostly_stale` | info | more stale documents than fresh |
| | `docs.none` | info | no document at all |
| `blast-radius` | `architecture.unowned_critical` | critical | critical, and no owner |
| | `architecture.concentration` | warning | three dependents or more, directly |
| | `architecture.business_critical` | warning | a failure reaches the business |
| | `architecture.unowned` | warning | no owner |
| | `architecture.leaf` | info | nothing depends on it |
| `incident-history` | `incident.severe` | critical | a critical incident |
| | `incident.open` | warning | incidents still open |
| | `incident.recurring` | warning | three incidents or more |
| | `incident.slow_recovery` | warning | half took more than four hours |
| | `incident.quiet` | info | no incident |
| `infrastructure-inventory` | `infra.unowned_critical` | critical | critical, and no one owns it |
| | `infra.unowned` | warning | resources of no service, application, team or person |
| | `infra.failed` | warning | resources failed |
| | `infra.not_running` | info | stopped or gone |
| | `infra.public` | info | reachable from the internet |
| | `infra.empty` | info | no resource |
| `data-landscape` | `data.secrets` | warning | secrets or credentials stored |
| | `data.unowned` | warning | a database no one answers for |
| | `data.personal` | info | personal data held |
| | `data.shared` | info | used by three services or more |
| | `data.none` | info | no database |
| `schema-health` | `schema.unindexed_foreign_key` | warning, critical on a table of a million rows or more | a foreign key no index starts with |
| | `schema.no_primary_key` | warning | tables without a primary key |
| | `schema.floating_money` | warning | an amount, price, total… in a floating type |
| | `schema.duplicate_index` | info | two indexes on the same columns |
| | `schema.timestamp_without_zone` | info | PostgreSQL dates without their time zone |
| | `schema.not_read` | info | no table's structure read yet: the source must sync again |
| | `schema.empty` | info | no table |
| `delivery-metrics` | `delivery.high_failure_rate` | warning, critical past 30 % | change failure rate above 15 % |
| | `delivery.failed_deployments` | warning | deployments failed |
| | `delivery.slow_recovery` | warning | recovering takes more than a day |
| | `delivery.stale` | info | last deployment more than 14 days ago |
| | `delivery.none` | info | no deployment in the period |

**What none of them does.** No code, diff, test, pipeline log, metric, cost,
vulnerability scan or IAM policy is read. What a column holds is read from
its name and comment, never a value. Each skill's `limitations` says its own.

## 10. To an agent

An agent names the skills it may be offered in its file (`skills:`,
[agent-runtime.md](agent-runtime.md) § 4):
- each is offered under its key, beside the agent's tools, with its summary
  and what it takes;
- only when it reads nothing the agent may not (`reads` ⊆ the agent's
  `entity_types`): otherwise withheld (`out_of_scope`), as is a skill LEKA
  does not have (`unknown`) or one the person who asked may not run
  (`not_permitted`);
- each call goes through the runtime, with the permissions of whoever asked
  the run, kept about it (`caller: agent:<key>`, `ref: agent_run:<id>`), and
  kept as a tool step of the run.

Ten of the library's agents (LEKA-400) name the skills of their domain,
version 1.1.0:

| Agent | Skills |
| --- | --- |
| `release-analysis` | `delivery-metrics`, `change-review` |
| `code-review` | `change-review`, `repository-profile` |
| `test-analysis` | `test-scope` |
| `security-review` | `security-posture` |
| `documentation-assistant` | `documentation-coverage` |
| `architecture-analysis` | `blast-radius` |
| `incident-investigation` | `incident-history`, `blast-radius` |
| `infrastructure-analysis` | `infrastructure-inventory` |
| `data-analysis` | `data-landscape` |
| `debug-assistant` | `incident-history` |
| `reliability-analysis` | `incident-history`, `blast-radius`, `delivery-metrics`, `infrastructure-inventory` |
| `dependency-analysis` | `blast-radius`, `change-review` |
| `database-review` | `schema-health`, `data-landscape` |

Each read the kinds of things its skills read: their `entity_types` grew to
cover them.

## 11. In a workflow

A step uses a skill as `uses: skill:<key>` ([workflows.md](workflows.md)):
- given only what the skill takes, its required fields given, checked when
  the workflow loads;
- run through the runtime with the permissions of whoever asked the run,
  kept about it (`caller: workflow:<key>`, `ref: workflow_run:<id>`);
- what it concluded — its signals — becomes the step's codes, which a later
  step's condition reads (`found`); its first warnings, the step's summary;
  what it gave, the step's output;
- a refusal fails the step, not retried; a timeout or an error, retried
  while its attempts last.

`release-readiness` composes three of them:
1. `delivery-metrics`, then `incident-history` (30 days), then `blast-radius`
   (its failure does not stop it);
2. only when delivery or incidents sound an alarm
   (`delivery.high_failure_rate`, `delivery.failed_deployments`,
   `incident.open`, `incident.severe`), the `release-analysis` agent, which
   reads through its own skills.

## Tested

`tests/test_skill_library.py`, pure (LEKA-401):
- eleven skills, on the common contract: they read, say what they read and
  conclude, need what they say;
- delivery in DORA's terms, its tiers, what no deployment says;
- one severity scale; an incident history open, recurring, severe, slow;
- an inventory and what stands out; a security posture; a data landscape;
  a schema's health from its catalogue (an index's key columns, a foreign
  key no index starts with, keys, duplicates, money, time zones);
  documentation coverage; a blast radius; a test scope; a change; a
  repository: each signal from the facts that call for it, and only those;
- an agent offered a skill only within what it reads.

`tests/test_skill_library_api.py`, on Acme's operations, infrastructure,
data and documentation, each through the whole pipeline:
- every skill run over HTTP on real records: the deployment an incident
  followed (a change failure rate of 1), the change request that caused an
  incident, what a failure of Billing API reaches, the public load balancer
  no one owns, the credentials table, the undocumented processes;
- a skill that needs a source refused until one is connected;
- the incident investigator calling `incident-history` and `blast-radius`,
  each call kept about its run;
- `release-readiness`: three skills, the alarm, the agent.

`tests/test_skills.py`:
- a skill registered with its contract, and what cannot be registered
  refused with every problem said;
- a version is its contract;
- which version runs;
- a value a model may leave out is not required;
- a run checked and kept, deprecated said;
- every refusal said and kept;
- a broken contract, a timeout and a failure said;
- the database refusing a write;
- a skill as a model calls it: filled in, its citations handed over, its
  errors said to the model.

`tests/test_skills_api.py`, on Acme's model:
- every skill listed with its contract;
- each of LEKA's reads run over HTTP, on Billing API;
- what it was given that it does not take, a thing it does not know, a
  version that does not exist: refused and kept;
- another workspace sees none of it;
- a skill that takes `source:manage`: refused to a member, run by an admin.

`tests/test_intention_analyst.py`: the analyst's tools are LEKA's reads, and
what it read is kept about the intention, for the person who asked.
