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
import { ActivityIcon } from "@/components/shell/nav-icons";
import { useCurrentWorkspace, useWorkspaces } from "@/components/shell/shell-provider";
import { routes } from "@/config/routes";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { workspace as session } from "@/lib/workspace";

/**
 * Which company's LEKA you are looking at.
 *
 * Shows the active workspace and lists the ones this account may switch to.
 * Choosing another tells the API — the workspace is read from the session,
 * never from the client (architecture rule 3) — then reloads on its
 * overview: nothing cached from the previous one survives.
 */
export function WorkspaceSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const t = useDictionary();
  const workspace = useCurrentWorkspace();
  const workspaces = useWorkspaces();

  async function open(id: string) {
    if (id === workspace?.id) return;
    try {
      await session.enter(id);
      window.location.assign(routes.overview());
    } catch {
      notify.error({ title: t.shell.switchFailed });
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t.shell.switchWorkspace}
        className={cn(
          "flex w-full items-center gap-[15px] rounded-lg px-3 py-2 text-start transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40",
          collapsed && "justify-center px-0",
        )}
      >
        {/* A soft violet tile with a mark, as on the mockup — the same for
            every workspace until a workspace can upload its own logo. */}
        <span className="flex size-[34px] shrink-0 items-center justify-center rounded-lg bg-brand-violet-soft text-shell-nav-active">
          <ActivityIcon className="size-4" aria-hidden="true" />
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
            <ChevronRight className="rtl:-scale-x-100 size-4 shrink-0 text-shell-muted" aria-hidden="true" />
          </>
        )}
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel>{t.shell.switchWorkspace}</DropdownMenuLabel>
          {workspaces.map((candidate) => (
            <DropdownMenuItem
              key={candidate.id}
              data-testid={`workspace-${candidate.slug}`}
              onClick={() => void open(candidate.id)}
            >
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
