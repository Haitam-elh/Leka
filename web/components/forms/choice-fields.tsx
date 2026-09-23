"use client";

import type { FieldValues, Path } from "react-hook-form";

import { FormField, type FormFieldProps } from "@/components/forms/form-field";
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * The fields that offer a fixed set of answers.
 *
 * They share a file because they share a shape: a value, a list of options,
 * and no searching. The moment a list is long enough to need searching it
 * is a ComboboxField, which is a different component for a different
 * problem — not a prop on this one.
 *
 * All four pass `wrapInControl={false}`: Base UI's Select, Checkbox, Switch
 * and Radio read the Field context themselves and label the element that
 * actually receives focus. Wrapping them would put the id on a root that
 * renders nothing, and the label would point at empty space.
 */

export interface Option {
  value: string;
  label: string;
  /** Under the label, in a Select or a RadioGroup. */
  hint?: string;
  disabled?: boolean;
}

type FieldProps<TFieldValues extends FieldValues, TName extends Path<TFieldValues>> = Omit<
  FormFieldProps<TFieldValues, TName>,
  "children" | "counter" | "wrapInControl" | "layout"
>;

/** A short list, chosen from a menu. "Environnement : Production". */
export function SelectField<TFieldValues extends FieldValues, TName extends Path<TFieldValues>>({
  options,
  placeholder,
  ...props
}: FieldProps<TFieldValues, TName> & { options: readonly Option[]; placeholder?: string }) {
  const t = useDictionary();

  return (
    <FormField {...props} wrapInControl={false}>
      {({ field, invalid, disabled }) => (
        <Select
          value={(field.value as string | undefined) ?? ""}
          onValueChange={field.onChange}
          disabled={disabled}
        >
          <SelectTrigger
            className="w-full"
            aria-invalid={invalid || undefined}
            onBlur={field.onBlur}
          >
            <SelectValue placeholder={placeholder ?? t.forms.selectPlaceholder} />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem key={option.value} value={option.value} disabled={option.disabled}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </FormField>
  );
}

/** One box, one statement it is either true or false about. */
export function CheckboxField<TFieldValues extends FieldValues, TName extends Path<TFieldValues>>(
  props: FieldProps<TFieldValues, TName>,
) {
  return (
    <FormField {...props} wrapInControl={false} layout="inline">
      {({ field, invalid, disabled }) => (
        <Checkbox
          checked={Boolean(field.value)}
          onCheckedChange={field.onChange}
          onBlur={field.onBlur}
          disabled={disabled}
          aria-invalid={invalid || undefined}
        />
      )}
    </FormField>
  );
}

/**
 * A setting that takes effect as it is flipped.
 *
 * The difference from a checkbox is not visual: a checkbox states something
 * that will be true once the form is saved, a switch turns something on
 * now. Using the wrong one makes people press Save and wonder whether it
 * counted.
 */
export function SwitchField<TFieldValues extends FieldValues, TName extends Path<TFieldValues>>(
  props: FieldProps<TFieldValues, TName>,
) {
  return (
    <FormField {...props} wrapInControl={false} layout="inline">
      {({ field, invalid, disabled }) => (
        <Switch
          checked={Boolean(field.value)}
          onCheckedChange={field.onChange}
          onBlur={field.onBlur}
          disabled={disabled}
          aria-invalid={invalid || undefined}
        />
      )}
    </FormField>
  );
}

/** Every option visible at once, because comparing them is the point. */
export function RadioGroupField<
  TFieldValues extends FieldValues,
  TName extends Path<TFieldValues>,
>({
  options,
  ...props
}: FieldProps<TFieldValues, TName> & { options: readonly Option[] }) {
  return (
    <FormField {...props} wrapInControl={false}>
      {({ field, invalid, disabled }) => (
        <RadioGroup
          value={(field.value as string | undefined) ?? ""}
          onValueChange={field.onChange}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          className="space-y-2"
        >
          {options.map((option) => (
            <label
              key={option.value}
              className="flex cursor-pointer items-start gap-2.5 text-sm text-shell-nav"
            >
              <RadioGroupItem value={option.value} disabled={option.disabled} className="mt-0.5" />
              <span>
                {option.label}
                {option.hint ? (
                  <span className="block text-xs text-shell-muted">{option.hint}</span>
                ) : null}
              </span>
            </label>
          ))}
        </RadioGroup>
      )}
    </FormField>
  );
}
