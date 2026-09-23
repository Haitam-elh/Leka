"use client";

import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * What to do with what has been ticked, kept in reach.
 *
 * It appears at the first selection rather than sitting there empty: a bar
 * offering to act on nothing is a permanent strip of disabled buttons, and
 * people stop seeing it.
 *
 * IT MUST NOT COVER THE LAST ROW. A sticky bar over a scrolling list hides
 * exactly one item — the last one — and the person who ticks eleven of
 * twelve never sees the twelfth. The caller is told to leave room through
 * `listPadding`, which is the class to put on the list, so the rule travels
 * with the component that causes it.
 *
 * It is announced, because a bar that appears at the bottom of a long list
 * is off screen for whoever is reading with a screen reader, and silence
 * is indistinguishable from nothing having happened.
 */

/** Put this on the list above the bar so its last row stays readable. */
export const SELECTION_BAR_PADDING = "pb-20";

export function SelectionActionBar({
  count,
  primary,
  secondary,
  onClear,
  className,
}: {
  count: number;
  primary: { label: string; onClick: () => void; disabled?: boolean };
  secondary?: { label: string; onClick: () => void };
  /** Adds "Tout désélectionner"; the quickest way out of a wrong selection. */
  onClear?: () => void;
  className?: string;
}) {
  const t = useDictionary();

  if (count === 0) return null;

  return (
    <div
      role="region"
      aria-live="polite"
      className={cn(
        "sticky bottom-4 z-10 mx-auto flex w-full max-w-2xl items-center gap-3 rounded-xl border border-shell-line bg-white px-4 py-3 shadow-lg",
        className,
      )}
    >
      <p className="flex-1 text-sm font-medium text-shell-nav">
        {fill(t.interactions.selectionCount, { count })}
      </p>
      {onClear ? (
        <Button type="button" variant="ghost" size="sm" onClick={onClear}>
          {t.interactions.clearSelection}
        </Button>
      ) : null}
      {secondary ? (
        <Button type="button" variant="outline" size="sm" onClick={secondary.onClick}>
          {secondary.label}
        </Button>
      ) : null}
      <Button type="button" size="sm" onClick={primary.onClick} disabled={primary.disabled}>
        {primary.label}
      </Button>
    </div>
  );
}
