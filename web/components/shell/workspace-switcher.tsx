"use client";

import { Check, ChevronRight } from "lucide-react";
import { cn } from "cn";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCurrentWorkspace, useWorkspaces } from "@/components/shell/shell-provider";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * Which company's LEKA you are looking at.
 *
 * Shows the active workspace and lists the ones this account may switch to.
 * TODO LEKA-331: `onSelect` is where the switch goes — it has to tell the
 * API, because the workspace is read from the session and never from the
 * client (architecture rule 3). Until then, choosing the active one is a
 * no-op and choosing another does nothing rather than lying about it.
 */
export function WorkspaceSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const t = useDictionary();
  const workspace = useCurrentWorkspace();
  const workspaces = useWorkspaces();

  const initials = (workspace?.name ?? "?").slice(0, 1).toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t.shell.switchWorkspace}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40",
          collapsed && "justify-center px-0",
        )}
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-brand-navy text-xs font-semibold text-white">
          {initials}
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-shell-nav">
                {workspace?.name ?? t.shell.noWorkspace}
              </span>
              <span className="block truncate text-xs text-shell-muted">
                {t.shell.workspace}
              </span>
            </span>
            <ChevronRight className="size-4 shrink-0 text-shell-muted" aria-hidden="true" />
          </>
        )}
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel>{t.shell.switchWorkspace}</DropdownMenuLabel>
          {workspaces.map((candidate) => (
            <DropdownMenuItem key={candidate.id} data-testid={`workspace-${candidate.slug}`}>
              <span className="flex-1 truncate">{candidate.name}</span>
              {candidate.id === workspace?.id && (
                <Check className="size-4 text-brand-violet" aria-hidden="true" />
              )}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
