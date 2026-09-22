"use client";

import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * The first thing in the tab order, invisible until it has focus.
 *
 * Without it, reaching the page's actual content past twelve navigation
 * links means twelve tab presses, on every page, for anyone not using a
 * mouse.
 */
export function SkipLink() {
  const t = useDictionary();

  return (
    <a
      href="#main-content"
      className="sr-only rounded-lg bg-brand-navy px-4 py-2 text-sm font-medium text-white focus-visible:not-sr-only focus-visible:fixed focus-visible:top-4 focus-visible:left-4 focus-visible:z-50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40"
    >
      {t.shell.skipToContent}
    </a>
  );
}
