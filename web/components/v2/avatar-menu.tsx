"use client";

import {
  CreditCard,
  Database,
  History,
  LayoutDashboard,
  LogOut,
  ShieldCheck,
  Users,
} from "lucide-react";
import { useRouter } from "next/navigation";

import { signOut } from "@/components/shell/user-menu";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { routes } from "@/config/routes";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { V2 } from "@/config/v2-routes";

/** The avatar's menu (2026-10-14, the product call): Configuration —
 * sources, sécurité, équipe —, Facturation, Historique, Déconnexion. Only
 * what the person may open: the API refuses the rest anyway. */
export function AvatarMenu() {
  const t = useDictionary();
  const w = t.v2.menu;
  const router = useRouter();
  const user = useCurrentUser();
  const may = usePermissions() ?? [];
  const email = user?.email ?? "";
  const given = [user?.first_name, user?.last_name].filter(Boolean).join(" ");
  const initials =
    [user?.first_name, user?.last_name]
      .map((part) => part?.trim().slice(0, 1).toUpperCase() ?? "")
      .join("") ||
    email.slice(0, 1).toUpperCase() ||
    "?";
  const go = (href: string) => () => router.push(href);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={w.account}
        data-testid="v2-avatar"
        className="flex size-9 items-center justify-center rounded-full bg-brand-violet/10 text-xs font-semibold text-brand-violet outline-none hover:bg-brand-violet/15 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        {initials}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-normal">
            {given ? <span className="block truncate font-medium text-brand-navy">{given}</span> : null}
            <span className="block truncate text-shell-muted">{email}</span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-xs text-shell-muted">{w.configuration}</DropdownMenuLabel>
          {may.includes("source:read") ? (
            <DropdownMenuItem onClick={go(routes.sources())} data-testid="v2-menu-sources">
              <Database className="size-4" aria-hidden="true" />
              {w.sources}
            </DropdownMenuItem>
          ) : null}
          {may.includes("workspace:update") ? (
            <DropdownMenuItem onClick={go(routes.governance())} data-testid="v2-menu-security">
              <ShieldCheck className="size-4" aria-hidden="true" />
              {w.security}
            </DropdownMenuItem>
          ) : null}
          {may.includes("member:invite") ? (
            <DropdownMenuItem onClick={go(routes.team())} data-testid="v2-menu-team">
              <Users className="size-4" aria-hidden="true" />
              {w.team}
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          {may.includes("workspace:update") ? (
            <DropdownMenuItem onClick={go(routes.billing())} data-testid="v2-menu-billing">
              <CreditCard className="size-4" aria-hidden="true" />
              {w.billing}
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuItem onClick={go(V2.history)} data-testid="v2-menu-history">
            <History className="size-4" aria-hidden="true" />
            {w.history}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={go(routes.overview())} data-testid="v2-menu-classic">
            <LayoutDashboard className="size-4" aria-hidden="true" />
            {w.classic}
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem onClick={() => void signOut()} data-testid="v2-menu-sign-out">
            <LogOut className="size-4" aria-hidden="true" />
            {w.signOut}
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
