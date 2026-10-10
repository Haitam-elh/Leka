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
| AI credits a month | 100 *(provisional)* | 500 *(provisional)* | 2,000 *(provisional)* | 8,000 *(provisional)* | by contract |
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
| Self-service | « Commencer » (Free: « Commencer gratuitement ») | sign-up, with `?plan&interval`. Checkout comes with the Stripe integration (§ 7) |
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

Free cannot reach a margin at €0. It is held by its 100-credit cap, abuse and rate limits, and its measured cost per active workspace (LEKA-430).

## 7. Not yet

LEKA-431's next pull request: **Stripe**.

- **Checkout** for the self-service plans.
- **Verified, idempotent webhooks**: checkout completed; subscription created, updated or deleted; invoice paid or payment failed; refunds.
- **Entitlements**: the workspace's plan and its included credits, granted only after a verified event.
- **Capacity packs**: credited once after a verified payment.
- **The documented policy** for renewals, cancellations, failed payments, plan changes and proration.
- **Documentation**: the Stripe dashboard configuration, and the test-to-live rollout.

Until then, no checkout or purchase flow is shown. The credit ledger and its consumption are LEKA-430's.
