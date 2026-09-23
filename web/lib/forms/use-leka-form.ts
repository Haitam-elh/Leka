"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { type DefaultValues, type FieldValues, useForm, type UseFormReturn } from "react-hook-form";

import { applyServerErrors } from "@/lib/forms/server-errors";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { z } from "@/lib/validation";

/**
 * Every form in LEKA, configured once.
 *
 * WHEN VALIDATION SPEAKS. `mode: "onTouched"`, which is not a detail of
 * configuration but the behaviour the product promises: nothing is said
 * while someone fills a field for the first time — being told an address is
 * invalid at the second character is a complaint about a value they are
 * still typing. It speaks when they leave the field, and from then on it
 * corrects live, because once an error is on screen the only thing that
 * matters is watching it go away.
 *
 * WHAT HAPPENS ON A FAILED SUBMIT. react-hook-form puts focus on the first
 * invalid field. Past three errors a form should also summarise, which is
 * FormErrorSummary's job, driven by the same `formState.errors`.
 *
 * WHAT HAPPENS WHEN THE SERVER REFUSES. The submit handler catches it and
 * routes it through applyServerErrors, so no screen has to remember to. A
 * form that failed stays filled in and editable: clearing it would throw
 * away the work that produced the error.
 *
 * NO DOUBLE SUBMISSION. The guard is here rather than on the button,
 * because a button is one of several ways to submit a form — Enter in a
 * text field is another — and a guard that only covers the button covers
 * the easy case.
 *
 * ONE LIMITATION, ON PURPOSE. Input and output are the same type, so a
 * schema that transforms its values does not fit. That is the right shape
 * for a form: the values on screen are the values submitted, and a form
 * whose fields hold something other than what it sends is a form nobody can
 * debug from what they can see.
 */

export type LekaForm<TValues extends FieldValues> = UseFormReturn<TValues, unknown, TValues> & {
  /** Hand this to `<form onSubmit={…}>`. */
  submit: (event?: React.BaseSyntheticEvent) => Promise<void>;
};

export interface LekaFormOptions<TValues extends FieldValues> {
  schema: z.ZodType<TValues, TValues>;
  defaultValues: DefaultValues<TValues>;
  onSubmit: (values: TValues) => Promise<void> | void;
}

export function useLekaForm<TValues extends FieldValues>({
  schema,
  defaultValues,
  onSubmit,
}: LekaFormOptions<TValues>): LekaForm<TValues> {
  const t = useDictionary();

  const form = useForm<TValues, unknown, TValues>({
    resolver: zodResolver(schema),
    defaultValues,
    mode: "onTouched",
    criteriaMode: "firstError",
    shouldFocusError: true,
  });

  const handle = form.handleSubmit(async (values) => {
    try {
      await onSubmit(values);
    } catch (caught) {
      applyServerErrors(form, caught, t.forms.submitFailed);
    }
  });

  return Object.assign(form, {
    submit: async (event?: React.BaseSyntheticEvent) => {
      if (form.formState.isSubmitting) return;
      await handle(event);
    },
  });
}
