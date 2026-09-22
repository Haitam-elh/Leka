/**
 * What the sidebar shows, and in what order.
 *
 * The shell RENDERS this list. No component in components/shell/ names an
 * entry, an icon or a route, so LEKA-338 — which owns the information
 * architecture — changes the product's navigation by editing this file and
 * the dictionary beside it, and nothing else.
 *
 * Labels are keys, not words: the interface speaks two languages. See
 * lib/i18n/dictionaries.ts.
 */

import {
  Activity,
  CreditCard,
  Home,
  Layers,
  LayoutGrid,
  type LucideIcon,
  Network,
  Plus,
  Search,
  Settings,
  Shield,
  ShieldCheck,
  Users,
} from "lucide-react";

import type { NavKey } from "@/lib/i18n/dictionaries";

/**
 * A number the shell may show beside an entry.
 *
 * The counts themselves belong to the features that produce them — how many
 * decisions are waiting is the approvals screen's business, not the shell's.
 * Until those exist, the shell is handed the numbers and shows them.
 */
export type BadgeKey = "pendingApprovals";

export interface NavigationEntry {
  /** Stable across renames and translations. Tests and `data-testid` use it. */
  id: string;
  labelKey: NavKey;
  href: string;
  icon: LucideIcon;
  badgeKey?: BadgeKey;
  /**
   * Hides the entry from whoever lacks it. Nothing evaluates this yet:
   * permissions are LEKA-402, and the shell must not invent its own.
   */
  requiredPermission?: string;
}

export const NAVIGATION: readonly NavigationEntry[] = [
  { id: "overview", labelKey: "overview", href: "/", icon: Home },
  { id: "new-intention", labelKey: "newIntention", href: "/intentions/new", icon: Plus },
  { id: "intentions", labelKey: "intentions", href: "/intentions", icon: Layers },
  { id: "environment", labelKey: "environment", href: "/environment", icon: Network },
  { id: "activity", labelKey: "activity", href: "/activity", icon: Activity },
  {
    id: "approvals",
    labelKey: "approvals",
    href: "/approvals",
    icon: ShieldCheck,
    badgeKey: "pendingApprovals",
  },
  { id: "capabilities", labelKey: "capabilities", href: "/capabilities", icon: LayoutGrid },
  { id: "sources", labelKey: "sources", href: "/sources", icon: Search },
  { id: "security", labelKey: "security", href: "/security", icon: Shield },
  { id: "team", labelKey: "team", href: "/team", icon: Users },
  { id: "billing", labelKey: "billing", href: "/billing", icon: CreditCard },
  { id: "settings", labelKey: "settings", href: "/settings", icon: Settings },
];

/**
 * Which entry a URL belongs to.
 *
 * Longest match wins, so /intentions/new lights up "New intention" rather
 * than "Intentions" — both prefixes match, and the more specific one is the
 * page the person is actually on. "/" only ever matches itself, or every
 * route would light up the overview.
 */
export function activeEntry(pathname: string): NavigationEntry | undefined {
  return [...NAVIGATION]
    .filter((entry) =>
      entry.href === "/"
        ? pathname === "/"
        : pathname === entry.href || pathname.startsWith(`${entry.href}/`),
    )
    .sort((a, b) => b.href.length - a.href.length)[0];
}
