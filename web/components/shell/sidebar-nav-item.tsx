"use client";

import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { cn } from "cn";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

interface SidebarNavItemProps {
  id: string;
  label: string;
  href: string;
  icon?: LucideIcon;
  /** This line is the page the person is on. */
  active: boolean;
  /** Icons only: the rail, between 1024 and 1279px, or when folded by hand. */
  collapsed: boolean;
  /** A line of a section: indented, under its name, without an icon. */
  nested?: boolean;
  badge?: number;
  /** Closes the drawer on small screens, where navigating leaves it open. */
  onNavigate?: () => void;
}

/**
 * One line of the navigation: a link to a page, or to a view of one
 * (LEKA-428, config/navigation.ts). The current page is `aria-current`:
 * one line, never two.
 */
export function SidebarNavItem({
  id,
  label,
  href,
  icon: Icon,
  active,
  collapsed,
  nested = false,
  badge,
  onNavigate,
}: SidebarNavItemProps) {
  const t = useDictionary();
  const counted = badge !== undefined && badge > 0;

  const link = (
    <Link
      href={href}
      onClick={onNavigate}
      // What a screen reader announces as "current page", and the only
      // machine-readable mark of where you are.
      aria-current={active ? "page" : undefined}
      data-testid={`nav-${id}`}
      className={cn(
        // Measured on the mockup: 42px tall, a 22px icon, the label at 70px
        // from the sidebar's edge. A nested line sits under its section's
        // name, shorter, its label where the section's starts.
        "group relative flex items-center rounded-lg pe-0 text-[0.8125rem] leading-5 font-medium tracking-[-0.015em] transition-colors outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
        nested ? "py-[7px] ps-[58px]" : "gap-5 py-[10px] ps-4",
        active
          ? "bg-brand-violet-soft text-shell-nav-active"
          : "text-shell-nav hover:bg-brand-violet-soft/60",
        collapsed && "justify-center px-0",
      )}
    >
      {Icon && !nested && (
        <Icon
          className={cn("size-[22px] shrink-0", !active && "text-shell-icon")}
          aria-hidden="true"
        />
      )}
      <span className={cn("flex-1 truncate", collapsed && "sr-only")}>{label}</span>

      {/* "À valider, 3 éléments en attente" — the number is part of the name
          the link is announced with, not a decoration beside it. */}
      {counted && (
        <span className="sr-only">{`, ${fill(t.shell.pendingApprovals, { count: badge })}`}</span>
      )}

      {counted &&
        (collapsed ? (
          <span
            aria-hidden="true"
            className="absolute top-1.5 end-3 size-1.5 rounded-full bg-shell-badge-foreground"
          />
        ) : (
          <span
            aria-hidden="true"
            className="me-2 rounded-full bg-shell-badge px-2 py-0.5 text-xs font-semibold text-shell-badge-foreground"
          >
            {badge}
          </span>
        ))}

      {/* No "Bientôt" pill and no padlock here: the mockup has neither. A
          page that is not built yet, or not in the plan, says so itself
          when opened (components/shell/placeholder-page.tsx). */}
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
