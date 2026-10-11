"use client";

import { Combobox as ComboboxPrimitive } from "@base-ui/react";
import type { FieldValues, Path } from "react-hook-form";

import type { Option } from "@/components/forms/choice-fields";
import { FormField, type FormFieldProps } from "@/components/forms/form-field";
import {
  Combobox,
  ComboboxChip,
  ComboboxChips,
  ComboboxChipsInput,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * The two fields for a list too long to read.
 *
 * A Select shows its options; past a dozen of them, showing is no longer
 * how anyone finds anything, and the field has to accept typing. That is
 * the whole difference, and it is why this is a separate component rather
 * than a `searchable` prop: the keyboard contract changes completely.
 *
 * THE FORM HOLDS IDS, NOT OPTIONS. Base UI works with whichever objects it
 * is handed, and matching on identity would put label text into the value
 * the API receives. The conversion happens here, at the edge, in both
 * directions, so the schema stays a list of strings.
 *
 * ASYNCHRONOUS LISTS. Loading, empty and failed are three different
 * sentences in the same place, and they are announced: Base UI's Status
 * part is a live region, so someone who cannot see the list still learns
 * that it arrived.
 */

export interface AsyncListState {
  loading?: boolean;
  /** True when the list could not be fetched. Not "no results". */
  failed?: boolean;
}

type Shared<TFieldValues extends FieldValues, TName extends Path<TFieldValues>> = Omit<
  FormFieldProps<TFieldValues, TName>,
  "children" | "counter" | "wrapInControl" | "layout"
> &
  AsyncListState & {
    options: readonly Option[];
    placeholder?: string;
  };

function useListMessage({ loading, failed }: AsyncListState): string {
  const t = useDictionary();
  if (loading) return t.forms.loading;
  if (failed) return t.forms.loadFailed;
  return t.forms.noResults;
}

const label = (option: Option) => option.label;
const same = (a: Option, b: Option) => a.value === b.value;

/** One choice, found by typing. */
export function ComboboxField<TFieldValues extends FieldValues, TName extends Path<TFieldValues>>({
  options,
  placeholder,
  loading,
  failed,
  ...props
}: Shared<TFieldValues, TName>) {
  const t = useDictionary();
  const message = useListMessage({ loading, failed });

  return (
    <FormField {...props} wrapInControl={false}>
      {({ field, invalid, disabled }) => (
        <Combobox
          items={options as Option[]}
          value={options.find((option) => option.value === field.value) ?? null}
          onValueChange={(option: Option | null) => field.onChange(option?.value ?? "")}
          itemToStringLabel={label}
          isItemEqualToValue={same}
          disabled={disabled || loading}
        >
          <ComboboxInput
            placeholder={placeholder ?? t.forms.searchPlaceholder}
            aria-invalid={invalid || undefined}
            onBlur={field.onBlur}
          />
          <ComboboxContent>
            <ComboboxEmpty>{message}</ComboboxEmpty>
            <ComboboxList>
              {(option: Option) => (
                <ComboboxItem key={option.value} value={option} disabled={option.disabled}>
                  {option.label}
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
      )}
    </FormField>
  );
}

/**
 * Several choices, each one a chip that can be taken back off.
 *
 * Backspace in an empty input removes the last chip — Base UI's behaviour,
 * and the one every tag field has taught people to expect. Each ✕ says what
 * it removes: twelve buttons all called "remove" are twelve identical
 * announcements and no way to tell them apart.
 */
export function MultiSelectField<
  TFieldValues extends FieldValues,
  TName extends Path<TFieldValues>,
>({
  options,
  placeholder,
  loading,
  failed,
  max,
  ...props
}: Shared<TFieldValues, TName> & { max?: number }) {
  const t = useDictionary();
  const message = useListMessage({ loading, failed });

  return (
    <FormField
      {...props}
      wrapInControl={false}
      description={
        max === undefined ? props.description : (props.description ?? fill(t.forms.maxReached, { max }))
      }
    >
      {({ field, invalid, disabled }) => {
        const selected = Array.isArray(field.value) ? (field.value as string[]) : [];
        const chosen = options.filter((option) => selected.includes(option.value));

        return (
          <Combobox
            multiple
            items={options as Option[]}
            value={chosen}
            onValueChange={(next: Option[]) => {
              // Refusing the change is quieter than accepting it and
              // truncating: the chip simply does not appear, and nothing
              // the person did is undone behind their back.
              if (max !== undefined && next.length > max) return;
              field.onChange(next.map((option) => option.value));
            }}
            itemToStringLabel={label}
            isItemEqualToValue={same}
            disabled={disabled || loading}
          >
            <ComboboxChips aria-invalid={invalid || undefined}>
              {chosen.map((option) => (
                <ComboboxChip key={option.value} showRemove={false}>
                  {option.label}
                  <ComboboxPrimitive.ChipRemove
                    aria-label={fill(t.forms.remove, { label: option.label })}
                    className="-me-0.5 ms-0.5 rounded p-0.5 opacity-60 outline-none hover:opacity-100 focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                  >
                    ✕
                  </ComboboxPrimitive.ChipRemove>
                </ComboboxChip>
              ))}
              <ComboboxChipsInput
                placeholder={chosen.length === 0 ? (placeholder ?? t.forms.searchPlaceholder) : ""}
                onBlur={field.onBlur}
              />
            </ComboboxChips>
            <ComboboxContent>
              <ComboboxEmpty>{message}</ComboboxEmpty>
              <ComboboxList>
                {(option: Option) => (
                  <ComboboxItem key={option.value} value={option} disabled={option.disabled}>
                    {option.label}
                  </ComboboxItem>
                )}
              </ComboboxList>
            </ComboboxContent>
          </Combobox>
        );
      }}
    </FormField>
  );
}
