# Intentions

What someone asks LEKA, kept from the moment they ask to the moment what
was done is verified — where it stands, what happened to it, what it rests
on and what came of it (LEKA-384). An action taken against a customer's
production system must be answerable months later: who asked, what LEKA
concluded, who approved, what ran.

This is the frame of the Intentions epic. LEKA-384 keeps the intention, its
lifecycle, its history and its links; LEKA-385 understands it (§ 9), LEKA-386 scopes it (§ 10), LEKA-387 grounds it in its context (§ 11), LEKA-388 analyses it (§ 12);
389 concludes; 390 decides; 391 acts; 392 verifies — each moving it along
this lifecycle and linking what it makes.

Code: `api/leka/intentions/` — `lifecycle.py` (the states and moves, pure),
`models.py`, `repository.py`, `service.py`; the routes in
`api/leka/api/intentions.py`.

---

## 1. The three things

| | What it is | Where |
| --- | --- | --- |
| **Intention** | What was asked: its words (`text`), a `title` — its first 300 characters unless one is given — the `scope` chosen (environment, period, services, sources), who asked (`created_by`), its `status` and since when, what it asks for as LEKA read it (`kind`: diagnose, change, migration, compliance, dependency, ownership, knowledge, general — LEKA-373), the context it is analysed from (`context_id`), what LEKA concluded in a sentence (`summary`, LEKA-389), whether it is archived | `intentions` |
| **Event** | One thing that happened to it: created, moved from one state to another, linked or unlinked, archived or restored — numbered (`sequence`), by whom (`actor`: a person and which — `by` — or LEKA itself), when, why (`reason`), and what else it says (`detail`: the scope asked, the context version, what was linked) | `intention_events` |
| **Link** | What it rests on, or what came of it: its context, a finding, an entity it is about — and its decisions, actions and outcomes (LEKA-390 to 392) — named as it was when linked (`label`, `detail`: a context's version, a finding's code), so the link still says it when the thing is gone | `intention_links` |

No foreign key from a link to what it names: findings are resolved and
pruned, contexts archived, and a link must still say what it was.

## 2. The lifecycle

```
submitted ──▶ analysing ──▶ awaiting_decision ──▶ approved ──▶ executing ──▶ verifying ──▶ completed
                 │                 │                 │  ▲          │              │
                 │                 ├──▶ rejected     ▼  │          └──▶ failed ◀──┘
                 └──▶ completed    │             scheduled
                      (answered)   └──▶ analysing (asked again)
```

| State | Means | Reached by |
| --- | --- | --- |
| `submitted` | asked: its words and scope kept, nothing read yet | creating it |
| `needs_clarification` | not understood enough to go on: what LEKA would ask is said (LEKA-385, § 9) | LEKA |
| `analysing` | its context assembled, LEKA analysing it (LEKA-387, 388) | LEKA, once its context is assembled; a person asking again |
| `awaiting_decision` | findings and recommendations ready: a person decides (LEKA-389, 390) | LEKA |
| `approved` | a person said act | a person — **never LEKA** |
| `scheduled` | to be acted on at a time chosen (LEKA-391) | a person, or LEKA |
| `executing` | its actions running (LEKA-391) | a person, or LEKA |
| `verifying` | what was done, checked (LEKA-392) | LEKA |
| `completed` | answered — a question needs no decision — or acted on and verified | LEKA, or a person verifying |
| `rejected` | a person said not to act | a person |
| `failed` | its analysis or its actions failed | LEKA |
| `cancelled` | withdrawn | a person |

**What may follow what** is said once (`lifecycle.TRANSITIONS`), each move
with the actors it allows and its name in the history:

| From | To | Name | By |
| --- | --- | --- | --- |
| submitted | analysing · needs_clarification · failed | `analysis_started` · `clarification_asked` · `failed` | LEKA |
| needs_clarification | analysing | `clarified` | a person, asking again |
| analysing | awaiting_decision · completed · failed | `proposed` · `answered` · `failed` | LEKA |
| analysing | analysing | `asked_again` | a person |
| analysing | needs_clarification | `clarification_asked` — asked again, still not understood | LEKA |
| awaiting_decision | approved · rejected · analysing | `approved` · `rejected` · `asked_again` | a person |
| approved | scheduled · executing | `scheduled` · `execution_started` | a person, LEKA |
| scheduled | executing · approved | `execution_started` · `unscheduled` | a person, LEKA · a person |
| executing | verifying · failed | `executed` · `failed` | LEKA |
| verifying | completed · failed | `verified` · `failed` | LEKA, a person |
| completed, rejected | analysing | `asked_again` | a person |
| failed | analysing · executing | `retried` | a person, LEKA |
| any but executing, verifying and closed | cancelled | `cancelled` | a person |

