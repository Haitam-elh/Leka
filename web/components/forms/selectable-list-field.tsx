"use client";

import { useId, useRef, useState } from "react";
import type { FieldValues, Path } from "react-hook-form";

import { cn } from "cn";
import { FormField, type FormFieldProps } from "@/components/forms/form-field";
import { Checkbox } from "@/components/ui/checkbox";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * A list of things to tick, where each thing needs more than a word.
 *
 * This is "Contexte qui sera analysé" in the mockups — GitHub, Jira, the
 * sources LEKA will read — and the list of recommendations on the decision
 * step. What makes it its own component rather than a stack of checkboxes
 * is that each row carries an icon, a title and a subtitle, and that the
 * rows have to be navigable as a group.
 *
 * EACH BOX IS NAMED BY ITS ROW. The field's label names the group; a box
 * named by it too — as Base UI's Field does for any control inside — makes
 * twelve boxes all called "Contexte qui sera analysé", and a screen reader
 * cannot tell GitHub from Jira. Each box points at its own title.
 *
 * ARROWS MOVE, TAB LEAVES. A list of twelve sources costs twelve tab stops
 * on the way to the button below it. The arrows walk the list and the whole
 * list is one stop, which is how a listbox behaves and what anyone who
 * reached it with a keyboard expects.
 */

export interface SelectableItem {
  value: string;
  title: string;
  subtitle?: string;
  /** A logo or a glyph. Decorative: the title carries the meaning. */
  icon?: React.ReactNode;
  disabled?: boolean;
}

export function SelectableListField<
  TFieldValues extends FieldValues,
  TName extends Path<TFieldValues>,
>({
  items,
  selectAll = false,
  max,
  more,
  ...props
}: Omit<FormFieldProps<TFieldValues, TName>, "children" | "counter" | "wrapInControl" | "layout"> & {
  items: readonly SelectableItem[];
  /** Adds the "Tout sélectionner" control above the list. */
  selectAll?: boolean;
  /** How many rows to show before the rest is asked for — a long list is
   * opened, not scrolled through beside the form (mockup 02's five). */
  max?: number;
  /** What opens the rest: "Voir toutes les sources ({count})". */
  more?: string;
}) {
  const t = useDictionary();
  const [all, setAll] = useState(false);
  const list = useRef<HTMLDivElement | null>(null);
  const rows = useId();

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const boxes = Array.from(
      list.current?.querySelectorAll<HTMLElement>('[data-slot="checkbox"]:not([disabled])') ?? [],
    );
    const index = boxes.indexOf(document.activeElement as HTMLElement);
    if (index === -1) return;
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    boxes[(index + step + boxes.length) % boxes.length]?.focus();
  }

  return (
    <FormField {...props} wrapInControl={false}>
      {({ field, disabled }) => {
        const selected = Array.isArray(field.value) ? (field.value as string[]) : [];
        const selectable = items.filter((item) => !item.disabled);
        const allChosen = selectable.length > 0 && selectable.every((i) => selected.includes(i.value));

        function toggle(value: string, checked: boolean) {
          field.onChange(
            checked ? [...selected, value] : selected.filter((current) => current !== value),
          );
        }

        return (
          <div className="space-y-2">
            {selectAll ? (
              <label className="flex cursor-pointer items-center gap-2 text-xs text-shell-muted">
                <Checkbox
                  checked={allChosen}
                  disabled={disabled}
                  onCheckedChange={(checked) =>
                    field.onChange(checked ? selectable.map((item) => item.value) : [])
                  }
                />
                {allChosen ? t.forms.clearSelection : t.forms.selectAll}
              </label>
            ) : null}

            <div
              ref={list}
              role="group"
              onKeyDown={onKeyDown}
              className="divide-y divide-shell-line overflow-hidden rounded-lg border border-shell-line"
            >
              {(all || max === undefined ? items : items.slice(0, max)).map((item, index) => {
                const checked = selected.includes(item.value);
                const title = `${rows}-${index}`;
                return (
                  <label
                    key={item.value}
                    className={cn(
                      "flex cursor-pointer items-center gap-3 bg-white px-3 py-2 transition-colors",
                      checked && "bg-brand-violet-soft/40",
                      (item.disabled ?? disabled) && "cursor-not-allowed opacity-60",
                    )}
                  >
                    <Checkbox
                      checked={checked}
                      disabled={item.disabled ?? disabled}
                      onCheckedChange={(next) => toggle(item.value, Boolean(next))}
                      onBlur={field.onBlur}
                      aria-labelledby={title}
                    />
                    {item.icon ? (
                      <span aria-hidden="true" className="shrink-0">
                        {item.icon}
                      </span>
                    ) : null}
                    <span className="min-w-0 flex-1">
                      <span
                        id={title}
                        className="block truncate text-sm font-medium text-shell-nav"
                      >
                        {item.title}
                      </span>
                      {item.subtitle ? (
                        <span className="block truncate text-xs text-shell-muted">
                          {item.subtitle}
                        </span>
                      ) : null}
                    </span>
                  </label>
                );
              })}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-shell-muted">
                {fill(t.forms.selectedCount, { count: selected.length })}
              </p>
              {max !== undefined && items.length > max ? (
                <button
                  type="button"
                  aria-expanded={all}
                  onClick={() => setAll(!all)}
                  className="rounded text-xs font-medium text-brand-violet outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                  data-testid="selectable-more"
                >
                  {all ? t.forms.fewer : fill(more ?? t.forms.all, { count: items.length })}
                </button>
              ) : null}
            </div>
          </div>
        );
      }}
    </FormField>
  );
}
