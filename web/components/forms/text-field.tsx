"use client";

import type { FieldValues, Path } from "react-hook-form";

import { FormField, type FormFieldProps } from "@/components/forms/form-field";
import { Input } from "@/components/ui/input";

/**
 * A single line of text: a name, an address, a URL, a password.
 *
 * The whole component is the wiring it does not do. Everything about
 * labelling, describing, invalidity and error text lives in FormField, so
 * what is left here is the control and the one thing specific to it — the
 * keyboard the browser offers, which is what `type` really chooses on a
 * phone.
 */
export function TextField<TFieldValues extends FieldValues, TName extends Path<TFieldValues>>({
  type = "text",
  placeholder,
  autoComplete,
  ...props
}: Omit<FormFieldProps<TFieldValues, TName>, "children"> & {
  type?: "text" | "email" | "url" | "password";
  placeholder?: string;
  autoComplete?: string;
}) {
  return (
    <FormField {...props}>
      {({ field, invalid }) => (
        <Input
          {...field}
          // An uncontrolled input is what React calls one whose value is
          // undefined, and it warns the first time a value arrives. A form
          // with no default for this field starts exactly there.
          value={field.value ?? ""}
          type={type}
          placeholder={placeholder}
          autoComplete={autoComplete}
          aria-invalid={invalid || undefined}
        />
      )}
    </FormField>
  );
}
