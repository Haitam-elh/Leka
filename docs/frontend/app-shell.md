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
    app-sidebar.tsx         logo, navigation, footer
    sidebar-nav-item.tsx    one entry: icon, label, badge, current-page mark
    app-header.tsx          search slot, notifications, account
    user-menu.tsx           the account, its menu, and the language
    workspace-switcher.tsx  the current workspace, and the ones to switch to
    page-container.tsx      PageContainer and PageHeader, used by every page
    shell-provider.tsx      who is signed in, asked once per visit
    skip-link.tsx           the first thing in the tab order
  config/navigation.ts      WHAT the sidebar shows — the only file LEKA-338 needs
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

## Adding an entry to the navigation

Two files, and nothing else:

1. `web/config/navigation.ts` — add an entry with its `id`, its `labelKey`,
   its `href` and a lucide `icon`. `badgeKey` adds a counter; the count is
   handed to `AppShell` by `(app)/layout.tsx`.
2. `web/lib/i18n/dictionaries.ts` — add the label under `nav`, in **both**
   languages. TypeScript fails the build if French is missing.

No component names an entry, so nothing else has to change. The entry the
current URL belongs to is computed by `activeEntry()`, longest match first:
`/intentions/new` lights up "New intention", not "Intentions".

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
into `<main>`. The current entry carries `aria-current="page"` — one entry,
never two. The fold button carries `aria-expanded` and `aria-controls`. On
the rail, labels stay in the accessibility tree and appear as tooltips. The
drawer traps focus, closes on Escape and gives focus back to the button that
opened it.

`components/shell/*.test.tsx` covers the config-driven navigation, the
current-page mark, the badge, the fold button and both menus under the
keyboard. `web/e2e/shell.spec.ts` covers the three viewports, the drawer, the
skip link and the language switch in a real browser. `app/design-tokens.test.ts`
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
  `(app)/layout.tsx`, where they are currently mocked. The features that
  produce them own them: LEKA-338 and after.
- **The global search and its ⌘K palette** are LEKA-338. The header takes a
  `search` slot; until then it shows an inert picture of a search field.
- **Loading, error and offline states** are LEKA-343's — see
  [`system-states.md`](system-states.md). The shell draws them while the
  session is checked, and offers "Réessayer" when it cannot be.
- **The design system** is LEKA-339. The colours, widths and radii are CSS
  variables in `app/globals.css`, sampled from the mockups; no component in
  `components/shell/` writes a colour of its own.

## Language

English by default, French available from the account menu, remembered in
`localStorage` under `leka.locale`. A component asks for words with
`useDictionary()`; it never holds a literal.

This is a seam, not a library: when a screen needs plural forms, dates or
locale-prefixed URLs, `next-intl` replaces `lib/i18n/locale-provider.tsx`
and no component changes.
