# Pricing — LEKA CORE's plans, prices and AI capacity (LEKA-431, LEKA-446)

What LEKA CORE sells, at what price, and how the public pricing page
(`https://leka-core.com/tarifs.html`) shows it.

- **One source of truth**: [`api/leka/billing/catalogue.yaml`](../api/leka/billing/catalogue.yaml).
- **One reader**: `leka.billing`, which checks the catalogue when it reads it.
- **One public route**: `GET /api/v1/pricing`, which computes every price.

The page states no price of its own, and checkout will charge what the route says.

**Decided by the founder (LEKA-446, 12–13 October 2026)**, over anything older here or in LEKA-431:
- **no agent is included in a plan**: agents and bundles are bought apart, once available, tested and priced;
- **the AI capacity is the plan's and is never sold apart**: no pack, no top-up, no overage. At the limit, what is billable stops, and a higher plan is offered, to be chosen explicitly;
- **Growth has a 14-day trial, a card required**: when it ends, the subscription starts and the card is charged, unless cancelled before;
- subscriptions, and agents or bundles bought, **renew automatically until cancelled**, on the terms shown when bought; nothing new is ever bought or changed without the customer's explicit action.

**Provisional.** The AI-credit allowances below are launch hypotheses. They change once usage and cost metering
(**LEKA-430**) has measured real usage, through a
documented pricing decision. Existing customers keep what they bought, or
are told in advance. They are never shown as a cost-validated guarantee.

## 1. The plans

| | Free | Starter | Growth | Business | Enterprise |
| --- | --- | --- | --- | --- | --- |
| For | trying LEKA on a first scope | a small engineering team wanting a clear view of its systems | teams running their systems with LEKA every day | organisations with several teams and scopes | large organisations, their security requirements, their own model |
| List price, a month excl. VAT | €0 | €59 | **€179** — recommended | €599 | per contract |
| Launch offer, monthly billing (−20 %) | — | €47.20 for 12 months, then €59 | €143.20 for 12 months, then €179 | €479.20 for 12 months, then €599 | — |
| Billed yearly (−30 %) | — | €41.30 a month, €495.60 a year | €125.30 a month, €1,503.60 a year | €419.30 a month, €5,031.60 a year | — |
| AI credits a month | 200 *(provisional)* | 2,000 *(provisional)* | 10,000 *(provisional)* | 40,000 *(provisional)* | by contract |
| Trial | — | — | **14 days, card required** | — | — |
| Language model | managed by LEKA | managed by LEKA | managed by LEKA | managed by LEKA | managed by LEKA, **or the customer's own** |
| Agents (§ 1 bis) | **none runs** | bought alone or in bundles | idem | idem | idem |
| People · sources · standard analyses a month · alert rules · recurring workflows *(to validate)* | 1 · 3 · 10 · 0 · 0 | 1 · 5 · 100 · 5 · 0 | 5 · 15 · 500 · 20 · 10 | 15 · 30 · 2,000 · 100 · 50 | by contract |
| Extra AI capacity | **never sold apart**: a higher plan | idem | idem | idem | by contract |
| How to start | sign up | sign up | sign up | sign up | **book a meeting with the team**, or the enquiry form |

**Not decided yet, so not stated anywhere**:
- workspaces and integrations per plan;
- support levels.

The quotas above come from the pricing screen shared after the product call of 2026-10-14, and are marked `provisional` (to validate) in the catalogue.

## 1 bis. Agents and bundles (LEKA-454)

The subscription mock-up of 14 October rules (it replaces « no agent in a plan »). Every value is in `api/leka/billing/catalogue.yaml`, `provisional: true`, to validate. The inventory — every agent, its price, status, what includes it and the bundles — is generated from the sources: [billing/agents-inventory.md](billing/agents-inventory.md).

