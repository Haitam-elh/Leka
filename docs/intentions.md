# Intentions

What someone asks LEKA, kept from the moment they ask to the moment what
was done is verified — where it stands, what happened to it, what it rests
on and what came of it (LEKA-384). An action taken against a customer's
production system must be answerable months later: who asked, what LEKA
concluded, who approved, what ran.

This is the frame of the Intentions epic. LEKA-384 keeps the intention, its
lifecycle, its history and its links; LEKA-385 understands it (§ 9), LEKA-386 scopes it (§ 10), LEKA-387 grounds it in its context (§ 11), LEKA-388 analyses it (§ 12),
LEKA-390 puts what it asks to do to people's decision (§ 13) — governed by LEKA-404 ([governance-rules.md](governance-rules.md)) — LEKA-391 carries it out (§ 14);
389 concludes; 392 verifies — each moving it along
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
| **Link** | What it rests on, or what came of it: its context, a finding, an entity it is about — and its decisions, actions and outcomes (LEKA-390 to 392) — named as it was when linked (`label`, `detail`: a context's version, a finding's code and values — the interface words a finding from them, as Insights does: its `label` is the API's English), so the link still says it when the thing is gone | `intention_links` |

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
| `submitted` | asked: its words and scope kept, nothing being read — before its analysis starts, or stopped by a person (LEKA-443) | creating it; a person stopping its analysis |
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
| analysing | submitted | `stopped` — its analysis stopped (LEKA-443) | a person |
| submitted | analysing | `resumed` (LEKA-443) | a person |
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

## 2 bis. Its journey: one state, the same on every screen (LEKA-443)

The lifecycle (§ 2) is what is kept. The **journey** is what a person reads.
The API derives it once, from what was kept (`leka/intentions/journey.py`,
pure), and serves it on every intention (`IntentionRead.journey`):

- `state`: one of the states below;
- `reason`: why it is there, as a code the screens put in words;
- `since`: since when;
- `next` and `by`: what comes next, and who does it (the asker, someone who
  may approve, or LEKA);
- `controls`: what a person may do now. Each route checks it again;
- `step`: where the five steps put it;
- `late`: past what it should take;
- `technical`: the error as kept, for whoever diagnoses it — never the
  words a person reads first.

It is read from three things:
- the lifecycle state;
- the move that brought it there (its name, its actor, its detail);
- its latest analysis.

**No screen derives a state of its own.** The list, the panel beside it,
its page, its steps, the overview all draw `journey`.

### The matrix

| State (words on screen) | Read from | Reached by | What a person may do | Reasons and errors | Next, by whom |
| --- | --- | --- | --- | --- | --- |
| `draft` — Brouillon | nothing kept: the composer's words, in this browser (sessionStorage) | typing | ask it | — | ask it — the asker |
| `needs_clarification` — Clarification requise | `needs_clarification` | `clarification_asked` | answer, ask again, cancel | `unclear`, `context_blocked` | answer LEKA's questions — the asker |
| `ready` — Prête à analyser | `analysing` with no analysis of this attempt started; or `submitted`, stopped by a person | `asked_again`, `clarified`, `retried`, `resumed`; `stopped` | analyse now (queued); resume (stopped); ask again; stop (queued); cancel | `queued` (late after 5 min), `stopped` | wait — LEKA; resume — the asker |
| `analysing` — Analyse en cours | `analysing`, an analysis of this attempt running | `analysis_started`, and the moves above once it starts | stop, ask again, cancel; analyse again once late | late after 10 min | wait — LEKA |
| `analysis_partial` — Analyse partielle | `completed` (a question), its analysis `partial` or `inconclusive` | `answered` | ask again, archive | `partial`, `inconclusive` | read the result — the asker |
| `analysis_failed` — Analyse échouée | `failed`, from its analysis | `failed` | analyse again, ask again, cancel | `interrupted`, `crashed`, `timed_out`, `model`, `context_blocked`, `error` | analyse again — the asker |
| `result_available` — Résultat disponible | `completed` (a question), its analysis complete | `answered` | ask again, archive | — | read the result — the asker |
| `decision_required` — Décision requise | `awaiting_decision` | `proposed` | decide, change the decision, ask again, cancel | `partial`: proposed on a partial analysis | decide — who may approve |
| `approved` — Approuvée | `approved`, `scheduled` | `approved`, `scheduled`, `unscheduled` | start the actions, unschedule, cancel | `scheduled` | start the actions — who may approve; wait for its time — LEKA |
| `rejected` — Rejetée | `rejected` | `rejected` | ask again, archive | `by_person` | ask again — the asker |
| `action_running` — Action en cours | `executing` | `execution_started` | stop the actions | — | follow it; a step may wait for a person — LEKA |
| `action_failed` — Action échouée | `failed`, from its actions or their outcome | `failed` | retry the actions, ask again, cancel | `step_failed`, `stopped`, `conditions_changed`, `expected_not_met` | retry — who may approve |
| `to_verify` — Résultat à vérifier | `verifying` | `executed` | conclude the check | — | LEKA checks; a person may conclude |
| `done` — Terminée | `completed`, acted on and verified | `verified` | ask again, archive | — | nothing |
| `cancelled` — Annulée | `cancelled` | `cancelled` | archive | `by_person` | nothing |
| `superseded` — Remplacée par une version plus récente | an analysis or a decision of an earlier version, never an intention | `asked_again`, `clarified` | — | — | — |

Archived, an intention keeps its state and may only be restored.

`tests/test_intention_journey.py` holds this table to the lifecycle:
- every lifecycle state is read by a row, and every move reaches one;
- a state never offers a control its row does not list;
- a control is never one the lifecycle would refuse.

### The rules

**Nothing is left running without a way out.**
- Queued, it may be asked for now. Five minutes on, it is said late. The
  sweep (every 15 minutes) runs what no job did.
- An analysis that raises is said failed (`crashed`, its type kept): never
  left running.
- An analysis running past 10 minutes is said `interrupted` by the sweep.
  Its intention fails, and can be analysed again. No analysis takes that
  long: a capability has 15 s, the model 60 s.
- A plan step running past 10 minutes is said `interrupted` by the plans'
  sweep (every 5 minutes): its worker died during the call. What the system
  did is said unknown, to be checked before retrying. The action failed,
  never left running.
- A step waiting on a person says so. A verification ends at its deadline.

**« Arrêter l'analyse »** (mockup 03) moves `analysing → submitted` by a
person (`stopped`), and back by `resumed`.
- The analysis running is said `stopped`. What it finds is kept, never its
  result.
- Stopped twice, the same.
- Cancelling stays final, and separate.

**Versions.** `intention.version` is 1 as asked, one more each time its
words, scope or answers are asked again.
- Each analysis keeps the version it read (`intention_version`) and says
  whether it is `current`. Stopped, or of an earlier version, it is not.
- A screen never shows a non-current analysis as its result, its evidence
  or its impact: it says « remplacée par une version plus récente », or
  « arrêtée ».
- The history gives each moment its version (`TimelineItem.version`) and
  groups them, the earlier said replaced.

**Retries never do anything twice.**

| Sent again | Is |
| --- | --- |
| `POST /intentions` with the same `Idempotency-Key` (the composer sends one per request as it stands) | the intention it made — held by a lock, so two at once are one |
| `POST …/ask`, the same words, scope and answers, while it is analysed | the same: no new version, nothing analysed twice |
| `POST …/analyse` while one is on its way | `queued: false`: the same job (its concurrency key) |
| `POST …/cancel`, `POST …/stop` | the same |
| `POST …/plan` while a plan is on its way | 409 `already_planned` |
| a vote twice | refused by the decision's rules (§ 13) |

**Errors say what happened and what next.**
- The reason code is put in words: « L'analyse s'est interrompue : le moteur
  d'analyse ne répondait plus. »
- The next step says who: « À vous · Relancez l'analyse. »
- The technical code is folded under « Détails techniques », with the
  version.

**The screens reflect the API, never a progress of their own.**
- The page and the list are read again every few seconds while LEKA works
  (`by: leka`).
- The five steps are `journey.step`.
- A plan's buttons are its `controls` (start, schedule, cancel, unschedule,
  stop, confirm a step, plan again): the rules its routes apply, said once
  (`plan_controls`).
- A run is « Exécuté · à vérifier » until its outcome is verified.
- What is selected and not yet approved is never said running: no plan
  exists before the decision.

### Tested across screens

The ticket's cases. Each one compares what the API says with what every
screen concerned shows.

