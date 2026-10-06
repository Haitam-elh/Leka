# Information architecture

Where every page of LEKA lives, who may open it, how the sidebar groups
them, and the rules that decide what the interface does when a person may
not open one. Built in LEKA-338 on the shell from LEKA-337; the sidebar
reorganised into three pillars by LEKA-428.

**Two files are the source of truth**, not this document:

- `web/config/routes.ts` — every PAGE: its path, its permission, its parent,
  its availability, the views it opens in. The breadcrumb, the browser tab
  title and each page's default title are generated from it. A route that is
  not in it does not exist as far as navigation is concerned.
- `web/config/navigation.ts` — the SIDEBAR: groups, sections and lines, each
  line naming the route it opens. The sidebar, its rail menus and the
  command palette are drawn from it.

No component anywhere names a label or spells out a URL.

## The sidebar

```
Vue d'ensemble                                   /overview
─────────────────────────────────────────────────────────────────────────
Intentions            Dites à LEKA ce que vous voulez accomplir.
  Nouvelle intention                             /intentions/new
  Mes intentions                                 /intentions
Mon environnement     Le système vivant de votre entreprise.
  Vue globale                                    /environment
  Applications                                   /environment?tab=applications
  Infrastructure                                 /environment?tab=infrastructure
  Données                                        /environment?tab=data
  Dépendances                                    /environment?tab=dependencies
  Équipes                                        /environment?tab=organisation
  Événements                                     /environment?tab=events
  Domaines                                       /environment?tab=domains
  Qualité                                        /environment?tab=quality
Capacités             Votre équipe technologique à la demande.
  Capacités disponibles                          /capabilities
  Mes capacités                                  /capabilities?tab=mine
  Configuration                                  /capabilities?tab=configuration
─────────────────────────────────────────────────────────────────────────
Activité                                         /activity
À valider                                        /approvals   with a count beside it: the
                                                              proposals (LEKA-380) and the
                                                              conflicts (LEKA-382) waiting
─────────────────────────────────────────────────────────────────────────
Administration
  Sources                                        /sources
  Sécurité & gouvernance                         /governance
  Équipe & accès                                 /team
  Facturation                                    /billing
  Paramètres                                     /settings
```

Three pillars — what a customer does with LEKA — each with the sentence that
says what it is for. Activité and À valider sit apart, across all three:
what happened, and what waits on someone. Administration is about running
LEKA rather than using it.

## The site map

Every page, including those the sidebar does not list:

```
/overview                                  the way home
/intentions/new                            the composer
/intentions                                the list
│   └── /intentions/:id                    overview · analysis · evidence · actions · history
/environment                               "Mon environnement", its view in ?tab=
│   ├── /environment/graph                 the detailed map
│   └── /environment/:type/:id             overview · metrics · dependencies · incidents
│                                          deployments · logs · configuration · documentation · context
/capabilities                              the page says "bientôt" until LEKA-393
│   └── /capabilities/:id
/activity
/approvals
│   └── /approvals/:id
/sources
│   └── /sources/:id
/governance                                the page says "included in a higher plan"
/team
/billing
/settings
/welcome                                   a new workspace's first steps, reached from the
                                           workspace gate rather than the sidebar

/(anything else)                           the "introuvable" state, inside the shell
```

`/` redirects to `/overview`: every zone has a named path, so the registry
has no entry that is "the one without a path of its own".

## The routes