- **Fundamental agents are every plan's**: LEKA's own capabilities — understanding the request, its analysis, its answer (LEKA Assistant) — run on every plan, Free included, within its quotas.
- **A plan may include some of the registry's agents** (`included`, per plan and every plan above). None is yet: the mock-ups include none; to validate.
- **Every other agent is a specialised option**, monthly, renewed until cancelled, at its tier's price: Standard **€9**, Specialised **€15**, Expert **€25** HT. It runs from **Starter** (`plan_required` on Free), once its option is active (`not_owned` otherwise). The 13 agents of the registry are on sale, each with the name the marketplace reference gives it (Architect, Code Reviewer, Test Strategist…); `architecture-analysis` and `code-change` have no equivalent there, their tier LEKA's.
- **The reference's agents not built** (47) are never sold, never shown available (`not_for_sale`).
- **Bundles** are the reference's five, at its prices — Engineering €59, Ship Safe €79, Incident Response €89, Security & Reliability €69, Frontend Craft €29 — and its compositions. A bundle is **sold only once every agent it names is built**: none is today. Its saving is computed from its members' prices and shown only when every member has one (Engineering −35 %, Frontend Craft −40 %; the others name Migration Planner or Reliability Analyst, which the reference does not price). « Jusqu'à 27 % » is not shown.
- **Paid before owned**: an option is granted when Stripe says it is paid (`payment_status: paid`, or `checkout.session.async_payment_succeeded` for a payment still processing), kept while Stripe retries a failed renewal (`past_due`), ended when the subscription is cancelled or unpaid. **An option's events never touch the plan.**
- **Bought from an intention's decision**, the agents chosen there are launched once it is paid (`leka.intentions.agents.run_bought_launch`).
- **LEKA's team's workspaces** keep every agent for tests: `python -m leka.billing.cli grant-agents <workspace> --by NAME --reason WHY`, `--end` to take it back.

To arbitrate: the equivalences between the reference's names and the registry's agents (in the catalogue), « Deployment & Release » and « Motion & Animation » read as the reference's « … Analyst » and « … Specialist », and Migration Planner and Reliability Analyst, named by bundles but absent from the reference's list.

**LEAD by LEKA** is not on this page: its packaging (a separate product or a module of LEKA CORE) is to be confirmed first.

## 2. The rules the catalogue enforces

`leka/billing/catalogue.py` refuses a catalogue that breaks any of these rules, when it reads it:

- the five plans, in order: Free, Starter, Growth, Business, Enterprise;
- at most one plan recommended (Growth);
- a self-service plan has a price;
- Enterprise is priced per contract and never self-service;
- connecting one's own model is **Enterprise only**;
- a discount needs a price to apply to;
- the launch offer applies to **monthly billing only**: it never stacks with the annual discount;
- a trial only on a plan bought online;
- **no automatic overage**: `automatic_overage` can only be `false`, and `capacity` holds nothing else — no pack can be added.

**What a plan costs** is computed by `quote(plan, interval)`, in whole cents, each unit price rounded half up. The page and checkout read the same figure.

| Interval | Discount | Charged |
| --- | --- | --- |
| month | the launch offer, **20 % for 12 months**, when the plan has it, the offer is open (`ends_on`) and the customer is eligible | the discounted price each month for 12 months, then the list price |
| month | none (not eligible, or the offer closed) | the list price |
| year | **30 %**, never the launch offer as well | 12 × the discounted monthly price, once a year |

**With Growth's trial** (`trial_days: 14`), the quote also says `trial_days` and `first_charge_on`: the day `charged` is first charged — today + 14 days — unless cancelled before. A workspace that has subscribed once gets no trial: charged the day it buys.

## 3. AI capacity

- **Credits are a capacity unit, not tokens.** How much an operation uses is metering's job (LEKA-430), from what it measures. Not every run costs the same.
- **The customer sees** what has been used, what is left, and a warning before the limit (LEKA-430).
- **At the included limit**, billable usage pauses until the next month, or until the customer **explicitly** moves to a higher plan. LEKA never charges automatically beyond the limit.
- **The capacity is never sold apart** (LEKA-446): no pack, no top-up — in the catalogue, the API (no route), Stripe (no product) and the page. An intention past its credits is offered the cheapest plan that is enough (`leka/intentions/feasibility.py`), never a pack.

## 4. The pricing page

`web/public/tarifs.html`, `tarifs.css` and `tarifs.js` are LEKA's own, on the site's design system and shell (header, footer, languages).

**What it shows**:
- the five plans, Growth highlighted as recommended;
- a monthly/yearly selector that shows the 30 %;
- the launch offer and its terms;
- AI capacity, Growth's trial and its terms, the agents (none included) and the own-model option, in plain words;
- prices excluding VAT;
- a note that the credits are launch values.

**Internal token costs never appear.**

**Calls to action**:

| Plan | Call to action | Where it goes |
| --- | --- | --- |
| Self-service | « Commencer » (Free: « Commencer gratuitement ») | sign-up, with `?plan&interval`; paying is then done from Facturation (§ 7) |
| Enterprise, `LEKA_SALES_BOOKING_URL` set | « Réserver un rendez-vous avec notre équipe » | the booking page (Calendly or equivalent), in a new tab, with « ou nous écrire » beside it |
| Enterprise, `LEKA_SALES_BOOKING_URL` not set | « Nous contacter » | the enquiry form (`LEKA_SALES_CONTACT_URL`, by default `demo.html?type=enterprise`). No booking address is ever guessed |

**States**:
- loading: « Chargement des tarifs… »;
- error: the page says so and offers the contact form.

