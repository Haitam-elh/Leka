"use client";

import { ArrowRight, Search, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "cn";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { usePermissions } from "@/components/shell/shell-provider";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { visibleRoutes } from "@/lib/navigation/access";
import {
  emptySearchProvider,
  looksLikeAQuestion,
  type SearchProvider,
  type SearchResult,
} from "@/lib/search";

interface PaletteItem {
  id: string;
  section: "actions" | "navigation" | "results";
  label: string;
  href: string;
  icon: typeof Search;
}

/**
 * ⌘K: find something, or go somewhere.
 *
 * Three sections, in this order, and the order is the decision. Actions
 * first, because creating an intention is what the product is for and a
 * search box beside it would quietly become a competing way to ask
 * questions. Then navigation — the pages this person may open, no others.
 * Then results, from a provider that is empty until the Context Engine
 * fills it.
 *
 * Everything is a link, so Enter, a click and a middle click all do what
 * they do everywhere else.
 */
export function CommandPalette({
  open,
  onOpenChange,
  search = emptySearchProvider,
  finalFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  search?: SearchProvider;
  /**
   * Where the keyboard goes when the palette closes. Base UI returns focus
   * to its own trigger; this palette is opened by a shortcut as often as by
   * a click, so it is told explicitly — otherwise Escape drops the focus at
   * the top of the page and the next Tab starts from nowhere.
   */
  finalFocus?: React.RefObject<HTMLElement | null>;
}) {
  const t = useDictionary();
  const router = useRouter();
  const permissions = usePermissions();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [results, setResults] = useState<readonly SearchResult[]>([]);
  const listRef = useRef<HTMLUListElement>(null);

  // A fresh palette every time: a query left over from yesterday is a
  // surprise, and the first item is where the eye goes.
  useEffect(() => {
    if (!open) {
      setQuery("");
      setActive(0);
      setResults([]);
    }
  }, [open]);

  useEffect(() => {
    let cancelled = false;
    if (query.trim().length === 0) {
      setResults([]);
      return;
    }
    void search(query).then((found) => {
      if (!cancelled) setResults(found);
    });
    return () => {
      cancelled = true;
    };
  }, [query, search]);

  const items = useMemo<PaletteItem[]>(() => {
    const typed = query.trim();
    const actions: PaletteItem[] = [
      {
        id: "create-intention",
        section: "actions",
        label:
          typed.length > 0
            ? fill(t.palette.createIntentionWith, { query: typed })
            : t.palette.createIntention,
        href: typed.length > 0 ? `${routes.intentionNew()}?q=${encodeURIComponent(typed)}` : routes.intentionNew(),
        icon: Sparkles,
      },
    ];

    const matches = (label: string) =>
      typed.length === 0 || label.toLowerCase().includes(typed.toLowerCase());

    const navigation: PaletteItem[] = visibleRoutes(permissions)
      .filter((route) => matches(t.nav[route.labelKey]))
      .map((route) => ({
        id: route.id,
        section: "navigation" as const,
        label: t.nav[route.labelKey],
        href: route.path,
        icon: route.icon ?? ArrowRight,
      }));

    const found: PaletteItem[] = results.map((result) => ({
      id: result.id,
      section: "results" as const,
      label: `${result.label} · ${result.kind}`,
      href: result.href,
      icon: Search,
    }));

    return [...actions, ...navigation, ...found];
  }, [permissions, query, results, t]);

  useEffect(() => {
    setActive((index) => Math.min(index, Math.max(items.length - 1, 0)));
  }, [items.length]);

  function go(item: PaletteItem | undefined) {
    if (item === undefined) return;
    onOpenChange(false);
    router.push(item.href);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (index + 1) % Math.max(items.length, 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (index - 1 + items.length) % Math.max(items.length, 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(items[active]);
    }
  }

  const sections: PaletteItem["section"][] = ["actions", "navigation", "results"];
  const titles = {
    actions: t.palette.actions,
    navigation: t.palette.navigation,
    results: t.palette.results,
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        finalFocus={finalFocus}
        className="top-[12vh] max-w-xl translate-y-0 gap-0 overflow-hidden p-0"
      >
        <DialogTitle className="sr-only">{t.palette.open}</DialogTitle>

        <div className="flex items-center gap-2 border-b border-shell-line px-4 py-3">
          <Search className="size-4 shrink-0 text-shell-muted" aria-hidden="true" />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={t.palette.placeholder}
            aria-label={t.palette.placeholder}
            aria-controls="command-palette-list"
            aria-activedescendant={items[active] ? `palette-${items[active].id}` : undefined}
            data-testid="palette-input"
            className="w-full bg-transparent text-sm outline-none placeholder:text-shell-muted"
          />
          <kbd className="rounded border border-shell-line px-1.5 py-0.5 text-xs text-shell-muted">
            Esc
          </kbd>
        </div>

        <ul
          ref={listRef}
          id="command-palette-list"
          role="listbox"
          aria-label={t.palette.open}
          className="max-h-80 overflow-y-auto p-2"
        >
          {sections.map((section) => {
            const group = items.filter((item) => item.section === section);
            if (group.length === 0) return null;
            return (
              <li key={section}>
                <p className="px-2 py-1.5 text-xs font-medium text-shell-muted">
                  {titles[section]}
                </p>
                <ul>
                  {group.map((item) => {
                    const index = items.indexOf(item);
                    const Icon = item.icon;
                    return (
                      <li key={item.id}>
                        <button
                          type="button"
                          id={`palette-${item.id}`}
                          role="option"
                          aria-selected={index === active}
                          data-testid={`palette-${item.id}`}
                          onMouseEnter={() => setActive(index)}
                          onClick={() => go(item)}
                          className={cn(
                            "flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm outline-none",
                            index === active
                              ? "bg-brand-violet-soft text-brand-violet"
                              : "text-shell-nav",
                          )}
                        >
                          <Icon className="size-4 shrink-0" aria-hidden="true" />
                          <span className="truncate">{item.label}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </li>
            );
          })}

          {results.length === 0 && query.trim().length > 0 && (
            <li className="px-2 py-3 text-sm text-shell-muted" data-testid="palette-no-results">
              <p>{t.palette.noResults}</p>
              {/* The rule, said out loud where someone would otherwise wait
                  for an answer that is never coming from here. */}
              {looksLikeAQuestion(query) && <p className="mt-1">{t.palette.searchHint}</p>}
            </li>
          )}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

/**
 * ⌘K, or Ctrl+K — unless you are typing.
 *
 * A shortcut that fires inside a text field steals the keystroke from
 * whoever is writing an intention, which is the one thing this product asks
 * people to do.
 */
export function useCommandShortcut(onOpen: () => void): void {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() !== "k" || !(event.metaKey || event.ctrlKey)) return;
      const target = event.target as HTMLElement | null;
      const typing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target?.isContentEditable === true;
      if (typing) return;
      event.preventDefault();
      onOpen();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onOpen]);
}
