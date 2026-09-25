"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { cn } from "cn";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { routes } from "@/config/routes";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * "Nouvelle intention": the second line of the navigation, drawn like the
 * others, as on the mockups.
 *
 * Its own component, not an entry of the list, for one reason: on
 * /intentions/new it is the place you are, and Intentions — its parent in
 * the registry — is not. The line is marked current, Intentions is not.
 *
 * On the rail it becomes an icon with the label as its accessible name and a
 * tooltip for everyone else.
 */
export function NewIntentionButton({
  collapsed,
  active,
  onNavigate,
}: {
  collapsed: boolean;
  active: boolean;
  onNavigate?: () => void;
}) {
  const t = useDictionary();
  const label = t.nav.newIntention;

  const button = (
    <Link
      href={routes.intentionNew()}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      data-testid="new-intention"
      className={cn(
        "flex items-center gap-5 rounded-lg py-[10px] pr-0 pl-4 text-[0.8125rem] leading-5 font-medium tracking-[-0.015em] transition-colors outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
        active
          ? "bg-brand-violet-soft text-shell-nav-active"
          : "text-shell-nav hover:bg-brand-violet-soft/60",
        collapsed ? "justify-center px-0" : "w-full",
      )}
    >
      <Plus className={cn("size-[22px] shrink-0", !active && "text-shell-icon")} aria-hidden="true" />
      <span className={cn(collapsed && "sr-only")}>{label}</span>
    </Link>
  );

  if (!collapsed) return button;

  return (
    <Tooltip>
      <TooltipTrigger render={<div />}>{button}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}
