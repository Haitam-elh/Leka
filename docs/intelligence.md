# The intelligence engine

What LEKA concludes from what it knows (LEKA-377): analyses over the company
model and the contexts, run on their own and on demand, each conclusion kept
as a **finding** with what shows it and where that was read — for the
intentions and the screens that build on them.

This is the frame of the Intelligence epic. LEKA-377 shipped the frame and
three representative analyses; LEKA-378 adds change and impact (§ 11),
LEKA-379 knowledge gaps (§ 12), LEKA-380 knowledge enrichment (§ 13); 381
(quality), 382 (conflicts) and 383 (evolution and insights) add theirs to
it.

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
| **Candidate** (LEKA-380) | An enrichment of the company model an analysis proposed — a relationship, an attribute — kept across runs under one key: proposed, accepted, rejected or withdrawn, how sure, what shows it, every decision taken. Once accepted, a fact the model's build applies (§ 13). | `enrichment_candidates`, `model_assertions` |

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
a team. And, read with it (LEKA-379):
- what the model holds around each card's entity (`GraphService.standing`):
  how critical its sources say it is, how many documents and spaces describe
  it, how many of them are documents not stale, when the latest changed,
  whether an application, a capability or a process holds it;
- how many documents the workspace has;
- each source kind's family — its connector's category (`leka.connectors`).

**The contexts in use:** those used in the last 30 days, at most 500, each
with:
- whether it follows the model;
- since when it has been behind, and how many changes are pending;
- the quality level and score of its latest version.

**The changes of the last 30 days** (LEKA-378), at most 100, each with its
footprint: what it was made to, what that reaches, what followed (§ 11).

Each part is read in **its own session**, and only when an analysis of the run
needs it — or *heeds* it (`Analyzer.heeds`): a part it reads when it can be
read, which only weighs what it concludes. Unread, that analysis still runs. A part that cannot be read is left out and logged
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
| `gaps_entities` (LEKA-379) | gaps | model (heeds changes) | A service whose runtime or code is unknown, a database whose tables are (§ 12) | by priority (§ 12): **high** from 0.6, **medium** from 0.35, **low** under |
| `gaps_relationships` | gaps | model (heeds changes) | What is tied to nothing; a service no application, capability or process holds | by priority |
| `gaps_documentation` | gaps | model (heeds changes) | What no document describes, or none known to be current | by priority |
| `gaps_staleness` | gaps | model (heeds changes) | A source failing or not read for 3 days; a dormant thing others still rely on | by priority |
| `gaps_coverage` | gaps | model | A whole family of sources not connected, once, with all it leaves unknown | by priority |
| `enrich_code`, `enrich_runtime`, `enrich_owner`, `enrich_application`, `enrich_criticality`, `enrich_description` (LEKA-380) | enrichment | model | Proposals, not findings: what the model lacks that the evidence around it says (§ 13) | — a confidence instead |
| `enrich_summary` | enrichment | model | What a service does, in words — model-assisted: skipped until the gateway exists | — |

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
   (`web/lib/i18n/dictionaries.ts`, `insights`; `word()` in
   `web/components/insights/leka-insights.tsx`). A code it does not know yet
   is shown as the draft's English `statement`.
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

## 12. Knowledge gaps (LEKA-379)

What LEKA does not know, or no longer knows, that limits what it can
understand — and which gap to close first. Code:
`api/leka/intelligence/gaps.py` (pure).

**Five families, five analyses** (category `gaps`). Each family has its own
codes, so a surface tells a missing entity from a missing relationship, from
missing documentation; `params.gap` names the family.

