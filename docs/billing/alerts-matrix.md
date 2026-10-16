# Alerts matrix (LEKA-463)

What each CORE plan is alerted of, past which threshold, through which
channel, how often and to whom — as the code and its configuration do it
today. Every value comes from a configuration, never from this page:

- the plans' watch: `monitoring` of each plan in `api/leka/billing/catalogue.yaml`;
- the AI credits: `plan_credits`, `credit_warnings`, `credits_enforced` in
  `api/leka/core/settings/credits.py`;
- the schedules: `api/leka/background/schedule.py`;
- the plans' users and sources: `quotas` in the catalogue, enforced by the
  server (#288).

Only two channels exist: in LEKA (`in_app`) and e-mail (`email`). No other
channel (Slack, Teams, SMS, webhook) is offered as available.

## Plan × alert

| Alert | Free | Starter | Growth | Business | Enterprise |
|---|---|---|---|---|---|
| AI capacity — 80 % of the month's credits used | in LEKA + e-mail | in LEKA + e-mail | in LEKA + e-mail | in LEKA + e-mail | in LEKA + e-mail |
| AI capacity — 100 %: spent | in LEKA + e-mail; LEKA's analyses paused until the month ends, a plan with more capacity offered | same | same | same | same (contract) |
| Environment — a thing unavailable (severity high) or degraded (medium) | — (states seen on its screens, no alert) | in LEKA | in LEKA + e-mail | in LEKA + e-mail | in LEKA + e-mail (contract) |
| Environment — a source failing | — | in LEKA | in LEKA + e-mail | in LEKA + e-mail | in LEKA + e-mail |
| Users / sources beyond the plan (1/3, 1/5, 5/15, 15/30) | refused when adding, said why and the plan that holds more | same | same | same | contract |
| Custom alert rules (Starter 5, Growth 20, Business 100) | not built — **postponed by Karim (15/10)**: no rule can be created, none is counted or shown as available | | | | |

## Threshold × frequency × recipients

| Alert | Threshold | Evaluated | Frequency | Recipients |
|---|---|---|---|---|
| AI capacity | `credit_warnings` = 80, 100 (% of the month's allowance: plan credits + packs) | every quarter of an hour (`credit-watch`, :03 :18 :33 :48) | once per threshold per month (unique `workspace, period, threshold`); a new month starts again | e-mail: the workspace's owners and admins; in LEKA: every member who reads Mon environnement (`source:read`), each threshold dated |
| Environment | the Digital Twin's states: unavailable, degraded; a source in error | every quarter of an hour (`monitoring-sweep`, :14 :29 :44 :59), after the sources are read | one open alert per thing and family — seen again, its last sighting moves, never a second; e-mail once, when it opens | e-mail: owners and admins (Growth and above); in LEKA: every member (`source:read`) |

## How an alert is kept

- **Dated and explainable**: opened, last seen, resolved — the state's
  reason, the incident it rests on, the sources that said it; a capacity
  threshold with when it was passed and how much was used then.
- **Freshness**: an alert's certainty follows its data — confirmed by a
  record, suspected from a deduction, unverified while what it rests on is
  stale. Silence resolves nothing: only a fresh measured or declared signal
  does.
- **Idempotent**: unique open alert per thing and family; unique capacity
  warning per threshold and month — a watch run twice tells nothing twice.
- **Taken in hand** (acknowledged): by who manages the sources
  (`source:manage`), by whom and when, the first only. It stays open until
  the trouble ends. The public demo, read-only, cannot.
- **History**: the alerts ended in the last 7 days stay listed with what
  ended them; capacity thresholds stay for their month.
- **No overage**: capacity spent never bills anything; it stops LEKA's
  analyses (when `credits_enforced`) and offers a plan with more capacity.
  A capacity alert is never an agent purchase.

## Proofs (tests)

- Capacity: `api/tests/test_ai_credits.py` — each threshold told once to
  owners and admins, past it all the same day told once more, read back
  dated; `web/components/environment/twin.test.tsx` — thresholds and
  spent shown, the way to more capacity.
- Environment: `api/tests/test_monitoring_api.py` — Free never alerted;
  Growth alerted once, by e-mail once, resolved only by a signal; Starter in
  LEKA only; taken in hand once by an admin, refused to a member, another
  workspace's not found.
- Spent at the intention: `api/tests/test_intention_offer.py` — blocked,
  the next plan offered, never an overage.
- Users and sources: `api/tests/test_plan_limits.py`.
