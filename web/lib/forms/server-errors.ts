import type { FieldValues, Path, UseFormReturn } from "react-hook-form";

import { ApiError } from "@/lib/api";

/**
 * Put what the API refused back onto the fields that caused it.
 *
 * LEKA-333 gives every error one shape, and apiFetch already turns its
 * `details: [{ field, message }]` into `fieldErrors` — so there is no format
 * to invent here, only a routing decision.
 *
 * The rule: a field error the form actually has goes on that field, where
 * the person is looking. Everything else — a rule about the whole request,
 * a field this screen does not show, a network failure — goes to the form's
 * own error, which FormAlert renders at the top. The alternative is an
 * error attached to a name nothing renders, which reaches the person as a
 * form that refuses to submit and says nothing about why.
 *
 * The first field to receive an error is focused, for the same reason the
 * first invalid field is focused on a failed submit: the correction should
 * not start with a hunt.
 */
export function applyServerErrors<TFieldValues extends FieldValues>(
  form: UseFormReturn<TFieldValues, unknown, FieldValues>,
  caught: unknown,
  fallbackMessage: string,
): void {
  if (!(caught instanceof ApiError)) {
    form.setError("root", { type: "server", message: fallbackMessage });
    return;
  }

  const known = new Set(Object.keys(form.getValues()));
  const unrouted: string[] = [];
  let focused = false;

  for (const [field, message] of Object.entries(caught.fieldErrors ?? {})) {
    // "scope.environment" belongs to this form if "scope" does. Anything
    // else is about a request this screen did not make.
    if (!known.has(field.split(".")[0])) {
      unrouted.push(message);
      continue;
    }
    const name = field as Path<TFieldValues>;
    form.setError(name, { type: "server", message }, { shouldFocus: !focused });
    focused = true;
  }

  // An unreachable API is not a sentence worth quoting: it says the API is
  // at localhost, which means nothing to the person and everything to us.
  const summary = caught.isUnreachable ? fallbackMessage : caught.message;
  const rest = [summary, ...unrouted].filter(Boolean).join(" ");
  if (!focused || unrouted.length > 0) {
    form.setError("root", { type: "server", message: rest || fallbackMessage });
  }
}
