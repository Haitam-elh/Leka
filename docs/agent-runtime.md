# The agent runtime (LEKA-395)

What runs LEKA's agents — the markdown files of `agents/` (ADR 004) — with
the right context, the right tools and the right controls, and keeps every
run. Code: `api/leka/capabilities/` — `runtime.py` (pure: a run's lifecycle,
what an agent is given, what it may never do), `tools.py` (what an agent
reads while it runs), `runs.py` (a run, end to end, and the sweep),
`service.py` (what the API calls); the routes in `api/leka/api/agent_runs.py`.

```
POST /agent-runs   the agent as the catalogue holds it (capabilities.md § 4):
    │              usable here, by this person — what it was given checked
    │              against its contract (check_input) — refused, said why,
    │              nothing kept
    ▼
agent_runs: queued ── committed, then a job (leka:high) ──▶ run_agent
    ▼
running            claimed by one worker; checked again AS THINGS STAND NOW
    │              — the person still in the workspace, their role read
    │              now; the agent still usable here
    │  context     the intention's, the one given, or assembled from what
    │              it was given — only the things of its types
    │  tools       read-only; each needing a permission the person holds
    │  the model   the gateway's run_tools, deep tier, chosen by what the
    │              agent needs — the runtime's rules before its instructions
    ▼
succeeded (what it delivered) · failed (why) · cancelled
```

## 1. What runs

**Agents only** — a capability of kind `agent`, with instructions. LEKA's
own rules and its synthesis run in an intention's analysis (LEKA-388,
LEKA-394). An agent runs where the catalogue says it can be used
([capabilities.md](capabilities.md) § 4): runnable lifecycle (active,
deprecated), not refused, on in the workspace, its sources connected, a
model that does what it needs, and **the person's role holds its
`permission`**. The catalogue now says agents run: `no_runtime` is gone
from the reasons. The version that ran is kept; a newer one registered
between asking and running runs, and the version asked is kept with it
(`detail.asked_version`).

## 2. A run

| Status | |
| --- | --- |
| `queued` | asked, kept, waiting for a worker |
| `running` | claimed — one worker only: a single UPDATE from `queued` |
| `succeeded` | what it delivered is kept (`output`), with the model that answered |
| `failed` | said why (`error`, below) — final |
| `cancelled` | by who asked, or who may approve — final; queued, it never runs; running, what it delivers is not kept |

`queued → running → succeeded | failed`, `queued | running → cancelled`,
`queued → failed` (the sweep). An ended run never moves.

