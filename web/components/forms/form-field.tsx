"use client";

import { Field } from "@base-ui/react/field";
import { Controller, type ControllerRenderProps, type FieldValues, type Path, useFormContext } from "react-hook-form";

import { cn } from "cn";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { resolveValidationMessage } from "@/lib/validation";

/**
 * The wrapper every field in LEKA is built on.
 *
 * WHY ONE WRAPPER. The accessibility of a field is six attributes that have
 * to agree with each other — a generated id, a label pointing at it,
 * `aria-describedby` listing the description and the error, `aria-invalid`,
 * `aria-required`. Written per field, they agree on the day they are
 * written and drift afterwards, and the drift is invisible: the screen
 * looks right and the label stops being announced. Here they are produced
 * once, by Base UI's Field, from state react-hook-form already holds.
 *
 * OPTIONAL IS MARKED, NOT REQUIRED. On a form where most fields must be
 * filled, an asterisk on each is noise; the exception is what carries
 * information. It matches the mockups, which say "Services (optionnel)".
 *
 * ABOUT ANNOUNCING THE ERROR. The message is linked through
 * `aria-describedby` and is NOT a live region. That is deliberate: once a
 * field has errored, validation runs on every keystroke, and a live region
 * there announces a new sentence at every character — the requirement is
 * that the error be announced once, not continuously. What announces is
 * movement: a failed submit puts focus on the first invalid field, and past
 * three errors FormErrorSummary takes focus instead. The gap left is an
 * error raised on blur while focus has already moved on, which no pattern
 * solves without the noise; TODO: settle it against a real screen reader
 * rather than against the specification.
 */

export interface FieldRenderProps<TFieldValues extends FieldValues, TName extends Path<TFieldValues>> {
  field: ControllerRenderProps<TFieldValues, TName>;
  invalid: boolean;
  disabled: boolean;
}

export interface FormFieldProps<
  TFieldValues extends FieldValues,
  TName extends Path<TFieldValues>,
> {
  name: TName;
  label: string;
  /** Adds "(optionnel)" after the label. */
  optional?: boolean;
  /** Help under the control. Explain the rule here, not in the error. */
  description?: string;
  disabled?: boolean;
  /** `n / max`, for the fields that have a limit worth watching. */
  counter?: { value: number; max: number };
  /**
   * False for a control that wires itself to the field.
   *
   * Base UI's own Select, Checkbox, Switch and Combobox read the Field
   * context directly and label their inner trigger from it. Wrapping one in
   * `Field.Control` would put the id and `aria-describedby` on a root that
   * renders no element, and the label would point at nothing.
   */
  wrapInControl?: boolean;
  /**
   * "inline" puts the control before the label, on one row.
   *
   * A checkbox labelled from above reads as a heading with an orphan box
   * under it. The wrapper stays the same one — the whole point of having
   * one — and only the order changes.
   */
  layout?: "stacked" | "inline";
  /**
   * Keeps the label for screen readers and hides it from the eye — for a
   * field that sits under a heading already saying the same words. Never
   * for saving space: a field with no visible label is a guessing game.
   */
  hideLabel?: boolean;
  className?: string;
  /** The control itself. Base UI clones it with the wiring. */
  children: (props: FieldRenderProps<TFieldValues, TName>) => React.ReactElement;
}

/** Past this share of the limit, the counter stops being decoration. */
const COUNTER_ALERT_RATIO = 0.9;

export function FormField<TFieldValues extends FieldValues, TName extends Path<TFieldValues>>({
  name,
  label,
  optional = false,
  description,
  disabled = false,
  counter,
  wrapInControl = true,
  layout = "stacked",
  hideLabel = false,
  className,
  children,
}: FormFieldProps<TFieldValues, TName>) {
  const t = useDictionary();
  const { control } = useFormContext<TFieldValues>();

  return (
    <Controller
      name={name}
      control={control}
      render={({ field, fieldState }) => {
        const message = fieldState.error?.message;
        const nearLimit =
          counter !== undefined && counter.value >= counter.max * COUNTER_ALERT_RATIO;

        const rendered = children({ field, invalid: fieldState.invalid, disabled });
        const control = wrapInControl ? (
          <Field.Control
            disabled={disabled}
            // aria-required rather than required: the browser's own
            // validation is off (see Form), and `required` would turn it back
            // on for this one control.
            aria-required={optional ? undefined : true}
            render={rendered}
          />
        ) : (
          rendered
        );

        return (
          <Field.Root
            name={name}
            invalid={fieldState.invalid}
            disabled={disabled}
            touched={fieldState.isTouched}
            dirty={fieldState.isDirty}
            className={cn(layout === "stacked" ? "space-y-2" : "space-y-1.5", className)}
          >
            <div className={cn(layout === "inline" && "flex items-center gap-2.5")}>
              {layout === "inline" ? control : null}
              <Field.Label
                className={cn(
                  "flex items-center gap-1.5 text-sm font-medium text-shell-nav",
                  layout === "inline" && "cursor-pointer font-normal",
                  hideLabel && "sr-only",
                )}
              >
                {label}
                {optional ? (
                  <span className="font-normal text-shell-muted">{t.forms.optional}</span>
                ) : null}
              </Field.Label>
              {layout === "stacked" ? control : null}
            </div>

            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1 space-y-1">
                {description ? (
                  <Field.Description className="text-xs text-shell-muted">
                    {description}
                  </Field.Description>
                ) : null}
                {message ? (
                  <Field.Error match className="text-xs text-shell-badge-foreground">
                    {resolveValidationMessage(t, message)}
                  </Field.Error>
                ) : null}
              </div>

              {counter ? (
                <p
                  className={cn(
                    "shrink-0 text-xs tabular-nums",
                    nearLimit ? "text-shell-badge-foreground" : "text-shell-muted",
                  )}
                >
                  {fill(t.forms.charCount, { count: counter.value, max: counter.max })}
                </p>
              ) : null}
            </div>
          </Field.Root>
        );
      }}
    />
  );
}
