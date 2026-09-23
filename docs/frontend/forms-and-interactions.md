# Forms and interactions

Every input in LEKA, every way of asking before doing, and the rules that
make them behave the same on twenty screens. Written for whoever adds the
twenty-first.

Built in LEKA-342. The primitives under it are shadcn's `base-nova` style
on [Base UI](https://base-ui.com), in `web/components/ui/`.

---

## The decisions this rests on

| | Decision | Why |
|---|---|---|
| **A** | `react-hook-form` + `zod`, with `@hookform/resolvers` | Already installed, typed, and the schemas can move to the backend later. No other form library. |
| **B** | Enter writes a newline, **⌘/Ctrl+Enter submits** the composer | An intention costs money and minutes and often takes several lines. The hint is printed beside the button and declared in `aria-keyshortcuts`. |
| **C** | The composer's draft lives in `sessionStorage`, one key per workspace | Checking a service name in another tab must not cost the paragraph. Cleared on submit and on a confirmed abandon. Every access is wrapped in `try/catch`: private browsing refuses storage and the app still has to work. |
| **D** | No Storybook. `/_dev/forms` instead | There is no Storybook in this repo yet. The gallery is development-only and 404s in a production build. |

Two deviations from the original ticket, agreed before building:

- **Toasts are Base UI's, not `sonner`'s.** Base UI was already installed and
  ships a toast; a second toast system means a second viewport competing for
  the same corner.
- **The combobox is Base UI's, not `cmdk`'s.** It already does multi-select
  with removable chips, and the ⌘K palette from LEKA-338 is built on
  `Dialog`, so `cmdk` would have been a third overlapping mechanism.

Three dependencies were added, and only three: `react-day-picker` and
`date-fns` (Base UI has no date primitive) and `@axe-core/playwright`.

---

## The catalogue

Everything lives in `web/components/forms/`, except the interaction patterns,
which live in `web/components/interactions/`.

### The wrapper

`FormField` is the one wrapper every field is built on. It owns the label,
the `(optionnel)` marker, the description, the error and the optional
counter, and it produces the accessibility wiring from state react-hook-form
already holds — generated id, `htmlFor`, `aria-describedby`, `aria-invalid`,
`aria-required`.

You will rarely use it directly. Use it when you are building a new field
type; use the fields below for everything else.

| Prop | What it does |
|---|---|
| `name` | The field in the surrounding form. Required. |
| `label` | Always. A field with no label is a field nobody can be told about. |
| `optional` | Adds "(optionnel)". **We mark optional, never required.** |
| `description` | The rule, in advance. Put the rule here and the failure in the message. |
| `counter` | `{ value, max }`. Turns to alert colour at 90 % of the limit. |
| `layout` | `"inline"` puts the control before the label — checkboxes, switches. |
| `wrapInControl` | `false` for Base UI controls that wire themselves. |

### The fields

| Component | Use it for | Notes |
|---|---|---|
| `TextField` | One line: name, email, url, password | `type` chooses the keyboard on a phone. |
| `TextareaField` | Several lines | Grows between `minRows` and `maxRows`. `max` shows `n / max`. |
| `SelectField` | A short list, no searching | Past a dozen options, use `ComboboxField`. |
| `ComboboxField` | One choice, found by typing | `loading` and `failed` are separate states from "no results". |
| `MultiSelectField` | Several choices, as removable chips | Backspace on an empty input removes the last. `max` refuses rather than truncates. |
| `DateField` | One day | Holds `yyyy-MM-dd`, never a `Date`. |
| `DateRangeField` | Two days and everything between | Holds `{ from, to }` as strings. |
| `PeriodField` | "Période" — 24 h / 7 j / 30 j / custom | Stores the **preset**, not the dates it resolves to. |
| `TimeField` | A time of day | Only when the day is decided elsewhere. |
| `CheckboxField` | A statement that will be true once saved | |
| `SwitchField` | A setting that takes effect as it is flipped | Using the wrong one makes people press Save and wonder. |
| `RadioGroupField` | A few options worth comparing side by side | |
| `SelectableListField` | Rich rows: icon, title, subtitle | Arrows walk the list; the list is one tab stop. `selectAll` optional. |
| `SearchInput` | Filtering a list | **Not a form field.** Debounced (300 ms), clearable, `role="searchbox"`. |

### The interaction patterns

| Component | Use it for |
|---|---|
| `useConfirm()` | `await confirm({…})` → `boolean`. With `reasonLabel`, → `string \| null`. |
| `ConfirmProvider` | Mounted once, in `app/(app)/layout.tsx`. Do not mount a second. |
| `SelectionActionBar` | Acting on a selection. Put `SELECTION_BAR_PADDING` on the list. |
| `notify.success / error / info` | The result of something asynchronous. |

---

## Validation

### One hook

```tsx
const form = useLekaForm({ schema, defaultValues, onSubmit });
```

It fixes four things so that no screen decides them again:

- **`mode: "onTouched"`.** Nothing is said while a field is filled for the
  first time. It speaks when the field is left, and corrects live from then
  on — once an error is on screen, watching it go is the only thing that
  matters.
- **Focus goes to the first invalid field** on a failed submit.
- **A refusal from the server is routed** through `applyServerErrors`, so no
  screen has to remember to.
- **No double submission.** The guard is in the hook, not on the button:
  Enter in a text field submits too.

### Messages are keys, not sentences

Never write `z.string().min(10, "Au moins 10 caractères")`. A sentence
compiled into a rule cannot be translated and drifts from the next schema
that says the same thing.

The error map in `web/lib/validation/messages.ts` emits
`leka.validation:tooShortString:{"min":10}`, and the field resolves it
against the dictionary of the language in use. Add a wording to
`validation` in `web/lib/i18n/dictionaries.ts` — **in both languages**, or
`tsc` fails.

Import `z` from `@/lib/validation`, not from `zod`: that is what installs
the map.

### Server errors

`applyServerErrors(form, caught, fallback)` consumes LEKA-333's shape —
`ApiError.fieldErrors`, already parsed from `details: [{ field, message }]`
by `lib/api.ts`. A field this form has gets the error; anything else goes to
the form's own error, which `FormAlert` renders at the top. An unreachable
API never quotes itself: "Cannot reach the API at localhost:8000" means
nothing to a customer.

### Summaries

`FormErrorSummary` appears **past three** errors, with an entry per field
that moves focus on demand. It does not steal focus — the first invalid
field already has it.

---

## When to ask before doing

| Situation | Pattern |
|---|---|
| Reversible, or no effect outside LEKA | **No confirmation.** A success toast, with "Annuler" when that is possible. |
| Launching an analysis (costs money and time) | **No dialog.** An explicit button: "Lancer l'analyse". |
| Abandoning an intention being written | `confirm({…})` **only if something was typed.** |
| "Arrêter l'analyse" | `confirm({ description: "Les résultats partiels seront conservés." })` |
| "Approuver" / "Valider et passer à l'action" | `destructive: true` with `impact` when the risk is real; a plain confirm otherwise. |
| "Refuser la sélection" | `confirm({ reasonLabel })` — the reason is **optional**. |
| Deleting a source, a member, a workspace | `destructive: true`, plus `requireTypedConfirmation` for a workspace or a source. |

Two rules that are not negotiable:

- **The button carries a verb.** "Lancer l'analyse", never "OK", never "Oui".
  Most people read the buttons and not the paragraph.
- **A destructive dialog opens with focus on Annuler.** Enter pressed by
  reflex must cancel.

---

## Which channel carries which message

| What happened | Where it goes |
|---|---|
| A value is wrong | Inline, on the field. |
| The submission was refused as a whole | `FormAlert`, at the top of the form. |
| An asynchronous action finished | A toast. |
| The whole page is in a state | `RouteState` (LEKA-338) or `ErrorState` — see [`system-states.md`](system-states.md). |

Every message says what happened **and what to do next**: "Impossible
d'enregistrer. Vérifiez votre connexion puis réessayez." No status codes, no
exception text.

A success toast leaves on its own after five seconds. An error stays until
it is dismissed: a message that disappears takes the only account of the
failure with it.

---

## The keyboard contract

| Component | Contract |
|---|---|
| Every field | Visible focus ring. Tab order follows the page. |
| `ComboboxField` / `MultiSelectField` | Arrows move, Enter selects, Escape closes without losing the value, Backspace on an empty input removes the last chip. |
| `SelectableListField` | Arrows walk the rows; the list is a single tab stop. |
| `SearchInput` | Escape clears a filled box, then leaves it on a second press. |
| `IntentionComposer` | Enter writes a newline. ⌘/Ctrl+Enter submits. |
| Every dialog | Focus trapped, Escape means Annuler, focus returns to whatever opened it. |
| Calendars | No trap. Disabled days are announced as disabled. |
| Global shortcuts | Never fire while focus is in a field — see `useCommandShortcut` in LEKA-338. |

One thing this does **not** solve, said plainly: a field error raised on blur
while focus has already moved elsewhere is announced by nothing. The message
is linked by `aria-describedby` and is deliberately not a live region,
because after the first error validation runs on every keystroke and a live
region would announce a sentence per character. There is a `TODO` on it in
`form-field.tsx`, to settle against a real screen reader rather than against
the specification.

---

## A complete form

```tsx
"use client";

import { Form } from "@/components/forms/form";
import { FormAlert } from "@/components/forms/form-alert";
import { TextField } from "@/components/forms/text-field";
import { SelectField } from "@/components/forms/choice-fields";
import { Button } from "@/components/ui/button";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { useUnsavedChangesGuard } from "@/lib/forms/use-unsaved-changes-guard";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { z } from "@/lib/validation";

const schema = z.object({
  name: z.string().trim().min(2).max(60),
  environment: z.string().min(1),
});

type Values = z.infer<typeof schema>;

export function ExampleForm() {
  const t = useDictionary();

  const form = useLekaForm<Values>({
    schema,
    defaultValues: { name: "", environment: "production" },
    // Throw an ApiError and applyServerErrors does the rest.
    onSubmit: async (values) => {
      await save(values);
      notify.success({ title: t.settings.saved });
      form.reset(values);
    },
  });

  const { isDirty, isSubmitting } = form.formState;
  useUnsavedChangesGuard(isDirty);

  return (
    <Form form={form}>
      <FormAlert />
      <TextField<Values, "name"> name="name" label={t.settings.name} />
      <SelectField<Values, "environment">
        name="environment"
        label={t.settings.defaultEnvironment}
        options={ENVIRONMENTS}
      />
      <Button type="submit" disabled={!isDirty || isSubmitting}>
        {isSubmitting ? t.forms.saving : t.forms.save}
      </Button>
    </Form>
  );
}
```

`web/components/settings/workspace-general-form.tsx` is this, in full, on a
real screen — including the server-error path, which `/settings?fail=1`
triggers on demand.

---

## Adding a field type

1. Build it on `FormField`. If you find yourself writing `aria-describedby`,
   stop: the wrapper does that, and a second one will disagree with it.
2. Put every word in `web/lib/i18n/dictionaries.ts`, in both languages.
3. Add it to `/_dev/forms` in each of its states — default, error, disabled,
   loading. That page is how the next change to the wrapper gets judged.
4. Write the keyboard test. The mouse path is the one that never breaks.

## What is deliberately not here

- No real network call. `submitIntention` waits and invents an id
  (LEKA-384).
- No upload. Attachments stay in memory behind a `TODO`.
- No dictation. Hidden where the browser could not do it, disabled behind a
  flag where it could.
- Sources, environments and services are mocked in the screens that use them
  (LEKA-341).
- Visual polish and tokens are LEKA-339's — see
  [`design-system.md`](design-system.md).