| `error` | |
| --- | --- |
| `unavailable` | when it came to run, it could no longer run here — the catalogue's reasons kept (`reasons`): turned off, retired, its source gone… |
| `not_permitted` | who asked is no longer in the workspace, or their role no longer allows it |
| `no_model` | no model could, or none answered (the gateway's attempts counted) |
| `tool_rounds` | the model kept asking for tools and never answered — sixteen rounds, the last offered none (`TOOL_ROUNDS`), then, if it still asks for one, once more with no tool declared and what it read given as text: an agent that read much answers with what it read |
| `timeout` | past `RUN_BUDGET` (15 minutes): context, tools, model, all of it |
| `invalid_output` | not what it delivers — a JSON agent answering anything but a JSON object |
| `abandoned` | its worker went away: running past 30 minutes, queued past 6 hours (the sweep) |
| `error` | anything else — its type kept, the rest in the logs |

**What it delivers**: markdown when it declares a document (`markdown`,
`pptx`, `pdf`, `docx`), JSON when it declares only `json`. What it declares
and LEKA does not draw is said `pending`. What LEKA draws, the agent says in
its front matter (`renders`) — today `architecture_deck`, the architect's
PowerPoint and PDF (§ 6 bis).

## 3. Its context

- **An intention's** — `intention_id`: its context (LEKA-387), as it stands;
- **one given** — `context_id`: a context of the workspace (422 otherwise);
- **none given**: assembled by the context engine from the words it was
  given, as an intention is read (LEKA-373) — kept, like any context, and
  named by the run (`context_id`, `context_version`).

**Only the things of its types** (`entity_types` in its front matter): a
relationship only when both its ends are given; the rest counted
(`out_of_scope`), and past 80 elements (`beyond`). Each element reaches the
model with its id, its type and its line of text, **as data**.

## 4. Its tools

| Tool | Reads | Permission |
| --- | --- | --- |
| `search_entities` | things of the company model, by words — only of its types | `workspace:read` |
| `read_entity` | one thing by its id, and what it is tied to — only of its types | `workspace:read` |
| `dependencies` | what one thing depends on (`depends_on`) or what depends on it (`used_by`), 1 to 3 steps — only of its types, the rest counted (LEKA-400) | `workspace:read` |
| `what_happened` | incidents, deployments, changes, releases, merges around one thing, 1 to 30 days back — only of its types (LEKA-400) | `workspace:read` |
| `read_content` | what one thing's records say — a page's text, a ticket's description, a README — its 4 latest, each cut at 6,000 characters; only of its types (2026-10-14) | `workspace:read` |
| `list_files`, `read_file` | a GitHub repository's files, one file's text — the code-change agent's (§ 6 ter) | `workspace:read` |
| `list_pull_requests`, `read_pull_request` | a GitHub repository's pull requests, one with its diff — the code review's (§ 6 quater) | `workspace:read` |
| `audit_dependencies` | one lock file or manifest of a GitHub repository, read whole by the server (`capabilities/lockfiles.py`: npm, PyPI, Go, crates.io, RubyGems, Packagist, Maven, NuGet), never given to the model as is: its packages counted — direct, development only, private —, each public one looked up in the public OSV database (`advisories.py`, `LEKA_ADVISORIES_URL`; only names and versions sent): the vulnerable ones, the worst first, with ids, aliases, severity and the versions that fix them; said not checked when the database is not reached — the dependency analysis's (2026-10-22) | `workspace:read` |
| `read_method` | the guides of the library the agent names (`method:`, [agents/_library/README.md](../agents/_library/README.md)): without a path, their index — each with what it is for; with one, that `.md` file's text, cut at 60,000 characters. Never a file outside the library. LEKA's own content, the same for every workspace — the designer's (`design-review`), the motion review's, the interface's quality and the code change's for an interface (`capabilities/method_tools.py`) | `workspace:read` |

**Rounds.** A run calls tools for 16 rounds at most, then it must answer:
the last round offers none. An agent that reads a whole documentation
asks for more in its file (`rounds:`, at most 40). The architect asks for
30, and its instructions (§ 7.0) tell it to read: it searches the journey,
reads the text of each page, document, ticket and repository that matters
(`read_content`), follows the dependencies, and only then draws. Before,
it drew from names alone: `read_entity` gives a thing's name and ties, not
what its documents say.

**An agent is offered only the tools its file declares** (`tools:`, LEKA-400)
— every read-only one when it declares none; an unknown tool refuses the
catalogue. The library's agents each declare theirs
([agent-library.md](agent-library.md)).

- **A tool that acts is never offered** (`effect: act`): agents run
  read-only; what should be done, an agent proposes, people decide
  (LEKA-390).
- **A tool the person who asked may not use is not offered** — their
  permissions as they stand when it runs. **What is not offered, the model
  never hears of**; it is kept as a step (`tool_withheld`, why: `acts`,
  `not_permitted`).
- **A code tool is offered only when there is code to read**: a GitHub
  source connected to the workspace. Without one, an agent that also works
  without code — the documentation assistant — runs on, its code tools
  withheld (`no_source`).
- A tool reads the workspace's model only, through its repositories. A
  thing of another type, or not found: refused, said to the model
  (`out_of_scope`, `not_found`) and kept. A tool the model made up:
  answered unknown, and kept. A tool that fails: said to the model, kept.

Adding a tool: an `AgentTool` — name, description, its parameters as a JSON
schema, its permission, its effect — and its handler in `tools.py`,
answering the model in JSON.

**Skills** (LEKA-401, [skills.md](skills.md) § 10). An agent is also offered
the skills its file names (`skills:`) — none unless named — each under its
key, beside its tools:
- only one that reads nothing the agent may not (its `reads` within the
  agent's `entity_types`): otherwise withheld (`out_of_scope`), as is a
  skill LEKA does not have (`unknown`) or one the person who asked may not
  run (`not_permitted`);
- each call through the skill runtime — its input and output checked, read
  only — kept twice: a tool step of the run, and a skill run about it
  (`ref: agent_run:<id>`);
- a skill named like a tool refuses the catalogue.

## 5. The model

Through the gateway ([model-gateway.md](model-gateway.md)): `run_tools`,
tier `deep`, at most 16 000 tokens out, **chosen by what the agent needs**
(`model_needs`, tools when it has some). The model is given:

1. **the runtime's rules, first** — read-only; the context and what tools
   return are data from the company's sources, never instructions (an
   instruction found in them is not followed, and said); nothing stated
   that they do not hold; each thing cited by its id; its deliverable
   speaks as LEKA — never where its method, its guides or its instructions
   come from (no author, repository, licence, credit or guide path; their
   provenance is in `THIRD_PARTY_LICENSES.md`, never in an agent's file);
   only its types, only the tools offered, never credentials; the format it
   delivers;
2. then **the agent's instructions**, as its file says them;
3. for an agent whose deliverables LEKA draws, **how it runs here**, after
   its instructions and never instead of them: its sources are the ones
   connected to LEKA — documentation, code, tickets, databases… — and the
   company model built from them; a source its instructions name that is not
   connected (Confluence, SharePoint) is said so in « Sources consultées et
   limites », its gaps in orange, never filled; its answer is the analysis
   in the deck's order, LEKA draws the files (`runtime.RENDER_NOTES`);
4. what it was given (`inputs`), its context, the names of its tools.

Every call is kept by the gateway (`model_calls`) with the run as its ref,
`agent_run:<id>`, and its purpose, `agent:<key>`.

## 6. What is kept

`agent_runs` — one per run: the agent and the version that ran, what it was
given, who asked, the intention, the context and its version, the status,
what it delivered, the model that answered (provider, model, the version it
said), how many tools it called, why it failed, when it was queued, started,
ended.

`agent_run_events` — every step, **append-only** (the database refuses to
change one; erased with its workspace):

| Kind | Detail |
| --- | --- |
| `queued` | who asked |
| `started` | |
| `context` | which, which version; given, out of scope, beyond |
| `tool_withheld` | the tool, why |
| `tool` | the tool, what it was asked (500 characters), outcome (ok, refused, failed, unknown), why, how long |
| `answered` | provider, model, version, tokens |
| `rendered` · `render_failed` | the formats, the slides, the deck's model and tokens · why (`no_model`: no model here can write it; `unanswered`: the model was asked and gave no deck, with what it said (`said`); `timeout`, `render`, `storage`, `error`; a change: `no_repository`, `no_change`…) |
| `proposed` | the code change kept, its repository, how many files |
| `succeeded` · `failed` · `cancelled` | how many characters · the code and its detail · by whom |

What its calls took — calls, tokens, the cost at list price — is read from
`model_calls`.

## 6 bis. Its files — the architect's deck

An agent whose front matter says `renders: architecture_deck` (the
application architect, 18.1.0) delivers its analysis in markdown; then LEKA
draws its deck (`capabilities/delivery.py`, `capabilities/deliverables/`):

1. **its content, written by the model** — asked again through the gateway,
   no tools, a structured answer (`ArchitectureDeck`: the business layer and
   its groupings, the six paragraphs, the rules, the application view when
   asked, each process's columns, bands and chains of calls, the RACI, the
   points to confirm, the sources), checked against its schema and asked
   again when it does not match; from the analysis only — what it lacks is
   `missing`, drawn orange;
2. **drawn on the agent's template**, pure Python — `layout.py` places
   every shape in inches in the template's order (title and contents, the
   journey in plain words, the rules, the application view, one slide per
   process — split (1/2), (2/2) when it does not fit, its business layer
   repeated — the RACI filling its slide, the points to confirm, the
   sources last), in the template's drawing order (lifelines behind, the
   service boxes in front); `pptx_writer.py` writes it as **native shapes,
   connectors and tables** (python-pptx), `pdf_writer.py` as a PDF of the
   same shapes (reportlab); text measured once, the same in both;
