# Permissions

Who may do what, in a workspace. This is the authorisation contract LEKA-331
delivers, and what its Definition of Done means by "authorisation boundaries
are documented".

**This page is checked by a test.** `api/tests/test_permissions_matrix.py`
parses the table below and compares it to `ROLE_PERMISSIONS` in
`api/leka/governance/schemas.py`. Changing one without the other fails CI —
a permission table that exists only in prose drifts from the code within a
month.

## Roles

Three, as the base of every other: a workspace builds its own on them
(LEKA-403, below).

| Role | Who it is for |
| --- | --- |
| `owner` | Whoever created the workspace, or was handed it. Answerable for the account itself. |
| `admin` | Runs the workspace day to day: members, sources, configuration. |
| `member` | Uses LEKA: reads the map, asks questions, creates intentions. |

Roles are a **chain**: an owner can do everything an admin can, an admin
everything a member can. `require_role(Role.ADMIN)` therefore admits an owner
too — listing both at every call site is how OWNER eventually gets left out
of one.

### Why not the seven roles in the mockups

The designs show Administrateur, Tech Lead, Développeur, Ops, Security,
Lecteur and Business. Those are **job titles**, and they are useful on screen.
They are not authorisation boundaries: a Tech Lead and an Ops engineer need
exactly the same things from LEKA. Modelling seven roles would mean seven
sets of permissions to keep straight, six of which are identical.

### Why no `viewer`

`member` already means "read, and create intentions". A `viewer` would differ
only by being unable to create an intention — which is most of what LEKA is
for. We have no evidence such a user exists yet.

The asymmetry decides it: adding a role later costs one `CHECK` constraint;
removing one costs migrating every existing membership. Wait for the
evidence.

**LEKA-403 kept the three as the base, and let a workspace name its own on
them** — « Tech Lead », « Sécurité » — rather than adding seats of a new
kind: a role of its own is a base role with permissions added and taken
away, so the chain and the matrix stay what everything else reads.

## The matrix

| Permission | member | admin | owner |
| --- | --- | --- | --- |
| `workspace:read` | yes | yes | yes |
| `workspace:update` | no | yes | yes |
| `workspace:delete` | no | no | yes |
| `workspace:transfer` | no | no | yes |
| `member:read` | yes | yes | yes |
| `member:invite` | no | yes | yes |
| `member:update_role` | no | yes | yes |
| `member:remove` | no | yes | yes |
| `source:read` | yes | yes | yes |
| `source:manage` | no | yes | yes |
| `intention:read` | yes | yes | yes |
| `intention:create` | yes | yes | yes |
| `intention:approve` | no | yes | yes |
| `context:manage` | no | yes | yes |
| `job:read` | no | yes | yes |
| `entity:restrict` | no | yes | yes |
| `entity:read_restricted` | no | yes | yes |
| `access:read` | no | yes | yes |
| `policy:manage` | no | yes | yes |

**`job:read` is admin and above.** It reads the history of the background jobs run for the
workspace: which job, how many attempts, when. That is how the system talks to itself, and a
member has no use for it. It shows no error text — an exception message names hosts, paths and
queries — and it never shows the system's own runs, which belong to no workspace.

**`intention:approve` decides what intentions ask to do** (LEKA-390): approve, reject,
modify, ask for changes. The workspace's approval policy may want more than one person for a
risky action, not the person who asked, and someone of a given role ([intentions.md](intentions.md)
§ 13); changing that policy, and granting a freeze or a waiver, takes `workspace:update`; an
approver may lend their authority to a member, whose votes then count as theirs (LEKA-404,
[governance-rules.md](governance-rules.md)). Carrying out what was approved — planning, starting,
scheduling, stopping a run, confirming a person's step — takes `intention:approve`; the
systems LEKA may act through are authorized with `workspace:update` (LEKA-391). What its
outcome should be, a person's word on it, reading it again and concluding take
`intention:approve`; its verification and its whole story are read with `intention:read`
(LEKA-392). The capability catalogue is read with `workspace:read` — kept at hand
too; turning a capability on or off for the workspace takes `workspace:update`
(LEKA-393).

