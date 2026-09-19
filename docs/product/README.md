# Product material

Reference material for LEKA. **Read-only for engineering** — this describes
what we are building, not how. The how lives in
[../architecture.md](../architecture.md).

| File | What it is |
| --- | --- |
| `LEKA-core.pdf` | the product specification |
| `Jira.csv` | the backlog export |
| `mockups/` | 16 screens, high fidelity |

## The screens

Numbered in the order a user meets them, not in the order they were drawn.

| # | File | Screen |
| --- | --- | --- |
| 01 | `01-vue-ensemble.jpeg` | Dashboard: environment health, recent activity, what awaits validation |
| 02 | `02-nouvelle-intention-1-decrire.jpeg` | New intention, step 1 — describe the need in natural language |
| 03 | `03-nouvelle-intention-2-analyse.jpg` | Step 2 — LEKA gathers context from the connected sources |
| 04 | `04-nouvelle-intention-3-resultats.jpg` | Step 3 — findings, main hypothesis, alternatives, confidence |
| 05 | `05-nouvelle-intention-4-decision.jpg` | Step 4 — proposed actions, selected by a human |
| 06 | `06-nouvelle-intention-5-action.jpg` | Step 5 — execution, step by step, with an audit log |
| 07 | `07-intentions-liste.jpg` | Every intention, its status and its impact |
| 08 | `08-mon-environnement-carte.jpg` | The map: users, applications, services, data, infrastructure |
| 09 | `09-fiche-service-payment-api.jpg` | One service in detail: metrics, dependencies, incidents, changes |
| 10 | `10-historique.jpg` | Timeline of everything that happened, analysed and contextualised |
| 11 | `11-a-valider.jpg` | The approval queue |
| 12 | `12-capacites.jpg` | The four capabilities: Understand, Build, Control, Act |
| 13 | `13-sources.jpg` | Connected systems and their sync state |
| 14 | `14-securite-gouvernance.jpg` | Compliance, access, policies, recommendations |
| 15 | `15-equipe-acces.jpg` | Members, roles, groups, access log |
| 16 | `16-facturation.jpg` | Subscription and invoices |

## What the mockups say that the foundation does not yet

Noted while indexing them, so nobody discovers these mid-ticket. None is a
defect in what exists — they are gaps between the foundation and the product.

- **Eighteen source kinds, not six.** Screen 13 shows "12 / 18": GitHub,
  Jira, Confluence, AWS, Azure, Google Cloud, Datadog, Slack, ServiceNow,
  Kubernetes, PostgreSQL, Figma, and more. Migration 001 declared six. This
  is exactly why `docs/adr/006-enum-storage.md` moved these lists off
  PostgreSQL ENUM types — that ADR is in an open pull request as this is
  written.
- **Seven roles, not three.** Screen 15 shows Administrateur, Tech Lead,
  Développeur, Ops, Security, Lecteur, Business. Migration 001 has
  `owner | admin | member`. **LEKA-330 decides the real list.**
- **Entity types the graph does not have.** Screen 08 organises the
  environment into users, applications, services, data and infrastructure.
  `application` is not an entity type today, and neither is `environment`
  (production / staging), which appears as a filter on several screens.
- **Billing is a module nobody has planned.** Screen 16 is a subscription and
  invoices page. It appears in no ADR and in no module of
  [../architecture.md](../architecture.md).
- **Capabilities are a product object, not only a code module.** Screen 12
  presents four capabilities — Understand, Build, Control, Act — each backed
  by agents, skills and workflows, with counts shown to the user. Today
  `leka.capabilities` loads agents; it has no notion of grouping them this
  way.