| Sidebar | Route | Permission | Availability |
| --- | --- | --- | --- |
| Vue d'ensemble | `/overview` | `workspace:read` | available |
| Intentions › Nouvelle intention | `/intentions/new` | `intention:create` | available |
| Intentions › Mes intentions | `/intentions`, `/intentions/:id` | `intention:read` | available |
| Mon environnement › its 8 views | `/environment`, `/environment/graph`, `/environment/:type/:id` | `workspace:read` | available |
| Capacités › its 3 views | `/capabilities`, `/capabilities/:id` | `workspace:read` | **soon** |
| Activité | `/activity` | `workspace:read` | available |
| À valider | `/approvals`, `/approvals/:id` | `intention:approve` | available |
| Administration › Sources | `/sources`, `/sources/:id` | `source:read` | available |
| Administration › Sécurité & gouvernance | `/governance` | `workspace:update` | **plan-gated** |
| Administration › Équipe & accès | `/team` | `member:invite` | available |
| Administration › Facturation | `/billing` | `workspace:update` | available |
| Administration › Paramètres | `/settings` | `workspace:read` | available |
| — (workspace gate) | `/welcome` | `source:manage` | available |

Two of these are choices rather than facts, and Karim owns them: Capacités
is marked "bientôt" because its catalogue is LEKA-393 and after, and
Sécurité & gouvernance is marked as an upper-plan feature. Changing either is
one word in the registry.

Two more are decisions worth stating. There is no `billing:*` permission, so
paying for the workspace is treated as administering it — `workspace:update`,
which an admin has and a member does not. And approving is `intention:approve`,
which an admin has: a member who cannot approve is not shown the queue.

What a member sees, therefore: the three pillars whole, Activité, and in
Administration only Sources and Paramètres.

## The decisions

**A. The workspace is not in the URL.** Not `/w/acme/...`. This was already
settled by the architecture: *"The workspace never comes from a URL or a
request body. It is read from the session, server side"*
(`docs/architecture.md`, rule 3). The consequence is accepted deliberately: a
link shared between colleagues opens in the recipient's active workspace, and
if the entity does not exist there they see the "introuvable" state.

**B. "Nouvelle intention" is a line of its own, marked on the composer.**
First a navy button above the list; the second line of the flat list from
2026-09-25, at the product owner's request; since LEKA-428 (2026-10-05) the
first line of Intentions. Throughout, it marks itself as the current page on
`/intentions/new` — and « Mes intentions » does **not** — because they are
two different places to be.

**C. ~~The sidebar is one flat list, in the mockup's order~~** — superseded
on 2026-10-05 by E. From 2026-09-25 to LEKA-428 the sidebar was the twelve
entries of `docs/product/mockups/01`, in its order, with no group titles —
which replaced an earlier grouping under Travail, Connaissance and
Administration that the mockups never showed.

**D. The terminology is "Mon environnement".** The ticket and the backlog say
"Company"; the interface says "Mon environnement" everywhere, and `environment`
is the technical id. "Company" stays in Jira and in backend vocabulary.

**E. Three pillars** (LEKA-428, 2026-10-05). Twelve places in a list did not
say what LEKA is for. The sidebar now says it: Intentions, Mon
environnement, Capacités, each with its sentence, its pages under it. No
technical concept — knowledge graph, agents, skills — is a top-level item:
they are how LEKA does it, and show through the pillars.
`web/config/navigation.test.ts` holds this: exactly three pillars, no
technical word at the top level, every page still reachable.

**F. A view of a page is a line, by its query.** « Applications » is
`/environment?tab=applications`, not a page of its own: the eight views of
Mon environnement are one screen with tabs (LEKA-369), and an address like
`/environment/applications` would collide with an entity's sheet,
`/environment/:type/:id`. A route declares the views it has; the first is
the address with no tab. The Capacités views are declared ahead of the
catalogue, which will read them.

**G. Sections fold, Intentions open.** A person opens and closes sections,
and the choice is remembered on their browser. Intentions starts open — two
lines, the way to act — and the others closed: all open, Activité and
À valider fell below the fold of a 13-inch laptop. Arriving on a page opens
its section, without remembering it. The sidebar keeps the mockup's 224px:
240px truncated the figures of Mon environnement at 1440px.

## The rules