| Family | Analysis | Codes | What it says |
| --- | --- | --- | --- |
| entity | `gaps_entities` | `gap.missing_entity.runtime`, `.code`, `.data_model` | A service no cloud resource is said to run; a service no repository is said to be the code of; a database whose tables, views and collections are unknown |
| relationship | `gaps_relationships` | `gap.missing_relationship.isolated`, `.business` | A service or a store tied to nothing at all; a service no application, capability or process holds — said only once the workspace knows its business at all |
| documentation | `gaps_documentation` | `gap.missing_documentation`, `gap.stale_documentation` | What runs or keeps data that no document or space describes, or that only documents not known to be current describe (neither fresh nor aging) — what the Documentation page calls a gap (LEKA-366), weighed |
| staleness | `gaps_staleness` | `gap.stale_source`, `gap.stale_knowledge.dormant` | A source switched on but in error, or not read for **3 days**: what it shows may no longer be so; a thing dormant (no activity for 180 days) that others still rely on |
| coverage | `gaps_coverage` | `gap.coverage.<family>`: `monitoring`, `cloud`, `code`, `documentation`, `data`, `organisation` | A whole family not connected — said once, with how much it leaves unknown |

**The family first, then the thing.** A thing's gap is said only when the
family of sources that would fill it is connected: a cloud for where it runs,
a code host for its code, a database source for its tables, any document for
its documentation. Otherwise it is one coverage gap — with no cloud, every
service's runtime is unknown, and that is one finding, not forty.
- A source is connected once someone switched it on: active, degraded or in
  error. A draft, tested or disabled one is not.
- The family is the connector's category (`leka.connectors.manifests()`):
  observability → monitoring, cloud, code, data.
- Documentation is read from the documents themselves — a custom source
  brings them too (LEKA-350).
- The organisation is missing when no team is known and no one is named owner
  of anything.

**One question at a time.**
- What is tied to nothing gets that gap, and its documentation's — not its
  runtime, code and business too: they are unknown because it is.
- An application runs as its services do: its runtime and code are not asked
  of it.
- What has gone dormant is asked one question, *is it still what they use?*,
  and only while something relies on it.
- Modules and tools drawn from the code are not what a gap is about.

**Prioritization.** Each gap starts from a base, by what it is:

| Base | Codes |
| --- | --- |
| 0.35 | `gap.stale_source` — +0.1 when in error, +0.03 per thing of the architecture it shows (at most +0.3) |
| 0.3 | `gap.coverage.*` — +0.03 per thing it leaves unknown (at most +0.3) |
| 0.25 | `gap.missing_entity.runtime` |
| 0.2 | `gap.missing_entity.code`, `gap.missing_relationship.isolated`, `gap.stale_knowledge.dormant` |
| 0.15 | `gap.missing_entity.data_model`, `gap.missing_relationship.business`, `gap.missing_documentation` |
| 0.1 | `gap.stale_documentation` |

A thing's gap then weighs what makes the thing matter — the defined signals,
in `params.signals`:

| Signal | Adds | When |
| --- | --- | --- |
| `relied_on` | 0.06 per thing relying on it, at most 0.3 | by the reliance roles of § 6, each dependent once |
| `critical` | 0.2 | its sources say critical, high, tier 1 or P1 |
| `unwell` | 0.1 | in incident, or needing attention |
| `production` | 0.1 | its environment says prod or live |
| `changing` | 0.15 | a current change (72 hours, § 11) touched or reached it |

The score is capped at 1: **high** from 0.6, **medium** from 0.35, **low**
under; the rank is the frame's (§ 5). Confidence is **0.9** for a thing's gap
— something unread may know it — and **1.0** for a stale source or a
coverage gap, facts about the workspace's own sources.

**Changes only weigh.** The gap analyses read the model and *heed* the
changes (§ 3): read, they add `changing`; unread, every gap is still said.

**What shows it.**
- A thing's gap: the thing as subject (`entity`); as evidence, what is
  missing ("no repository of a connected code host is said to be its code");
  the kinds of its sources.
- A stale source: the source as subject (`source`: id, name, kind); as
  evidence, its status and when it was last read.
- A coverage gap: the family as subject (`coverage`, no id); as evidence, the
  sources connected.

**Who reads them.**
- The API: `GET /intelligence/findings?category=gaps` — or `analyzer=gaps_…`,
  or `subject=` an entity's or a source's id — the most pressing first.
