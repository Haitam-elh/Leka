# The application shell

The frame every authenticated screen sits in: the sidebar, the header, and
the container a page's content goes into. Built in LEKA-337 from the
mockups in `docs/product/mockups/`.

## What is where

```
web/
  app/
    (app)/layout.tsx        the shell + the session check, for every route inside
    (app)/…/page.tsx        one page per navigation entry
    (auth)/…                sign-in, register, recovery — deliberately outside the shell
  components/shell/
    app-shell.tsx           composes the three regions, owns the responsive state
    app-sidebar.tsx         logo, navigation tree, footer; which sections are open
    sidebar-section.tsx     a section: its name and sentence, its lines; on the rail, a menu
    sidebar-nav-item.tsx    one line: icon, label, badge, current-page mark
    app-header.tsx          search slot, notifications, account
    user-menu.tsx           the account, its menu, and the language
    workspace-switcher.tsx  the current workspace, and the ones to switch to
    page-container.tsx      PageContainer and PageHeader, used by every page
    shell-provider.tsx      who is signed in, asked once per visit
    skip-link.tsx           the first thing in the tab order
  config/routes.ts          every page: path, permission, parent, views (LEKA-338)
  config/navigation.ts      WHAT the sidebar shows, and in which section (LEKA-428)
  lib/navigation/tree.ts    reads it: what a person is offered, where they are
  lib/i18n/                 the words, in English and French
```

## Adding a page inside the shell

Create `web/app/(app)/<route>/page.tsx`. It gets the shell, the session
check and the layout for free:

```tsx
"use client";

import { PageContainer, PageHeader } from "@/components/shell/page-container";

export default function SourcesPage() {
  return (
    <PageContainer>
      <PageHeader
        title="Sources"
        subtitle="Where LEKA reads from."
        breadcrumb={[{ label: "Settings", href: "/settings" }, { label: "Sources" }]}
        actions={<Button>Add a source</Button>}
      />
      …
    </PageContainer>
  );
}
```

A page that must NOT have the shell — anything an anonymous visitor sees —
goes under `app/(auth)/` instead.

## The navigation (LEKA-428)

Three pillars — what a customer does with LEKA — each with the sentence that
says what it is for, and its pages under it; and Administration. À valider
sits with the intentions, Activité with the environment (2026-10-07); a
folded section shows what waits in it:

```
Mon Dashboard
Intentions            Dites à LEKA ce que vous voulez accomplir.
  Nouvelle intention · Mes intentions · À valider
Mon environnement     Le système vivant de votre entreprise.
  Vue globale · Applications · Infrastructure · Données · Dépendances
  · Équipes · Événements · Domaines · Qualité · Activité
Capacités             Votre équipe technologique à la demande.
  Capacités disponibles · Mes capacités · Configuration
Administration
  Sources · Sécurité & gouvernance · Équipe & accès · Facturation · Paramètres
```

Nothing technical at the top level — the knowledge graph, agents, skills are
how LEKA does it, and show through the pillars. `config/navigation.test.ts`
holds this: three pillars, no technical word, every page still reachable.

**Two files, two jobs.** `config/routes.ts` declares every PAGE: its path,
who may open it, its parent for the breadcrumb, its availability.
`config/navigation.ts` declares the SIDEBAR: groups, sections, and lines,
each line naming the route it opens (`routeId`). No route was added, renamed
or removed by the reorganisation; every page keeps its address.

**A view of a page is a line too.** "Applications" is `/environment?tab=applications`:
the line carries `query: { tab: "applications" }`, the page reads its tab from
the address (`environment-screen.tsx`, `useTab`) and writes it back when a tab
is clicked. A page lists the views it has in `views` (`ENVIRONMENT_VIEWS`,
`CAPABILITY_VIEWS`); the first is the address with no tab. The capabilities
catalogue is not built yet (LEKA-393 on): its lines open the placeholder, and
the catalogue will read `?tab=` when it is.

**Where you are** — `activeNav(pathname, search)` in `lib/navigation/tree.ts`:
the ONE line that is the current page, and its section. The page's own
line, the one whose view the address asks for when several open it; a detail
page marks the line of the page it belongs to (an entity's sheet marks
"Vue globale", a source marks "Sources"). `/intentions/new` marks
"Nouvelle intention", not "Mes intentions".

**Sections open and close.** A button with `aria-expanded` and
`aria-controls`; its lines are a list, `hidden` when closed. Intentions
starts open (`defaultOpen`), the others closed — closed, the whole
navigation holds on a 13-inch screen. The person's choices are remembered
in `localStorage` under `leka.sidebar.sections`. Arriving on a page opens
its section, without remembering it — leaving closes it again unless the
person opened it. The current line is scrolled into view.