**Accessibility and layout**:
- the interval selector is a radio group, with the arrow keys;
- cards are articles with headings;
- `aria-busy` is set while loading;
- the grid is responsive: 5 columns, then 3, 2, 1.

**Languages**:
- French by default, English through the site's switcher (`i18n.js`).
- A plan's words come from the catalogue (`fr`, `en`).
- Other languages fall back to French for the page's own text and English for the plans.

**Analytics** (`POST /api/v1/pricing/events`, kept in `site_events`):
- **Events**: `page_viewed`, `interval_selected`, `plan_selected`, `cta_clicked`, `enterprise_booking_clicked`, `enterprise_contact_clicked`.
- **What is kept**: the plan, the interval and the language. **Never** who, a workspace or an address.
- **Limits**: anonymous, 60 a minute per address, quietly dropped beyond.
- **Reading them**: `leka.billing.counts(session, since=…)`. There is no public reading route.

## 5. Changing a price, a discount, an allowance

1. Edit `catalogue.yaml`: amounts in cents, and `provisional: true` on a launch hypothesis.
2. `tests/test_pricing.py` holds the computed prices. Update them in the same pull request.
3. Deploy. The page follows, with nothing else to edit.

Enterprise's booking page: `LEKA_SALES_BOOKING_URL` in `production.env` (https), see [configuration.md](configuration.md).

## 6. Margin guardrails (internal, provisional)

**Target**: 80 % gross margin on subscription revenue excluding VAT, after variable service costs. It is a target, not a proven figure.

**Review thresholds**, per paid tier, once enough cost data exists:
- **review floor**: 70 % blended → review quotas, routing and pricing, without silently raising customer charges;
- **urgent review**: below 60 %.

**Variable cost ceilings** under the launch offer, at 80 %, before VAT:

| Plan | Net price | Ceiling, a month |
| --- | --- | --- |
| Starter | €47.20 | €9.44 |
| Growth | €143.20 | €28.64 |
| Business | €479.20 | €95.84 |

Free cannot reach a margin at €0. It is held by its 200-credit cap, abuse and rate limits, and its measured cost per active workspace (LEKA-430).

**The credits a month are metering's (LEKA-430), not the catalogue's.** They are `LEKA_PLAN_CREDITS` (200, 2,000, 10,000, 40,000), read by `GET /pricing`: what the page promises is what a workspace gets, and the two can never disagree (`tests/test_pricing.py`). Agreed with LEKA-430 on 2026-10-11.

**Against the ceilings above**, a credit being $0.01 of LEKA's model cost, a plan whose credits are all used costs at most: Starter $20, Growth $100, Business $400 a month — above each ceiling. Most workspaces will not use all their credits; the metering reports (`python -m leka.metering.cli report plans`) say how many do, and are where these values are revisited.

## 7. Paying: Stripe

Self-service plans are paid through **Stripe**, with no SDK:
`leka/billing/stripe.py` makes the REST calls and checks the signatures.