**`context:manage` is admin and above.** A member makes contexts, makes them again,
widens and narrows them, and archives or stops following the ones they made. Archiving
or stopping someone else's — which changes what everyone reads of it — takes an admin
([context-api.md](context-api.md)). It is a write: a suspended workspace refuses it.

**An admin cannot delete the workspace or hand it over.** Running a workspace
day to day and ending the company's account are different responsibilities,
and the person doing the first should not be one click from the second.

## Rules that hold regardless of role

**The last owner cannot be removed or demoted.** A workspace with no owner
can never be deleted, transferred or rescued — a support ticket created by
one careless click. Promote another owner first (409 otherwise).

**A suspended workspace refuses writes and allows reads.** Every permission
in `WRITE_PERMISSIONS` is refused with 403 and an explanation; everything
else works. An unpaid invoice must not look like data loss, and never a 404.

**A workspace awaiting deletion refuses writes entirely.** Access stops when
deletion is requested; the data goes at the end of the grace period.

**Removing a membership takes effect immediately.** The role is resolved from
the database on every request, never cached in the session. No sign-out, no
token refresh, no waiting.

## How a Principal is built, end to end

Since LEKA-330 the chain is complete and has no stub in it:

1. The browser sends its session cookie.
2. `leka.identity` hashes the token, finds the session row, and checks
   revocation, absolute expiry and idle timeout.
3. The seam returns the user id, and the active workspace — read from the
   session **row**, never from a header or a URL.
4. `leka.governance` reads the membership **from the database, on this
   request**, and attaches the role and the workspace's lifecycle state.
5. The route's permission dependency decides.

Step 4 is why removing a membership takes effect immediately. Caching the
role in the session is the obvious optimisation and would turn a revocation
into a delay — there is a test that fails if anyone tries it.

See [security.md](security.md) for what steps 1 to 3 protect against.

## How this is enforced

Permissions are FastAPI dependencies, never an `if` in a route body
(architecture rule 5):

```python
@router.delete("/current")
async def request_deletion(
    principal: Annotated[Principal, Depends(require_permission(Permission.WORKSPACE_DELETE))],
    ...
```

A dependency sits in the signature where a reviewer sees it. An `if` is
forgotten in the fourteenth route by someone in a hurry, and nothing fails
until a customer reads another customer's data.

`require_permission` also runs the lifecycle check, so a suspended workspace
is refused there rather than in whichever service remembered to look.

## The authorisation model (LEKA-402)

One function decides, everywhere — `evaluate(subject, permission, resource,
anyones=…)` in `api/leka/governance/policy.py`, pure — and says its rule and
its reason. In order, the first that refuses decides:

| Rule | Refuses when | Reason |
| --- | --- | --- |
| `workspace` | it awaits deletion (everything), or is suspended (a write) | `workspace_unavailable`, `workspace_suspended` |
| `role` | the role lacks the permission | `role_lacks_permission` |
| `owner` | the resource is someone else's, and the role lacks the permission that reaches anyone's (`anyones`: `intention:approve` for another's run, `context:manage` for another's context) | `not_owner` |
| `restriction` | the resource is a restricted entity, and the role may not read restricted entities | `restricted` |

Allowed, it says why too: `role_grants`, `owner`, `read_restricted`.
`require_permission` is this function, for the routes; services deciding an
execution call `authorize(…)`, which decides and keeps the decision.

### Restricted entities

An admin restricts an entity of the company model, saying why
(`PUT /governance/restrictions/{entity}`, `entity:restrict`); lifting it
gives it back to everyone (`DELETE`). **Only a role holding
`entity:read_restricted` — admin, owner — sees it.** For everyone else it is
not hidden by each route remembering to: **the database guard leaves it out
of every read** (`hidden_entities`, `api/leka/db/repository.py`) — the entity,
and every row that refers to it: its relationships, versions and assertions,
a context's elements and feedback, a finding, a conflict, a quality score,
an intention's link. Each such table declares the columns that refer to an
entity (`__entity_refs__`); a new one must too.

