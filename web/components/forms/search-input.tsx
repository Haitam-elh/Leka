"use client";

import { Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "cn";
import { useDictionary } from "@/lib/i18n/locale-provider";

/** Long enough to stop typing, short enough not to feel stuck. */
const DEFAULT_DEBOUNCE_MS = 300;

/**
 * The box above a list that filters it.
 *
 * Not a form field: it has no label above it, no validation and no place in
 * a schema. It reports what was typed, after a pause, and the list it feeds
 * decides what that means.
 *
 * THE PAUSE IS THE POINT. Filtering on every keystroke sends a request per
 * character, and the answers come back out of order — the list flickers
 * through the results of "p", "pa", "pay" and settles on whichever was
 * slowest. The value on screen stays immediate; only what it reports waits.
 *
 * ESCAPE EMPTIES, THEN LEAVES. Pressing it once on a filled box clears the
 * filter, which is what someone wants who can see results they did not
 * mean to ask for. Pressing it on an empty box gives the keyboard back to
 * the page, rather than trapping it in a box with nothing to clear.
 */
export function SearchInput({
  value,
  onChange,
  placeholder,
  debounceMs = DEFAULT_DEBOUNCE_MS,
  autoFocus,
  className,
  "aria-label": ariaLabel,
}: {
  /** The current filter. The caller owns it; this box only proposes. */
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  debounceMs?: number;
  autoFocus?: boolean;
  className?: string;
  "aria-label"?: string;
}) {
  const t = useDictionary();
  const [typed, setTyped] = useState(value);
  const input = useRef<HTMLInputElement | null>(null);
  const latest = useRef(onChange);
  latest.current = onChange;

  // The caller may reset the filter from outside — a cleared page, a
  // restored URL. What it says wins over what was typed.
  useEffect(() => setTyped(value), [value]);

  useEffect(() => {
    if (typed === value) return;
    const timer = window.setTimeout(() => latest.current(typed), debounceMs);
    return () => window.clearTimeout(timer);
  }, [typed, value, debounceMs]);

  function clear() {
    setTyped("");
    onChange("");
  }

  return (
    <div className={cn("relative", className)}>
      <Search
        className="pointer-events-none absolute top-1/2 start-3 size-4 -translate-y-1/2 text-shell-muted"
        aria-hidden="true"
      />
      <input
        ref={input}
        type="search"
        role="searchbox"
        value={typed}
        autoFocus={autoFocus}
        aria-label={ariaLabel ?? t.forms.searchPlaceholder}
        placeholder={placeholder ?? t.forms.searchPlaceholder}
        onChange={(event) => setTyped(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          if (typed.length > 0) {
            // Stops the dialog or the page from also treating it as "close".
            event.stopPropagation();
            clear();
            return;
          }
          input.current?.blur();
        }}
        className="h-9 w-full rounded-lg border border-shell-line bg-white pe-9 ps-9 text-sm outline-none placeholder:text-shell-muted focus-visible:border-brand-violet focus-visible:ring-3 focus-visible:ring-brand-violet/30 [&::-webkit-search-cancel-button]:hidden"
      />
      {typed.length > 0 ? (
        <button
          type="button"
          onClick={clear}
          aria-label={t.forms.clear}
          className="absolute top-1/2 end-2 -translate-y-1/2 rounded p-1 text-shell-muted outline-none hover:text-shell-nav focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
