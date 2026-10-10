# Governance of consequential actions

LEKA-404. What LEKA proposes to do to a customer's systems is decided by
people ([intentions.md](intentions.md) § 13) and carried out only once
approved (§ 14). This is the governance around that: how risky an action
is and why, who must approve it, the exceptions a workspace grants, who
may approve for someone else, what happens to a decision left waiting, and
what is checked again before anything runs. Every rule is enforced by the
API; every change to them is kept.

Code: `api/leka/intentions/decisions.py` (the policy, the risk, the tally,
pure), `governance.py` (exceptions, delegations, escalation, the checks
before running, pure), `oversight.py` (`OversightService`: exceptions,
delegations, the trail, escalation), `approval.py` (`DecisionService`:
the policy applied when a decision opens and when a vote is cast),
`actions.py` (the checks before running), the routes in
`api/leka/api/decisions.py`.

---

## 1. The risk

Four levels: **low**, **medium**, **high**, **critical**. A decision's risk
is the analysis's ([intentions.md](intentions.md) § 12) — `medium` when it
cannot say — raised, never lowered, by:

| Raised by | To at least | Reason kept |
| --- | --- | --- |
| an action in production (`production`, `prod`, `prd`), when `production_raises` | medium | `production` |
| a rule that holds of one of its actions | the rule's `at_least` | `rule` with the rule's name, the action, its level |

LEKA starts every workspace with three rules:

| Rule | Holds of | At least |
| --- | --- | --- |
| `irreversible` | an action that cannot be undone (a migration) | high |
| `irreversible_in_production` | the same, in production | critical |
| `critical_target_in_production` | an action in production on something the company model says is critical (`attributes.criticality`) | high |

A workspace replaces them with its own (30 at most). A rule holds of an
action when every condition it states holds — a condition left empty holds
of anything:

| Condition | Holds when |
| --- | --- |
| `actions` | the action is one of these (`restart`, `migrate`…) |
| `environments` | it runs in one of these; `production` means any of its names |
| `target_types` | one of its targets is of one of these kinds (`database`, `service`…) |
| `target_criticality` | one of its targets is this critical (`critical`, `high`…) |
| `reversible` | it can (true) or cannot (false) be undone |

Every reason is kept with the decision (`governance.reasons`) and said on
its card: « L'analyse l'estime faible · Irréversible en production : au
moins critique ».

## 2. What each risk needs

| Risk | Approvals | The asker may approve | A role among the approvers | An approval holds | Escalated after |
| --- | --- | --- | --- | --- | --- |
| low | 1 | yes | — | until it runs | never |
| medium | 1 | yes | — | until it runs | 48 h |
| high | 2 | no | — | 72 h | 24 h |
| critical | 2 | no | an **owner** | 24 h | 4 h |

LEKA's defaults, kept in `workspace.settings.approval_policy` once a
workspace changes them (`PUT /decisions/policy`, `workspace:update`). What
a change does not say is kept; per risk, `null` means none (no role, never
expires, never escalated). Refused (422): an unknown risk; approvals out of
1–5; a riskier level needing fewer approvals than a safer one; a role other
than `admin` or `owner`; hours out of 1–720; a rule that cannot hold, two
rules of one name.

A policy kept before LEKA-404 knew three risks: read as it said, critical
needs at least what high does, and keeps the asker apart when high does.

A decision keeps what was required when it opened (`required_approvals`,
`separate_asker`, `required_role`, `governance.requirement`): a later change
does not move it. A modification reads its risk again under the policy it
was opened with.

## 3. Who approves

- **Distinct people**: one person's approvals count once.
- **Four eyes**: on the risks the policy keeps apart, the asker approves
  neither for themselves nor for someone else (`asker_may_not_approve`).
- **A role**: one approver must hold it, or a higher one (owner ≥ admin).
  Enough approvals without it, the decision waits for someone who does.
- **Who may approve at all**: `intention:approve` — an admin, an owner.

### Delegation

An approver lends their authority to another member of the workspace
(`POST /decisions/delegations`, `intention:approve`):

| | |
| --- | --- |
| to whom | a member of the workspace — never oneself |
| up to | a risk level: beyond it, the delegation gives nothing |
| for | a window, 90 days at most |
| why | said, kept |

The member votes with `on_behalf_of` — any verdict. Their vote counts as
the lender's approval, once, at the lender's role; it keeps both names, the
role and the delegation (`context.delegation_id`). Refused
(`no_delegation`, 403): no delegation from that person to the voter holds
now at this risk, or the lender may no longer approve. Revoked by who lent
it, or an admin; kept.

## 4. Exceptions

Granted by an admin (`POST /decisions/exceptions`, `workspace:update`),
each saying why, from when to when (90 days at most), on what — actions,
environments, things (none said: any):

| | |
| --- | --- |
| **Freeze** | what it covers cannot be approved — `approve` and `modify` refused (`frozen`, 409) — nor run while it holds; rejecting and asking for changes still may. A decision opened under it says so (`governance.frozen`) and is kept in the trail (`decision_frozen`). |
| **Waiver** | a standard change: what it covers is **approved in advance** in its grantor's name, as the decision opens — no one votes. It names its actions **and** environments, covers at most a **medium** risk, and only decisions whose every action it covers. The intention is moved by its grantor, the waiver said (`decision_waived`). |

