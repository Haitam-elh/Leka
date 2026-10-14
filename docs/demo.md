# The demonstration (LEKA-449, LEKA-451)

Someone who has not connected their tools yet can see what LEKA does with
them: **Explorer la démo**, offered where a new workspace starts (`/welcome`)
and in the first steps of the overview while nothing is read.

## What it is

A workspace of the person's own, marked `workspaces.demo`, named « Nova
Retail (démo) ». Its four sources — GitHub, Jira, Datadog, Confluence — are
built as their connectors' kinds and read by the pipeline as a customer's
are, but answer from `api/leka/connectors/demo/world.py`: Nova Retail, a
fictive e-commerce company.

| Tool | What it holds |
| --- | --- |
| GitHub | `nova-retail/nova`: the storefront, checkout-api, catalog-api, a worker, PostgreSQL, Redis, Amazon S3 (from its compose files, as `components.py` reads them); three teams; five commits, three pull requests, two releases, three deployments; the issue #214 |
| Jira | the project NOVA: the incident NOVA-130, its cause NOVA-131, the stories and tasks before |
| Datadog | three monitors, the incident #42 open since yesterday, the deploy event, the service catalogue (owners, dependencies, application) |
| Confluence | the space ENG: the platform's architecture, checkout-api's runbook, who owns what |

The story they tell together: 3-D Secure v2 on the checkout (#212), released
in v2.14.0, deployed to production yesterday; refused payments up since —
the monitor alerts, the incident is open, its likely cause is the Stripe
retry #212 removed. Every date is said from now, so « this week » always
has something.

## What keeps it apart

- **Its own workspace.** Nothing of it is in anyone else's, nothing of
  anyone else's in it: workspace isolation, as for any customer.
- **No request leaves.** A demonstration's source is a `Replayed` connector
  (`leka.connectors.demo`): its `http()` refuses, whatever asks.
  `SourceService._build` builds one for every source of a `demo` workspace.
- **Nothing reaches a real system.** Governance refuses `DEMO_REFUSED` in
  it ([permissions.md](permissions.md)): no source added, no endpoint for
  its actions — so a plan's steps are carried out by a person, simulated —
  no model of its own, no payment, no invitation.
- **Its AI credits are its own**, as any workspace's: nothing asked in it is
  taken from the person's real workspace.

## How it is used

- `POST /api/v1/demo` — mine, made when I have none, and the session moved
  into it; `?fresh=true` erases the one before and makes a new one: a clean
  state. Answers `{workspace, created}`.
- Every page of it says so — « Environnement de démonstration » — with
  **Recommencer**, **Connecter mes outils** and **Quitter la démo** (to the
  person's own workspace) (`web/components/demo/demo.tsx`).

## Tested

`api/tests/test_demo.py`: opened, entered, opened again the same, made
afresh; its four sources read through every stage with the network
refusing; the company model holding Nova Retail's services, deployment and
incident, one each; « Qui est responsable de nova-checkout-api ? » answered
« Paiements »; a source, an invitation and a payment refused in it; Acme's
workspace holding none of it, another member unable to enter it.
`web/components/demo/demo.test.tsx`, `welcome-page.test.tsx`.

## Not yet

- A person's name is one entity per tool that names them differently
  (Jira's account, GitHub's login and address): « Léa Martin » may show
  twice, as it would for a customer.
- Whether the demonstration's questions count against a quota of its own
  is Karim's decision; today they use its own Free allowance.