- The Insights LEKA card: each code worded in French and English, leading to
  the thing's sheet, the source's page, or the sources, to connect one.
- An intention, through `IntelligenceService`: the same reads.

**On the demo** (`scripts/seed.py`):
- the Confluence runbooks space, in error, never read;
- payment-api's code unknown — the repository acme/backend is not tied to
  it;
- its only runbook unchanged since February, while it was deployed 26 hours
  ago (`changing`);
- no database source;
- postgres-prod, auth-service and user-service described by no document.

**Not here:** filling a gap — finding the missing entity, writing the
missing document. Enrichment is LEKA-380 (§ 13).

## 13. Knowledge enrichment (LEKA-380)

What the company model lacks that the evidence around it says — proposed,
never imposed. Code: `api/leka/intelligence/enrichment.py` (the proposals,
pure), `curation.py` (what becomes of them).

**Not ingestion's enrichment.** Enrichment at ingestion
([enrichment.md](enrichment.md), LEKA-359) completes each record as it comes
in and keeps every inference sure enough. This reads the whole model, as the
other analyses do, and **proposes**. A proposal is kept as a **candidate**,
and reaches the model only once validated.

**What is proposed.** Four families, one or more analyses each (category
`enrichment`, `params` worded by the interface):

| Family | Analysis | Proposes | Confidence |
| --- | --- | --- | --- |
| relationship | `enrich_code` | for a service whose code is unknown, the repository of its name (`part_of`, from the repository) | 0.8 the same name, 0.65 one word more |
| | `enrich_runtime` | for a service whose runtime is unknown, the cloud resource of its name (`deployed_to`) | 0.75, 0.6 |
| organisation | `enrich_owner` | for what runs or keeps data that no one owns: the team owning its repository (`owned_by`) — or the team most of its maintainers are members of, two thirds at least | 0.9; 0.5 + 0.35 × the share |
| business | `enrich_application` | for a service no application holds: the application its neighbours are part of — two at least, two thirds of them — or whose name it carries (`part_of`) | 0.5 + 0.3 × the share; 0.7 |
| semantic | `enrich_criticality` | how critical a thing is: the level of the application holding it, when high or critical; `high` when five or more rely on it — where nothing is said, or above what is | 0.75; 0.65 |
| | `enrich_description` | a service's description, from the repository that is its code — and its alone | 0.7 |
| | `enrich_summary` | what a service does, in words — model-assisted, skipped until the gateway exists (`no_model`) | — |

A name says what it is without what kind of thing it is: `payment-api`,
`acme/payments` and `payments-service` are one name (`words`, the kind words
— api, service, backend, prod… — and plurals left out). Each analysis
proposes only where the family of sources that would say it is connected
(the rule of § 12), only when one answer stands out — two repositories named
alike say nothing — and nothing a thing already has.

**A candidate's life.**

| State | |
| --- | --- |
| `proposed` | waiting. Seen again, it is updated; no longer seen — its evidence went — it is `withdrawn` |
| `accepted` | by a person, or by the **policy**: what is sure (0.9 or more), made by rules, and adds without replacing — today, the team owning a thing's repository. A fact of the model from then on |
| `rejected` | by a person, with a reason if they give one: never proposed again under its key. An accepted candidate rejected is withdrawn from the model |
| `withdrawn` | no longer proposed; proposed again if its evidence comes back. Forgotten after a year unseen — a decision is kept |

**Reprocess** sends a rejected or withdrawn candidate back to its analysis:
proposed again at once, the analysis queued — the next run keeps it if its
evidence still holds, withdraws it otherwise. One in the model is rejected
first. Every decision is kept on the candidate (`history`): status, via
(person or policy), by whom, when, why.

**Trusted information is not overwritten without a controlled
validation.** A proposal that would replace what a source says
(`overrides` — `EntityStanding.stated` says which attributes a source
states) is never the policy's, and a person accepts it only by saying so
(`override: true`; without it, 409).