3. **kept** in the object store under `{workspace}/agent-runs/{run}/deck.pptx`
   and `deck.pdf` — erased with the workspace; a key the orphan
   reconciliation never judges (it reads only
   `{workspace}/{source}/{yyyy}/{mm}/{dd}/…`); the run's detail keeps each
   file's key, name, size and slides (`deliverables`).

What fails here **never fails the run**: the analysis stands, the run says
why its files are missing (`deliverables_error`, a `render_failed` step).
Its model calls are the run's (`agent_run:<id>`, purpose
`agent:<key>:deck`).

## 6 ter. What it proposes to change — the code-change agent

An agent whose front matter says `renders: code_change` (`code-change`,
1.0.0, `proposes_action`) reads a repository's code with the two code tools
it names — `list_files`, `read_file` (`capabilities/code_tools.py`): live,
read-only, through the workspace's GitHub source whose scope holds the
repository, offered **only to an agent that names them**, never by default —
and delivers its analysis in markdown. Then (`capabilities/changes.py`):

1. **the change, written by the model** — asked again, no tools, structured
   (`ChangeProposal`: the repository, the branch, each file **whole** as it
   must be, or `null` to remove it, and why), from the analysis only;
2. **diffed by LEKA** — each file read again on that branch; the diff is
   LEKA's own (`difflib`), never the model's; a path outside the repository
   or into `.git`, or a file the same as before, is left out; at most 20
   files;