- **An approval is a person's, never LEKA's** (architecture § 5): the move
  to `approved` or `rejected` by LEKA is refused. A person's move names the
  person: one without `by` is refused.
- **Cancelled is final.** Completed and rejected may be asked again.
- **Nothing is cancelled while its actions run**: they finish, or fail, and
  are verified. Stopping an action is LEKA-391's.
- **Archived** is beside the lifecycle: an intention done with — completed,
  rejected, cancelled — may be set aside, and restored. An archived one
  does not move until restored.
- **Phases**, how a list groups them (mockup 07): `active` (submitted to
  verifying, and failed — something to do), `scheduled`, `finished`
  (completed, rejected, cancelled).

A move the lifecycle does not allow is `IllegalTransitionError` — 409 from
the API — and changes nothing.

## 3. Its history, audited

Every change is an event, written in the change's transaction, numbered
from 1 (`events_count` on the intention gives the next). **The database
refuses to change an event** (trigger `intention_events_append_only`,
SQLSTATE `restrict_violation`): the history cannot be rewritten, by LEKA
or by anyone with a SQL prompt. The one change allowed is who did it
forgotten — `by` set null when the user is deleted (a GDPR erasure); what
was done, when and why stays. Deleting stays possible: an intention's
events go with it, a workspace's with the workspace.

| Event | Says |
| --- | --- |
| `created` | by whom, the scope asked |
| `moved` | from, to, the move's name, by whom, why — asking again: the words and scope before, the context's new version |
| `linked`, `unlinked` | what kind, which, its label |
| `archived`, `restored` | by whom |

## 4. Asking — one transaction

`POST /intentions` takes what the new intention's form sends — the words
and the scope, as the context engine reads them (`IntentAsk`, LEKA-373):

1. the intention is kept, `submitted` (event 1: `created`);
2. the context it asks for is assembled — its subject the intention
   (`contexts.subject_type = 'intention'`), read as LEKA-373 reads it;
3. it is linked (event 2), its `kind` is the context's reading;
4. it moves to `analysing` (event 3, by LEKA).

**Nothing to start from** — its words name nothing in the company model and
say no word to search: 422, and nothing is kept, neither the intention nor
its context.

**Asked again** (`POST /intentions/{id}/ask`), its words or scope changed:
its context made again — the same context, a new version that says what
LEKA reads differently (LEKA-374) — and analysed again (`asked_again`; from
`failed`, `retried`). Refused once cancelled, archived, or while its
actions run.

## 5. What it is linked to

| Kind | Linked by | Checked |
| --- | --- | --- |
| `context` | LEKA, when it is assembled; a person | a context of this workspace (`leka.context`) |
| `finding` | a person; the analysis (LEKA-388) | a finding of this workspace (`leka.intelligence`) |
| `entity` | a person; understanding (LEKA-385, 386) | an entity of this workspace (`leka.knowledge`) |
| `decision`, `action`, `outcome` | what makes them (LEKA-390 to 392), in code | named by what makes them; not linked through the API until they exist |

Linked twice, the same link. The context it is analysed from cannot be
unlinked. `GET /intentions?linked=<id>` gives the intentions linked to a
context, a finding or an entity — what LEKA was asked about a service.

## 6. Who may do what

| | Permission |
| --- | --- |
| read intentions, their history | `intention:read` — every member |
| ask; ask again, cancel, archive, restore, link — **one's own** | `intention:create` |
| the same on **another's** intention | its asker, or who may approve (`intention:approve`) — else 403 |
| approve, reject | LEKA-390 |

Another workspace's intention is 404: the workspace is the session's
(architecture rule 3).

## 7. The API

