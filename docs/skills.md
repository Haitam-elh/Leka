# Skills (LEKA-396)

A **skill** is one operation LEKA's capabilities are made of: one read of the
company model, one lookup, one check. It is defined once, with its contract,
and run one way by whoever needs it: LEKA's analyst today
([intentions.md](intentions.md) § 12), the agents and the workflows next
(LEKA-397, LEKA-400, LEKA-401). A **capability** is what a person asks LEKA
for and sees in Capacités ([capabilities.md](capabilities.md)). A skill is
what a capability uses: it is not in Capacités.

Code:
- `api/leka/capabilities/skills.py`: the model, the registry, the runtime and
  the runs.
- `api/leka/intentions/skills.py`: LEKA's reads, as skills.
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
| `limitations` | what it cannot do, and what it needs to be of use (a source connected…) |

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
LEKA's reads.

## 4. A run

| Status | `reason` | |
| --- | --- | --- |
| `succeeded` | — | what it gave, checked against its output |
| `refused` | `not_found` | no such skill, or no such version |
| | `not_runnable` | that version is draft, review or retired |
| | `not_permitted` | the caller lacks its permission |
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

**LEKA's analyst reads through them.** Every read its model asks for is a
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

## Tested

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