| Case | Where |
| --- | --- |
| The same intention on the list, its panel, its page, its results, its history | `e2e/intention-journey.spec.ts`; `test_intention_journey_api.py` (list = page at each step); `journey.test.tsx` |
| Changed after an analysis finished | `e2e/intention-journey.spec.ts`; `test_intention_journey_api.py` (versions, `current`, timeline) |
| Stopped or cancelled while analysed | `e2e/intention-journey.spec.ts`; `test_intention_journey_api.py` (stopped mid-run, result kept, resumed); `test_intentions_api.py` (cancelled twice) |
| A source failing during a multi-source analysis | `test_intention_journey_api.py` (partial, on the list as on its page); `test_intention_explain.py` (LEKA-441) |
| Several recommendations, part approved, refused | `test_intention_journey_actions_api.py` (selected = planned = running; refused, nothing planned) |
| A run failed, timed out, retried, verified | `test_intention_journey_actions_api.py` (a person's failure, a timeout, two retries, to verify, concluded short) |
| A page refreshed, or come back to, while actions run | `e2e/intention-journey.spec.ts`; `test_intention_journey_actions_api.py` (read twice: still running) |
| Nothing left running | `test_intention_journey_api.py` (an analysis that raises, one past its deadline); `test_intention_journey_actions_api.py` (a step past its deadline) |

### Defects found, and fixed

Each one was reproduced before it was fixed. The tests above now protect
it.

| # | Defect | Reproduced by | Fixed by |
| --- | --- | --- | --- |
| 1 | An analysis whose worker died, or that raised, stayed `running` forever. The sweep never ran it again: an analysis existed for that version. The intention stayed « En analyse » for good. | An exception after the analysis is recorded (e.g. in its explanation), or a worker killed mid-analysis | the crash guard; the sweep interrupts what runs past 10 minutes |
| 2 | A plan step whose worker died during the call stayed `running` forever. « Arrêter » waited for it, so the plan never finished. | A step marked running, its job gone | `interrupt_overdue_steps` in the plans' sweep |
| 3 | Asked again, Preuves and the decision's side showed the previous version's evidence and impact as current | Ask a question, analyse it, ask again with new words, open Preuves | `current` on each analysis; the screens draw only a current one |
| 4 | Queued with nothing running, the pill said « En analyse » | Ask with no worker running | the `ready` state, reason `queued`, said late after 5 minutes |
| 5 | A run said « Exécuté » while its outcome was still being verified | Confirm a person's step: the plan said « Exécuté », the intention « En vérification » | « Exécuté · à vérifier » and the `to_verify` state |
| 6 | « En échec » was the same word for an analysis that failed and an action that failed. The list and its panel never said why. | Fail an analysis, then fail a run | `analysis_failed` and `action_failed`, each with its reason; the panel says why |
| 7 | The same request sent twice made two intentions | `POST /intentions` twice — a double click, a retry after a network timeout | `Idempotency-Key` |
| 8 | The same words asked again twice made two versions and two analyses | `POST …/ask` twice with the same body while analysed | asked again identically while analysed: the same |
| 9 | Cancelling twice answered 409, and an error was shown although it was cancelled | A retried cancel | cancelling twice is the same |
| 10 | No way to stop an analysis (mockup 03's « Arrêter l'analyse ») but cancelling the intention for good | — | stop and resume |
| 11 | « Prochaines étapes » listed lifecycle states — « Annulée », « En analyse » — as if they were next steps | Open any intention's Vue d'ensemble | the journey's next step, and who |
| 12 | Its history mixed its versions: version 1's analysis and version 2's, unmarked | Ask again after an analysis, open Historique | versions grouped, the earlier said replaced |
| 13 | A plan's buttons were decided by the screen, from statuses of its own reading | — | the plan's `controls`, from the API |

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
| `linked`, `unlinked` | what kind, which, its label — a finding's code and values with it |
| `archived`, `restored` | by whom |

With its analyses, its decision, its plan and its outcome, this history is
its whole story, told as one timeline (§ 15).

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
| approve, reject, modify, ask for changes | who may approve (`intention:approve`) — or a member an approver lent their authority to — not the asker when the policy keeps them apart, and someone of the role it requires among the approvers (§ 13) |
| change the approval policy; grant or revoke a freeze or a waiver | `workspace:update` ([governance-rules.md](governance-rules.md)) |
| lend one's authority to approve | `intention:approve`; revoked by the lender or an admin |
| plan, start, schedule, stop a run; confirm a person's step | `intention:approve` (§ 14) |
| authorize a system LEKA acts through | `workspace:update` (§ 14) |

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
| `GET /intentions/{id}/decisions` · `POST …/decision/{verdict}` | its decisions; a vote (§ 13) — and `GET /decisions`, `/decisions/summary`, `GET` · `PUT /decisions/policy`, the governance routes ([governance-rules.md](governance-rules.md) § 8) |
| `GET /intentions/{id}/plans` · `POST …/plan`, `/plan/start`, `/plan/cancel`, `/plan/steps/{step_id}/report` | carrying it out (§ 14) — and `/action-endpoints` |
| `PUT /intentions/{id}/plan/expectations` · `GET …/verifications` · `POST …/verification/check`, `/verification/expectations/{expectation_id}/report`, `/verification/conclude` | what came of it (§ 15) |
| `GET /intentions/{id}/timeline?category&actor&since&until&limit` · `GET /intention-history?…&by` | its whole story; every intention's (§ 15) |

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
  next; *Historique* — its whole story in words, in order, by LEKA or by a
  person, filtered (§ 15); *Analyse* and *Preuves* —
  its analysis, how it went and on what (§ 12); *Actions* says it comes
  with the decision and its execution — and, for a question, that it calls
  for none: LEKA answers, never acts; to act, ask for it. Its asker, or who may
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
| `actions` | each `{code, said, changes_systems}` — the verbs asked, never the nouns: « déploie » is asked, « le déploiement » happened. Nor what is planned, studied or explained (« un plan pour migrer », « le risque de migrer », « comment redémarrer », « how to restart »), nor what was done (« a été redémarrée », « qui a redémarré », « has been rolled back »: its goal is `find_change`) — LEKA-440. « Mettre à jour » a documentation, a runbook, a page is `document`, which changes no system |
| `withheld` | the actions spoken of but not asked (LEKA-434), each with its `polarity`: `negated` (« ne redémarre pas », « don't restart », « never »), `conditional` (« si Billing API tombe, redémarre-la »), `ambiguous` (a negation before it, not on it: « je ne sais pas s'il faut redémarrer »). Never acted on, never proposed. What is quoted (« … », " … ") is cited, not asked |
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
| `unknown_subject` | **when acting**, else a warning | a thing asked for is not in the model — or a name its words give (« billing-gateway », « svc_orders ») that nothing it is about answers to (LEKA-440): the answer says LEKA does not know it, and states no cause found elsewhere |
| `action_without_target` | yes | an action on systems, on nothing named |
| `ambiguous_subject` | **when acting**, else a warning | the same words name several things — options: those things. Read each to answer a question; never act on a guess |
| `competing_goals` | no | two kinds said as much: read as the first — options: both goals |
| `several_requests` | no | several « ? », or several actions joined (et, and, puis, then) |
| `ambiguous_action` | yes | an action on systems negated in part, conditional or doubtful (LEKA-434): asked before anything is proposed |
| `unknown_environment` | no | an environment the model does not know — options: those it knows |

**Read by a model, worked on as it is.**
LEKA's job is to understand the whole request and do the work; asking back is the exception. When a model read it (`reading.py`):
- **A plan is not an action.** A verb that changes systems (« migrer ») made the rules read an action. The model may settle that the request is a plan, an assessment or a document (`plan_migration`, `assess_impact`, `map_dependencies`, `check_compliance`, `find_knowledge`), but only when its words ask for one: « évalue », « simule », « propose un plan », « documente », « génère », « PDF »…
  - Then nothing that would change systems is asked of anyone.
  - What only an action needs is no longer blocking: which thing exactly (`no_subject`, `unknown_subject`, `ambiguous_subject`, `action_without_target`).
  - « les serveurs AWS » is every AWS server LEKA knows.
- **A real command stays one.** « Redémarre Billing API » stays the action it is, whatever a model says.
- **A request the model understood** (`understood: true`, confident) is analysed even when its goal fits none of the list: `unclear_goal` is no longer blocking.
- **Only what nothing can be made of is asked back.** Asking back keeps every rule above when no model read it.

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

**Read with a model, since LEKA-394** (`reading.py`, through the LLM runtime
since LEKA-429 — [llm-runtime.md](llm-runtime.md)): when a model can
answer, it reads the same words — the goal, a question or a request, what is
asked in a sentence — in twelve seconds at most. It **settles a goal the
rules could not tell** (« Billing API, c'est à qui de voir ça ? »: the
blocking « unclear goal » gone, the intention analysed), or one it is surer
of; it never changes the things named, the actions asked, nor a request to
act — those stay the rules', read from the words; a polite request it may
read as the question it is, never a question as a request. Kept beside the rules'
reading: `restated`, `read_by` (provider, model, version, confidence) —
« Lu par Gemini 3.8 Flash, avec les règles de LEKA ». No model, or none in
time: the rules alone, as before.

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

**What a verb says without asking it (LEKA-440).** Measured by the
benchmark (`docs/benchmarks/intentions.md`), the rules no longer read as an
action:
- an infinitive a plan, a study, a risk or a cost governs — « Prépare un
  plan pour migrer payment-api », « Évalue le risque de migrer » — nor a way
  to do it asked — « Comment redémarrer », « How to restart »; « Fais un
  plan, puis redémarre auth-service » still asks the restart;
- what was done: a participle (« redémarrée », « restarted ») or a verb
  after its auxiliary (« a redémarré », « has been rolled back »), never an
  infinitive (« j'ai besoin de redémarrer », « I have to restart ») nor a
  noun after an article (« do a rollback »);
- a question about something it knows, with no goal said (« Quel est le SLA
  de payment-api ? », « Sur quoi travaille Thomas Berger ? »): what is known
  of it (`find_knowledge`), never stopped for it.
And « qu'est-ce qui a changé » is what changed, not « qui ».

**Each action on its own targets (LEKA-434).** An action is on the things
said after it, before the next one: « Redémarre Billing API et rollback
Payment API » restarts Billing API and rolls back Payment API — one proposal
each, never both on both (`actions[].targets`, then the decision's
proposals). An action said with nothing after it takes what the next one is
on (« redémarre et scale Billing API »); a thing not found in the words, every
action.

## 9 bis. Its brief: what LEKA must know, asks, and what follows (LEKA-439)

Someone writes what they need, however incompletely. Before anything is
analysed, LEKA says what it understood, asks only what it truly lacks, lets
it be corrected, says what it will read — then it is launched.

**The contract** (`intentions/brief.py`, `IntentionBrief`). Five parts, each
with a state — **known** (said, or answered), **assumed** (LEKA's reading:
a model's goal, a default period — never shown as a fact), **missing**,
**unknown** (its asker said « je ne sais pas ») — and how much LEKA needs it:

| Part | What it is | Needed |
| --- | --- | --- |
| goal | explain, find, assess, act… (`understanding.goal`) | blocking |
| target | the things of the company model it is about | blocking for an action; useful for a question (LEKA looks across everything) |
| scope | where and when: environment, period | blocking for an action (production is not staging); optional otherwise |
| expected | an answer, a document (PDF, deck…), a plan, an action on systems | useful |
| constraints | read only, no downtime, a deadline… | optional |

**The questions** are what understanding cannot tell (`ambiguities`, § 9) —
never a generic « précisez »: the blocking first, then by part (target,
goal, expected, scope, constraints). Each says why it is asked
(`intentions.brief.whys`) and what it could be: the things it may mean **by
id** (`choices` — two services both called « Billing API »; what the words
may name), the environments LEKA knows, the goals, « oui / non » for a
doubtful action, « seulement regarder » for a contradiction — their own
words when that helps, and always « je ne sais pas ». An action on nothing
known asks once on what (`action_without_target`), with what the words may
name — not twice.

**The answers** (`intentions.answers`, `IntentionAnswer`: a question, a
value, unknown) are kept with the intention, one per question, the latest,
and read again every time it is understood (`answered_ask`, `answered`):

- a thing chosen by id narrows its scope (the context's roots);
- an environment chosen holds it there;
- a goal chosen is the one meant;
- a doubtful action, « oui », is asked — never one its asker said not to do;
  « non », withheld (LEKA-434);
- a contradiction, « seulement regarder », withholds what would change
  systems; « agir », drops « read only »;
- their words are read with the rest of what they asked; still unclear,
  asked again.

The words kept with the intention are its asker's, never rewritten; the
scope it is kept with is theirs, an answer is not written into it.

**The decision** (`IntentionBrief.decision`):

| Decision | When | What follows |
| --- | --- | --- |
| analyse | nothing is missing | launched |
| clarify | a blocking question is unanswered | not launched; on its page, `needs_clarification` |
| continue | only what is useful is missing, or not known | launched, its limits said (`limits`) |
| block | an action on systems whose blocking question its asker cannot answer | never acted on a guess: `needs_clarification`, said why |

A clear intention — short or long — has no question: it is launched in one
more click, its reading shown. An action is never proposed from a request
still ambiguous, negated or contradictory (§ 9, § 13).

**Before it is asked** — `POST /intentions/brief` (an `IntentionRequest`:
the words, the scope, the answers): what LEKA understood, its brief, the
sources it would read, and what it takes (below). Nothing is kept.
`POST /intentions` and `…/ask` take the answers too.

**After** — `POST /intentions/{id}/answers` (`{answers}`), by its asker or
who may approve: kept with those answered before, the latest for each; it
is asked again with them (`asked_again`, its history says which were
answered); analysing, its analysis queued. 409 once cancelled, archived, or
while its actions run.

**In the app.** Nouvelle intention: « Continuer » reads it — what LEKA
understood, part by part; its questions, each with why and what it could
be; what it will read; what it takes — each answer read again at once;
« Lancer l'analyse » only once nothing blocks, its limits said. Changed
since it was read: read again first. Its page (step 1): the same, its
questions answered there while it waits — no more rewriting the whole
request.

### What it takes to carry it through (LEKA-439)

`intentions/feasibility.py`, `GET /intentions/{id}/feasibility` (and in the
preview). It reads; it never buys nor changes anything.

- **The capabilities** it needs: what the router sends it to (LEKA-398),
  what always runs with an analysis, and — a document expected — what makes
  one. Each **offered**:
  - included: LEKA's own analysis — never an agent: no plan includes one
    (LEKA-446);
  - beta: an agent while it is not on sale — usable by every plan, its
    future price said (decided 2026-10-13);
  - add_on: on sale, bought;
  - planned: not ready, never offered as usable.

  Each is **usable here or not**, and why: a source to connect, a language
  model, a permission, turned off.
- **The credits** this month (metering, LEKA-430): left, and what it should
  cost — the median of the agent's runs here, unknown before any.
- **The verdict**:
  - ready;
  - prerequisites: something to connect or allow first — only what it is
    routed to counts, what always runs only adds;
  - over_quota: spent, or too few for what it should cost;
  - impossible: a document expected and nothing LEKA has makes it — LEKA can
    still analyse and answer.
- **The least it takes**, cheapest first:
  1. what to connect or allow;
  2. an add-on, or a bundle when it costs less than its agents one by one;
  3. the cheapest plan whose credits are enough — never the dearest by
     default, and never a capacity pack: none is sold (LEKA-446);
  4. past Business, Enterprise by contract.

  Anything that costs money is consented to first. In the app, changing plan
  says its price, its credits and its launch offer, then opens the secure
  payment page (Stripe, LEKA-431). Only who may pay for the workspace
  (`workspace:update`) sees that button; a member is told to ask an
  administrator.

Shown before it is asked, on its step 1, and beside its decision (step 4).

### Scenarios, and what is expected

Pure (`tests/test_intention_brief.py`, `tests/test_intention_feasibility.py`),
through the API (`tests/test_intention_brief_api.py`), on screen
(`components/intentions/brief.test.tsx`, `intention-form.test.tsx`,
`intentions.test.tsx`), in a browser (`e2e/intentions.spec.ts`,
`e2e/forms.spec.ts`).

| Intention | Expected |
| --- | --- |
| « Pourquoi Billing API est lente depuis hier ? » (short, clear) | analyse; no question |
| A long paragraph, clear (several sentences, one need) | analyse or continue; no blocking question |
| « Why is Billing API slow since yesterday? » (English) | analyse, goal explain_cause |
| « Fais-moi un deck PDF de l'architecture de Billing API » | expected: document, said |
| « Billing » (too short) | clarify, asked in their words; answered « Qui est responsable de Billing API ? » → analyse, find_owner |
| « Redémarre Billing API en production », two Billing API | clarify, choices by id; one chosen → scope narrowed to it → analyse |
| « Redémarre le service en production » (nothing known) | clarify — one question on what, with what the words may name |
| the same, « je ne sais pas » | block; not analysed |
| « Pourquoi c'est lent ? », target « je ne sais pas » | continue, limit: everything LEKA knows is read |
| « Redémarre Billing API », environments production and staging | clarify, the environments as options; « staging » → analyse, scope staging |
| « Ne redémarre pas Billing API, dis-moi pourquoi elle est lente » | no action; analyse |
| « Je ne sais pas s'il faut redémarrer Billing API » | clarify; « non » → no action; « oui » → restart asked |
| « Redémarre … sans rien modifier » (contradictory) | clarify; « seulement regarder » → no action; « agir » → read only dropped |
| « Pourquoi … ? Et qui en est responsable ? » (several) | continue, limit: the first request first |
| A goal a model read | assumed, never known |
| Free, credits left, LEKA's own analysis | ready, nothing to buy |
| Free, credits spent | over_quota → Starter (not Business), asked first |
| A run that costs more than Starter's month | over_quota → Growth |
| Past Business | Enterprise by contract, no checkout |
| Past the credits | a higher plan, never a pack (none is sold) |
| A security review (specialist agent) | beta, usable, nothing to buy |
| Two specialist agents on sale, a bundle cheaper | buy_bundle; one alone cheaper → buy_add_on |
| A document nothing makes | impossible, rephrase |
| The architect without Confluence nor GitHub | prerequisites: connect a source |
| A draft agent the only one that would make it | never usable: impossible |

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
| `excluded` | what it names to set apart: after « sauf », « hors », « à part », « except », « excluding », « sans », « ne touche pas à », « don't touch » (LEKA-440) — not its subjects |
| `environments`, `environment_origin` | where it is held to: `asked` (the form), `text` (« en prod »), `constraint` (« uniquement en staging ») — none: everywhere |
| `period` | `{since, until, origin, said, explicit}` — explicit when asked, read from the words or the model (« depuis le déploiement »), not its kind's default |
| `sources` | the sources the form held it to; none: every one |
| `constraints` | each `{kind, said, value, hard}` (below) |
| `missing` | the critical information missing: the kinds of the blocking ambiguities it adds |

**Constraints**, from the words (French and English) and the form:

| Kind | Said by | Value | Hard |
| --- | --- | --- | --- |
| `exclude` | sauf, hors, except, ne touche pas à, don't touch… + a thing named | its id | yes |
| `read_only` | sans rien modifier, lecture seule, ne touche à rien, read only, without changing… — not « ne touche pas à payment-api », which excludes it | true | yes |
| `no_downtime` | sans interruption, sans coupure, zero downtime… | true | yes |
| `deadline` | avant / d'ici / by / before + demain, ce soir, a weekday, la fin de la semaine | the day, when it can be told | yes |
| `window` | hors heures ouvrées, la nuit, ce soir, ce week-end, après 22h, entre 22h et 23h30, outside business hours, tonight, after 10pm, between 9pm and 11pm… — read by execution in the plan's time zone (LEKA-440: by its hours too) | the words | yes |
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
| `subject_gone` | **when acting**, else a warning | a thing it is about is removed or archived in the model — a removed thing named is found again when nothing there now answers to its name (LEKA-440): « Qu'est-ce qui dépend encore de redis-sessions ? » is answered with it |
| `everything_excluded` | **when acting** | every thing it names, it excludes — a question about everything else is about everything else (LEKA-440) |
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
| `blocked` | **an action** (it asks to change systems), and a critical gap — nothing named, a model never built… — or a critical conflict — two owners of what it acts on, its tier disputed…; or it holds nothing |
| `limited` | **a question** with something critical in the way — said, and answered anyway: LEKA's analyst (§ 12) looks for itself and says what its sources disagree on; or warnings — stale evidence, a source failing, mostly inferred ties… — or its quality is low |
| `ready` | nothing in the way |

Only an action is ever blocked. A question about everything — « quoi de
neuf depuis hier en prod », « quels services n'ont pas de responsable » —
names nothing, and a disagreement between two sources on an attribute
(payment-api's SLA) has nothing to do with who owns it: before 2026-10-09
both stopped the question, and an intention stopped this way stayed
analysing for ever.

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
step 2 and the intention's page. A blocked action is not analysed — the
person is asked to clarify (`needs_clarification`, what is in the way
said); the analysis (LEKA-388) starts from `ready` or `limited`. Readiness is not a
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
ready with what it holds by side; an action blocked by a critical gap, a
critical conflict, nothing held — a question limited by them; limited by
warnings or a low level.
`tests/test_context_ranking.py`: what a request excludes is never held,
however relevant, and said so. `tests/test_intentions_api.py`, on Acme's
model: « sauf Checkout » keeps Checkout out of the context — and in it
without; an ownership question ready, its sides and sources counted,
provenance on every element, a version read again; a diagnosis no source
can ground limited by `no_source_for`, and analysed; « tout est si lent »
limited by `no_subject`, analysed; « Redémarre tout en production » asked
what it acts on; another workspace's context 404.

### Where it goes (LEKA-398)

Read with its context, an intention is **routed** to the capabilities that
fit it — LEKA's own analyses, the agents — ranked by defined signals (its
goal, its kind, what it is about, its words, what its context holds), the
unavailable, the unauthorized and what a policy forbids left out, said why;
**LEKA's analysis** when nothing fits better; **what to ask** when it is not
clear. Every decision kept; `GET`, `POST /intentions/{id}/routing`; on its
overview, **Capacité choisie**, a chosen agent offered to run for it.
[capability-router.md](capability-router.md).

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
   ──▶ an action, its readiness blocked?   not run: an analysis `blocked`, what is in the way kept; the person asked to clarify
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
| `incidents` | explain_cause, investigate, find_change; kinds diagnose, change | its incidents in the period — every one in the workspace when it names nothing — their causes — a source's word first, then what is suspected, then what changed just before (0.7 within 6 h, 0.55 within a day, 0.4 after) — what they reached; the risk from the severity declared |
| `changes` | find_change, explain_cause, act | what changed on it or around it in the period (72 h after for what followed), what each reached, the incidents that followed — everywhere in the environment it says (« prod » is production) when it names nothing |
| `evolution` | find_change, investigate; kind change | what LEKA learned in the period: the things that appeared in what its sources say, changed (which fields), went, came back — services, repositories, databases, resources, teams, documents; the events are the two above's |
| `documentation` | find_knowledge, check_compliance | what describes it, and whether it is current |
| `compliance` | check_compliance | an owner, current documentation, a criticality, nothing serious open, well known — each a check |
| `migration` | plan_migration | where to — missing when not said — and its ties both ways |
| `action` | act | the action asked, what depends on its target, the last deployment, the hard constraints — said, never done: a person approves (LEKA-390) |

**Each runs isolated.** A capability that raises is `failed` (its
exception's type kept, not its text), one over its budget `timed_out`, one
missing what it reads `skipped` (`no_material`) — the others go on. A part
of the material that cannot be read is logged and skips what needs it.

**Orchestrated, as one plan (LEKA-399, `orchestration.py`).** The
capabilities chosen for an intention are planned as a graph and run as one:

- **Planned.** Each capability says where it stands among the others:
  what must have succeeded before it (`after`), what it reads when it did
  (`uses`), what runs in its place when it fails (`fallback`). `plan()`
  orders them in **levels**: each level after the one before, its
  capabilities together, in parallel. One a model runs (the synthesis,
  LEKA's analyst) reads all the others: it is last, the **conclusion**. A
  capability named that was not chosen is no prerequisite; a cycle is
  refused, said which (`OrchestrationError`).
- **Run.** Level by level, each capability isolated as before, a level's
  together (`asyncio.gather`; the rules run in threads: two slow ones take
  the time of one). Each is **handed** what the capabilities it names
  produced — those only, frozen, as they produced them (`Material.handed`).
- **Handoffs, today**:
  - `incidents` uses `changes`: a change whose reach (what depends on what
    it touched) holds what an incident affects is a cause the incident's
    own record does not tie to it;
  - `action` uses `ownership` and `dependencies`: who should be told
    before it is done (`action.inform`), and what depends on what it acts
    on beyond its own read;
  - the conclusion reads them all.
- **Failures coordinated.**

  | What happened | What follows |
  | --- | --- |
  | a prerequisite (`after`) did not succeed | not run: `skipped`, `upstream`, which one said (`capability.upstream`) |
  | something it uses did not succeed | run with the rest, said `degraded` (`capability.degraded`) |
  | it failed, and it has a `fallback` | its fallback runs in its place, said (`fallback_of`), and what follows reads the fallback's word |

  A partial failure stays what it was: the analysis is `partial`, each
  failure said.
- **Traced.** The plan is kept with the analysis
  (`detail.orchestration`: its levels, each step's level, method,
  prerequisites, uses, fallback). Each step keeps its `level`, when it
  started (`started_ms`, after the analysis did), how long, what it was
  `handed`, what it ran without (`degraded`), what it stood in for
  (`fallback_of`), how it ended and why.
- **In the app.** *Analyse* lists the capabilities level by level —
  « Étape 1 · en parallèle », « Étape 2 », « Conclusion » — each with what
  it received (« reçoit : Changements »), ran without (« sans :
  Responsabilités »), stood in for (« à la place de … ») or waited on in
  vain (« attendait : … »).

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
`superseded`, and opens no decision. Asked again, its context keeps its id
and takes a newer version: an analysis is current only for both — the
same context **and** the version it read (`context_version`, LEKA-433). A failed one is analysed again by its asker or an approver:
`retried` to `analysing`, then queued.

**Queued, and swept.** Created and asked again, the route commits, then
queues the job (`queue_analysis`); `POST …/analyse` the same. Every 15
minutes (`intention-analysis-sweep`, :07 :22 :37 :52) the intentions
analysing whose context version has no analysis yet are analysed — what no
worker took, a newer version's lost job included. Idempotent.

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
  reaches — and, apart, what LEKA recommends (below). On its way: « LEKA analyse votre
  demande », read again every 4 s, the intention read again once done;
  blocked: what its context lacks (§ 11); failed: « Relancer l'analyse ».
  Its earlier analyses listed.
- *Preuves*: every piece of evidence collected — where it came from, its
  record, its origin and confidence, which capability cites it.
- *Vue d'ensemble*: its summary, in the reader's words — the written answer
  when there is one.

**LEKA's analyst** (`analyst.py`, 2026-10-09): the **synthesis**
capability (`method: model`) runs after the rules — and is no longer a
model rewording what they found. It is a language model that knows what
LEKA is and reads what the question needs through LEKA's own reads, read
only, as a colleague with access to everything LEKA knows would. Each read
is a skill (LEKA-396, [skills.md](skills.md)): what the model asks is checked
against what it takes, run with what the person who asked may read (their
role now), the database holding it read only, and kept about the intention
(`GET /skills/runs?ref=intention:<id>`).

| Skill | What it reads |
| --- | --- |
| `find` | things by name or words — services, applications, repositories, databases, resources, teams, people, documents |
| `describe` | one thing: what it is, its state, what its sources say of it, who answers for it (owners, maintainers, leads, experts — LEKA-365), what it is tied to |
| `dependencies` | what it depends on, or what depends on it, two steps |
| `happened` | what happened in a period — deployments, merged pull requests, releases, change requests, incidents opened or resolved — everywhere, in one environment, or around one thing |
| `incident` | one incident: severity, state, what it affected, what is said or suspected to have caused it, what changed in the 72 hours before |
| `learned` | what LEKA's model gained, changed, lost in a period |
| `sources` | what LEKA reads, each source's state, when it was last read |
| `insights` | what LEKA already concluded and is still open |
| `overview` | what the model holds: how many of each kind, the environments, its last build |

And the skill library (LEKA-401, [skills.md](skills.md) § 9): the
assessments an expert of each domain would make — `delivery-metrics`,
`incident-history`, `blast-radius`, `test-scope`, `change-review`,
`repository-profile`, `security-posture`, `documentation-coverage`,
`infrastructure-inventory`, `data-landscape`. It is told to use the skill
that computes an assessment rather than reads put together, and to rest on
the signals it gives. The question's environment is filled in when the model
leaves it out.

It is told what LEKA is (things, events, relationships, sources, stated or
inferred, a state measured only when monitoring is connected) and how to
answer: the answer first, plainly, then names, versions, counts, dates in
the asker's zone (« hier à 15h57 »); facts and inferences apart; when
nothing is found, what was checked — which sources, which period, when last
read — so « nothing changed » can be trusted; never an invented name, date
or cause; no internal words; in the question's language; never an action.
It starts from what the rules found (the same input the synthesis always
had) and a part of the context; at most six rounds of tools, the last one
made to answer (`Task.conclude`); low thinking, 120 s.

Its answer is checked: each point cites what a read returned (`entity:…`,
`event:…`, `source:…`, `finding:…`), what the rules found, or the context;
a citation of nothing it read or was given is dropped, a point citing
nothing goes, an answer resting on nothing — when there was something — is
not kept. **What it cites becomes the analysis's evidence** (the Preuves
tab), and an analysis the rules alone found inconclusive is `complete` on
it. Not kept, or no model with tools reachable: the synthesis as it was
(`writing.py`) — what the rules found, said in words, low thinking, room
for its answer (before 2026-10-09 an answer was cut short by its own
thinking, judged invalid and asked again: paid for twice, for nothing).
No model: skipped, said (`no_model`).

What it costs, measured on the demo with Gemini 3.8 Flash: a question the
rules already answered, one call, about 1 cent; one it looks into, two to
six calls, 1.3 to 2 cents — the start of each round read from Google's
cache, billed a tenth (model-gateway.md). The intention's cost, average,
is in Paramètres › Modèle de langage.

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
what waits; another workspace's 404; asked again while analysed, the old
version's analysis superseded — no move, no decision — and the newer one
recovered by the sweep (LEKA-433). `tests/test_intention_model.py`, Gemini
scripted: words the rules cannot read, read by the model and analysed; a
request to act staying the rules'; the answer written, a made-up citation
dropped; an answer resting on nothing not kept. `tests/test_intention_analyst.py`:
the analyst told what LEKA is, given its nine reads, read only, looking a
thing up, answering on it — what it cites the analysis's evidence, the
analysis complete, each read kept about the intention for whoever asked; an answer resting on nothing it read not kept, the
rules' said instead. `tests/test_intention_analysis.py`: what happened
everywhere, in production, said where; what LEKA learned; « prod » is
production. `tests/test_intention_orchestration.py`, pure (LEKA-399): a
plan in levels, the conclusion last, a cycle refused; a level run together;
each handed what it names and only that; a prerequisite failed skips, a use
failed degrades, a fallback stands in and what follows reads it; the
incidents read the causes the changes reach; an action reads who owns what
it acts on. `web/lib/intention-analysis.test.ts`,
`web/components/intentions/analysis-tab.test.tsx`;
`e2e/intention-analysis.spec.ts`, on the demo: asked, analysed, followed,
its evidence and history; a restart waiting for a person.

### What LEKA recommends (LEKA-389)

What to do next, from what the analysis found — **a proposal, never a
fact**, and never done by LEKA. Code: `api/leka/intentions/recommend.py`
(pure), run after `assemble()`; kept in the result
(`IntentionAnalysisResult.recommendations`), apart from its findings,
causes and uncertainties.

**Each recommendation** (`AnalysisRecommendation`):

| Field | |
| --- | --- |
| `code`, `params`, `text` | what to do — worded by the interface from its code (`recommend.*`), in English for what reads it without one |
| `why` | why — the cause, the finding or the uncertainty it follows from (`params.of` names it, so the interface says it as the analysis does) |
| `basis`, `evidence` | **traceable**: the ids of the findings and causes it follows from, and of the evidence they rest on — all in the same result |
| `action` | rollback, change, monitor, other |
| `changes_systems` | it would change a customer's systems: shown « soumis à validation » — only once a person approves (§ 13) |
| `priority`, `risk`, `reversible` | how urgent, how risky, whether it can be undone |
| `confidence` | **never surer than what it follows from**: a cause's confidence, × 0.8 when only suspected; none when it is not a bet |
| `target` | what it is about, when it is one thing |

**The rules:**

| From | Recommends | Changes systems |
| --- | --- | --- |
| a change (deployment, change, release, pull request, commit) said to have caused an incident, or suspected at 0.8 or more | `recommend.rollback` — high priority, reversible, at the analysis's risk | yes |
| the same, only suspected (under 0.8) | `recommend.confirm_cause` first (high), then the rollback at medium priority | no, then yes |
| an incident nothing says or suggests caused (`incident.no_cause`) | `recommend.investigate` | no |
| nobody named owner (`ownership.unknown`) | `recommend.assign_owner` | no |
| several owners (`ownership.several`) | `recommend.settle_owner`, from the owner findings and their evidence | no |
| no document, or none current (`documentation.none`, `.stale`) | `recommend.document`, `recommend.update_documentation` | no |
| a compliance check failed | its remedy: assign an owner, update the documentation, say the criticality, deal with what is open, improve the knowledge | no |
| a thing known poorly (`standing.known_poorly`) | `recommend.improve_knowledge` — connect its sources | no |
| applications reached, at high or medium risk | `recommend.notify` their teams | no |
| an inconclusive analysis with nothing else to propose | `recommend.ask_differently` | no |
| a failed analysis | nothing | — |

Each once (by what it is about), the most urgent and surest first. What is
known proposes nothing: an owner said is not proposed again.

**In the app** — tab *Analyse*: « Recommandations de LEKA » apart from the
facts, causes and impact (`AnalysisView`, LEKA-341), drawn when LEKA
proposes something: each worded, its why, « Modifie vos systèmes : soumis à
validation » when it would, its priority, reversibility, risk and
confidence, and on opening the evidence it rests on — the same evidence the
*Preuves* tab lists. Inconclusive: « Analyse non concluante » and what to
do; partial: what is missing (a capability that did not finish).

**Tested** — `tests/test_intention_recommend.py`, pure, on LEKA-388's own
capabilities: a stated cause proposed undone, as sure as it; a suspected
one confirmed first; an incident nothing explains investigated; nobody
owning, several owners, a stale document, a failed check — each its
remedy; a wide reach of high risk, its people told; inconclusive and
failed; never a finding; every one traceable to the result's findings,
causes and evidence. `tests/test_intention_recommend_api.py`, on Acme's
model: « Qu'est-ce qui dépend de Billing API ? » proposes telling Billing
platform's and Shop's teams; a known owner proposes no owner.
`web/components/intentions/analysis-tab.test.tsx`: proposals apart, worded,
their why, approval said, evidence opened; inconclusive; partial.

### On what it rests, said (LEKA-441)

An analysis says what LEKA understood, what it really read and in what
state, what is certain and what is only thought, how sure it is and why,
what is missing or contradictory, its limits, and what to do next, and why.
Nothing on screen is persuasive decoration: every figure is counted from the
result, defined, and opens on what it was counted from.

`api/leka/intentions/explain.py`, pure, after `recommend`: the result's
`explanation` (`AnalysisExplanation`), kept with it. The result's status and
confidence are held to it:
- **never `complete`** while a source it read from was failing, degraded or
  still syncing: it is `partial`, with `analysis.sources_pending` in
  `missing`;
- **never a figure surer than its level**: low ≤ 0.59, medium ≤ 0.84;
  unknown, none.

| Field | What it holds |
| --- | --- |
| `understood` | What LEKA understood: goal, the things, the unknown names, where, what is excluded, the period said, the actions. Worded by the interface from its values. |
| `consulted` | Each source behind what it read, with how much it brought and its **state** when it read: `read`, `error`, `degraded`, `stale` (not synced for 7 days), `syncing`, `disabled`, `gone`. Never shown read when it was not. |
| `capabilities` | Each capability chosen and how it went. One that did not answer says **what that leaves unknown** (`limit.capability.<name>`), e.g. « what changed is not known: a cause may be missing ». |
| `confidence` | `{level, reasons}`: high, medium, low or unknown, and why (below). Never a bare percentage. |
| `claims` | The figures a screen may say, each `{code, count, holds, definition, refs}` (below). |
| `conflicts` | What its sources disagree on **about what it asks**, every side with who says it. Disagreements about other things in its context do not weigh on it. |
| `stale` | Sources out of date or failing, documents not current. |
| `limits` | What did not answer, sources failing or syncing, a context lacking something. |
| `next` | What to do next and **why** (below). |
| `context_version` | The version of its context it read. `GET …/analysis` adds `context_now`, the version its intention's context is at now: newer, the screen says it read an older one, with the way to analyse again. |

**Causes, by strength** (`analysis.strength_of`, kept as `causes[].strength`):
- `confirmed`: its source states it is the cause;
- `probable`: LEKA infers it with enough to go on (≥ 0.6: a change within 6 hours on what it affects, an enrichment rule);
- `correlated`: only time ties it to what happened. It is tagged « Corrélation, pas une cause », with no percentage, and never shown as a cause.

**How sure — defined criteria.**

| What it rests on | Level |
| --- | --- |
| a cause its source states | high |
| a cause LEKA infers, probable | medium |
| only a correlation in time | low |
| findings from two sources or more | high |
| findings from a single source | medium |
| a name LEKA does not know, nothing else asked about | low |
| nothing found | low |
| it could not run | unknown |

**Capped at medium** by:
- a capability that did not answer (the written synthesis excepted);
- a context lacking something it needs;
- a contradiction on what it asks;
- a source failing, degraded, syncing or out of date.

Each cap is a reason, said.

**The figures (claims).** Each one is counted, never estimated:

| Code | Counts | Shown |
| --- | --- | --- |
| `sources` | distinct sources the evidence of its findings and causes was read from | « 3 sources à l'appui des constats » |
| `correlated_events` | changes tied to an incident by time or inference, none confirmed by a source | « 1 événement corrélé, non confirmé comme cause » |
| `contradictions` | conflicts on what it asks | « Aucune contradiction sur ce qui est demandé » |
| `impacted_users` | **only when a source states it** (`impacted_users`, `users_affected`…) | « 2400 utilisateurs touchés, selon la source ». Absent otherwise: never « 2 400 utilisateurs impactés » from nothing. |

**Recommendations, with what they need first** (`preconditions`,
`assumptions`, `executable`):
- undoing a change needs:
  - the **version to go back to**, from its source (`previous_version`, `previous`, `from_version`, `rollback_to`), never guessed;
  - **where** it ran;
  - non-blocking: that the change is **confirmed** as the cause, and a person's **approval**.
- What it rests on that is not confirmed is what it **assumes**.
- A blocking precondition unmet makes it « Pas exécutable en l'état », with what to settle first.

**Next step** (`next.code`), the first that applies:
1. it could not run: `fix_source` or `rerun`;
2. a source was still syncing: `rerun` once it has synced;
3. it names something LEKA does not know: `ask_differently`;
4. its sources disagree on what it asks (« le SLA »): `settle_conflict`;
5. its first recommendation:
   - changes systems and can be carried out: `decide`;
   - cannot be carried out as it stands: `prepare`, with what it needs;
   - otherwise `confirm_cause`, `ask_differently` or `act`;
6. a disagreement: `settle_conflict`;
7. a capability that did not answer: `rerun`;
8. inconclusive: `ask_differently`;
9. otherwise `nothing`.

**On screen** (`components/intelligence/explained.tsx`, reusable):
- above the results:
  - `UnderstoodLine`;
  - `FreshnessNotice`, with « Relancer »;
- in the synthesis: the confidence **level in words**, and the claims, each opening on what it counts and what it was counted from;
- on the right:
  - `NextStepPanel` with its why;
  - `ConfidenceExplained` with its reasons;
  - impact;
  - recommendations, with their preconditions, assumptions and « Pas exécutable en l'état »;
  - `ConflictList`;
  - `AnalysisLimits` (what did not answer and what that leaves unknown, what may be out of date);
  - `SourcesConsulted`, each source in its state;
- when the analysis could not run: what to do next and its limits, never a bare « échec ».

An analysis made before LEKA-441 has no explanation: it draws as it did.

#### The scenarios (`tests/test_intention_explain.py`)

**1. Several sources really agreeing**
- **Input**: a cause stated by its source; evidence from GitHub and Jira, both read.
- **Evidence**: the incident, the deployment, two sources.
- **Confidence**: high, `cause_confirmed`.
- **Forbidden**: none.
- **Shown**: « Confiance élevée », « 2 sources à l'appui », « Aucune contradiction ».

**2. A source partial or unavailable**
- **Input**: Jira in error; `changes` failed.
- **Evidence**: what GitHub said.
- **Confidence**: medium at most, with `capability_failed` and `sources_unsure`.
- **Forbidden**:
  - Jira shown « Lue »;
  - « Analyse terminée »;
  - « Confiance élevée ».
- **Shown**:
  - partial;
  - Jira « En échec »;
  - « Changements n'a pas répondu — une cause peut manquer ».

**3. Sources contradicting each other**
- **Input**: « Quel est le SLA de payment-api ? », with 99.95 against 99.9.
- **Evidence**: both values, and who says each.
- **Confidence**: medium at most, with `conflicts`.
- **Forbidden**:
  - a single SLA stated as a fact;
  - « 0 contradiction ».
- **Shown**:
  - both sides and their sources;
  - next: « Trancher : payment-api · sla ».

**4. Data out of date**
- **Input**: Jira not synced for 30 days.
- **Evidence**: what it said 30 days ago.
- **Confidence**: medium at most, with `sources_unsure`.
- **Forbidden**: Jira shown « Lue ».
- **Shown**:
  - Jira « Pas à jour » under « Ce qui peut être daté »;
  - complete, since out of date is not failing.

**5. A correlation in time, no proof of cause**
- **Input**: a change 26 hours before the incident (0.55).
- **Evidence**: the two events.
- **Confidence**: low, `cause_correlated`.
- **Forbidden**:
  - « cause » for it;
  - « 55 % »;
  - a rollback proposed first.
- **Shown**:
  - « Corrélation, pas une cause »;
  - « 1 événement corrélé, non confirmé comme cause »;
  - next: confirm the cause.

**6. A plausible recommendation, not executable for lack of preconditions**
- **Input**: a rollback whose sources do not say the version it replaced (the demo company's case).
- **Evidence**: the stated cause.
- **Confidence**: as its cause.
- **Forbidden**: an invented « Revenir à la version v2.7.9 ».
- **Shown**:
  - « Pas exécutable en l'état — À régler d'abord : version à restaurer inconnue »;
  - next: « Préparer ».

**7. An analysis finished before its sources did**
- **Input**: Jira still syncing.
- **Evidence**: what was read.
- **Confidence**: medium at most.
- **Forbidden**: « Analyse terminée ».
- **Shown**:
  - partial;
  - Jira « Synchro en cours »;
  - next: rerun once the sync is done.

**8. Also checked**
- An analysis that could not run has confidence `unknown`, no figure, and next `rerun`.
- An unknown name: confidence low, next `ask_differently`.
- A figure no source states is never said.
- A result made before reads without its explanation.

On screen: `web/components/intelligence/explained.test.tsx` covers complete, partial, uncertain, contradictory, failed, not executable and a context moved on. `web/lib/intention-analysis.test.ts` covers the wording, in French and in English.

## 13. Its decision (LEKA-390)

What it asks to do is never LEKA's to decide: once analysed (§ 12), an
intention that asks to act on systems waits for people — under a policy
its workspace sets, every vote kept. Code: `api/leka/intentions/decisions.py`
(pure: the policy, the risk, the proposals, the tally), `approval.py`
(`DecisionService`: opening, voting, the queue, the policy), the routes in
`api/leka/api/decisions.py`.

**Opened by the analysis.** When it moves an intention to
`awaiting_decision`, the analysis opens a decision (`intention_decisions`)
and links it (`intention_links`, kind `decision`, `#1`):

| | |
| --- | --- |
| the proposals | one per action that changes systems (LEKA-385): the action, what it is on, where (`environment`), the hard constraints (no downtime, a window…), whether it can be undone (`reversible`: a restart, a rollback, a deployment yes; a migration no; else not said) |
| the risk | low, medium, high or critical: the analysis's (§ 12) — `medium` when it cannot say — raised by the policy's rules, each reason kept (`governance.reasons`, LEKA-404) |
| what it needs | `required_approvals`, `separate_asker` (four eyes: the asker may not be one of them), `required_role`, how long an approval holds and when it is escalated, read from the policy in force — kept with it (`policy`, `governance`), so a later change does not move it |
| what it rests on | the analysis, the context's version, the asker |

An earlier decision still waiting on the same intention is superseded.

**The policy** — `workspace.settings.approval_policy`, LEKA's default for
what it does not say: per risk, the approvals, whether the asker may be
one, the role one must hold, how long an approval holds, when a waiting
decision is escalated; the rules that raise a risk. By default one approval
for low and medium, two for high and critical, never the asker on those,
an owner among a critical one's. `GET /decisions/policy` says it; `PUT
/decisions/policy` changes it (`workspace:update`). A freeze stops what it
covers; a waiver approves a standard change in advance; an approver may
lend their vote. All of it: [governance-rules.md](governance-rules.md).

**Voting** — `POST /intentions/{id}/decision/{verdict}`, `intention:approve`:

| Verdict | | Says why |
| --- | --- | --- |
| `approve` | one approval of the current revision | may |
| `reject` | one is enough: rejected, the intention `rejected` — nothing runs | must |
| `modify` | a new revision: where it runs (`environment`), which actions are kept (`keep`) — its risk read again under the policy it was opened with, the earlier approvals void, the modifier's own counting | must |
| `request-changes` | sent back: `changes_requested`, the intention still awaiting a decision until its asker asks again — the next analysis opens a new one | must |

Enough distinct approvers of the current revision — the asker not among
them when `separate_asker`, one of them of the `required_role` — approve
it: `approved`, the intention `approved` by the person whose vote decided
it, its history saying the decision, its revision, risk and approvers.
Refused, with the refusal's code in `details` (`field: "refusal"`):
`asker_may_not_approve`, `no_delegation` (403), `already_approved`,
`frozen` (409), `reason_required`, `invalid_change`, `nothing_changed`
(422); nothing open — decided, or its intention moved — 409.

**Every vote kept** (`intention_decision_votes`): who, when, why, on which
revision, what a modification changed (`changes`: from, to) and the context
it was cast in (`context`: the risk, the proposals, how many were required,
the analysis, the context's version, where the intention stood). Append-only:
the database refuses to change one — only who cast it is forgotten, with
the user.

**Its intention moved meanwhile** — cancelled, asked again, archived — a
decision still proposed is read as `superseded` and leaves the queue: it is
no longer the one.

**The API**: `GET /decisions?status=proposed|approved|rejected|withdrawn`
— À valider's queue, each with its intention; `GET /decisions/summary`;
`GET /intentions/{id}/decisions` — every one, the latest first, each with
its votes. `intention:read`; another workspace's is 404.

**In the app**:

- *À valider* (mockup 09): the actions to decide join the queue — type
  *Action*, their impact (the risk), their state; opened, the panel says
  what was asked and by whom, the actions proposed, how many must approve
  and how many have, « Vous gardez le contrôle », then *Valider* (asked
  first, with what it opens the way to), *Refuser*, *Modifier* (where it
  runs, which actions are kept, why), *Demander des modifications* — the
  asker kept apart by the policy, and a member who may not approve, told
  why they cannot — and every vote. Counted in the sidebar's badge and on
  Mon Dashboard.
- *An intention's page*: its latest decision, the same, on its overview.

The composer's step 4 (mockup 05, `DecisionStep`) still shows its example:
LEKA-389's recommendations fill it, and it calls these routes.

**Tested** — `tests/test_intention_decisions.py`, pure: the policy kept or
refused; the risk decided at; what is proposed; the tally — a rejection,
changes asked, distinct approvers, the asker and an earlier revision not
counting; who may vote; a modification. `tests/test_intention_decisions_api.py`,
on Acme's model: « Redémarre Billing API en production » proposed — restart,
production, reversible, medium, one approval — linked, approved by an admin
not a member, its history and vote with their context; a question, no
decision; rejected saying why; modified to staging, the earlier approval
void, the same person refused twice, a second admin deciding; the asker
kept apart; the policy an admin's, kept, refused, an open decision keeping
its own; changes asked then superseded; a cancelled intention's decision
left behind; the queue, its counts, a vote the database refuses to change,
another workspace. Web: `approvals-page.test.tsx` (the decisions in À
valider), `intention-decision.test.tsx`; e2e `intention-decisions.spec.ts`,
on the demo: approved in À valider, refused from the intention's page.

### What an action must rest on (LEKA-436)

A question may be answered in part — its analysis `partial`, what is
missing said — and is never gated. An action is proposed only as grounded
as what its analysis read: before its decision opens, the capabilities its
risk needs must have succeeded, and its context must not be stale.

| Risk | Evidence it needs |
| --- | --- |
| low, medium | `standing` (the state of what it targets), `action` (what it reaches) |
| high, critical | those, and `changes` (the last change on it), `ownership` (who owns it) |

A capability not run or not succeeded is missing; a context whose readiness
says `model_stale` or `stale_evidence` is stale. Then the decision opens
**gated** — `governance.grounding {gate, missing, stale}`, said on the
decision card:

- `blocked` (high, critical): it cannot be approved (refusal `ungrounded`)
  until the intention is analysed again — asked again, its evidence read
  anew;
- `validation` (low, medium): one more approval than the policy asks.

A gated decision is never approved by a waiver.

## 14. Carrying it out (LEKA-391)

What an approved decision becomes: a plan, checked before it runs, each
action run by a system the workspace authorized — or by a person — what
came of each kept, said as it is, the intention moved as it goes. Code:
`api/leka/intentions/execution.py` (pure: the plan, the checks, windows
and deadlines, the signature, what an answer means), `actions.py`
(`EndpointService`, `ActionService`, the job and the sweep), the routes in
`api/leka/api/actions.py`.

**Authorized systems** (`action_endpoints`). LEKA holds no write access to
a customer's systems: it calls only the endpoints an admin registered
(`workspace:update`) — their own automation, a CI job, a runbook — each
saying which actions (LEKA-385's codes, or `*`), in which environments (or
`*`), and optionally on which things it accepts. https, a public address:
refused at once otherwise, and refused again when called — the call goes
through the connectors' transport (`connectors/network.py`: public
addresses only, pinned against DNS rebinding). Its signing secret is made by
LEKA, shown once, kept encrypted (`secret_box`) — and re-encrypted with the
sources' credentials when the key rotates (`intentions/tasks.py`,
`scripts/rotate_encryption_key.py`, the runbook). Paramètres → *Actions
autorisées*.

**The plan** — `POST /intentions/{id}/plan`, `intention:approve`, on an
intention `approved` (or `failed`: a retry):

| | |
| --- | --- |
| its steps | one per action the decision approved — of what did not succeed, on a retry — each run by the first endpoint authorized for that action, environment and target, else by a person (`manual`) |
| when | now, or at a moment chosen; asked in a window (« cette nuit », « hors heures ouvrées », « ce week-end », LEKA-386), its next opening is suggested (`suggested_for`), in the plan's time zone |
| linked | to the intention (`intention_links`, kind `action`) |

**Checked before anything runs** — when started, again when a scheduled
plan's time comes, and again before each system is called; each check
kept with the plan (`checks`), one failing and nothing runs (409, the
failing ones in `details`):

| Check | |
| --- | --- |
| `decision_approved` | the decision still approved, at the plan's revision |
| `approvers_allowed` | enough of its approvers may still approve (their role today) |
| `endpoint_allows` | the endpoint still enabled, still authorizing that action there |
| `targets_present` | the thing acted on still in the company model (not removed, not archived) |
| `in_window` · `before_deadline` | inside the window asked; before the deadline (the end of its day) |

**Running** — `POST …/plan/start {scheduled_for?, timezone}`: the intention
`executing` (or `scheduled`; the sweep `intention-plans-due`, every five
minutes, starts what is due). Step by step:

- **a person's step** waits (`awaiting`) for who may approve to say it is
  done or failed — `POST …/plan/steps/{step_id}/report {outcome, note,
  link?}`, the note required, the link http(s) only;
- **a system's step** is called by the job (`leka.intentions.actions.run_plan`),
  once the route has committed: `POST` to its URL, signed. **Checked again
  at the last moment** (LEKA-435), just before the call — a plan waits, and
  what held when it started may not any more: still approved, its approval
  not expired, its approvers still allowed, the policy met, no freeze, the
  endpoint still authorizing it, its targets still there, inside its window,
  before its deadline. One failing: nothing is sent — the step `failed`
  (`no_longer_authorized`, or `checks_failed` for what is no longer *now*),
  the failing checks kept with it, `action.executed` audited `denied`,
  `sent: false`. What it answered decides, never assumed — **the executor's
  contract**:

  | Answer | The step |
  | --- | --- |
  | 2xx with `{"status": "succeeded"}` | succeeded — the only answer taken for done |
  | 202, or `{"status": "accepted" \| "pending" \| "running" \| "queued"}` | awaiting a person's confirmation — accepted is not done |
  | any other 2xx — empty, not JSON, no or an unknown `status` | awaiting a person's confirmation (`unconfirmed`): it may have acted — never said done, never retried as failed |
  | `{"status": "failed"}`, anything but 2xx | failed (`reported_failed`, `http_<code>`) |
  | no answer within 20 s | failed (`no_answer`: it may have acted — a person checks) |
  | a private address | failed (`blocked_address`) |

All succeeded: the plan `succeeded`, the intention `verifying` — its outcome
verified (§ 15). One failed: the steps after it not run (`skipped`), the
plan `failed`, the intention `failed` — planned again, a new plan of what did
not succeed. A step is never said done that was not.

**Stopping** — `POST …/plan/cancel {reason}`: planned or scheduled, the plan
cancelled and the intention `approved` again; running, what has not
started is cancelled — what is running ends and is said — the intention
`failed`.

**The call**, for who builds an endpoint:

```
POST <url>
Content-Type: application/json
X-Leka-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<body>" with the secret>
X-Leka-Delivery: <step id>   (one per step: an endpoint may refuse one it already ran)

{"event": "leka.action", "delivery": "<step id>", "workspace": "…",
 "intention": {"id", "title"}, "decision": {"id", "revision"},
 "plan": {"id", "number"}, "action": "restart",
 "targets": [{"id", "name", "type"}], "environment": "production",
 "constraints": [{"kind": "no_downtime", "value": true}], "requested_at": "…"}
```

Recompute the signature over the raw body, compare in constant time,
refuse a `t` older than five minutes (`execution.verify` does it). Answer
`{"status": "succeeded" | "accepted" | "failed", "detail"?, "ref"?,
"metrics"?}` — `metrics`, what it measured (`{"p95_ms": 180}`, at most 50
numbers or words), read when its outcome is verified (§ 15).

**Evidence kept**: each step's `evidence` — what was sent (the URL, the
payload, its SHA-256, when signed), what answered (status, duration, the
first 2 000 characters), the outcome and its reference, a person's note and
link — and every event of the plan (`intention_plan_events`: planned,
checks failed, scheduled, started, a step started, awaiting, succeeded,
failed, cancel requested, cancelled), who, when, append-only — the
database refuses to change one.

**The API**: `GET /intentions/{id}/plans` — every plan, the latest first,
with its steps, checks and events; `GET /action-endpoints`
(`intention:read`), `POST` · `PATCH` · `DELETE` (`workspace:update`).

**In the app** — the intention's tab *Actions* (mockup 06): *Préparer
l'exécution*; the plan — each action, who runs it (an authorized system,
signed; or a person), the window asked and its next opening; *Lancer
maintenant* (asked first, what it runs said) or *Planifier*; the checks,
passed or not; each action's progress — Préparation, Exécution,
Vérification (LEKA-392), Finalisation — its evidence; *Marquer comme fait* /
*Signaler un échec* with what shows it; *Interrompre l'exécution* (why);
*Relancer ce qui n'a pas réussi*; the *Journal d'exécution*. Read again
every 4 s while it runs. Anyone else follows it.

**Tested** — `tests/test_intention_execution.py`, pure: what an endpoint
is authorized for; a step to a system or a person; windows in a time zone
and their next opening; a deadline; every check, one failing; the signature
made and verified — tampered, another secret, too old refused; an answer
taken as it is. `tests/test_intention_actions_api.py`, on Acme's model with
a stand-in system behind the real transport: a person's step confirmed,
the intention verifying; a system called signed, its answer kept; accepted
waiting for a person; a 500 failing it, retried; no answer, a private
address; an endpoint disabled since, an approver demoted — refused; scheduled
and run by the sweep; cancelled before and while running; admins'
systems, a link that is not http(s) refused, the log append-only, another
workspace. Web: `actions-tab.test.tsx`, `action-endpoints.test.tsx`; e2e
`intention-actions.spec.ts`, on the demo: prepared, run, a person's step
confirmed; scheduled and called off.

## 15. What came of it, and its whole story (LEKA-392)

Whether what ran achieved what was expected — read, never assumed — and
everything that happened to the intention, in one timeline. Code:
`api/leka/intentions/outcome.py` (pure: what is expected, what is read, the
verdict), `verification.py` (`VerificationService`, the sweep),
`timeline.py`, the routes in `api/leka/api/outcomes.py`.

**Expected** — each plan carries what should be true once it ran
(`intention_plans.expectations`), LEKA's defaults set when it is prepared:

| Kind | Met when | By default |
| --- | --- | --- |
| `healthy` | no incident open on the thing acted on (an `affects` from an incident `open` or `in_progress`) and, when the model holds its state, a healthy one — a resource's normalised `running`, a service's as its tool says it (PagerDuty `active`, a status page `operational`); `failed`, `stopped`, `critical`, `warning`, `disabled`, an outage are not | on each thing acted on by an action that heals (restart, rollback, deploy, fix, scale, update) |
| `incident_resolved` | the incidents open on it when it was planned no longer open | when incidents are open on what it acts on |
| `metric` | `{name, comparator: lt·lte·eq·gte·gt, value, source}` — read in the model (the thing's attribute) or from what the system that acted reported (`metrics` in its answer, § 14) | — |
| `confirmed` | a person says so, with what shows it | — |

Who may approve changes them until it runs — `PUT /intentions/{id}/plan/expectations`;
refused once it started (409 `not_planned`) or for one that cannot be checked
as said (422 `invalid_expectation`); the plan's log says so (`expectations_set`).

**Verified** — every step succeeded, a verification opens
(`intention_verifications`, one per plan), the intention `verifying`. LEKA
lets it settle ten minutes, then reads it again every five
(`intention-verifications-due`) until all is met or its deadline, 24 hours
after it ran. Each expectation is `met`; `not_met`, said why (incidents still
open, its state); `unknown` — the model does not say, or no source has shown
the thing since it ran: what the model held before says nothing of what came
of it; or `awaiting` a person. Nothing is said met that was not read or
confirmed.

- `POST …/verification/check` — read again now;
- `POST …/verification/expectations/{expectation_id}/report {met, note,
  link?}` — a person's word on one, the link http(s) only; kept when read
  again;
- `POST …/verification/conclude {note}` — concluded now: what is not met
  counts so.

**Concluded** — all met: `succeeded`, the intention `completed`
(« verified »). At the deadline, or by a person: `partial` (some met) or
`failed`, the intention `failed`, why said. Linked to the intention (kind
`outcome`). Tried again from the tab *Actions*: a new plan of all of it —
everything ran, what was expected did not come.

**The company's context told** — a success asks the model to be built again
from its sources: an operation of the model's course (LEKA-383, in
*Activité*) whose reason names the intention (« After « … »: its outcome
verified »), a rebuild already queued being the one; its id kept with the
verification (`context_update`), the build queued once committed.

**Its whole story** — `GET /intentions/{id}/timeline` reads each record
where it is kept, append-only or written once: its history (§ 3, category
`intention`), its analyses (`analysis`: started, finished), its decision
and every vote (`decision`), its plan's events (`action`) and its
outcome's (`outcome`: expected, verification started, a person's word, the
verdict) — each by LEKA or a person (by name), when, why. The latest first;
at the same instant, the cause before what it moved. Filtered by `category`
(repeated), `actor`, `since`, `until`, `limit` (≤ 500).
`GET /intention-history` — every intention's, each with its title; by `by`
too.

**In the app** — the tab *Actions*: *Résultat attendu*, changed until it
runs (*Modifier*: removed; a metric, a thing healthy or a person's
confirmation added); once it ran, *Vérification du résultat* — each
expectation met or not and why, *Dire si c'est atteint* with what shows it,
*Vérifier maintenant*, *Conclure* (why), the verdict, the context rebuilt
(→ *Activité*); Vérification and Finalisation in each action's progress;
« De l'intention à l'impact » → *Voir l'historique complet*. The tab
*Historique*: the whole story told in order, the latest last, each in words
with its kind, filtered by kind and by who. Read again every 30 s while it
is verified. Anyone else follows it.

**Tested** — `tests/test_intention_outcome.py`, pure: an expectation kept
only when it can be checked; the defaults; healthy from the incidents open
on it and its state; met only when shown since it ran; an incident resolved,
a metric from the model or the system, a confirmation; a person's word
kept; the verdict; a system's measures read from its answer.
`tests/test_intention_outcomes_api.py`, on Acme's model, an incident coming
from PagerDuty as in production: a system's reported latency met — the
intention completed, the model rebuilt by an operation naming it, the
outcome linked; healthy not met while the incident is open, met once it is
resolved and both synced; partial at the deadline, a person's word kept; a
person concluding — failed, tried again whole; expectations set only before
it runs, by who may approve, checked; nothing expected, the outcome once
settled; the timeline — every kind, by who, in order, filtered, the
workspace's, another workspace's 404. Web: `actions-tab.test.tsx`,
`intentions.test.tsx`; e2e `intention-outcomes.spec.ts`, on the demo:
expected, confirmed by a person, achieved, its story told and filtered;
concluded short of it, failed.

## 15 bis. Handed to the agent that does the work

A request for what an agent delivers (a deck, a document, a review, an investigation, a plan) is handed to that agent: LEKA does the work, not only answers it (`dispatch.py`).

1. **At the start of its analysis, a model reads two things:**
   - the request;
   - the agents the person may use here, each with what it delivers, its formats and its inputs.

   It says which agent does the work, with which inputs, taken from the request's own words. Or it says none: LEKA's own analysis answers then, and a plain question is the analysis's.
2. **Checked before anything starts:**
   - the agent is one of those offered;
   - its inputs are exactly its contract's: unknown ones are dropped, booleans are read as such, and no required input is missing.
3. **Started for the person who asked,** as if they had launched it:
   - the same checks, re-made by the worker (their role read then);
   - the same approval controls (LEKA-406);
   - the run is kept on the intention, where its files (the PDF, the PowerPoint) appear.
4. **Said first in the answer:** which agent is at work and what it delivers. Never that LEKA cannot produce a document: its agents do.

**Once per intention:** analysing it again starts nothing more, and the agent already at work is the one said.

An agent at work on it unblocks it: what an action would need first no longer stops it.

No model, or no agent offered: nothing is started, and the analysis answers as before.

## 16. Tested

- `tests/test_intention_lifecycle.py`, pure: the way from asking to
  verified, each step's actor; a decision a person's, never LEKA's; what
  LEKA concludes and runs its own; nothing approved before analysed, nor run
  before approved; cancelling until actions run; cancelled final, the rest
  asked again; every state in one phase.
- `web/components/intentions/intentions.test.tsx`: the list and its tabs,
  the page, its whole story in words, filtered, cancelling with a reason, a
  missing one;
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
- LEKA-443: its journey — the matrix held to the lifecycle, the same state
  on every screen, versions apart, stopped and resumed, retries that do
  nothing twice, nothing left running — § 2 bis.
- LEKA-439: the brief, its questions and answers, what it takes — § 9 bis.
- LEKA-440: the whole engine, measured on a versioned set of cases against
  a reference — a regression, or a critical failure it does not know,
  refuses a change: `docs/benchmarks/intentions.md`.

## Not yet

- **Acting on a recommendation** (LEKA-389, 390): a recommendation that
  changes systems is proposed; turning it into the actions a decision
  approves — the composer's step 4 (`DecisionStep`) still shows its
  example — comes with that.
- **Agents** (`agents/*.md`) as capabilities: run with their runtime
  (LEKA-395).
- **Metrics read from monitoring**: a metric is read in the model or from
  what the system that acted reported (§ 15); reading a monitoring source's
  series when verifying comes with metrics in the model.
- **Every intention's history on a screen**: `GET /intention-history`
  answers it (§ 15); each intention's is its tab *Historique*.
- **A system's own report**: an endpoint that accepted the work (202) is
  confirmed by a person today; a signed callback can say it instead.
- **Mes intentions**' impact and sources columns (mockup 07): from the
  analysis.