| Route | |
| --- | --- |
| `POST /intentions` | ask: 201 `{intention, context}`; 422 when nothing can start it |
| `GET /intentions?phase&status&mine&q&linked` | paginated, the latest changed first (`sort=updated_at`) or asked (`sort=created_at`); not archived unless `phase=archived` |
| `POST /intentions/understand` | what LEKA would understand of these words (§ 9); nothing kept |
| `GET /intentions/counts?mine` | all, active, scheduled, finished, archived — the list's tabs |
| `GET /intentions/{id}` | where it stands, where it may go next (`moves`), what it is linked to |
| `GET /intentions/{id}/history` | every event, in order |
| `POST /intentions/{id}/ask` | `{intention, context}` |
| `POST /intentions/{id}/cancel` `{reason?}`, `/archive`, `/restore` | the intention |
| `POST /intentions/{id}/links` `{kind, ref_id}` · `DELETE …/links/{link_id}` | context, finding, entity |
| `GET /intentions/{id}/analysis` · `/analyses` · `POST …/analyse` | its analysis, the latest and every one; analysed again (§ 12) |

**In code**, for the tickets that move it: `IntentionService.move(id, to,
actor=…, by=…, reason=…, detail=…, summary=…)` and `link(id, kind, ref_id,
actor=…, label=…)`.

## 8. In the app

- **A new intention** (`/intentions/new`): submitting posts to
  `/intentions` — kept, its context assembled — and step 2 shows the
  context, with « Suivre dans Mes intentions ». Edited, it is asked again
  (`/intentions/{id}/ask`): the same intention, its context's next version.
- **Mes intentions** (`/intentions`, mockup 07): the intentions, the latest
  changed first — their title, their kind, their status in words, when they
  last moved — by phase, each tab counted by the API, searched by words;
  each leads to its page. The mockup's impact and sources columns come with
  the analysis.
- **An intention's page** (`/intentions/{id}`, its tabs in the URL):
  *Vue d'ensemble* — what was asked, its kind, the scope chosen, what LEKA
  concluded (or that it has not yet), what it is linked to, where it may go
  next; *Historique* — every event in words, by LEKA or by a person, with
  the context's version and the reason given; *Analyse* and *Preuves* —
  its analysis, how it went and on what (§ 12); *Actions* says it comes
  with the decision and its execution. Its asker, or who may
  approve, cancels it — asked first, with a reason — archives it once done
  with, restores it.

## 9. What LEKA understands of it (LEKA-385)

From the words, what the asker wants to achieve — without their knowing the
technical steps. Code: `api/leka/intentions/understanding.py`, pure; read
with LEKA-373's reading of the same words (`IntentPlan`: the kind, the
things named, the period, the environment, the gaps), never redone.

**The structured intent** — `Understanding`, version `UNDERSTANDING_VERSION`
(1), kept with the intention (`intentions.understanding`, its goal alone in
`intentions.goal` for lists), returned by `GET /intentions/{id}` and by
`POST /intentions/understand` (nothing kept):

| Field | |
| --- | --- |
| `text` | the words, as asked — the original wording, linked to all the rest |
| `mode`, `mode_said` | `question` — to answer — or `request` — to act on — and what said it: « ? », an interrogative first word (pourquoi, qui, comment, why, who…), a polite or wanting request (peux-tu, je veux, il faut, can you, please…) with an action, or an action verb |
| `kind` | LEKA-373's: diagnose, change, ownership, dependency, compliance, migration, knowledge, general |
| `goal` | `{code, said, confidence}` (below) |
| `actions` | each `{code, said, changes_systems}` — the verbs asked, never the nouns: « déploie » is asked, « le déploiement » happened |
| `entities` | what it is about: `{entity_id, name, type, how (asked, named, business), said, confidence}` — LEKA-373's subjects |
| `period`, `environment` | as LEKA-373 reads them, with their origin and words |
| `ambiguities` | each `{kind, blocking, said, options}` (below) |
| `clear` | no blocking ambiguity: it can be analysed |

**The goal**, in this order:

