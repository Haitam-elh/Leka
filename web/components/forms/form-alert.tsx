"use client";

import { type FieldValues, useFormContext } from "react-hook-form";

import { Alert, AlertDescription } from "@/components/ui/alert";

/**
 * What went wrong with the form as a whole, at the top of it.
 *
 * The channel rule this belongs to: a problem with one value is shown on
 * that field, because that is where the correction happens. A refusal that
 * blocks the whole submission has no field to sit on — a rule about two
 * values together, a session that expired, an API that did not answer — and
 * it belongs here, above the first field, where someone who just pressed
 * the button is looking.
 *
 * It renders nothing when there is nothing to say, so it can be left in
 * every form without a condition around it.
 */
export function FormAlert<TValues extends FieldValues>({ className }: { className?: string }) {
  const {
    formState: { errors },
  } = useFormContext<TValues>();
  const message = errors.root?.message;

  if (!message) return null;

  return (
    // Alert already carries role="alert", which is right here and wrong on
    // a field: this appears once, in answer to a press, and never again
    // while someone types. Adding a second one nested inside it announces
    // the same sentence twice — which a test here now refuses.
    <Alert variant="destructive" className={className}>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