**Where you are.** Exactly one line is marked `aria-current="page"`, and its
section with it — whether the section is open or folded. A detail page marks
the line of the page it belongs to: `/environment/services/payment-api`
marks Vue globale, `/sources/github` marks Sources. On a page some lines open
in several views, the view the address asks for picks the line. The one
exception is the composer, above. Matching prefers a literal segment over a
parameter, which is why `/intentions/new` is the composer rather than an
intention whose id is "new".

**Tabs live in the URL.** `/intentions/42/evidence` and
`/environment?tab=domains` can be sent to a colleague, reloaded and opened in
a second tab; a tab kept in React state looks identical and does none of
that. Which tabs and views exist is declared by the route.

**Permissions: hide, or refuse.** What a role may never open is not offered —
in the sidebar or the palette — and a section left with nothing is not drawn,
because a list of links that refuse is a list nobody trusts. What is typed by
hand is refused in the shell, with a way out. **Neither is security.** Hiding
a link hides a link; the API checks the same permission and refuses whatever
the browser believes. Server-side authorisation is LEKA-402 and LEKA-403.

**Availability.** `soon` and `plan-gated` pages stay in the sidebar — an
entry that disappears teaches nothing — but drawn plainly, as the mockup
does: no "bientôt" pill, no padlock (revised 2026-09-25). The page behind
says what it is — not built yet, or in a higher plan — and offers the plans
when a plan is what is missing.

**The rail.** Between 1024 and 1279px, or folded by hand, the sidebar is its
icons. A section is one icon: its name and sentence on hover, its pages in a
menu on click. Below 1024px the full sidebar is a drawer.

**Search does not compete with intention.** The palette finds and goes. It
never answers. It offers the sidebar's lines — "Mon environnement ›
Applications" — and what the company model knows. A question typed into it —
"pourquoi l'API de paiement est lente ?" — is offered as an intention, which
is where LEKA actually answers. The header's search field is a button for the
same reason: a second place to type would become a second, worse way to ask.

**States.** Every dead end says what happened *and* what to do next: empty,
bientôt, plan, refusé, introuvable. Their visual design is LEKA-343; their
existence and wording are LEKA-338's.

## Adding a page

1. **The page** — `web/config/routes.ts`: an entry with its `id`, `path`,
   `labelKey`, `parentId`, `requiredPermission`, and its `views` if it opens
   in several.
2. **Its line**, if the sidebar offers it — `web/config/navigation.ts`: a
   line in the section it belongs to, naming the route (and a view, by its
   `query`); an icon only at the top level.
3. **The words** — `web/lib/i18n/dictionaries.ts`: the label under `nav` (a
   new section's sentence under `pillars`), in **both** languages.
   TypeScript fails the build if English is missing.
4. **The route** — `web/app/(app)/<path>/page.tsx`. It inherits the shell, the
   session check, the permission guard, the breadcrumb and the title.
5. **A link to it** — a helper in `routes`, never a string in a component.

The tests will tell you if you forget: an orphan `parentId`, a route with no
permission or a link helper pointing at a path the registry does not declare
fail `config/routes.test.ts`; a line opening an unknown route or a view its
page does not have, a page reachable from nowhere, a top-level line without
an icon or a missing translation fail `config/navigation.test.ts`.

How the sidebar is built — its components, states and accessibility — is
`docs/frontend/app-shell.md`.

## What is still mocked, and who owns it

| Mocked | Owner |
| --- | --- |
| The decisions on intentions in "À valider", and their part of its count — the enrichment proposals (LEKA-380) and the conflicts between sources (LEKA-382) are real | LEKA-390 |
| The notification dot | no ticket yet |
| The Capacités pages, and their three views | LEKA-393 and after |
| Switching workspace | LEKA-331 |
| "Demander l'accès" (disabled) | LEKA-402 |
| Entity names in the breadcrumb (the identifier, made readable) | LEKA-369 |

There is no decision log in `docs/` yet. When one exists, decisions A to G
belong in it; until then this document is where they are written down.
