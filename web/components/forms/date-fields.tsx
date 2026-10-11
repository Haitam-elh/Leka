"use client";

import { format, parseISO } from "date-fns";
import { enUS, fr as frLocale } from "date-fns/locale";
import { CalendarIcon } from "lucide-react";
import { useState } from "react";
import type { DateRange } from "react-day-picker";
import { type FieldValues, type Path, useWatch } from "react-hook-form";

import { cn } from "cn";
import { SelectField } from "@/components/forms/choice-fields";
import { FormField, type FormFieldProps } from "@/components/forms/form-field";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";

/**
 * Dates, and the one decision underneath all of them.
 *
 * A CALENDAR DATE IS NOT AN INSTANT. "2026-09-23" is the same day in Paris
 * and in Tokyo; the moment it becomes a Date object it acquires a time, a
 * zone, and the ability to be the day before. So the form holds
 * `yyyy-MM-dd` strings and converts only to draw the calendar. It removes
 * the whole class of bug where a date chosen at 1am is saved as yesterday.
 *
 * TODO LEKA-331: the workspace has no timezone preference yet, so anything
 * that really is an instant — a time of day, a range boundary sent to the
 * API — is interpreted in the browser's zone. When the setting exists, it
 * is the one to read here.
 */

/** What the form stores, and what the API will be sent. */
const WIRE = "yyyy-MM-dd";

function toDate(value: unknown): Date | undefined {
  if (typeof value !== "string" || value === "") return undefined;
  const parsed = parseISO(value);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed;
}

type Base<TFieldValues extends FieldValues, TName extends Path<TFieldValues>> = Omit<
  FormFieldProps<TFieldValues, TName>,
  "children" | "counter" | "wrapInControl" | "layout"
> & {
  /** Bounds, as `yyyy-MM-dd`. */
  min?: string;
  max?: string;
};

function useDateFnsLocale() {
  const { locale } = useLocale();
  return locale === "fr" ? frLocale : enUS;
}

/** A trigger that reads like a value, not like a control. */
function DateTrigger({
  children,
  invalid,
  disabled,
  onBlur,
}: {
  children: React.ReactNode;
  invalid: boolean;
  disabled: boolean;
  onBlur: () => void;
}) {
  return (
    <PopoverTrigger
      disabled={disabled}
      onBlur={onBlur}
      aria-invalid={invalid || undefined}
      className={cn(
        "flex h-9 w-full items-center gap-2 rounded-lg border border-shell-line bg-white px-3 text-start text-sm outline-none focus-visible:border-brand-violet focus-visible:ring-3 focus-visible:ring-brand-violet/30 disabled:cursor-not-allowed disabled:opacity-60",
        invalid && "border-shell-badge-foreground",
      )}
    >
      <CalendarIcon className="size-4 shrink-0 text-shell-muted" aria-hidden="true" />
      {children}
    </PopoverTrigger>
  );
}

/** One day. */
export function DateField<TFieldValues extends FieldValues, TName extends Path<TFieldValues>>({
  min,
  max,
  ...props
}: Base<TFieldValues, TName>) {
  const t = useDictionary();
  const dateLocale = useDateFnsLocale();
  const [open, setOpen] = useState(false);

  return (
    <FormField {...props} wrapInControl={false}>
      {({ field, invalid, disabled }) => {
        const selected = toDate(field.value);
        return (
          <Popover open={open} onOpenChange={setOpen}>
            <DateTrigger invalid={invalid} disabled={disabled} onBlur={field.onBlur}>
              {selected ? (
                format(selected, "d MMMM yyyy", { locale: dateLocale })
              ) : (
                <span className="text-shell-muted">{t.forms.pickDate}</span>
              )}
            </DateTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                locale={dateLocale}
                selected={selected}
                defaultMonth={selected}
                startMonth={toDate(min)}
                endMonth={toDate(max)}
                disabled={[
                  ...(min ? [{ before: parseISO(min) }] : []),
                  ...(max ? [{ after: parseISO(max) }] : []),
                ]}
                onSelect={(next) => {
                  field.onChange(next ? format(next, WIRE) : "");
                  setOpen(false);
                }}
                autoFocus
              />
            </PopoverContent>
          </Popover>
        );
      }}
    </FormField>
  );
}

/** Two days, and everything between them. */
export function DateRangeField<
  TFieldValues extends FieldValues,
  TName extends Path<TFieldValues>,