| Goal | When | Confidence |
| --- | --- | --- |
| `act` | a request with an action that changes systems — or documents, notifies, opens a ticket | 0.9 with a thing named, 0.5 without |
| `explain_cause` · `find_change` · `find_owner` · `map_dependencies` · `check_compliance` · `plan_migration` · `find_knowledge` | the kind: diagnose · change · ownership · dependency · compliance · migration · knowledge | 0.8 when two words or more say it, 0.6 one |
| `assess_impact` | a dependency kind whose words say impact (impact, affecte, touche, casse…) | idem |
| `investigate` | none of these, but a looking action: analyse, compare, check, list | 0.4 |
| `unknown` | nothing says it | 0 |

**Actions** (French and English verbs, folded):

| Changes systems — only after a person approves (LEKA-390, 391) | Does not |
| --- | --- |
| `restart`, `rollback`, `deploy`, `scale`, `stop`, `fix`, `update`, `migrate` | `investigate`, `compare`, `assess`, `list`, `document`, `notify`, `ticket` |

**Ambiguities** — flagged for clarification, never guessed:

| Kind | Blocking | When |
| --- | --- | --- |
| `too_short` | yes | fewer than two words that say something |
| `unclear_goal` | yes | no goal can be told — options: the goals |
| `no_subject` | yes | its kind is about something, and it names nothing LEKA knows (LEKA-373's `no_subject`) — options: what it may have meant |
| `unknown_subject` | yes | a thing asked for is not in the model |
| `action_without_target` | yes | an action on systems, on nothing named |
| `ambiguous_subject` | **when acting**, else a warning | the same words name several things — options: those things. Read each to answer a question; never act on a guess |
| `competing_goals` | no | two kinds said as much: read as the first — options: both goals |
| `several_requests` | no | several « ? », or several actions joined (et, and, puis, then) |
| `unknown_environment` | no | an environment the model does not know — options: those it knows |

**In the lifecycle.** Understood at creation, after its context is read: clear,
it is `analysing`; not, `needs_clarification` — the move's detail says the
goal and the blocking ambiguities. Clarified by asking again
(`POST /intentions/{id}/ask`, a person: `clarified`) — understood again, and
`needs_clarification` again if it still is not. Nothing is decided on what
was not understood: `needs_clarification` leads only to `analysing` or
`cancelled`.

**In the app.** « Ce que LEKA a compris » — on step 2 and on the intention's
page: the goal and whether it asks or requests, the actions — those that
change systems said « validation requise » — what it is about, each with
the words it came from; what LEKA needs, as questions with what it could
mean; « Préciser ma demande » opens the composer on the same intention
(`/intentions/new?intention=<id>`), its words to say better. The status
« À préciser » in Mes intentions.

**Deliberately words, not a model**: the model gateway does not exist yet
(LEKA-394). A model-assisted understanding will fill the same contract —
the reason it says every part's words.

**Tested** — `tests/test_intention_understanding.py`, pure: seven questions,
each its goal; a procedure needing no thing named; restart, rollback asked
politely, documenting and opening a ticket; the noun that happened against
the verb asked; looking without a kind; and the ambiguous — too short, no
goal, nothing named, an action on nothing, the same words naming two things
(a warning for a question, blocking for an act), two goals, several
requests, an unknown environment; every part's words in the text.
`tests/test_intentions_api.py`: understood and kept; « Redémarre le
service » flagged, asked, clarified; still unclear, asked again; a dry run
keeps nothing.

## 10. Its scope and constraints (LEKA-386)

Exactly what an intention is about and within which boundaries it must be
processed, so the analysis — and anything done after — stays within what
was meant. Code: `api/leka/intentions/scope.py`, pure; part of the
understanding (`Understanding.scope`, version 2 on), kept with it, routed
the same way: what is missing blocks, and goes to clarification first.

**The scope contract** — `IntentScope`:

| Field | |
| --- | --- |
| `entities` | what it is about: LEKA-373's subjects, **resolved against the company model**, each with its `lifecycle` there now (active, dormant, archived, removed; none when unread) |
| `excluded` | what it names to set apart: after « sauf », « hors », « à part », « except », « excluding », « sans » — not its subjects |
| `environments`, `environment_origin` | where it is held to: `asked` (the form), `text` (« en prod »), `constraint` (« uniquement en staging ») — none: everywhere |
| `period` | `{since, until, origin, said, explicit}` — explicit when asked, read from the words or the model (« depuis le déploiement »), not its kind's default |
| `sources` | the sources the form held it to; none: every one |
| `constraints` | each `{kind, said, value, hard}` (below) |
| `missing` | the critical information missing: the kinds of the blocking ambiguities it adds |

**Constraints**, from the words (French and English) and the form:

| Kind | Said by | Value | Hard |
| --- | --- | --- | --- |
| `exclude` | sauf, hors, except… + a thing named | its id | yes |
| `read_only` | sans rien modifier, lecture seule, read only, without changing… | true | yes |
| `no_downtime` | sans interruption, sans coupure, zero downtime… | true | yes |
| `deadline` | avant / d'ici / by / before + demain, ce soir, a weekday, la fin de la semaine | the day, when it can be told | yes |
| `window` | hors heures ouvrées, la nuit, ce week-end, outside business hours, tonight… | the words | yes |
| `urgency` | urgent, urgence, asap, au plus vite, immédiatement… | high | no — it weighs |
| `environment_only` | uniquement / seulement / only + en / in + an environment | the environment | yes |
| `target` | a migration's « vers … » / « to … » | the word | yes |
| `services`, `sources` | the form | their ids | yes |

**Missing or at odds** — ambiguities of the understanding:

| Kind | Blocking | When |
| --- | --- | --- |
| `missing_environment` | yes | an action on systems, no environment held, and the model knows several — options: those |
| `missing_target` | yes | a migration, and not where to |
| `conflicting_constraints` | yes | an action on systems, and read only |
| `subject_gone` | yes | a thing it is about is removed or archived in the model |
| `everything_excluded` | yes | every thing it names, it excludes |
| `subject_dormant` | no | a thing it is about has been inactive 180 days: is it still what is used? |

**Read with the model now.** At creation and each time it is asked again,
the service reads each subject's lifecycle and the environments the model
knows (`GraphRepository.by_ids`, `.environments`) and hands them to the
pure reading; `POST /intentions/understand` does the same, keeping nothing.

**In the app.** « Ce que LEKA a compris » says the scope: the environment
and where it comes from, the period — said in the request, with its words,
or its kind's default — what is excluded, the constraints (hard ones
marked), a thing no longer active. Its questions say what is missing.

