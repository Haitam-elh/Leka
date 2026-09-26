# The design system

Colours, radii and the primitive catalogue every screen is built from.
Finished in LEKA-339 — the ticket
[`app-shell.md`](app-shell.md) and [`forms-and-interactions.md`](forms-and-interactions.md)
both defer their own colours and tokens to.

---

## Tokens

### Colour

Three families, each decided somewhere else and gathered here:

| Family | Tokens | Decided in |
|---|---|---|
| shadcn semantic | `--primary`, `--secondary`, `--muted`, `--accent`, `--destructive`, `--border`, `--input`, `--ring`, `--card`, `--popover`, … | shadcn's `base-nova` scaffold; `--primary` and `--ring` aliased to the brand in LEKA-339 |
| Brand & shell | `--brand-navy`, `--brand-violet`, `--brand-violet-soft`, `--shell-surface`, `--shell-page`, `--shell-canvas`, `--shell-line`, `--shell-muted`, `--shell-nav`, `--shell-nav-active`, `--shell-icon`, `--shell-badge`, `--shell-badge-foreground` | LEKA-337, sampled pixel-by-pixel from the mockups; re-measured 2026-09-25 against a screenshot of ours (page white, secondary text blue-grey, active entry deep indigo, icons a shade lighter than labels) — see [`app-shell.md`](app-shell.md) |
| System state | `--state-success[-soft]`, `--state-warning[-soft]`, `--state-danger[-soft]`, `--state-info[-soft]` | LEKA-343 — see [`system-states.md`](system-states.md); the info tone added for the overview and the knowledge components |

**Every one of them is measured, not chosen twice.** `web/app/design-tokens.test.ts`
reads each pair actually put on screen as text out of `globals.css` and
checks it against WCAG AA (4.5:1) — three values sampled from the mockups
failed on the first run and were darkened by the least that passes. Adding a
token that puts text on a background nobody has measured means adding a pair
to that file, not trusting the eye.

`--primary` and `--ring` alias `--brand-navy` / `--brand-violet` — one level
of `var()` indirection, which the test file's `token()` helper follows; more
than one level is what it exists to catch, not chase.

