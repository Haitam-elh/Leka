# The intelligence engine

What LEKA concludes from what it knows (LEKA-377): analyses over the company
model and the contexts, run on their own and on demand, each conclusion kept
as a **finding** with what shows it and where that was read — for the
intentions and the screens that build on them.

This is the frame of the Intelligence epic. LEKA-377 shipped the frame and
three representative analyses; LEKA-378 adds change and impact (§ 11); 379
(knowledge gaps), 380 (enrichment), 381 (quality), 382 (conflicts) and 383
(evolution and insights) add theirs to it.

Code: `api/leka/intelligence/` — `analysis.py` (the frame), `rules.py` (the
analyses), `service.py`, `repository.py`, `job.py`; the routes in
`api/leka/api/intelligence.py`.

---

## 1. The four things

| | What it is | Where |
| --- | --- | --- |
| **Analysis** | A named, versioned function from *material* to *drafts*: what it reads (the company model, the contexts), how it reasons (`rules`, or `model` once the gateway exists), how long it may take (`budget`, 30 s by default). | `Analyzer`, `ANALYZERS` |
| **Run** | One time LEKA analysed a workspace: why (`model`, `schedule`, `request`), by whom, from which build of the model (`model_built_at`), which analyses, the background job that ran it (`job_run_id`), what came of it. | `intelligence_runs` |
| **Step** | One analysis of a run: its version, its duration, what it found — or the error's type, or why it was skipped. | `intelligence_steps` |
| **Finding** | What an analysis concluded about one thing, kept across runs under one key: open or resolved, how bad, how sure, what it is about, what shows it, where that was read, which runs saw it. | `intelligence_findings` |

An analysis never touches the database. A run reads its **material** once
(§ 3), hands it to each analysis, and keeps what comes back. So an analysis is
a pure function, tested in a millisecond (`tests/test_intelligence_rules.py`).

## 2. When it runs

```
the model built ──▶ event "knowledge.model_built" ──▶ run_intelligence_for_event ─┐
someone asks    ──▶ POST /intelligence/runs ──────────────────────────────────────┤──▶ intelligence:<workspace>
the sweep       ──▶ hourly, :56 ──────────────────────────────────────────────────┘        one at a time
```

- **The model changed.** Every build that changed something publishes
  `knowledge.model_built` (LEKA-374). The contexts follow it, and the
  workspace is analysed again. Both are routes of the same event
  (`leka/background/routes.py`).
- **Someone asks.** `POST /intelligence/runs` runs every analysis, or the ones
  named. One run at a time per workspace: a second ask while one is queued or
  running answers `{"queued": false}`, and the running one will answer.
- **The sweep** (`intelligence-sweep`, hourly at :56) queues what no event
  will:
  - a workspace never analysed;
  - one whose model was built since its last run;
  - one whose latest run used another catalogue (an analysis added, or a
    version raised);
  - one not analysed for 24 hours — a context falls behind with time, not
    only with builds.

  It is also where old runs and stuck runs are cleaned up (§ 8).

## 3. What a run reads

**The company model, as the architecture reads it:**
`GraphService.architecture(detailed=True)`. These are the same cards, states,
teams, maintainers and named links that *Mon environnement* draws, so a
finding never disagrees with what the person sees. Up to 200 cards per
column. With it, who owns each card's entity: the teams and the people a
source names as owners (`GraphService.owners`). The architecture names only
a team.

**The contexts in use:** those used in the last 30 days, at most 500, each
with:
- whether it follows the model;
- since when it has been behind, and how many changes are pending;
- the quality level and score of its latest version.

**The changes of the last 30 days** (LEKA-378), at most 100, each with its
footprint: what it was made to, what that reaches, what followed (§ 11).

Each part is read in **its own session**, and only when an analysis of the run
needs it. A part that cannot be read is left out and logged
(`intelligence_material_unread`), and the analyses that need it are skipped
with `no_material`. The others run: a database error in one read would
otherwise abort the transaction of the next.

## 4. Execution, and what happens when it fails

The job (`analyse_workspace`) works in four phases:

1. **The run is recorded `running`** and committed before anything is read.
   A run a worker dies in is therefore found later, and closed (§ 8).