**Tested** — `tests/test_intention_scope.py`, pure: things resolved with
their lifecycle; a default period not explicit; an exclusion set apart;
staging only, no downtime, before Friday (the 9th, from Wednesday the 7th),
outside business hours, urgent — each with its words; a migration's
target; the form's services and sources; read only for a question; and
the incomplete — acting among two environments (one known: none asked), a
migration without where to, acting while read only, a thing removed, a
dormant one only said, everything excluded. `tests/test_intentions_api.py`:
the scope kept, read against Acme's model, a dormant thing said.

## 11. Its context, and whether it can ground the analysis (LEKA-387)

How an intention gets the context its analysis needs, from the context
engine ([context.md](context.md)) and the company model. Code:
`api/leka/intentions/grounding.py` (pure), `IntentionService.create`,
`.ask_again`, `.context`; in the context engine, `IntentAsk.exclude` and
the `excluded` reason.

**The order, at creation and each time it is asked again:**

```
the words + the form's scope
   ──▶ ContextService.plan_intent        LEKA-373: kind, subjects, period, environment, gaps
   ──▶ understand()                      LEKA-385/386: goal, actions, ambiguities, the scope
   ──▶ refined()                         the ask, as the scope settled it
   ──▶ ContextService.assemble_intent    (or .reask: the same context, its next version)
   ──▶ readiness()                       can it ground the analysis?
   ──▶ kept with the intention, said in the move to analysing — or needs_clarification
```

**Assembled from its structured scope** (`refined()`):

| From the scope | To the context engine |
| --- | --- |
| what it excludes (« sauf Checkout ») | `IntentAsk.exclude` → never a subject or a root of the plan, nor what it belongs to; `ContextRequest.exclude` → never held, whatever found it — left out as `excluded` (« Excluded by the request. »), counted in `ranking.left_out` |
| the environment its words hold it to (« uniquement en staging ») | `IntentAsk.environment`, unless the form chose one |
| the period, the services and sources asked, the kind's facets, retrievers and ties | as LEKA-373 reads them — the technical, business, organizational and temporal sides each kind asks for (context.md § 13) |