**On the rail**, a section is its icon: a menu button (named, and "page
actuelle" when you are in it) whose menu holds the section's name, its
sentence and its pages — real links, the current one `aria-current`. The
menu is drawn inside the `<nav>` landmark, positioned `fixed`.

### Adding a line

1. The page: an entry in `web/config/routes.ts` (see "Adding a page" above;
   its permission is what hides the line from who may not open it).
2. The line: in `web/config/navigation.ts`, `leaf(id, labelKey, routeId)`
   in the section it belongs to — with `{ query: { tab } }` for a view, the
   view declared in the route's `views`; with `{ icon }` at the top level.
   `badgeKey` adds a counter; the count is handed to `AppShell` by
   `(app)/layout.tsx`.
3. The words: `web/lib/i18n/dictionaries.ts`, under `nav` (and `pillars` for a
   new section's sentence), in **both** languages. TypeScript fails the build
   if French is missing.

No component names a line, so nothing else changes: the sidebar, the rail's
menus and the palette (which names a section's line "Section › Line") all
draw from the tree.

## Breakpoints

| Width | Sidebar |
| --- | --- |
| ≥ 1280px | full, with labels; can be folded to the rail by hand |
| 1024–1279px | the rail (icons only) by default; can be unfolded by hand |
| < 1024px | off screen, in a drawer behind the header's menu button |

The choice is remembered in `localStorage` under `leka.sidebar.collapsed`;
with nothing stored, the viewport decides. The sidebar and the header never
scroll — the content does.

Below 1024px nothing breaks, but the product is not designed for a phone:
that is out of LEKA-337's scope.

## Accessibility, and what is checked

`<header>`, the sidebar's `<aside>`, `<nav aria-label="Navigation principale">`
and `<main id="main-content">` are real landmarks, each named from the
dictionary. The skip link is first in the tab order and moves focus
into `<main>`. The current line carries `aria-current="page"` — one line,
never two. The fold button and every section carry `aria-expanded` and
`aria-controls`. On the rail, labels stay in the accessibility tree and
appear as tooltips; a section's menu is in the navigation landmark. The
drawer traps focus, closes on Escape and gives focus back to the button that
opened it.

`components/shell/*.test.tsx` covers the navigation tree, the sections and
what is remembered of them, the current-page mark, the badge, the rail's
menus, the fold button and both account menus under the keyboard;
`lib/navigation/tree.test.ts` where you are and what you are offered;
`config/navigation.test.ts` the tree's invariants. `web/e2e/shell.spec.ts`
covers the three viewports, the drawer, the skip link and the language
switch in a real browser; `web/e2e/navigation.spec.ts` every page with its
line, the views by address, sections by mouse and keyboard, the rail's menu
and a member's sidebar; `web/e2e/accessibility.spec.ts` the sidebar with
every section open and a rail menu open. `app/design-tokens.test.ts`
reads the tokens out of globals.css and measures every text pair against
WCAG AA — three colours taken from the mockups failed it, and were darkened
by the least that passes.

The automated audit it once listed as a TODO exists since LEKA-343: axe,
WCAG 2.1 A/AA plus best practices, on every core screen and every state —
see [`system-states.md`](system-states.md#accessibility).

## Where the real data plugs in

- **The signed-in person** comes from `auth.me()` (LEKA-330) through
  `ShellProvider`. Components read `useCurrentUser()`, never the API.
- **Workspaces** come from the same call. `WorkspaceSwitcher` lists them and
  marks the active one; **switching is LEKA-331** — the workspace lives in
  the session and only the API may change it (architecture rule 3).
- **Badges and notification counts** are handed to `AppShell` as props by
  `(app)/layout.tsx`, read by `useNavBadges` (`web/lib/nav-badges.ts`)
  inside the providers. The one counted today: beside "À valider", the
  enrichment proposals (LEKA-380) and the conflicts between sources
  (LEKA-382) waiting, for who may approve. The
  notification count has no ticket yet: none is shown.
- **The global search and its ⌘K palette** are LEKA-338. The header takes a
  `search` slot; until then it shows an inert picture of a search field.
- **Loading, error and offline states** are LEKA-343's — see
  [`system-states.md`](system-states.md). The shell draws them while the
  session is checked, and offers "Réessayer" when it cannot be.
- **The design system** is LEKA-339 — see
  [`design-system.md`](design-system.md). The colours, widths and radii are
  CSS variables in `app/globals.css`, sampled from the mockups; no component
  in `components/shell/` writes a colour of its own.

## Language

English by default, French available from the account menu, remembered in
`localStorage` under `leka.locale`. A component asks for words with
`useDictionary()`; it never holds a literal.

This is a seam, not a library: when a screen needs plural forms, dates or
locale-prefixed URLs, `next-intl` replaces `lib/i18n/locale-provider.tsx`
and no component changes.
