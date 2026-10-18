"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "cn";

import { usePermissions } from "@/components/shell/shell-provider";
import { routeById, routes } from "@/config/routes";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { canOpen } from "@/lib/navigation/access";
import { useNavBadges } from "@/lib/nav-badges";

/**
 * The header's navigation (LEKA-494): the five pages of the mockup —
 * Accueil, Mon environnement, Agents, Bundles, Historique —, and the
 * decisions waiting, only while one waits. The pages of running the
 * workspace are in the profile menu; every other page is one ⌘K away.
 */

type Entry = { id: string; routeId: string; href: string; active: (path: string) => boolean };

const ENTRIES: readonly Entry[] = [
  { id: "home", routeId: "overview", href: routes.overview(), active: (p) => p === routes.overview() },
  { id: "environment", routeId: "environment", href: routes.environment(), active: (p) => p.startsWith("/environment") },
  { id: "agents", routeId: "capabilities", href: routes.capabilities(), active: (p) => p.startsWith("/capabilities") },
  { id: "bundles", routeId: "capabilities", href: `${routes.capabilities()}#bundles`, active: () => false },
  { id: "history", routeId: "intentions", href: routes.intentions(), active: (p) => p.startsWith("/intentions") },
];

/** The entries this person may open, with what waits on the decisions. */
export function useMainNav() {
  const t = useDictionary().shell.main;
  const permissions = usePermissions() ?? [];
  const path = usePathname() ?? "";
  const waiting = useNavBadges().approvals ?? 0;
  const opens = (routeId: string) => {
    const route = routeById(routeId);
    return route !== undefined && canOpen(route, permissions);
  };
  const entries = ENTRIES.filter((e) => opens(e.routeId)).map((e) => ({
    id: e.id,
    href: e.href,
    label: t[e.id as keyof typeof t],
    current: e.active(path),
    count: 0,
  }));
  if (waiting > 0 && opens("approvals")) {
    entries.push({
      id: "approvals",
      href: routes.approvals(),
      label: t.approvals,
      current: path.startsWith("/approvals"),
      count: waiting,
    });
  }
  return entries;
}

export function MainNav() {
  const t = useDictionary();
  const entries = useMainNav();
  return (
    <nav aria-label={t.shell.mainNavigation} className="hidden items-center gap-1 md:me-auto md:flex">
      {entries.map((entry) => (
        <Link
          key={entry.id}
          href={entry.href}
          aria-current={entry.current ? "page" : undefined}
          data-testid={`nav-${entry.id}`}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium outline-none transition-colors hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40",
            entry.current ? "text-shell-nav-active" : "text-shell-nav",
          )}
        >
          {entry.label}
          {entry.count > 0 ? (
            <span className="rounded-full bg-brand-violet px-1.5 text-xs text-white">{entry.count}</span>
          ) : null}
        </Link>
      ))}
    </nav>
  );
}
