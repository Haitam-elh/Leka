"use client";

import { Search, X } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { cn } from "cn";

import { IconTile, typeIcon, typeLabel } from "@/components/environment/parts";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { SearchHit } from "@/lib/knowledge-graph";
import { MIN_SEARCH, useGraphSearch } from "@/lib/knowledge-graph-queries";

/** Waits for the typing to pause before asking: one request a word, not a letter. */
function useSettled(value: string, delay = 200): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

/**
 * Picks an entity by searching the company model (LEKA-369): what is typed
 * goes to the knowledge search, its hits are offered — each with its kind
 * and where it is — and the one picked is handed back.
 */
export function EntityPicker({
  label,
  placeholder,
  onPick,
  testId,
}: {
  label: string;
  placeholder: string;
  onPick: (hit: SearchHit) => void;
  testId?: string;
}) {
  const t = useDictionary();
  const id = useId();
  const [typed, setTyped] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const settled = useSettled(typed);
  const search = useGraphSearch(settled);
  const hits = settled.trim().length >= MIN_SEARCH ? (search.data?.entities ?? []) : [];
  const shown = open && typed.trim().length >= MIN_SEARCH;

  function pick(hit: SearchHit | undefined) {
    if (!hit) return;
    onPick(hit);
    setTyped("");
    setOpen(false);
  }

  return (
    <div className="relative min-w-0 flex-1" data-testid={testId}>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-shell-muted">
        {label}
      </label>
      <div className="flex items-center gap-2 rounded-lg border border-shell-line bg-white px-3 focus-within:ring-3 focus-within:ring-brand-violet/40">
        <Search className="size-4 text-shell-muted" aria-hidden="true" />
        <input
          id={id}
          type="search"
          role="combobox"
          aria-expanded={shown}
          aria-controls={shown ? `${id}-list` : undefined}
          aria-activedescendant={shown && hits[active] ? `${id}-option-${active}` : undefined}
          aria-autocomplete="list"
          autoComplete="off"
          value={typed}
          placeholder={placeholder}
          onChange={(event) => {
            setTyped(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((index) => Math.min(index + 1, Math.max(hits.length - 1, 0)));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((index) => Math.max(index - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              pick(hits[active]);
            } else if (event.key === "Escape") {
              setOpen(false);
            }
          }}
          className="h-9 min-w-0 flex-1 bg-transparent text-sm text-brand-navy outline-none placeholder:text-shell-muted"
        />
        {typed ? (
          <button
            type="button"
            onClick={() => setTyped("")}
            aria-label={t.environment.explorer.clear}
            className="text-shell-muted outline-none hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        ) : null}
      </div>
      {shown ? (
        <ul
          id={`${id}-list`}
          role="listbox"
          aria-label={label}
          className="absolute z-30 mt-1 max-h-80 w-full overflow-auto rounded-lg border border-shell-line bg-white p-1 shadow-lg"
        >
          {hits.length === 0 ? (
            <li className="px-3 py-2 text-sm text-shell-muted">
              {search.isFetching ? "…" : t.environment.explorer.noMatch}
            </li>
          ) : (
            hits.map((hit, index) => (
              <li
                key={hit.entity.id}
                id={`${id}-option-${index}`}
                role="option"
                aria-selected={index === active}
                data-testid="picker-option"
                // A mouse down before the input's blur: the click lands.
                onMouseDown={(event) => {
                  event.preventDefault();
                  pick(hit);
                }}
                // Moved over, not merely appeared under a still pointer: a
                // list opening beneath the mouse keeps the keyboard's choice.
                onMouseMove={() => setActive(index)}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5",
                  index === active && "bg-brand-violet-soft/60",
                )}
              >
                <IconTile icon={typeIcon(hit.entity.type)} tone="violet" className="size-7" />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-brand-navy">
                    {hit.entity.name}
                  </span>
                  <span className="block truncate text-xs text-shell-muted">
                    {[typeLabel(t, hit.entity.type), hit.holder?.name].filter(Boolean).join(" · ")}
                  </span>
                </span>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
