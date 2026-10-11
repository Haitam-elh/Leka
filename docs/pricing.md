# Pricing — LEKA CORE's plans, prices and AI capacity (LEKA-431)

What LEKA CORE sells, at what price, and how the public pricing page
(`https://leka-core.com/tarifs.html`) shows it.

- **One source of truth**: [`api/leka/billing/catalogue.yaml`](../api/leka/billing/catalogue.yaml).
- **One reader**: `leka.billing`, which checks the catalogue when it reads it.
- **One public route**: `GET /api/v1/pricing`, which computes every price.

The page states no price of its own, and checkout will charge what the route says.

**Provisional.** The AI-credit allowances below are launch hypotheses. They change once usage and cost metering
(**LEKA-430**) has measured real Architect and QA usage, through a
documented pricing decision. Existing customers keep what they bought, or
are told in advance. They are never shown as a cost-validated guarantee.

## 1. The plans

| | Free | Starter | Growth | Business | Enterprise |
| --- | --- | --- | --- | --- | --- |
| For | trying LEKA on a first scope | a small engineering team wanting a clear view of its systems | teams running their systems with LEKA every day | organisations with several teams and scopes | large organisations, their security requirements, their own model |
| List price, a month excl. VAT | €0 | €59 | **€179** — recommended | €599 | per contract |
| Launch offer, monthly billing | — | €41.30 for 12 months, then €59 | €125.30 for 12 months, then €179 | €419.30 for 12 months, then €599 | — |
| Billed yearly (−20 %) | — | €47.20 a month, €566.40 a year | €143.20 a month, €1,718.40 a year | €479.20 a month, €5,750.40 a year | — |
| AI credits a month | 200 *(provisional)* | 2,000 *(provisional)* | 10,000 *(provisional)* | 40,000 *(provisional)* | by contract |
| Core agents: Application Architect, QA (test analysis) | included | included | included | included | included |
| Language model | managed by LEKA | managed by LEKA | managed by LEKA | managed by LEKA | managed by LEKA, **or the customer's own** |
| Specialist agents (security review, incident investigation, infrastructure, code review, data, release, documentation, debugging, build fixer, architecture analysis) | add-ons, **not on sale yet** | add-ons | add-ons | add-ons | add-ons |
| Extra AI capacity, at any time | yes, once packs are set | yes | yes | yes | by contract |
| How to start | sign up | sign up | sign up | sign up | **book a meeting with the team**, or the enquiry form |

**Not decided yet, so not stated anywhere**:
- seats, sources, workspaces and integrations per plan;
- add-on and bundle prices;
- capacity-pack sizes and prices;
- support levels.

Each is added to the catalogue when decided, and the page shows it with nothing else to edit. The plans differ today by price, AI capacity, and the own-model option on Enterprise. They do not differ by any capability, because the product does not gate any by plan.

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
- **no automatic overage**: `automatic_overage` can only be `false`.

**What a plan costs** is computed by `quote(plan, interval)`, in whole cents, each unit price rounded half up. The page and checkout read the same figure.

| Interval | Discount | Charged |
| --- | --- | --- |
| month | the launch offer, **30 % for 12 months**, when the plan has it, the offer is open (`ends_on`) and the customer is eligible | the discounted price each month for 12 months, then the list price |
| month | none (not eligible, or the offer closed) | the list price |
| year | **20 %**, never the launch offer as well | 12 × the discounted monthly price, once a year |

## 3. AI capacity

- **Credits are a capacity unit, not tokens.** How much an operation uses is metering's job (LEKA-430), from what it measures. Not every run costs the same.
- **The customer sees** what has been used, what is left, and a warning before the limit (LEKA-430).
- **At the included limit**, billable usage pauses until the customer **explicitly** buys capacity or moves to a higher plan. LEKA never charges automatically beyond the limit.
- **Extra capacity can be bought at any time**, before the allowance runs out too, without changing plan.
- **Pack sizes, prices, eligibility and expiry** go in `capacity.packs`. The list is empty until they are decided from LEKA-430's data, and the page then says only that capacity can be added.

## 4. The pricing page

`web/public/tarifs.html`, `tarifs.css` and `tarifs.js` are LEKA's own, on the site's design system and shell (header, footer, languages).

**What it shows**:
- the five plans, Growth highlighted as recommended;
- a monthly/yearly selector that shows the 20 %;
- the launch offer and its terms;
- AI capacity, specialist add-ons and the own-model option, in plain words;
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
| Starter | €41.30 | €8.26 |
| Growth | €125.30 | €25.06 |
| Business | €419.30 | €83.86 |

Free cannot reach a margin at €0. It is held by its 200-credit cap, abuse and rate limits, and its measured cost per active workspace (LEKA-430).

**The credits a month are metering's (LEKA-430), not the catalogue's.** They are `LEKA_PLAN_CREDITS` (200, 2,000, 10,000, 40,000), read by `GET /pricing`: what the page promises is what a workspace gets, and the two can never disagree (`tests/test_pricing.py`). Agreed with LEKA-430 on 2026-10-11.

**Against the ceilings above**, a credit being $0.01 of LEKA's model cost, a plan whose credits are all used costs at most: Starter $20, Growth $100, Business $400 a month — above each ceiling. Most workspaces will not use all their credits; the metering reports (`python -m leka.metering.cli report plans`) say how many do, and are where these values are revisited.

## 7. Paying: Stripe

Self-service plans and capacity packs are paid through **Stripe**, with no SDK:
`leka/billing/stripe.py` makes the REST calls and checks the signatures.