**How a fact reaches the model** (leka.knowledge, [company-model.md § 6](company-model.md)):
- **Accepted** — the fact is written to `model_assertions`, under the
  candidate's id, in the decision's transaction, and a build is queued.
- **The build applies it**:
  - an attribute where no source says one, before enrichment's own guess;
  - over a source's value only when it overrides it, the value it replaced
    kept (`provenance.attributes.<name>.replaced`);
  - a relationship with the origin `accepted`, the decision in its
    provenance. A source's stated relationship is kept over it; an
    inferred one gives way to it; a loop is never broken by dropping it.
- **The fingerprint** of the validated facts is part of what a build was
  made from (`model_runs.assertions`): the hourly sweep builds what a
  decision did not get built.
- **Rejected** — the fact is deleted in the same transaction; the next
  build no longer applies it, and what the sources say comes back.
- **A build that fails** changes nothing — the model is written in one
  transaction — and keeps the facts for the next.

**Downstream**, a validated fact is the model's like any other, with its
origin:
- `GET /knowledge/relationships?origin=accepted`;
- an entity's `provenance.attributes`;
- the context engine — an accepted link is trusted at 0.9, between a
  source's word (1.0) and an inference (0.7), and said "proposed by …,
  validated" in a context's text;
- Mon environnement's text alternative: "(proposé par LEKA, validé)".

**The API:**

| Route | | Permission |
| --- | --- | --- |
| `GET /intelligence/enrichment/candidates?status&family&analyzer&subject` | The candidates, the latest seen first (`sort=last_seen_at`) or the surest (`sort=confidence`); `subject` matches the thing enriched or either end | `workspace:read` |
| `GET /intelligence/enrichment/candidates/{id}` | One: what it proposes, its evidence, where it was read, every decision | `workspace:read` |
| `GET /intelligence/enrichment/summary` | How many are proposed (by family), accepted (by the policy among them), rejected, withdrawn | `workspace:read` |
| `POST …/candidates/{id}/accept` `{override?, reason?}` | 409 when it is not proposed, when what it is about has gone, when its relationship's contract does not take its ends, or when it overrides and `override` is not said | `intention:approve` |
| `POST …/candidates/{id}/reject` `{reason?}` | From proposed or accepted; 409 otherwise | `intention:approve` |
| `POST …/candidates/{id}/reprocess` | 202 `{candidate, queued}`; 409 for one in the model | `intention:approve` |

Deciding what goes into the company model is approving: `intention:approve`,
as À valider is.

**In the app:**
- **À valider** (`/approvals`, mockup 09) lists the proposals: waiting,
  accepted (by the policy among them), rejected, withdrawn; by type; each
  worded, with why and how sure. Opened, a proposal says:
  - what it would change, and warns when it replaces a source's word;
  - what shows it, and where it was read;
  - every decision taken.

  Who may approve accepts — an override only once confirmed — rejects with
  a reason, or sends back what was rejected.
- **Vue d'ensemble**, card "À valider": the three latest proposals waiting.
- **The sidebar**: the count of proposals waiting, beside "À valider", for
  who may approve.

**On the demo** (`scripts/seed.py`):
- Thomas and Mei maintain postgres-prod — the database no one is named to
  own — and both are members of Platform: "Platform est responsable de
  postgres-prod", 0.85.
- acme/user-service is a repository nothing ties to user-service:
  "acme/user-service est le code de user-service", 0.8. Accepted and built,
  the gap "Le code de user-service est inconnu" (§ 12) resolves.

**Not here:** the decisions on intentions (LEKA-389, LEKA-390), which will
join À valider's queue; a workspace's own policy threshold, which is one
constant today (`POLICY_CONFIDENCE`).

## Not yet

- **Model-assisted analyses.** The model gateway is empty (LEKA-329); they
  are declared and skipped.
- **Dismissing a finding** ("known, accepted"). That is a decision, and it
  belongs to LEKA-389/390 (findings, human decision).
- **The epic's other analyses** — quality, conflicts, evolution — are
  LEKA-381 to 383, on this frame.
