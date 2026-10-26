# The application shell

The frame every authenticated screen sits in: a header across the top and
the container a page's content goes into — **no sidebar** (LEKA-455, then
LEKA-494). Built first in LEKA-337 with a sidebar; the sprint's mockups
replaced it with the header. What a screen looks like today is what this
frame and the page's own components render — read them, not this page's
history (2026-10-25: a designer drew the removed sidebar from an older
version of this document).

## What is where

```
web/
  app/
    (app)/layout.tsx        the shell + the session check, for every route inside
    (app)/…/page.tsx        one page per address
    (auth)/…                sign-in, register, recovery — deliberately outside the shell
  components/shell/
    app-shell.tsx           the header, then <main> — the content scrolls, the header does not
    app-header.tsx          the logo (the way home), the main pages, the running intentions,
                            the plan, the notifications, the workspace, who you are
    main-nav.tsx            the main pages: Accueil, Mon environnement, Agents, Historique;
                            the decisions waiting, beside the bell, only while one waits
    user-menu.tsx           the account, the pages of running the workspace, the language
    workspace-switcher.tsx  the current workspace, and the ones to switch to
    command-palette.tsx     ⌘K: every page, and what the company model knows
    page-container.tsx      PageContainer and PageHeader, used by every page
    shell-provider.tsx      who is signed in, asked once per visit
    skip-link.tsx           the first thing in the tab order
  config/routes.ts          every page: path, permission, parent, views (LEKA-338)
  config/navigation.ts      the tree of pages (LEKA-428): what ⌘K and the menus offer
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

## The navigation

**The header** (`main-nav.tsx`) holds the main pages — Accueil, Mon
environnement, Agents, Historique — for who may open them, the current one
marked `aria-current="page"`. **The profile menu** (`user-menu.tsx`) holds
the pages of running the workspace: sources, security, team, billing,
settings. **Every page** is one ⌘K away.

**Two files, two jobs.** `config/routes.ts` declares every PAGE: its path,
who may open it, its parent for the breadcrumb, its availability.
`config/navigation.ts` declares the TREE of pages (LEKA-428's three pillars
— Intentions, Mon environnement, Capacités — and Administration), each line
naming the route it opens (`routeId`): the palette names a line « Section ›
Line » from it. It is no longer drawn as a sidebar (LEKA-494).

### Adding a page to the navigation

1. The page: an entry in `web/config/routes.ts` (its permission is what
   hides it from who may not open it).
2. Its line in the tree: in `web/config/navigation.ts`, `leaf(id, labelKey,
   routeId)` in the section it belongs to — with `{ query: { tab } }` for a
   view declared in the route's `views`.
3. One of the main pages: an entry in `main-nav.tsx`'s `ENTRIES`; a page of
   running the workspace: the profile menu.
4. The words: `web/lib/i18n/dictionaries.ts`, in **both** languages.
   TypeScript fails the build if French is missing.

## Widths

The header holds on a 13-inch screen; below, its labels give way before
its actions. The header never scrolls — the content does.

## Accessibility, and what is checked

`<header>`, `<nav aria-label="Navigation principale">` and `<main
id="main-content">` are real landmarks, each named from the dictionary. The
skip link is first in the tab order and moves focus into `<main>`. The
current page carries `aria-current="page"` — one entry, never two. The menus
close on Escape and give focus back to the button that opened them.

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