**What it holds** is the context engine's: retrieved by its retrievers
(graph, words, content, timeline, paths), ranked (relevance and trust,
LEKA-372), each element with its provenance — the sources and records
that say it (§ 7) — and the version's quality and confidence (LEKA-375).
Nothing is retrieved twice: the intention links its context
(`intention_links`, kind `context`, with its version) and the context's
subject is the intention.

**Can it ground the analysis?** — `ContextReadiness`, read from the
context's own quality, never judged again:

| Status | When |
| --- | --- |
| `blocked` | a critical gap — nothing named, a model never built, no source able to read what happened when that is the question, nothing happened… — or a critical conflict — two owners of what was asked, its tier disputed…; or it holds nothing |
| `limited` | warnings — stale evidence, a source failing, mostly inferred ties… — or its quality is low |
| `ready` | nothing in the way |

with `level` and `score` (LEKA-375), `elements`, `facets` — how many
things it holds on each side: technical, business, organizational,
temporal (incidents, deployments, changes, releases, pull requests,
commits, alerts) — `sources`, and the `critical` and `warnings` issues,
each a gap (with its origin: the context's quality, or the reading) or a
conflict (what about, which attribute or role), with the elements it is
about.

**Surfaced before analysis.** Kept with the intention (`readiness`, in
`GET /intentions/{id}`), said in the move to `analysing` or
`needs_clarification` (`detail.readiness`, `detail.critical`), shown on
step 2 and the intention's page. A blocked intention is not analysed: the
analysis (LEKA-388) starts from `ready` or `limited`. Readiness is not a
state of the lifecycle — what blocks it is not always the asker's to fix
(a model to build, a source to connect) — but what the analysis reads
first.

**Inspected and reused downstream.** `GET /intentions/{id}/context?version`
— and `IntentionService.context(id, version=…)` in code — returns the
context engine's contract (`AssembledContext`, LEKA-376: every element with
its provenance, the quality and confidence, the gaps and conflicts) with
its readiness, recomputed for that version: a context kept up with the
model (LEKA-374) is read as it now is. `intention:read`; another
workspace's is 404.

**Tested** — `tests/test_intention_grounding.py`, pure: the ask its scope
settled — exclusions, an environment held to, the form's word standing;
ready with what it holds by side; blocked by a critical gap, a critical
conflict, nothing held; limited by warnings or a low level.
`tests/test_context_ranking.py`: what a request excludes is never held,
however relevant, and said so. `tests/test_intentions_api.py`, on Acme's
model: « sauf Checkout » keeps Checkout out of the context — and in it
without; an ownership question ready, its sides and sources counted,
provenance on every element, a version read again; a diagnosis no source
can ground blocked by `no_source_for`, still understood; « tout est si
lent » blocked by `no_subject` and asked to clarify; another workspace's
context 404.

## 12. Its analysis (LEKA-388)

What answers an intention: LEKA's capabilities, run on the context
assembled for it (§ 11) and the company model, each isolated, each said —
then one structured result, kept, for the decision interface (LEKA-389).
Code: `api/leka/intentions/analysis.py` (the core, pure: the material,
selecting, running, assembling, the evidence), `capabilities.py` (LEKA's
built-in capabilities, pure), `processing.py` (the pipeline: read, run,
keep, move — the job and the sweep).

**The pipeline**, for one intention `analysing`:

```
queued when asked, asked again, or analysed again (job intention-analysis:<id>, one at a time)
   ──▶ its readiness blocked?        not run: an analysis `blocked`, what is in the way kept; it stays analysing
   ──▶ asked_of()                    what it wants, about what, when, where, within which constraints
   ──▶ select()                      the capabilities its goal, kind and actions call for — and why
   ──▶ the material                  its context (that version) + the company model, each part read alone
   ──▶ execute() each                on the context's sides it reads, within its budget
   ──▶ assemble()                    one result: findings, causes, impact, risk, evidence, confidence
   ──▶ kept, and the intention moved by LEKA
```

