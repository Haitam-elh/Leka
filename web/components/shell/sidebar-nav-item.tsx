"use client";

import { Lock } from "lucide-react";
import Link from "next/link";
import { cn } from "cn";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { RouteEntry } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

interface SidebarNavItemProps {
  entry: RouteEntry;
  /** The route the person is on belongs to this entry, or to one of its children. */
  active: boolean;
  /** Icons only: the rail, between 1024 and 1279px, or when folded by hand. */
  collapsed: boolean;
  badge?: number;
  /** Closes the drawer on small screens, where navigating leaves it open. */
  onNavigate?: () => void;
}

export function SidebarNavItem({
  entry,
  active,
  collapsed,
  badge,
  onNavigate,
}: SidebarNavItemProps) {
  const t = useDictionary();
  const label = t.nav[entry.labelKey];
  const Icon = entry.icon;
  const counted = badge !== undefined && badge > 0;
  const soon = entry.availability === "soon";
  const gated = entry.availability === "plan-gated";

  const link = (
    <Link
      href={entry.path}
      onClick={onNavigate}
      // What a screen reader announces as "current page", and the only
      // machine-readable mark of where you are.
      aria-current={active ? "page" : undefined}
      data-testid={`nav-${entry.id}`}
      className={cn(
        "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
        active
          ? "bg-brand-violet-soft text-brand-violet"
          : "text-shell-nav hover:bg-brand-violet-soft/60",
        collapsed && "justify-center px-0",
      )}
    >
      {Icon && <Icon className="size-[1.125rem] shrink-0" aria-hidden="true" />}
      <span className={cn("flex-1 truncate", collapsed && "sr-only")}>{label}</span>

      {/* "À valider, 3 éléments en attente" — the number is part of the name
          the link is announced with, not a decoration beside it. */}
      {counted && (
        <span className="sr-only">
          {`, ${fill(t.shell.pendingApprovals, { count: badge })}`}
        </span>
      )}

      {counted &&
        (collapsed ? (
          <span
            aria-hidden="true"
            className="absolute top-1.5 right-3 size-1.5 rounded-full bg-shell-badge-foreground"
          />
        ) : (
          <span
            aria-hidden="true"
            className="rounded-full bg-shell-badge px-2 py-0.5 text-xs font-semibold text-shell-badge-foreground"
          >
            {badge}
          </span>
        ))}

      {soon && !collapsed && (
        <span className="rounded-full bg-brand-violet-soft px-2 py-0.5 text-[0.6875rem] font-medium text-brand-violet">
          {t.shell.soon}
        </span>
      )}
      {gated && (
        <Lock
          className={cn("size-3.5 shrink-0 text-shell-muted", collapsed && "hidden")}
          aria-label={t.shell.planGated}
        />
      )}
    </Link>
  );

  if (!collapsed) return link;

  // Folded, the label stays in the accessibility tree; the tooltip puts it
  // back for everyone else.
  return (
    <Tooltip>
      <TooltipTrigger render={<div className="relative" />}>{link}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}