- Resolved on every request, from the role read then: restricting takes
  effect at the next request, as removing a member does.
- **Work done for a person sees what they may** — an agent run, a workflow,
  an intention's analysis are run inside the asker's `hidden_entities`, read
  when they run.
- Asked for directly (`GET /knowledge/entities/{id}`), a restricted entity
  answers 404 — **the same answer as an entity of another workspace** — and
  the refusal is kept.
- The system's own work (building the model, enriching it, the sweeps) sees
  everything: hiding is for people.
- **Limit**: what was computed and stored as text before a restriction — an
  analysis's result, a context's intent plan — keeps the names it held then;
  a new analysis does not.

### Every decision that matters, kept

`access_decisions` — append-only (the database refuses to change one; who
asked is forgotten with their account): who asked, as which role, to do
what (a permission, or an action under one: `agent:run`, `workflow:run`), on
what resource, allowed or refused, by which rule and why, the route, the
request id. **Kept: every refusal** — written on its own, so the request's
rollback never takes it — **and every write and execution allowed**; reads
allowed are not, they would bury the rest. `GET /governance/decisions` reads
them (`access:read`), filtered by decision, person, action.

### Capabilities and actions, before they run

Running an agent or a workflow is decided by `authorize` against the
capability's own permission **before anything is kept or queued** — 403,
kept, when refused; allowed, kept with the run. Its steps and tools are then
checked again, for the same person, when they run (LEKA-395, 397).

### Across workspaces

A person's principal has exactly one workspace, from the server-side
session; every query is scoped to it by the guard, fail-closed
(ADR 007). Another workspace's intention, run, context, entity or decision is
**not found** — never "forbidden", which would say it exists.

### In the app

**Gouvernance**: the permissions of each role (the reader's own marked), the
restricted entities — restricted, said why, and lifted, by an admin — and the
trail of decisions, refusals first to hand.

## Roles and policies of the workspace's own (LEKA-403)

### A role of its own

An admin (`policy:manage`) names a role on a base — **member or admin**,
never owner — with what it **adds** and what it **takes away**
(`PUT /governance/roles/{key}`):

- **Inherited, then added, then taken away — taking away wins.**
- Refused (422, said why): adding what only an owner may
  (`workspace:delete`, `workspace:transfer`), adding what its base already
  has, taking away what its base has not, taking away `workspace:read`
  (it would lock its holder out), adding and taking away the same.
- **Given to a person whose seat has its base** (`PUT
  /governance/assignments/{user}`) — another base is refused (409): change
  the seat first, which stays the members' screen's. A seat that changes base
  no longer carries it. Taken back (`role: null`): the seat's own again.
- **Read on every request**, like the seat: given or taken back, in force
  at the next one. What it grants decides everything the role did — routes,
  the catalogue and the router, restricted entities, the work done for the
  person.
- Held, it cannot be deleted (409); its base cannot change while held.

### A policy

A rule of the workspace (`/governance/policies`, `policy:manage`):

| Field | |
| --- | --- |
| `effect` | `deny` — refuse; or `allow` — an exception |
| `actions` | permissions, or the executions decided before they run (`agent:run`, `workflow:run`); `*` every one |
| `roles` | `member`, `admin`, `owner` or a role of its own; none: everyone |
| conditions | `resource_types`, `risk_at_least` (low · medium · high), `kinds`, `categories` — a policy with any applies only to a resource that meets them all |
| `priority` | 0 to 100 |
| `enabled` | off, it is kept and not applied |

**Evaluated in the one evaluation, after the role, before the owner and the
restriction** — so it applies wherever a permission is decided: every
route's dependency, an agent or a workflow started (with the capability's
risk, kind, category), and again **when it runs** — an agent, an agent step
of a workflow — for the person, as things stand then.

### Precedence, deterministic