A freeze wins over a waiver. A waiver holds only while its grantor may
still approve: their approval is what it gives. Revoked (`POST
/decisions/exceptions/{id}/revoke`), an exception no longer holds; it is
kept, with who revoked it.

## 5. Escalation

A decision still waiting past its requirement's hours (`escalate_at`) is
escalated — once: `escalated_at` set, `decision_escalated` kept, its asker
and the workspace's owners told by email. The `decisions-escalation` sweep
looks every 15 minutes ([background.md](background.md)). A decision its
intention left behind (cancelled, asked again) is not escalated.

## 6. Before anything runs

Starting a plan, and the sweep running scheduled ones, check — with the
checks of [intentions.md](intentions.md) § 14 — what the governance says
now:

| Check | Fails when |
| --- | --- |
| `not_frozen` | an active freeze covers one of its actions — checked again before each step is called |
| `approval_valid` | the approval is older than its requirement's hours (`valid_until`) |
| `policy_met` | its approvers still allowed, with their roles today, no longer meet what today's policy asks of its risk — a policy tightened since asks again |
| `waiver_holds` | (approved by a waiver) the waiver was revoked, or its grantor may no longer approve |

One failing, nothing runs (409, each failed check in `details`).

## 7. The trail

`governance_events` — append-only, the database refusing to change one;
only who acted is forgotten, with their account:

| Kind | |
| --- | --- |
| `policy_changed` | what changed, before and after |
| `exception_granted` · `exception_revoked` | its kind, scope, window, reason |
| `delegation_granted` · `delegation_revoked` | to whom, up to which risk, the window, why |
| `decision_frozen` · `decision_waived` · `decision_escalated` | the decision, its risk, the exception |

The votes themselves are kept with their decision
(`intention_decision_votes`, append-only too).

## 8. The API

| Route | |
| --- | --- |
| `GET /decisions/policy` · `PUT` | the policy; changed by `workspace:update` |
| `POST /decisions/policy/evaluate` `{action, environment?, targets?, risk?}` | what the policy says of it now: risk, reasons, requirement, frozen, waived — nothing kept |
| `GET /decisions/exceptions` · `POST` · `POST …/{id}/revoke` | freezes and waivers; granted and revoked by `workspace:update` |
| `GET /decisions/delegations` · `POST` · `POST …/{id}/revoke` | lent by `intention:approve`; revoked by the lender or an admin |
| `GET /decisions/governance-history?limit` | the trail, the latest first |
| `POST /intentions/{id}/decision/{verdict}` `{…, on_behalf_of?}` | a vote — one's own (`intention:approve`), or lent |

Reading needs `intention:read`. A decision says its governance
(`governance`: reasons, required role, hours, escalation, validity, frozen,
waived); a vote, `on_behalf_of` and `role`.

## 9. In the app

- **Sécurité & gouvernance › Approbations**: the policy per risk (approvals,
  four eyes, role, validity, escalation) and its rules, an action simulated,
  the freezes and waivers, the delegations, the journal. Admins change;
  approvers lend; the page is the administrators' (`access:read`).
- **A decision's card** (À valider, an intention's page): why its risk, the
  role it needs, a freeze or waiver that covered it, escalated or when it
  will be, how long its approval holds, each vote's « au nom de ». A member
  an approver lent their authority to votes there, in that approver's name.

## 10. Tested

- `tests/test_governance_policy.py`, pure: the risk and every reason; a
  workspace's rules; an owner awaited on a critical decision; a delegated
  vote counted once for its authority, never the asker's; a delegation's
  window, risk, person; exceptions granted only as they may be; a freeze
  stopping what it covers and winning over a waiver; a waiver approving only
  what it wholly covers, while its grantor is there; escalation once; the
  checks before running.
- `tests/test_intention_decisions.py`: the defaults, a policy kept before
  LEKA-404, refusals.
- `tests/test_governance_api.py`, on Acme's model: the policy configured,
  evaluated and every change kept; something critical in production making
  a restart high; a migration in production critical — two admins wait for
  the owner; a member voting for an admin, beyond the risk refused, revoked
  refused; a freeze refusing approval then execution; a waiver approving a
  restart in advance, which runs, and no longer runs once revoked; an
  expired approval and a tightened policy stopping execution; escalation
  once, asker and owner told; the trail append-only, a deleted person
  forgotten.
- Web: `approval-governance.test.tsx` (the tab: policy, rules, simulation,
  exceptions, delegations, journal, read-only), `decision-governance.test.tsx`
  (the card: reasons, role, freeze, escalation, a lent vote).

## Not yet

- **Approver groups**: a requirement names a role; naming a team (« the
  payments team's leads ») comes with teams in permissions.
- **An escalation chain**: one escalation, to the owners; levels and an
  on-call rotation come with notifications in the app.
- **A change-advisory tool**: a decision opened in ServiceNow or Jira and
  decided there.
- **Simulating on things**: the API evaluates an action on things of the
  model (`targets`); the tab simulates without them.
