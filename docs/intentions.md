# Intentions

What someone asks LEKA, kept from the moment they ask to the moment what
was done is verified — where it stands, what happened to it, what it rests
on and what came of it (LEKA-384). An action taken against a customer's
production system must be answerable months later: who asked, what LEKA
concluded, who approved, what ran.

This is the frame of the Intentions epic. LEKA-384 keeps the intention, its
lifecycle, its history and its links; 385 to 389 understand it, scope it,
assemble its context, analyse it and conclude; 390 decides; 391 acts; 392
verifies — each moving it along this lifecycle and linking what it makes.

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
| submitted | analysing · failed | `analysis_started` · `failed` | LEKA |
| analysing | awaiting_decision · completed · failed | `proposed` · `answered` · `failed` | LEKA |
| analysing | analysing | `asked_again` | a person |
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
| `GET /intentions/counts?mine` | all, active, scheduled, finished, archived — the list's tabs |
| `GET /intentions/{id}` | where it stands, where it may go next (`moves`), what it is linked to |
| `GET /intentions/{id}/history` | every event, in order |
| `POST /intentions/{id}/ask` | `{intention, context}` |
| `POST /intentions/{id}/cancel` `{reason?}`, `/archive`, `/restore` | the intention |
| `POST /intentions/{id}/links` `{kind, ref_id}` · `DELETE …/links/{link_id}` | context, finding, entity |

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
  the context's version and the reason given; *Analyse*, *Preuves*,
  *Actions* say they come with the analysis engine. Its asker, or who may
  approve, cancels it — asked first, with a reason — archives it once done
  with, restores it.

## 9. Tested

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

- **Understanding, scope, analysis, findings** (LEKA-385 to 389): today an
  intention stays `analysing` once its context is assembled — the analysis
  that moves it on comes with them.
- **Decisions, actions, outcomes** (LEKA-390 to 392): their tables, routes
  and screens; the lifecycle and the links are ready for them.
- **Mes intentions**' impact and sources columns (mockup 07): from the
  analysis.