1. **A policy only takes away.** An exception never grants what the role
   does not carry: it lifts a refusal of lower priority.
2. Of the policies that apply, **the highest priority decides**.
3. **At the same priority, a refusal wins** over an exception.
4. Same priority, same effect: by id — always the same order.

The decision says which policy decided (`policy`), its rule `policy`, its
reason `policy_denied` or `policy_allows`; the trail keeps it.
`POST /governance/evaluate` asks the decision a role would get — a
permission, an action, a resource — **without doing anything**.

### Their history

`governance_events` — every role created, changed, deleted; every role
given or taken back; every policy created, changed (enabled, disabled),
deleted — who, when, **before and after**; append-only, the database refusing
to rewrite one (`GET /governance/history`, `access:read`). The data
protection policy's changes join it (`subject_type` protection, LEKA-405).

## Data protection (LEKA-405)

`GET /governance/data-protection` — the platform's protections as they
stand, the policy, per source what was found in its records and taken out,
in kinds and counts — takes `access:read`; `PUT
/governance/data-protection/policy`, `policy:manage`. Both decided and kept
as every permission is. [data-protection.md](data-protection.md).

## AI governance (LEKA-406)

Who may ask is decided here; what the workspace's AI may then do — which
models, how much, what an answer may not carry, which agents wait for
approval — by its AI controls, at the model gateway and where an agent is
asked to run. Changing them takes `policy:manage`; approving a held run,
`intention:approve`, never by who asked it; what they did, `access:read`.
See [ai-governance.md](ai-governance.md).

## What is deliberately absent

Groups, SSO-mapped roles, roles of its own on the owner's base, and grants
to one person on one entity: a restriction is by role. All are plausible one day; none is needed
by any screen that exists. See
[adr/007-tenant-isolation-strategy.md](adr/007-tenant-isolation-strategy.md).

## Équipe & accès, Facturation

`GET /team/members` — everyone with a seat, with their name, address, role,
when they joined and last signed in — any member. `GET /invitations` (the
pending, the expired said so) and `DELETE /invitations/{id}` (revoked, its
link dead) take `member:invite`. An invitation is emailed when it is made —
its link, who invites, to which workspace, as what — and accepted at
`/invitations/<token>` by someone signed in (or signing in, then back),
the workspace entered at once. `GET /billing/usage` — what the workspace
holds and did this month, counted — any member; no plan, payment nor
invoice is held by LEKA yet.

## Agents (LEKA-395)

Running an agent (`POST /agent-runs`) takes `intention:create` **and the
agent's own permission** (its front matter's, `intention:create` by
default): a role without it is refused, 403. Its tools are offered only
when the person who asked holds their permission — read when it runs, not
when it was asked: someone who left the workspace meanwhile, their run
fails. Reading runs takes `intention:read`; cancelling one, being who asked
it or holding `intention:approve`. [agent-runtime.md](agent-runtime.md).

## Workflows (LEKA-397)

Running a workflow (`POST /workflow-runs`) takes `intention:create` and the
workflow's own permission; **each step's capability is checked for the
person when the step runs** — one their role may not use fails the step.
Reading takes `intention:read`; cancelling or retrying a run, being who
asked it or holding `intention:approve`. [workflows.md](workflows.md).

## Routage (LEKA-398)

An intention's routing (`GET /intentions/{id}/routing`) takes
`intention:read`; routing it again, `intention:create`; words routed alone
(`POST /capabilities/route`), `workspace:read`. **Routed for whoever asks**:
a capability their role may not use is excluded from their routing, said
why. [capability-router.md](capability-router.md).

## Modèle de langage (LEKA-394)

`GET /models` (what answers here, the providers one may bring) and
`GET /models/usage` (calls, tokens, cost) — any member. Bringing, changing,
testing or removing the workspace's own model (`PUT`, `DELETE
/models/settings`, `POST /models/settings/test`) takes `workspace:update`.
Its key is never sent back, to anyone: its last four characters are.
[model-gateway.md](model-gateway.md).