2. **The material is read** (§ 3).
3. **Each analysis runs, isolated** (`analysis.execute`, which never raises),
   and its outcome is kept in **its own transaction**.
4. **The run is finished:**
   - `succeeded` when nothing failed (skipped steps count as fine);
   - `partial` when some steps failed;
   - `failed` when none succeeded or was skipped.

   Its counts are the sum of its steps'.

What can go wrong, and what is done:

| What | The step | The run | The findings |
| --- | --- | --- | --- |
| The analysis raises | `failed`, `error` = the exception's type | partial (or failed) | its own **untouched** — not seeing them is not knowing they are gone |
| It exceeds its budget | `timed_out` | partial | untouched. Its thread is left to end on its own: Python cannot stop it |
| Its findings cannot be written (a database error) | rolled back alone, recorded `failed` in a fresh session | partial | untouched |
| It needs a model | `skipped`, `reason = no_model` | unaffected | — |
| It needs material that could not be read | `skipped`, `reason = no_material` | unaffected | — |
| The run cannot even start | — | none | — : the background loop retries the job (ADR 013) |

**Error text is never stored, only its type.** Messages name hosts, paths and
queries; they go to the logs:
- `intelligence_step_failed`, with the run, the analysis, the status and the
  duration;
- `intelligence_step_unrecorded`, with the traceback.

The run's `job_run_id` is the background run's id, which is the `run_id` of
every log line the worker wrote for it. So "the run" and "the worker's logs"
are one search.

## 5. A finding's life

A finding's identity is its analysis and its **key**, for example
`entity:<id>` or `context:<id>:behind`. The same key from run to run is the
same finding:

```
                       seen again ─┐
not there ──▶ OPEN ◀───────────────┘          (occurrences + 1, what it says rewritten)
               │  not produced by a run whose step succeeded
               ▼
            RESOLVED  (resolved_at, resolved_run_id)
               │  produced again
               ▼
            OPEN      (reopened + 1)
```

Each run rewrites what a finding says: its severity, rank, confidence, words,
evidence and provenance, as of that run. The finding keeps:
- `first_seen_at` and `first_run_id`;
- `last_seen_at` and `last_run_id`;
- `resolved_run_id`;
- `occurrences`;
- `reopened`.

**What a finding says.** A `code` and its `params`, which the interface words
in each language, plus a `statement` in English for anything that reads it
without a dictionary (an agent, a log).

**How it is ordered.** `severity` (`high`, `medium`, `low`), then a `score`
within it, gives the `rank`: 300 to 399 for a high finding. Lists are sorted
by rank by default.

**What shows it.** `evidence` is the entity, each relationship with its role
and the file and line that state it, and the context with its version.
`related` lists the other things it involves.

**Where it was read.** `provenance` holds:
- the analysis and its version, and its method;
- the run;
- the build of the model it read (`model_built_at`);
- the kinds of sources it rests on;
- the context version, when it read one.

## 6. The first analyses

| Analysis | Category | Reads | What it says | Severity |
| --- | --- | --- | --- | --- |
| `dependency_concentration` | architecture | model | What 3 or more things rely on (roles `calls`, `queue`, `cache`, `stores`, `files`, `email`, `uses`, `depends`, `deployed_on`; each dependent counted once) | **high** when it is in incident or needs attention, or when 5+ rely on it and nothing watches it · **medium** when unwatched, or 5+ rely on it · **low** otherwise |
| `ownership` | organisation | model | What runs or keeps data (the *services* and *data* columns) with no owner named for it: no team and no person a source says owns it (`owned_by` from it, or `owns` to it) | **high** when 3+ rely on it or it is in incident · **medium** for a service, or when something relies on it · **low** otherwise — one step lighter when people maintain it by their work. Confidence 0.9: an owner may exist that no source names |
| `context_health` | context | contexts | The contexts used in the last 30 days that failed, fell behind the model (following it, more than a day, changes pending), or were judged `low` | failed: **high** if used in the last 7 days, else medium · behind and weak: **medium** if used in the last 7 days, else low |
| `change_impact` (LEKA-378) | change | changes | Each current change that matters — or that an incident followed — about the service it was made to: what it reaches, the most affected first, what followed (§ 11) | **high** when an incident followed, or a failed production change reaches something · **medium** when a production change reaches something, or it failed, or touches something critical · **low** otherwise |