**The capabilities** (`CAPABILITIES`), each a `Capability`: a name and a
version, what it is for, the goals and kinds that call it, the sides of the
context it reads (technical, business, organizational, temporal), the parts
of the material it needs, its budget (15 s), and how it runs — `rules` over
the company model, or `model`: an agent (`agents/*.md`) that waits for the
model gateway (LEKA-394) and is said `skipped`, `no_model`.

| Capability | Called by | What it says |
| --- | --- | --- |
| `standing` | always | each thing it is about: its state, lifecycle, criticality, how well LEKA knows it, what LEKA already concluded on it (LEKA-377 to 383) — the scene, not an answer |
| `ownership` | find_owner, act; kind ownership | who owns it, maintains it, leads its teams, knows it, its escalation — several owners an uncertainty, none said |
| `dependencies` | map_dependencies, assess_impact, plan_migration | what it depends on, what depends on it and what that reaches — applications, business capabilities, processes; the risk: high when the business or something critical relies on it |
| `incidents` | explain_cause, investigate; kind diagnose | its incidents in the period, their causes — a source's word first, then what is suspected, then what changed just before (0.7 within 6 h, 0.55 within a day, 0.4 after) — what they reached; the risk from the severity declared |
| `changes` | find_change, explain_cause, act | what changed on it or around it in the period (72 h after for what followed), what each reached, the incidents that followed |
| `documentation` | find_knowledge, check_compliance | what describes it, and whether it is current |
| `compliance` | check_compliance | an owner, current documentation, a criticality, nothing serious open, well known — each a check |
| `migration` | plan_migration | where to — missing when not said — and its ties both ways |
| `action` | act | the action asked, what depends on its target, the last deployment, the hard constraints — said, never done: a person approves (LEKA-390) |