`.dark` exists in the stylesheet (shadcn's scaffold) but nothing toggles it —
the mockups describe no dark theme, and LEKA-339 chose not to invent one
twice. Treat every colour above as the only one that ships.

### Radius

```
--radius: 0.625rem
--radius-sm  = --radius * 0.6   (0.375rem)
--radius-md  = --radius * 0.8   (0.5rem)
--radius-lg  = --radius         (0.625rem)
--radius-xl  = --radius * 1.4
--radius-2xl = --radius * 1.8
--radius-3xl = --radius * 2.2
--radius-4xl = --radius * 2.6
```

One number, `--radius`, scales the whole set — change the product's
roundedness in one place, not per component. Tailwind's `rounded-*`
utilities read these directly; no primitive hardcodes a radius in pixels.

### Spacing

No custom spacing scale. Tailwind v4's default (`0.25rem` steps) is what
every primitive uses, and LEKA-339 did not invent a second one where the
first already covered it. The only spacing tokens that exist are
shell-specific, not general purpose — `--shell-sidebar-width`,
`--shell-sidebar-rail`, `--shell-header-height`, `--shell-content-max` — see
[`app-shell.md#breakpoints`](app-shell.md#breakpoints).

### Typography

Same story: no custom type scale. `--font-sans` is `next/font`'s Geist;
`--font-heading` currently aliases it too, since nothing in the mockups asked
for a second family. Every `text-*` size in the codebase is Tailwind's
default step. If a screen seems to need a size Tailwind doesn't have, that's
a reason to check the mockup again before adding one, not a token to reach
for.

### Icons

[`lucide-react`](https://lucide.dev), throughout — no second icon set. The
convention every primitive follows: `[&_svg:not([class*='size-'])]:size-4` on
the wrapper, so a consumer's own `className` on an icon overrides the
primitive's default size, and nothing sizes an icon by hand at the call
site.

### Borders

`--border` / `--input` for the two hairline colours; nothing else. A
primitive's own coloured border (an invalid field's `border-destructive`, a
success alert's `border-state-success/30`) always comes from a semantic
token above, never a one-off value.

---

## The primitive catalogue

Everything below lives in `web/components/ui/`, wraps a Base UI headless
primitive where one exists — keyboard handling, ARIA roles and focus
management are the primitive's, this layer is styling only, the same split
`tabs.tsx`'s top comment states in full — and is previewed at `/_dev/ui`
(`web/app/%5Fdev/ui/gallery.tsx`) alongside forms (`/_dev/forms`) and system
states (`/_dev/states`).

| Primitive | Variants / sizes | Notes |
|---|---|---|
| `Alert` | `default` · `destructive` · `success` | `role="alert"`. No `warning` variant — nothing calls for one yet; add it from `--state-warning` the day something does. |
| `AlertDialog` | size `default` · `sm` | Blocking confirmation — see [`forms-and-interactions.md#when-to-ask-before-doing`](forms-and-interactions.md#when-to-ask-before-doing) for when to reach for it over `Dialog`. |
| `Avatar` / `AvatarGroup` | size `sm` · `default` · `lg` | `AvatarBadge` overlays a status dot; `AvatarGroup` overlaps with `-space-x-2` and caps with `AvatarGroupCount`. |
| `Badge` | `default` · `secondary` · `destructive` · `outline` · `ghost` · `link` | Can `render` as an `<a>` — the `[a]:hover:` classes are for that case. |
| `Button` | `default` · `outline` · `secondary` · `ghost` · `destructive` · `link`; size `default` · `xs` · `sm` · `lg` · `icon` · `icon-xs` · `icon-sm` · `icon-lg` | The base every other interactive primitive's own button (dialog close, combobox trigger, pagination previous/next…) renders through — `focus-visible`, `disabled` and `aria-invalid` styling lives here once, inherited everywhere. |
| `Calendar` | — | Wraps `react-day-picker`; day cells render through `Button` and take real DOM focus one day at a time (`modifiers.focused`), not a ring on every cell at once. |
| `Card` | size `default` · `sm` | `CardHeader` / `CardTitle` / `CardDescription` / `CardAction` / `CardContent` / `CardFooter`. |
| `Checkbox` | — | `aria-invalid`, `disabled`, `focus-visible` all present; coordinates with `FormField`'s label wrapper (`group-has-[:focus-visible]/field-label:`) so the ring doesn't double up. |
| `Combobox` | — | Single or multi-select (`ComboboxChips`) with search; see [`forms-and-interactions.md`](forms-and-interactions.md) for the field wrapper built on it. |
| `Dialog` | — | Modal; `showCloseButton` defaults on. |
| `DropdownMenu` | item `default` · `destructive` | Checkbox and radio items included. Items highlight via `focus:bg-accent` — virtual focus, not a literal `focus-visible` ring, because DOM focus never actually leaves the trigger. |
| `InputGroup` | — | Composes `Input`/`Textarea` with `InputGroupAddon` / `InputGroupButton` / `InputGroupText` on either side. |
| `Input` / `Textarea` | — | `aria-invalid`, `disabled`, `focus-visible` on both. |
| `Label` | — | Not focusable itself; its `peer-disabled:` styling reacts to the control it labels, not to a state of its own. |
| `Pagination` | — | Presentational only, on purpose — LEKA's API is cursor-based (`{ data, next_cursor }`), not page-numbered. `PaginationPrevious` / `PaginationNext` are what a real list wires up; `PaginationLink`'s numbered items are for the rare fully-known small list, which is nothing in this app today. See the comment atop `pagination.tsx` and [`api.md`](../api.md). |
| `Popover` | — | |
| `RadioGroup` | — | Same focus/disabled/invalid treatment as `Checkbox`. |
| `Select` | size `default` · `sm` | Items highlight the same virtual-focus way as `DropdownMenu`'s. |
| `Separator` | orientation `horizontal` · `vertical` | |
| `Sheet` | side `top` · `right` · `bottom` · `left` | A `Dialog` that slides in from an edge instead of centring. |
| `Skeleton` | — | `animate-pulse` placeholder; sizing is the caller's job via `className`. |
| `Switch` | size `sm` · `default` | |
| `Table` | — | `Table` puts `overflow-x-auto` on a wrapper `<div>`, never on `<table>` itself — a table wider than its column scrolls in place instead of growing the page. `TableHead` carries `scope="col"`. |
| `Tabs` | — | Base UI's default manual-activation: arrows move focus, Enter/Space activates. See `tabs.test.tsx` for why that default was kept rather than overridden. |
| `Toast` / `Toaster` | type `success` · `info` · `warning` · `error` · `loading` (via `ToastIcon`) | `createToastManager()` / `useToastManager()` are exposed for anything that needs its own manager; most call sites use the default one exported as `toast`. |
| `Tooltip` | side `top` · `right` · `bottom` · `left` · `inline-start` · `inline-end` | |

---

## Variants and states: what was audited, and what changed

LEKA-339 audited every primitive above against `focus-visible`, `disabled`
and `aria-invalid`. The result was mostly confirmation, not correction:

- Every real form control already carried all three.
- Non-interactive primitives (`Alert`, `Avatar`, `Card`, `Separator`,
  `Skeleton`, `Table`) correctly have none of them — there is nothing on
  them to focus or disable.
- Overlay containers (`Dialog`, `Sheet`, `Popover`, `Tooltip`, `AlertDialog`)
  delegate to their trigger and close button, both of which already render
  through `Button`.
- Item lists with virtual/roving focus (`ComboboxItem`, `DropdownMenuItem`,
  `SelectItem`, a calendar day) highlight the active item with
  `data-highlighted` / `focus:` / a roving ring instead of a literal
  `focus-visible` ring — correct for that pattern, since DOM focus never
  actually leaves the input, or moves one cell at a time on the calendar.

The one concrete gap was on the variants axis, not the states one: `Alert`
had no positive-tone variant, so the one caller that needed a `success` look
(`FormMessage`, the auth success/error banner) had already hand-rolled it
from raw `--state-success` classes instead of a variant. `Alert` now has
`variant="success"`, built from the same tokens `StatePanel` and the offline
banner already use for that tone, and `FormMessage` reads it instead of
repeating it.

---

## The logo

Drawn by `components/brand/logo.tsx` and nowhere else — no screen holds a
logo file path or the logo's colours.

| | Use | File |
|---|---|---|
| `<Wordmark />` | "LEKΛ" where there is room: the sidebar, the sign-in pages | `public/brand/leka-wordmark.png` |
| `<Mark />` | the Λ alone, where there is not | inline SVG, same path as `public/brand/leka-mark.svg` |
| Tab icon | every browser | `app/icon.svg`, `app/favicon.ico` (16, 32, 48) |
| Home-screen icon | iOS | `app/apple-icon.png` (180 × 180, white tile) |

The originals are `docs/product/mockups/logoleka.jpeg` (the mark) and
`lekalogo2.jpeg` (the wordmark). The mark is redrawn as a vector from
them, so it is sharp at any size. The wordmark is the original with its
grey ground made transparent: clean on the light surfaces the product uses,
but a small, compressed JPEG underneath — **ask for the SVG original**
before it goes on a dark background, a slide or print.

The logo's colours (`#0a0f2b`, `#5037fb` → `#6243fd`) are the logo's own
and live in its files. They are close to, not equal to, `--brand-navy` and
`--brand-violet`: aligning the interface on them is a separate decision.

## Adding a primitive

1. Wrap the Base UI primitive if one exists for it — check
   [base-ui.com](https://base-ui.com) before building keyboard handling or
   ARIA roles by hand; this layer has not reimplemented either once.
2. Style with the tokens above, never a literal colour, radius, or inline
   `oklch()`/hex value. If the token you need does not exist, that's the
   conversation to have before writing the component, not after.
3. Add it to `/_dev/ui` in every variant and state it has — that page is how
   the next change to it gets judged, the same rule
   [`forms-and-interactions.md`](forms-and-interactions.md#adding-a-field-type)
   sets for fields.
4. Write the test file beside it. `tabs.test.tsx`, `table.test.tsx`,
   `pagination.test.tsx` and `alert.test.tsx` are the pattern: assert on
   role, name and keyboard path, not on class names — except where the class
   itself is the contract (`table.test.tsx`'s wrapper-not-table overflow
   check; `alert.test.tsx`'s variant tokens).

## What is deliberately not here

- **No dark mode.** `.dark` exists in the stylesheet from shadcn's scaffold
  and nothing toggles it; the mockups describe one theme. Left in place
  rather than stripped — removing dead CSS is a separate, larger cleanup
  than this ticket's scope.
- **No custom typography or spacing scale.** Tailwind v4's defaults were
  already what every primitive used before LEKA-339 touched anything;
  inventing a second scale nothing was missing from would be a rename, not
  a fix.
- **No Storybook.** `/_dev/ui`, `/_dev/forms` and `/_dev/states` are
  development-only React pages, not a second build system.
- **No `warning` Alert variant yet.** `--state-warning` exists and
  `StatePanel`/the offline banner already use it for their own tone, but
  nothing calls `Alert` that way today — add the variant the day something
  does, not ahead of it.

---

## Related

- [`app-shell.md`](app-shell.md) — the frame every screen sits in, and where
  the brand tokens were sampled from.
- [`forms-and-interactions.md`](forms-and-interactions.md) — the field-level
  components built on these primitives, and the confirm/toast/validation
  conventions around them.
- [`system-states.md`](system-states.md) — loading, error and offline
  states, and the `--state-*` tokens' full story.
- [`knowledge-components.md`](knowledge-components.md) — entities, relationships, provenance,
  quality and freshness (LEKA-340).
- `web/app/design-tokens.test.ts` — the contrast test every colour pair
  above is measured against.