**What "watched" means.** A thing is watched when its state is known — from a
monitoring tool, or its provider — and not deduced. If its state is unknown,
`unmonitored`, or deduced from what runs it, nothing watches it.

**What they find on LEKA's own repository**
(`tests/test_intelligence_engine.py`):
- PostgreSQL, relied on by the API, the worker and the scheduler, with
  nothing watching it;
- every service, with no owner named — a personal GitHub account has no
  teams, and nothing in the code says who owns what.

## 7. The API

| Route | What it does | Permission |
| --- | --- | --- |
| `GET /intelligence/analyzers` | The catalogue: name, version, category, method, what it reads, whether it can run here. | `workspace:read` |
| `POST /intelligence/runs` | Analyse now. The body is `{"analyzers": [...]}` (optional). An unknown name gets 422 and nothing is queued. Answers 202 `{"queued": bool}`. | `intention:create` — asking LEKA something, like an intention; refused to a suspended workspace |
| `GET /intelligence/runs` | The runs, latest first, paginated. | `workspace:read` |
| `GET /intelligence/runs/{id}` | One run, with each step. | `workspace:read` |
| `GET /intelligence/findings` | Paginated, sorted by `rank` (default) or `last_seen_at`. Filters: `status`, `severity`, `category`, `analyzer`, `subject`. | `workspace:read` |
| `GET /intelligence/findings/{id}` | One finding, with its evidence, related things, provenance and runs. | `workspace:read` |
| `GET /intelligence/summary` | Open findings by severity, the 5 most pressing, and the latest run — for a product surface at a glance. | `workspace:read` |
| `GET /intelligence/changes`, `GET /intelligence/changes/{id}` | The changes, judged, and one change's impact (LEKA-378, § 11). | `workspace:read` |

Another workspace's run or finding is 404. The workspace always comes from
the session (architecture rule 3).

**Downstream, in code.** `IntelligenceService.about(ids)` returns the open
findings about given entities or contexts. An intention looking at a service
starts from what LEKA already concluded about it.

**In the app.** The *Insights LEKA* card on *Vue d'ensemble* and on *Mon
environnement* shows the summary.

## 8. Retention and housekeeping

All of it is done by the sweep:

- **Runs still `running` after the job time-out plus an hour** are
  `abandoned`, with error `WorkerLost`.
- **Runs older than 90 days** are deleted with their steps, except each
  workspace's latest. Findings keep their run ids without a foreign key: they
  still say which runs saw them.
- **Findings resolved over a year ago** are deleted. Open ones are kept.

## 9. Adding an analysis

1. Write a function `Material → list[Draft]` in `rules.py`, or in a module of
   its own for the tickets after this one. It must be pure: everything it
   needs is in `Material`. If it needs more, add a part to `Material` and read
   it in `job.py`, in its own session.
2. Add an `Analyzer(...)` line to `ANALYZERS`: name, version, category,
   method, what it reads, a one-line summary.
3. Give every draft a **stable key**, so that the same conclusion is the same
   finding run after run, and a code that the interface words
   (`web/lib/i18n/dictionaries.ts`, `intelligence.codes`).
4. When what it concludes changes, raise its **version**. The catalogue hash
   changes, and the sweep analyses every workspace again within the hour.

A model-assisted analysis is declared with `method=Method.MODEL`. It is
skipped (`no_model`) until `leka.capabilities` calls a model (architecture
rule 7). The frame does not change the day one runs: `intelligence` sits above
`capabilities` for that reason (`tests/test_module_boundaries.py`).

## 10. Operating it

```sql
-- the latest runs, and how they went
SELECT workspace_id, trigger, status, started_at, finished_at, counts
FROM intelligence_runs ORDER BY started_at DESC LIMIT 20;

-- what failed, by analysis, this week
SELECT analyzer, status, error, count(*)
FROM intelligence_steps
WHERE status IN ('failed', 'timed_out') AND started_at > now() - interval '7 days'
GROUP BY 1, 2, 3 ORDER BY 4 DESC;

-- a run, to the worker's logs: its job_run_id is their run_id
SELECT id, job_run_id FROM intelligence_runs WHERE id = '…';

-- what is open, by analysis and severity
SELECT analyzer, severity, count(*) FROM intelligence_findings
WHERE status = 'open' GROUP BY 1, 2 ORDER BY 1, 2;
```

