"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "cn";

import type { TabKey } from "@/lib/i18n/dictionaries";
import { matchRoute } from "@/lib/navigation/active";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * The tabs of a detail page — and they are links, not state.
 *
 * The segment in the URL is the truth: /intentions/42/evidence can be sent
 * to a colleague, reloaded, and opened in a second tab. A tab kept in React
 * state looks identical and does none of that.
 *
 * Which tabs exist is declared by the route, so this component never names
 * one. The first tab is the page itself, without a segment, so the canonical
 * URL of a detail page stays short.
 */
export function RouteTabs() {
  const t = useDictionary();
  const pathname = usePathname() ?? "/";
  const match = matchRoute(pathname);
  const tabs = match?.route.tabs ?? [];

  if (match === undefined || tabs.length === 0) return null;

  const base = match.route.path
    .split("/")
    .map((segment) => (segment.startsWith(":") ? match.params[segment.slice(1)] : segment))
    .join("/");
  const current = match.tab ?? tabs[0];

  return (
    <div className="mb-6 -mx-1 overflow-x-auto border-b border-shell-line">
      <nav aria-label={t.shell.sections} className="flex min-w-max gap-1 px-1">
        {tabs.map((tab, index) => {
          const active = tab === current;
          return (
            <Link
              key={tab}
              href={index === 0 ? base : `${base}/${tab}`}
              aria-current={active ? "page" : undefined}
              data-testid={`tab-${tab}`}
              className={cn(
                // 10 tabs on an element's sheet fit at 1280 px with 2.5 (LEKA-438); a narrower screen scrolls.
                "-mb-px border-b-2 px-2.5 py-2 text-sm font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                active
                  ? "border-brand-violet text-brand-violet"
                  : "border-transparent text-shell-muted hover:text-shell-nav",
              )}
            >
              {t.tabs[tab as TabKey]}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