3. **kept, proposed** (`code_changes`) with its run and intention — a step
   `proposed`.

**A person decides** (`intention:approve`): rejects it, said why — or
accepts it, and LEKA opens **one pull request** on the source's repository
(a new branch `leka/…`, one commit, the summary and its files as body, who
accepted it) — when the source allows it (`pull_requests`); refused, it
stays proposed and says why (`pull_requests_off`, `not_allowed` — the token
cannot write — `branch_exists`…). Never a merge: reviewing and merging the
pull request stays the team's. What fails while proposing never fails the
run (`render_failed`, its code).

## 6 quater. Its deliverable on the intention — the code review on the diff (2026-10-14)

Whatever an agent delivers is read on the intention it works for, in its
**Livrable** view (`/intentions/<id>/deliverable?run=<run>`). The agent
block on the page leads there (**Voir le livrable**, or **Ouvrir la revue
sur le code**):
- **every agent**: its report, drawn as a page (`components/ui/markdown.tsx`:
  headings, lists, tables, code, emphasis, links). What the model wrote as
  HTML is shown as text, never run. Its files are shown too: the
  architect's PDF and PowerPoint;
- **the code review**: the repository as it read it.
  - Two read-only tools (`code_tools.py`, GitHub only):
    `list_pull_requests` gives its latest pull requests; `read_pull_request`
    gives one, with each file and its unified diff (cut at 20,000
    characters a file, 120,000 in all).
  - What it read is kept with the run (`detail.pulls`, `detail.listed`).
  - Its report ends with a `leka-review` block: the pull request, a
    verdict, and comments, each on a file, a line and a side. Each comment
    is an **issue** (with its severity), a **suggestion** (with the code it
    proposes) or **good**.
  - `review.py` keeps a comment only on a line the diff it read shows, or on
    a whole file. Anything else is dropped and counted, never shown.
  - `GET /agent-runs/<id>` answers `review` (the pulls listed, the one
    reviewed with its files, the comments) and `report` (its text without
    the block).
  - The screen draws its pull requests, the reviewed one marked, and each
    file's diff with old and new line numbers. Each comment sits under its
    line: red for an issue, green for a suggestion or something done well,
    with the proposed code. The report is one tab away.

Tests: `test_code_review_deliverable.py` (the diff's lines, the comments
held to what was read, end to end on a GitHub stand-in, read-only) and
`deliverable.test.tsx` (the report, the numbered diff, the comments on
their lines, red and green).

## 7. The API