| | |
| --- | --- |
| **The catalogue in Stripe** | `python -m leka.billing.cli stripe-sync` creates what is missing (`leka/billing/sync.py`): each plan a product (`leka_core_<plan>`), each price a Stripe price found by its **lookup key** (`leka_core_<plan>_<interval>_<cents>`, e.g. `leka_core_growth_year_150360`), the launch offer a coupon (`leka_launch_20_12m`: 20 %, 12 months, on the plans' products), and the customer portal's settings. Prices are amounts excluding VAT (`tax_behavior: exclusive`). No price id is configured: a price changed in the catalogue is a new Stripe price, found by its new key. Run it once per environment, then after each catalogue change |
| **Checkout** | `POST /billing/checkout {plan, interval}` (`workspace:update`) opens Stripe Checkout for Starter, Growth or Business. It charges the price found by its key, so it charges what the page shows. The launch coupon is added **only** for monthly billing, while the offer is open, on a workspace that never subscribed. A year gets the annual discount alone, and no promotion codes are accepted. Growth, for a workspace that never subscribed, gets its trial: `trial_period_days: 14`, the card always taken (`payment_method_collection: always`), and a trial without a card ends rather than converts. A workspace already subscribed is sent to the portal (409) |
| **The portal** | `POST /billing/portal`: Stripe's customer portal, to change the card, see invoices, change plan or cancel |
| **The webhook** | `POST /billing/stripe/webhook`, public. It is believed only when its `Stripe-Signature` holds (HMAC-SHA256, 5 minutes of tolerance); otherwise it gets a 400. Each event is kept once by its id (`stripe_events`), so a repeated delivery changes nothing. When applying it fails, the event is not kept and Stripe delivers it again |

**What a verified event changes**:

| Event | Effect |
| --- | --- |
| `checkout.session.completed`, a subscription | Its subscription is read, and the workspace is put on its plan (`leka.governance.set_plan`, audited, with "stripe" as who) |
| `checkout.session.completed`, a one-time payment | Nothing: no AI capacity is sold. Ignored, kept as such |
| `customer.subscription.created/updated/deleted` | The plan as Stripe says it now: `active`, `trialing` and `past_due` keep it; `unpaid`, `canceled` and `incomplete_expired` go back to Free — a trial cancelled before its end too. An event older than the last one applied never undoes it |
| `invoice.paid`, `invoice.payment_failed` | Said on the account. A failed payment is shown on Facturation |
| `charge.refunded` | Kept. What a refund undoes is a person's decision |

The plan comes **only from a verified event**, never from the browser coming back from Checkout. Each month's included credits are the plan's (LEKA-430, `leka.governance.allowance`).

**The policy** (what the portal's settings make; the trial and renewals decided in LEKA-446):

| | |
| --- | --- |
| Upgrade, or any change of plan or interval | In the portal, immediate, **prorated**: the difference is charged now, or credited on the next invoice |
| Cancellation | At the **end of the period paid for**: the plan holds until then, then Free. No refund |
| Failed renewal | Stripe retries (its Smart Retries) while the subscription is `past_due`, and the plan holds. Once Stripe gives up (`unpaid` or `canceled`), the workspace goes back to Free |
| The launch offer | Once per workspace: a workspace that ever subscribed does not get it again |
| Growth's trial and the launch offer | Stripe counts the coupon's 12 months from the subscription's start, the trial inside them; its invoices fall on day 14, then each month — twelve of them inside the 12 months, the thirteenth at the list price: **12 paid months at −20 %**, as the offer says. Nothing to change |
| Growth's trial | Once per workspace, 14 days, a card required. At its end the subscription starts and the card is charged what was shown, unless cancelled before; cancelled before, nothing is charged and the workspace goes back to Free |
| Renewal | Automatic, until cancelled, at the terms shown when bought |
| Overage | Never. At the limit, runs pause until the next month or a higher plan (LEKA-430) |

**In Facturation** (`web/components/billing/subscription-section.tsx`):
- Without Stripe configured, the page says payment is not open.
- Otherwise, Starter, Growth and Business are shown at the pricing's prices: with the launch offer only while the workspace may take it, and yearly with the yearly total; for Growth, while the workspace may still have it, its trial — the first payment, its amount and day, then each period, and that cancelling before costs nothing. The credits are said to be a launch value. « Choisir … » opens Checkout, which says the same before the customer pays.
- Once subscribed, the page shows the plan, its renewal or end, a failed payment, and « Gérer l'abonnement » (the portal).
- Coming back from Stripe, it says what happened: the plan comes with Stripe's confirmation, and a cancelled checkout charged nothing.

**Invoices and VAT**: Stripe sends receipts and invoices, and the portal lists them. **Stripe Tax is not enabled**: prices are excluding VAT and no tax is added until Karim decides how VAT is charged (an EU B2B reverse charge…). Nothing here claims VAT compliance.

### Setting Stripe up (test, then live)

1. **Keys**: `LEKA_STRIPE_SECRET_KEY` (`sk_test_…`, then `sk_live_…`) in `production.env`, never in the repository and never in a browser.
2. **Catalogue**: `docker compose … exec api python -m leka.billing.cli stripe-sync`. It prints each price's key and id.
3. **Webhook**: in Stripe, Developers → Webhooks → Add endpoint:
   - URL: `https://api.leka-core.com/api/v1/billing/stripe/webhook`;
   - events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`, `charge.refunded`.
   - Settings → Billing → Subscriptions and emails: turn on the **reminder e-mail before a trial ends** (the trial notification), and the e-mails for failed payments.

   Then put its signing secret (`whsec_…`) in `LEKA_STRIPE_WEBHOOK_SECRET` and redeploy.
4. **Try it in test mode**, on Facturation:
   - card `4242 4242 4242 4242`, any future date, any CVC: the plan comes within seconds;
   - card `4000 0000 0000 0341`: the renewal fails;
   - Growth: trialing at once, nothing charged; advance the subscription's test clock past 14 days: charged, Growth still; cancel during the trial: Free, nothing charged;
   - cancel from the portal: Free at the period's end.
5. **Live**: once the account is verified, the VAT decided and the policy confirmed, follow the same steps with the live key and a live webhook (its own secret).

### Not yet

- **Agents and bundles**: not on sale until available, tested and priced with their margin shown.

- **Stripe Tax**: once the VAT treatment is decided.