**Each runs isolated.** A capability that raises is `failed` (its
exception's type kept, not its text), one over its budget `timed_out`, one
missing what it reads `skipped` (`no_material`) — the others go on. A part
of the material that cannot be read is logged and skips what needs it.

**The result** (`IntentionAnalysisResult`):

| | |
| --- | --- |
| `status` | `failed` when nothing that ran succeeded; `partial` when something failed or timed out; `inconclusive` when what was asked about found nothing — what sets the scene (`standing`) does not answer, unless nothing else ran; else `complete` |
| `summary`, `findings`, `causes` | each a code, its values and an English sentence — the interface words it from the code; findings are facts (a source says, LEKA observed), causes hypotheses (`stated` or `inferred`, how sure, why) |
| `impact`, `risk`, `risk_basis` | what it reaches by area (dependents, applications, capabilities, processes); the worst risk said, and on what |
| `uncertainties`, `missing` | what LEKA does not know; what did not finish (`capability.failed`, `capability.timed_out`) |
| `confidence`, `support` | the mean of the capabilities' — × 0.85 on a `limited` context; what it rests on: the context's sources, their contradictions, its readiness |
| `evidence` | every piece once, cited by id from the statements: an entity, a relationship's record, an event, an inference — with its sources (id, kind, name; none when deleted since), the records that stated it, its origin and confidence, and what its label is made of (a tie's ends, a finding's code and values) |

**Evidence keeps its provenance.** The context's word on a thing when it
holds it — the element's provenance (§ 11, context.md § 7): its sources,
records, origin, confidence; else the thing's own sources in the model.

**Kept** in `intention_analyses`, one row per run, numbered: why it ran
(`created`, `asked_again`, `requested`, `sweep`), who asked, the context
and version it read, its readiness, when it started and finished, the
capabilities considered and why (`selection`), what each did (`steps`:
status, duration, error), the result, an error (`context_blocked`) and
`detail` (what blocked it; `superseded`).

**The intention moved by LEKA** — `failed` when the analysis failed;
`awaiting_decision` when it asks to act on systems (`proposed`); else
`completed` (`answered`), its `summary` the result's first sentence — and
up to ten of LEKA's findings it rests on linked. An intention that moved
meanwhile (cancelled, asked again) is not moved: the analysis is kept,
`superseded`. A failed one is analysed again by its asker or an approver:
`retried` to `analysing`, then queued.

**Queued, and swept.** Created and asked again, the route commits, then
queues the job (`queue_analysis`); `POST …/analyse` the same. Every 15
minutes (`intention-analysis-sweep`, :07 :22 :37 :52) the intentions
analysing whose context has no analysis yet are analysed — what no worker
took. Idempotent.

**The API**: `GET /intentions/{id}/analysis` — the latest (404 « No
analysis yet. »); `GET …/analyses?limit` — every one, the latest first;
`POST …/analyse` — 202 `{queued}`, 409 in any other state than analysing
or failed. `intention:read`, analysing again `intention:create` and its
asker or an approver; another workspace's 404.

**In the app** — the intention's tabs:

- *Analyse*: which analysis, why it ran, when, how long, on which context
  version; each capability mobilised, why, and how it went — done, failed
  (its error), timed out, not run; then what it found, laid out as every
  analysis is (`AnalysisView`, LEKA-341): the synthesis and its confidence
  and support, the facts, the probable causes, the evidence, what it
  reaches — without proposals (LEKA-389). On its way: « LEKA analyse votre
  demande », read again every 4 s, the intention read again once done;
  blocked: what its context lacks (§ 11); failed: « Relancer l'analyse ».
  Its earlier analyses listed.
- *Preuves*: every piece of evidence collected — where it came from, its
  record, its origin and confidence, which capability cites it.
- *Vue d'ensemble*: its summary, in the reader's words.

Every sentence is worded from its code and values (`lib/intention-analysis.ts`),
a finding LEKA already concluded as Insights words it — the API's English
when the interface does not know a code.

**Tested** — `tests/test_intention_analysis.py`, pure: what its goal, kind
and actions call for and why, its standing always; an agent waiting for a
model; each isolated — failed, timed out, skipped, the others going on;
failed, partial, inconclusive — the scene alone does not conclude; each
capability on a hand-made company. `tests/test_intention_analysis_api.py`,
on Acme's model: « Qui est responsable de Billing API ? » answered with
the catalogue's record, completed; what relies on it — Checkout, Invoicing,
high; « Redémarre Billing API » awaiting a person's decision; a diagnosis
no source can ground not analysed; a failing and a slow capability said,
the others going on; nothing that ran failed, then analysed again; a late
analysis superseded; queued when asked and asked again, the sweep running
what waits; another workspace's 404. `web/lib/intention-analysis.test.ts`,
`web/components/intentions/analysis-tab.test.tsx`;
`e2e/intention-analysis.spec.ts`, on the demo: asked, analysed, followed,
its evidence and history; a restart waiting for a person.

## 13. Tested

- `tests/test_intention_lifecycle.py`, pure: the way from asking to
  verified, each step's actor; a decision a person's, never LEKA's; what
  LEKA concludes and runs its own; nothing approved before analysed, nor run
  before approved; cancelling until actions run; cancelled final, the rest
  asked again; every state in one phase.
- `web/components/intentions/intentions.test.tsx`: the list and its tabs,
  the page, its history in words, cancelling with a reason, a missing one;
  `e2e/intentions.spec.ts`, in a browser: asked from the composer, followed,
  its history told, cancelled, found among the finished.
- `tests/test_intentions_api.py`, on Acme's model: asked and kept with its
  context, its history three events; nothing to start from keeps nothing;
  queried by phase, status, asker, words, link, and counted; the lifecycle
  from analysis to verified through the service, LEKA refused an approval;
  asked again — the context's next version; cancelled, archived, restored
  by its asker or an approver, 403 otherwise, 409 for a move not allowed;
  links checked, twice the same, the context kept; decisions, actions,
  outcomes linked in code; the history refused an UPDATE, allowed `by`
  forgotten; another workspace's 404.

## Not yet

- **Findings presented for a decision, recommendations** (LEKA-389): the
  analysis's result (§ 12) is their input; its *Analyse* tab draws it
  without proposals.
- **Agents** (`agents/*.md`) as capabilities: selected, said `no_model`
  until the model gateway (LEKA-394).
- **A model-assisted understanding** (LEKA-394): the same contract.
- **Decisions, actions, outcomes** (LEKA-390 to 392): their tables, routes
  and screens; the lifecycle and the links are ready for them.
- **Mes intentions**' impact and sources columns (mockup 07): from the
  analysis.
