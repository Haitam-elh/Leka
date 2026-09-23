# System states, responsive and accessibility

What a screen shows when it is not simply working — loading, empty, failed,
refused, offline — and how LEKA stays usable across the screen sizes and
assistive technologies it supports. LEKA-343.

For the frame these states sit in, see [`app-shell.md`](app-shell.md). For
forms, validation and confirmation, see
[`forms-and-interactions.md`](forms-and-interactions.md).

---

## The one rule

**Every state says what happened and what to do next.** A state that only
describes is a dead end: it sends the person back to the sidebar to guess.

The corollary: **the interface never shows an error's own message.** That
text is written for whoever debugs. The shell used to print "Cannot reach
the API at http://localhost:8000. Is it running?" to people who run
nothing, and the sign-in page did the same. The wording comes from what
*kind* of failure it was, never from what the error says.

---

## The states, and what draws each one

| State | Component | Where it lives |
|---|---|---|
| Loading | `LoadingState` (page or section), `Skeleton` | `components/states/`, `components/ui/skeleton.tsx` |
| Empty | `RouteState variant="empty"`, or `StatePanel` with the page's own words | `components/shell/route-state.tsx` |
| Error, whole page | `ErrorState` | `components/states/error-state.tsx` |
| Error, a form | `FormAlert`, inline field errors | LEKA-342 |
| Error, an async action | `notify.error` — stays until dismissed | `lib/notify.ts` |
| Success | `notify.success` — leaves after 5 s; `StatePanel tone="success"` for a page | `lib/notify.ts` |
| Disabled | the control, **plus the reason** (see below) | — |
| Permission | `RouteState variant="forbidden"` or `"plan-gated"`; the sidebar hides what cannot be opened | `components/shell/` |
| Offline | `OfflineBanner` in the shell; `ErrorState` words any failure as offline | `components/states/offline-banner.tsx` |
| Not found | `RouteState variant="not-found"` inside the shell; `app/not-found.tsx` outside it | — |

Every whole-area state is drawn by **`StatePanel`**: an icon, a title, what
to do, the way to do it, and optional small print. Same layout for "nothing
here", "not allowed" and "it broke", so they read as answers from one
product.

**See them all at `/_dev/states`** (development only; the folder is spelled
`%5Fdev` because Next leaves `_folders` out of routing).

---

## Errors: from the kind, never the message

`lib/errors.ts` sorts any failure into one of six kinds. Each has its own
next step, and `ErrorState` words it from the dictionary:

| Kind | When | Says | Offers |
|---|---|---|---|
| `offline` | the browser has no connection — **checked first** | check your connection | retries **on its own** when it returns |
| `unreachable` | the request never got an answer | the service is unreachable, nothing is lost | Try again |
| `server` | a 5xx | our side, not yours; quote the reference | Try again, reference |
| `forbidden` | a 403 | your role does not open this | back to the overview |
| `not-found` | a 404 | this address matches nothing | back to the overview |
| `unknown` | anything else, a crash included | could not be displayed | Try again, back to the overview |

Offline wins over whatever the error says. A request that failed offline
looks exactly like our API being down, and "our service is unreachable"
would send the person to wait for us instead of checking their connection.

The **reference** is the API's request id — or Next's `digest` for a crash —
printed as "Référence : …" so a support conversation can find the exact
request in the logs.

The sign-in screens word their errors the same way:
`authErrorMessage(t, error, online)` in `components/auth/form-message.tsx`
maps the API's codes to sentences and falls back on the kind.

### Where the boundaries are

| File | Catches |
|---|---|
| `components/shell/app-shell.tsx` | the session check failing: `ErrorState` with "Try again", which re-runs it |
| `app/(app)/error.tsx` | a page crashing while rendering. The frame stays; "Try again" re-renders only the page |
| `app/global-error.tsx` | the root layout itself failing. Renders its own `<html>`, in French — no provider survives |
| `app/(app)/[...unknown]` | an unknown address inside the application, with the frame kept |
| `app/not-found.tsx` | `notFound()` outside the shell |

---

## Loading

- **Nothing for the first 200 ms**, to the eye or to a screen reader. Most
  loads are faster; a skeleton that flashes, or "Chargement" read out for
  something already there, is noise.
- **A skeleton, not a spinner**: the shape of what is coming, so the page
  does not jump when it lands.
- While the shell is loading, `<main>` is `aria-busy`, so assistive
  technology waits instead of reading a half-drawn page.
- The live region is rendered empty and filled later: a region that appears
  already full is not reliably announced.
- A button that sends shows its own state ("Enregistrement…") and refuses a
  second press — LEKA-342.

## Disabled

**A disabled control says why.** A button that is greyed out with no reason
reads as broken. The reason is visible and tied to the control with
`aria-describedby`:

> the composer's send button, below ten characters — "Encore 4 caractère(s)
> pour pouvoir lancer", announced politely as it changes.

Prefer an enabled control that explains on use when the reason is long.
The one known exception is "Demander l'accès" on the forbidden state, inert
until LEKA-402 gives it somewhere to send the request.