| | |
| --- | --- |
| **The catalogue in Stripe** | `python -m leka.billing.cli stripe-sync` creates what is missing (`leka/billing/sync.py`): each plan a product (`leka_core_<plan>`), each price a Stripe price found by its **lookup key** (`leka_core_<plan>_<interval>_<cents>`, e.g. `leka_core_growth_year_171840`), the launch offer a coupon (`leka_launch_30_12m`: 30 %, 12 months, on the plans' products), capacity packs (`leka_core_pack_<key>_<cents>`), and the customer portal's settings. Prices are amounts excluding VAT (`tax_behavior: exclusive`). No price id is configured: a price changed in the catalogue is a new Stripe price, found by its new key. Run it once per environment, then after each catalogue change |
| **Checkout** | `POST /billing/checkout {plan, interval}` (`workspace:update`) opens Stripe Checkout for Starter, Growth or Business. It charges the price found by its key, so it charges what the page shows. The launch coupon is added **only** for monthly billing, while the offer is open, on a workspace that never subscribed. A year gets the annual discount alone, and no promotion codes are accepted. A workspace already subscribed is sent to the portal (409) |
| **AI capacity** | `POST /billing/capacity/checkout {pack}`, at any time and whatever the plan: a one-time Checkout. A pack not in the catalogue cannot be bought |
| **The portal** | `POST /billing/portal`: Stripe's customer portal, to change the card, see invoices, change plan or cancel |
| **The webhook** | `POST /billing/stripe/webhook`, public. It is believed only when its `Stripe-Signature` holds (HMAC-SHA256, 5 minutes of tolerance); otherwise it gets a 400. Each event is kept once by its id (`stripe_events`), so a repeated delivery changes nothing. When applying it fails, the event is not kept and Stripe delivers it again |

**What a verified event changes**:

| Event | Effect |
| --- | --- |
| `checkout.session.completed`, a subscription | Its subscription is read, and the workspace is put on its plan (`leka.governance.set_plan`, audited, with "stripe" as who) |
| `checkout.session.completed`, a paid pack | The pack's credits are added once (`add_pack`). The same payment told again, even under another event id, is never credited twice. Not paid yet: nothing |
| `customer.subscription.created/updated/deleted` | The plan as Stripe says it now: `active`, `trialing` and `past_due` keep it; `unpaid`, `canceled` and `incomplete_expired` go back to Free. An event older than the last one applied never undoes it |
| `invoice.paid`, `invoice.payment_failed` | Said on the account. A failed payment is shown on Facturation |
| `charge.refunded` | Kept. What a refund undoes is a person's decision |

The plan and its credits come **only from a verified event**, never from the browser coming back from Checkout. Each month's included credits are the plan's (LEKA-430, `leka.governance.allowance`).

**The policy** (to confirm with Karim; it is what the portal's settings make):

| | |
| --- | --- |
| Upgrade, or any change of plan or interval | In the portal, immediate, **prorated**: the difference is charged now, or credited on the next invoice |
| Cancellation | At the **end of the period paid for**: the plan holds until then, then Free. No refund |
| Failed renewal | Stripe retries (its Smart Retries) while the subscription is `past_due`, and the plan holds. Once Stripe gives up (`unpaid` or `canceled`), the workspace goes back to Free |
| The launch offer | Once per workspace: a workspace that ever subscribed does not get it again |
| Overage | Never. At the limit, runs pause until capacity is bought or the plan changes (LEKA-430) |

**In Facturation** (`web/components/billing/subscription-section.tsx`):
- Without Stripe configured, the page says payment is not open.
- Otherwise, Starter, Growth and Business are shown at the pricing's prices: with the launch offer only while the workspace may take it, and yearly with the yearly total. « Choisir … » opens Checkout.
- Once subscribed, the page shows the plan, its renewal or end, a failed payment, and « Gérer l'abonnement » (the portal).
- Coming back from Stripe, it says what happened: the plan comes with Stripe's confirmation, and a cancelled checkout charged nothing.

**Invoices and VAT**: Stripe sends receipts and invoices, and the portal lists them. **Stripe Tax is not enabled**: prices are excluding VAT and no tax is added until Karim decides how VAT is charged (an EU B2B reverse charge…). Nothing here claims VAT compliance.

### Setting Stripe up (test, then live)

1. **Keys**: `LEKA_STRIPE_SECRET_KEY` (`sk_test_…`, then `sk_live_…`) in `production.env`, never in the repository and never in a browser.
2. **Catalogue**: `docker compose … exec api python -m leka.billing.cli stripe-sync`. It prints each price's key and id.
3. **Webhook**: in Stripe, Developers → Webhooks → Add endpoint:
   - URL: `https://api.leka-core.com/api/v1/billing/stripe/webhook`;
   - events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`, `charge.refunded`.

   Then put its signing secret (`whsec_…`) in `LEKA_STRIPE_WEBHOOK_SECRET` and redeploy.
4. **Try it in test mode**, on Facturation:
   - card `4242 4242 4242 4242`, any future date, any CVC: the plan comes within seconds;
   - card `4000 0000 0000 0341`: the renewal fails;
   - cancel from the portal: Free at the period's end.
5. **Live**: once the account is verified, the VAT decided and the policy confirmed, follow the same steps with the live key and a live webhook (its own secret).

### Not yet

- **Capacity pack sizes and prices**: `capacity.packs` stays empty until LEKA-430's data decides them.
- **Specialist add-ons**: not on sale until available.
- **Stripe Tax**: once the VAT treatment is decided.