>({ min, max, ...props }: Base<TFieldValues, TName>) {
  const t = useDictionary();
  const dateLocale = useDateFnsLocale();
  const [open, setOpen] = useState(false);

  return (
    <FormField {...props} wrapInControl={false}>
      {({ field, invalid, disabled }) => {
        const value = (field.value ?? {}) as { from?: string; to?: string };
        const range: DateRange | undefined = value.from
          ? { from: toDate(value.from), to: toDate(value.to) }
          : undefined;

        return (
          <Popover open={open} onOpenChange={setOpen}>
            <DateTrigger invalid={invalid} disabled={disabled} onBlur={field.onBlur}>
              {range?.from ? (
                <span>
                  {t.forms.dateFrom} {format(range.from, "d MMM yyyy", { locale: dateLocale })}
                  {range.to
                    ? ` ${t.forms.dateTo.toLowerCase()} ${format(range.to, "d MMM yyyy", { locale: dateLocale })}`
                    : ""}
                </span>
              ) : (
                <span className="text-shell-muted">{t.forms.pickDate}</span>
              )}
            </DateTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="range"
                locale={dateLocale}
                selected={range}
                defaultMonth={range?.from}
                startMonth={toDate(min)}
                endMonth={toDate(max)}
                disabled={[
                  ...(min ? [{ before: parseISO(min) }] : []),
                  ...(max ? [{ after: parseISO(max) }] : []),
                ]}
                onSelect={(next) =>
                  field.onChange({
                    from: next?.from ? format(next.from, WIRE) : "",
                    to: next?.to ? format(next.to, WIRE) : "",
                  })
                }
                autoFocus
              />
            </PopoverContent>
          </Popover>
        );
      }}
    </FormField>
  );
}

/** A time of day, when the day itself is decided elsewhere. */
export function TimeField<TFieldValues extends FieldValues, TName extends Path<TFieldValues>>(
  props: Omit<FormFieldProps<TFieldValues, TName>, "children" | "counter" | "layout">,
) {
  return (
    <FormField {...props}>
      {({ field, invalid }) => (
        <input
          {...field}
          type="time"
          value={typeof field.value === "string" ? field.value : ""}
          aria-invalid={invalid || undefined}
          className="h-9 w-full rounded-lg border border-shell-line bg-white px-3 text-sm outline-none focus-visible:border-brand-violet focus-visible:ring-3 focus-visible:ring-brand-violet/30 disabled:cursor-not-allowed disabled:opacity-60"
        />
      )}
    </FormField>
  );
}

/**
 * "Période" from the mockups: three answers and an escape hatch.
 *
 * Almost every analysis is about the last day, the last week or the last
 * month, and a calendar for those is three clicks where one would do. The
 * calendar stays for the case it is actually needed, behind "Personnalisé…",
 * and only appears once chosen — an empty range picker sitting under every
 * preset is a question nobody asked.
 *
 * The value is `{ preset, range }`, not a pair of dates: "the last 7 days"
 * asked again tomorrow means a different week, and flattening it to two
 * dates at the moment of choosing would freeze it.
 */
export const PERIOD_PRESETS = ["24h", "7d", "30d", "custom"] as const;

export type PeriodPreset = (typeof PERIOD_PRESETS)[number];

export interface PeriodValue {
  preset: PeriodPreset;
  range?: { from?: string; to?: string };
}

export function PeriodField<TFieldValues extends FieldValues>({
  name,
  label,
  optional,
  description,
  disabled,
}: {
  name: Path<TFieldValues>;
  label: string;
  optional?: boolean;
  description?: string;
  disabled?: boolean;
}) {
  const t = useDictionary();
  const presetName = `${name}.preset` as Path<TFieldValues>;
  const rangeName = `${name}.range` as Path<TFieldValues>;
  const preset = useWatch({ name: presetName }) as PeriodPreset | undefined;

  const options = [
    { value: "24h", label: t.forms.period24h },
    { value: "7d", label: t.forms.period7d },
    { value: "30d", label: t.forms.period30d },
    { value: "custom", label: t.forms.periodCustom },
  ];

  return (
    <div className="space-y-2">
      <SelectField<TFieldValues, Path<TFieldValues>>
        name={presetName}
        label={label}
        optional={optional}
        description={description}
        disabled={disabled}
        options={options}
      />
      {preset === "custom" ? (
        <DateRangeField<TFieldValues, Path<TFieldValues>>
          name={rangeName}
          label={t.forms.periodCustom}
          disabled={disabled}
        />
      ) : null}
    </div>
  );
}