## Offline

`OfflineBanner` sits first inside `<main>`, pinned to its top: above the
content rather than over it — what is on screen is still worth reading, it
just may be out of date — and inside a landmark. It says both halves:
"may no longer be up to date" and "nothing will be saved until the
connection is back". When the connection returns it says so for four
seconds and leaves.

`useOnlineStatus()` (`lib/use-online-status.ts`) is `navigator.onLine`,
which is **false only when certainly offline**. `true` is not a promise, so
a request that fails while it says true is classified by what the request
said.

## Headings

A state that **replaces** the page — not found, forbidden, a crash — titles
it with an `h1`; one that sits under a `PageHeader` uses an `h2`. Without
the `h1`, a screen reader user's first move, jumping to the page's title,
lands nowhere. `RouteState` and `ErrorState` take `headingLevel`; the
defaults follow this rule.

## Colour

Three tones, sampled from the status pills of the sources mockup and
darkened to the least that reads **AA** on their own soft background and on
white. `app/design-tokens.test.ts` measures every pair.

| Token | Value | Soft background |
|---|---|---|
| `--state-success` | `#157a3c` | `#e8f6ee` |
| `--state-warning` | `#a4510a` | `#fdf1e2` |
| `--state-danger` | `#c2272f` | `#fdecec` |

**Colour is never the only signal.** Every state has a word and an icon;
one person in twelve cannot tell the green from the red.

---

## Responsive

| Width | Status |
|---|---|
| 1024 – 1920 px | **supported**: laptop to large desktop |
| < 1024 px | usable, not designed for: the sidebar becomes a drawer (LEKA-337) |

`web/e2e/responsive.spec.ts` opens every core screen at 1024, 1280, 1440
and 1920 px and checks that nothing overflows, that the page has its `h1`
and that the primary control is on screen.

Overflow is not enough, and the defects this ticket found prove it: at
1024 px nothing overflowed, and yet the composer's "⌘↵ pour lancer" broke
over three lines and a panel link left its question mark alone on one. The
rule: **a toolbar wraps by groups, never by words** — `flex-wrap` on the
row, `whitespace-nowrap` on each group. The spec checks the composer's
hints stay on one line.

## Accessibility

### What a machine checks

`web/e2e/accessibility.spec.ts` runs **axe** — WCAG 2.1 A and AA, **plus
best practices** — on:

- every core screen: overview, new intention, the decision step, settings,
  a placeholder, a plan-gated page;
- every state that replaces one: not found, the API down, offline;
- the sign-in pages.

The best practices are what caught two of this ticket's defects: two
unnamed "complementary" regions on the new-intention screen, and a
not-found page with no `h1`. Neither fails WCAG alone; both make the first
move of a screen reader user — list the landmarks, jump to the title —
land nowhere.

### Landmarks

| Region | Element | Name |
|---|---|---|
| Sidebar | `<aside>` | Barre latérale |
| Main navigation | `<nav>` | Navigation principale |
| Breadcrumb | `<nav>` | Fil d'Ariane |
| Content | `<main id="main-content">` | — (the skip link targets it) |
| The new-intention side panel | `<aside>` | Contexte et périmètre |

Every name comes from the dictionary. The breadcrumb was "Breadcrumb",
hard-coded — the last English landmark in a French interface.

### What the keyboard covers

| Journey | Test |
|---|---|
| Skip link, sidebar, drawer, both menus | `e2e/shell.spec.ts`, `components/shell/menus.test.tsx` |
| ⌘K palette | `components/shell/command-palette.test.tsx`, `e2e/navigation.spec.ts` |
| Composer, fields, confirmations, leaving a dirty form | `e2e/forms.spec.ts`, `components/**/*.test.tsx` |
| Recovering from the API being down — Enter on "Réessayer" | `e2e/states.spec.ts` |

### What a machine cannot check

Whether the wording helps, whether the tab order makes sense on a new
screen, whether a live region says too much. Before a screen ships:

1. Tab through it without the mouse. Every control is reachable, in reading
   order, and shows its focus.
2. Provoke its failure — `page.route(…, route => route.abort())` — and read
   what it says. It must name a next step.
3. Cut the network (`context.setOffline(true)`). The banner appears; nothing
   on screen claims to have been saved.
4. Open it at 1024 px with the rail. Nothing wraps inside a word.

---

## Where things are still thin

- **The API's own messages are English.** The interface never shows them for
  a failure it can classify, but a validation message the API returns for a
  field (LEKA-342's `applyServerErrors`) is still quoted as written. Server
  side, that is LEKA-333's error contract.
- **"Demander l'accès" is inert** until LEKA-402.
- **No page fetches data yet** beyond the session: the placeholders have
  nothing to load. When a feature does, it uses `LoadingState size="section"`
  and `ErrorState size="section"` in the panel that waits, not the page.
- **The visual design of these states is LEKA-339's** to refine; the
  structure, the words and the behaviour are this ticket's.