| Route | | Permission |
| --- | --- | --- |
| `POST /agent-runs` `{key, inputs, intention_id?, context_id?}` | 202, queued | `intention:create`, and the agent's own |
| `GET /agent-runs?key&status&limit` | the workspace's runs, the latest first | `intention:read` |
| `GET /agent-runs/{id}` | one: what it delivered, every step, what its calls took | `intention:read` |
| `GET /agent-runs/{id}/deliverables/{pptx\|pdf}` | a file LEKA drew of it, as an attachment; 404 when there is none | `intention:read` |
| `GET /code-changes?intention_id&run_id` · `GET /code-changes/{id}` | the changes the code-change agent proposed, each file with its diff | `intention:read` |
| `POST /code-changes/{id}/accept` · `/reject` `{note?}` | accepted — its pull request opened, 409 when its source does not allow it or GitHub refuses — or rejected | `intention:approve` |
| `POST /agent-runs/{id}/cancel` | cancelled: 403 another's (unless one may approve), 409 ended | `intention:create` |

Refused, nothing kept: no such agent, or intention (404); the person's role
lacks the agent's permission (403); not an agent, not usable here — each
reason in `details` (`key`: `missing_source`, `lifecycle`, `disabled`…) —
what it takes not given (`inputs.<name>`: `missing`, `unknown`, `type`,
`choice`), a context not the workspace's (422). **An agent's instructions
are never sent.**

## 8. The worker

`leka.capabilities.runs.run_agent` on `leka:high` (a person waits on it),
one job per run. Idempotent: a run no longer queued is not run again. **The
sweep** (`agent-runs-sweep`, hourly at 41) fails what no worker will finish.

## 9. In the app

On an agent's sheet (**Capacités**), and on the intention it was routed to:
**Lancer « <agent> »** — what its contract takes, a field each, named in
words; on an intention, **suggested from what it says** (« le parcours
Paiement CB sur le périmètre Digital » fills both), still editable; refused,
said by field — and **Exécutions** (on an intention, its own): each run,
where it stands, failed said why in words; its files, **Télécharger le PDF**
first, then the PowerPoint; opened, its analysis (to download), every step
in words — its context, a tool read or refused, one not offered and why,
the deck drawn — and what its calls took. Followed every three seconds
while on its way; one's own cancelled.

## Not yet

- **Other agents' files** — a `docx`, a deck on another template: said
  `pending` until LEKA draws them.
- **Running a routed agent on its own**: the router (LEKA-398,
  [capability-router.md](capability-router.md)) offers it on the intention;
  a person runs it — orchestration is LEKA-399.
- **Acting on what an agent proposes**: a decision (LEKA-390), never the
  agent.
- More tools — a document's text, a source's records — each read-only, each
  with its permission.

## 6 quinquies. The designer's mock-ups (`renders: design_mockups`)

The designer (`design-review`) proposes screens, not only findings. When a
request asks it to propose, improve, redraw or fully review a screen, its
review holds « La proposition », opened by the line `<!-- leka-design -->`:
the screen today with its values, then two or three proposals on named axes,
and the one it recommends. Then (`capabilities/mockups.py`):

- the model is asked again, no tools, with the review and the files the run
  read (`read_file`, kept with the run, at most 40,000 characters each and
  160,000 in all) for the screen today and each proposal — each a mock-up,
  its CSS and its body (`deliverables/design.py`, `DesignProposal`);
- every mock-up is cleaned: no script, frame or embedded object, no event
  handler, no link that leads anywhere, no source but `data:` images, no
  `@import`; LEKA makes the page itself, opened by a Content-Security-Policy
  that allows inline styles and `data:` only;
- kept at `{workspace}/agent-runs/{run}/design.json`; the run's detail says
  it in short (`design`), its report reads without the mark;
- `GET /agent-runs/{id}/design` gives each mock-up as its page, to whoever
  may read the run. The screen shows them in frames sandboxed with no
  permission at all, before and after, side by side, at a desktop's, a
  tablet's or a phone's width; the browser draws a PNG capture itself.

A review without the mark draws nothing and asks no model. What fails here
never fails the run: its review stands, `deliverables_error` says why.