## 11. Change and impact (LEKA-378)

Which changes matter, what they reach, and what followed them.

**The facts** come from the company model (`GraphService.footprints`, in
`leka.knowledge`). For each change — a deployment, a change request, a
release, a pull request — its *footprint* is:

- **What it was made to:** what its source ties it to — part of, affecting,
  deployed to — when it is a service, an application, a repository, a
  database or a resource (not an environment, not a commit). A change made in
  a repository is made to the service that repository is part of
  (`via_repository`): a GitHub deployment says its repository, and the
  repository says its service.
- **What it reaches:** what depends on that, two steps up, each with its
  distance and through which.
- **The business holding it:** the applications, capabilities and processes
  (`KnowledgeService.impact`, the same reach an incident's analysis shows).
- **What followed:** the incidents that opened on that footprint within
  **48 hours** of it, with what they affected; and any incident whose source
  says the change caused it, whenever it opened. An incident that opened
  before the change is never tied to it.
- **What its source says of it:** ref, commit, version, URL, risk, and the
  kinds and ids of its sources.

**The judgement** is pure (`leka/intelligence/changes.py`):

| | |
| --- | --- |
| Signals | `production` (its environment says prod, live), `failed` (failed, error, rolled back, canceled), `incident_after` (one followed on its footprint), `stated_cause` (a source says it caused one), `wide` (3+ reached), `business` (a capability or a process holds it), `critical` (something it touches or reaches is said critical) |
| Significance | its kind's weight (deployment 0.35, change 0.3, release 0.25, pull request 0.1) plus each signal's (stated cause 0.4, incident after 0.3, failed 0.25, production 0.2, wide 0.15, business 0.1, critical 0.1), up to 1. Made to nothing the model knows: a third of that |
| Current or history | within **72 hours** it is current, still playing out. Older is history: it is in the timeline, never a finding |
| Impacts ranked | what an incident hit first (+0.4), then what it was made to (0.5), then what depends on it (0.3 one step, 0.15 two); +0.1 when critical; an application holding it 0.25 |

**A finding** (`change.impact`) is made of each current change that matters
(significance ≥ 0.4) or that an incident followed. Its subject is the
service it was made to, so it leads to that service's sheet. It says:
- the change, when, where, how it went;
- how much it reaches, the three most affected;
- the incidents that followed.

Its confidence is **1.0** when a source states the cause or when no incident
is involved, and **0.7** when only time ties an incident to it: likely, not
proven. When the change becomes history, and no incident keeps it current,
the finding is resolved by the next run.

**The API:**
- `GET /intelligence/changes?since&until&entity&limit` lists the changes, the
  latest first (30 days by default, 90 at most), each judged: current or
  history, significance and signals, what it was made to, how far it
  reaches, the three most affected, the incidents that followed. With
  `entity`, it lists the changes made to it, to what it is made of, or to
  what it depends on (and what each of those is made of): a deployment in
  the repository of a service it calls is around it.
- `GET /intelligence/changes/{id}` gives everything a change reaches,
  ranked, the business, what followed and how many hours after, and what its
  source says of it.

Both are `workspace:read`.

**For an intention**, `IntelligenceService.change_timeline` and
`change_detail` are the same reads in code: "what changed around payment-api
this week, and what did it reach" is one call.

**Not here:** changes LEKA sees in its own model from one build to the next
— a dependency appearing, an owner gone. Those are the model's evolution
(LEKA-383); this reads the changes the sources record.

## Not yet

- **Model-assisted analyses.** The model gateway is empty (LEKA-329); they
  are declared and skipped.
- **Dismissing a finding** ("known, accepted"). That is a decision, and it
  belongs to LEKA-389/390 (findings, human decision).
- **The epic's other analyses** — change and impact, gaps, enrichment,
  quality, conflicts, evolution — are LEKA-378 to 383, on this frame.
