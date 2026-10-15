"use client";

import { Crown, LayoutGrid, Search } from "lucide-react";
import Link from "next/link";

import { Wordmark } from "@/components/brand/logo";
import { usePermissions, useShell } from "@/components/shell/shell-provider";
import { UserMenu } from "@/components/shell/user-menu";
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher";
import { routes } from "@/config/routes";
import { useCredits } from "@/lib/billing-queries";
import { useDictionary } from "@/lib/i18n/locale-provider";

interface AppHeaderProps {
  /** Opens the drawer that holds every page. */
  onOpenNavigation: () => void;
  /** Opens the command palette — the same thing ⌘K does. */
  onOpenSearch: () => void;
  /** So the palette can hand the keyboard back to the button that opened it. */
  searchTriggerRef?: React.RefObject<HTMLButtonElement | null>;
}

const ICON_BUTTON =
  "rounded-lg p-2 text-shell-nav transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40";

/**
 * The header of the sprint's mockups (LEKA-455): the logo, the way home, on
 * the left; the workspace, its plan and who you are on the right. Search
 * (⌘K) and every page (the menu) sit before them: the mockups draw neither,
 * and both are features nothing else on screen gives.
 */
export function AppHeader({ onOpenNavigation, onOpenSearch, searchTriggerRef }: AppHeaderProps) {
  const t = useDictionary();
  // Nothing asked of the API before the session is known: a visitor signed
  // out is sent to sign in by the shell, not bounced by a 401 of the plan's.
  const ready = useShell().status === "ready";

  return (
    <header className="flex h-header shrink-0 items-center gap-2 border-b border-shell-line bg-white px-4 lg:px-8">
      <Link
        href={routes.overview()}
        aria-label={t.shell.home}
        data-testid="home-logo"
        className="me-auto rounded-md outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        <Wordmark className="h-[23px]" priority />
      </Link>

      <button
        ref={searchTriggerRef}
        type="button"
        onClick={onOpenSearch}
        aria-label={t.shell.searchPlaceholder}
        data-testid="open-search"
        className={ICON_BUTTON}
      >
        <Search className="size-5" aria-hidden="true" />
      </button>
      <button
        type="button"
        onClick={onOpenNavigation}
        aria-label={t.shell.openNavigation}
        data-testid="open-navigation"
        className={ICON_BUTTON}
      >
        <LayoutGrid className="size-5" aria-hidden="true" />
      </button>

      <div className="hidden sm:block">
        <WorkspaceSwitcher />
      </div>
      {ready && <PlanBadge />}
      <UserMenu variant="header" />
    </header>
  );
}

const BADGE =
  "inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand-violet px-3 text-sm font-medium text-white capitalize outline-none";

/** The workspace's plan, as metering reads it; to Facturation for who may
 * open it. Nothing until it is known: never a plan guessed. */
function PlanBadge() {
  const t = useDictionary();
  const plan = useCredits().data?.plan;
  // Facturation's own permission (config/routes.ts): a member sees the plan, no door.
  const pays = usePermissions()?.includes("workspace:update") ?? false;
  if (!plan) return null;
  const said = (
    <>
      <Crown className="size-4" aria-hidden="true" />
      {plan}
    </>
  );
  return pays ? (
    <Link
      href={routes.billing()}
      aria-label={`${t.shell.plan} ${plan}`}
      data-testid="plan-badge"
      className={`${BADGE} hover:bg-brand-violet/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40`}
    >
      {said}
    </Link>
  ) : (
    <span aria-label={`${t.shell.plan} ${plan}`} data-testid="plan-badge" className={BADGE}>
      {said}
    </span>
  );
}
