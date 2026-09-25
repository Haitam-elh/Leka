# Information architecture

Where every page of LEKA lives, who may open it, and the rules that decide
what the interface does when they may not. Built in LEKA-338 on the shell
from LEKA-337.

**The registry is the source of truth**, not this document:
`web/config/routes.ts`. The sidebar, the breadcrumb, the browser tab title,
the command palette and each page's default title are generated from it. A
route that is not in it does not exist as far as navigation is concerned,
and no component anywhere names a label or spells out a URL.

## The site map

```
/overview                                  the way home
/intentions/new                            "Nouvelle intention", the second line
/intentions                                the list
│   └── /intentions/:id                    overview · analysis · evidence · actions · history
/environment                               the map — "Mon environnement"
│   └── /environment/:type/:id             overview · metrics · dependencies · incidents
│                                          deployments · logs · configuration · documentation
/activity
/approvals                                 with a count beside it
│   └── /approvals/:id
/capabilities                              the page says "bientôt" until LEKA-393
│   └── /capabilities/:id
/sources
│   └── /sources/:id
/governance                                the page says "included in a higher plan"
/team
/billing
/settings

/(anything else)                           the "introuvable" state, inside the shell
```

That is the sidebar, top to bottom, exactly as `docs/product/mockups/01`
draws it: one list, no group titles.

`/` redirects to `/overview`: every zone has a named path, so the registry
has no entry that is "the one without a path of its own".

## The routes

| Zone | Route | Permission | Availability |
| --- | --- | --- | --- |
| Vue d'ensemble | `/overview` | `workspace:read` | available |
| Nouvelle intention | `/intentions/new` | `intention:create` | available |
| Intentions | `/intentions`, `/intentions/:id` | `intention:read` | available |
| À valider | `/approvals`, `/approvals/:id` | `intention:approve` | available |
| Activité | `/activity` | `workspace:read` | available |
| Mon environnement | `/environment`, `/environment/:type/:id` | `workspace:read` | available |
| Sources | `/sources`, `/sources/:id` | `source:read` | available |
| Capacités | `/capabilities`, `/capabilities/:id` | `workspace:read` | **soon** |
| Sécurité & gouvernance | `/governance` | `workspace:update` | **plan-gated** |
| Équipe & accès | `/team` | `member:invite` | available |
| Facturation | `/billing` | `workspace:update` | available |
| Paramètres | `/settings` | `workspace:read` | available |

Two of these are choices rather than facts, and Karim owns them: Capacités
is marked "bientôt" because its catalogue is LEKA-393 and after, and
Sécurité & gouvernance is marked as an upper-plan feature. Changing either is
one word in the registry.

Two more are decisions worth stating. There is no `billing:*` permission, so
paying for the workspace is treated as administering it — `workspace:update`,
which an admin has and a member does not. And approving is `intention:approve`,
which an admin has: a member who cannot approve is not shown the queue.

## The four decisions this ticket made

**A. The workspace is not in the URL.** Not `/w/acme/...`. This was already
settled by the architecture: *"The workspace never comes from a URL or a
request body. It is read from the session, server side"*
(`docs/architecture.md`, rule 3). The consequence is accepted deliberately: a
link shared between colleagues opens in the recipient's active workspace, and
if the entity does not exist there they see the "introuvable" state.

**B. "Nouvelle intention" is the second line of the list** — revised on
2026-09-25, at the product owner's request, to match the mockups exactly. It
was first a navy button above the list, on the argument that it is the one
thing to *do* among places to *look*. It still marks itself as the current
page on `/intentions/new` — and `/intentions` does **not** — because they are
two different places to be. On the rail it folds to a `+` that keeps its name.

**C. The sidebar is one flat list, in the mockup's order** — revised the same
day, for the same reason. It was grouped under Travail, Connaissance and
Administration, titles the mockups never showed. The order is the mockup's:
Vue d'ensemble, Nouvelle intention, Intentions, Mon environnement, Activité,
À valider, Capacités, Sources, Sécurité & gouvernance, Équipe & accès,
Facturation, Paramètres. `web/components/shell/app-sidebar.test.tsx` holds
that list word for word.

**D. The terminology is "Mon environnement".** The ticket and the backlog say
"Company"; the interface says "Mon environnement" everywhere, and `environment`
is the technical id. "Company" stays in Jira and in backend vocabulary.

## The rules

**Where you are.** Exactly one entry is marked `aria-current="page"`. A detail
page marks the list it belongs to — `/environment/services/payment-api` marks
Mon environnement — so the sidebar answers "where am I" and never "nowhere".
The one exception is the composer, above. Matching prefers a literal segment
over a parameter, which is why `/intentions/new` is the composer rather than
an intention whose id is "new".

**Tabs live in the URL.** `/intentions/42/evidence` can be sent to a
colleague, reloaded and opened in a second tab; a tab kept in React state
looks identical and does none of that. Which tabs exist is declared by the
route.

**Permissions: hide, or refuse.** What a role may never open is not offered —
in the sidebar or the palette — because a list of links that refuse is a list
nobody trusts. What is typed by hand is refused in the shell, with a way out.
**Neither is security.** Hiding a link hides a link; the API checks the same
permission and refuses whatever the browser believes. Server-side
authorisation is LEKA-402 and LEKA-403.

**Availability.** `soon` and `plan-gated` pages stay in the list — an entry
that disappears teaches nothing — but the list itself draws them plainly, as
the mockup does: no "bientôt" pill, no padlock (revised 2026-09-25). The page
behind says what it is — not built yet, or in a higher plan — and offers the
plans when a plan is what is missing.

**Search does not compete with intention.** The palette finds and goes. It
never answers. A question typed into it — "pourquoi l'API de paiement est
lente ?" — is offered as an intention, which is where LEKA actually answers.
The header's search field is a button for the same reason: a second place to
type would become a second, worse way to ask.

**States.** Every dead end says what happened *and* what to do next: empty,
bientôt, plan, refusé, introuvable. Their visual design is LEKA-343; their
existence and wording are this ticket's.

## Adding a page

1. **The registry** — `web/config/routes.ts`: an entry with its `id`, `path`,
   `labelKey`, `parentId`, `requiredPermission` and, if it belongs in the
   sidebar, an `icon` — placed in the list where the mockup puts it, since
   the sidebar follows the registry's order.
2. **The words** — `web/lib/i18n/dictionaries.ts`: the label under `nav`, in
   **both** languages. TypeScript fails the build if English is missing, and
   `config/routes.test.ts` fails if a label key has no translation.
3. **The route** — `web/app/(app)/<path>/page.tsx`. It inherits the shell, the
   session check, the permission guard, the breadcrumb and the title.
4. **A link to it** — a helper in `routes`, never a string in a component.

The tests will tell you if you forget: an orphan `parentId`, a sidebar entry
with no icon, a route with no permission and a link helper pointing at a path
the registry does not declare each fail `config/routes.test.ts`.

## What is still mocked, and who owns it

| Mocked | Owner |
| --- | --- |
| The count beside "À valider" | LEKA-390 |
| The notification dot | no ticket yet |
| Search results (the provider returns nothing) | Context Engine, LEKA-371 and after |
| Switching workspace | LEKA-331 |
| "Demander l'accès" (disabled) | LEKA-402 |
| Entity names in the breadcrumb (the identifier, made readable) | LEKA-369 |

There is no decision log in `docs/` yet. When one exists, decisions A to D
belong in it; until then this document is where they are written down.
