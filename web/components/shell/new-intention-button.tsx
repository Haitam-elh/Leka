"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { cn } from "cn";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { routes } from "@/config/routes";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * The way into the product's one real workflow.
 *
 * A button, not a line in the list, and that is the decision this ticket
 * makes: everything else in the sidebar is somewhere to look, this is the
 * thing to do. Twelve lines of equal weight bury it.
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
        "flex items-center gap-2 rounded-lg bg-brand-navy px-3 py-2 text-sm font-medium text-white transition-colors outline-none hover:bg-brand-navy/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40",
        active && "ring-3 ring-brand-violet/40",
        collapsed ? "justify-center px-0" : "w-full",
      )}
    >
      <Plus className="size-[1.125rem] shrink-0" aria-hidden="true" />
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
