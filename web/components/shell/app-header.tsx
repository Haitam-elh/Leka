"use client";

import { BadgeCheck, Crown, Search } from "lucide-react";
import Link from "next/link";

import { Wordmark } from "@/components/brand/logo";
import { NotificationBell } from "@/components/notifications/bell";
import { MainNav, WaitingDecisions } from "@/components/shell/main-nav";
import { RunningIntentions } from "@/components/shell/running-intentions";
import { useShell } from "@/components/shell/shell-provider";
import { UserMenu } from "@/components/shell/user-menu";
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher";
import { routes } from "@/config/routes";
import { useCredits } from "@/lib/billing-queries";
import { ENTERPRISE, logoAddress, useLogo } from "@/lib/contract";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

interface AppHeaderProps {
  /** Opens the command palette — the same thing ⌘K does. */
  onOpenSearch: () => void;
  /** So the palette can hand the keyboard back to the button that opened it. */
  searchTriggerRef?: React.RefObject<HTMLButtonElement | null>;
}

const ICON_BUTTON =
  "rounded-lg p-2 text-shell-nav transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40";

/**
 * The header of the sprint's mockups (LEKA-455): the logo, the way home, on
 * the left, then the main pages (LEKA-494); the workspace, its plan and who
 * you are on the right — the pages of running it in the profile menu.
 * Search (⌘K) finds every page.
 */
export function AppHeader({ onOpenSearch, searchTriggerRef }: AppHeaderProps) {
  const t = useDictionary();
  // Nothing asked of the API before the session is known: a visitor signed
  // out is sent to sign in by the shell, not bounced by a 401 of the plan's.
  const shell = useShell();
  const ready = shell.status === "ready";
  // Under an Enterprise contract (2026-10-25): its badge and its logo, never
  // a plan to compare; « Contrat » in the menu.
  const enterprise = useCredits({ enabled: ready }).data?.plan === ENTERPRISE;

  return (
    <header className="flex h-header shrink-0 items-center gap-2 border-b border-shell-line bg-white px-4 lg:px-8">
      <Link
        href={routes.overview()}
        aria-label={t.shell.home}
        data-testid="home-logo"
        className="me-auto shrink-0 rounded-md outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40 xl:me-4"
      >
        <Wordmark className="h-[23px]" priority />
      </Link>
      {ready && <MainNav />}

      {ready && <RunningIntentions />}
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

      {/* What happened, told (LEKA-476): once the session is known. */}
      {ready ? <WaitingDecisions className={ICON_BUTTON} /> : null}
      {ready ? <NotificationBell className={ICON_BUTTON} /> : null}

      <div className="hidden sm:block">
        <WorkspaceSwitcher />
      </div>
      {ready ? enterprise ? <EnterpriseBadge name={shell.workspace?.name ?? ""} /> : <PlanBadge /> : null}
      <UserMenu contract={enterprise} />
    </header>
  );
}

const BADGE =
  "inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand-violet px-3 text-sm font-medium text-white capitalize outline-none";

/** « Entreprise » and its organisation's logo when its admin gave one —
 * its name, in the switcher beside it, otherwise; its contract one click
 * away. */
function EnterpriseBadge({ name }: { name: string }) {
  const t = useDictionary();
  const logo = useLogo();
  return (
    <span className="flex items-center gap-2">
      {logo ? (
        // eslint-disable-next-line @next/next/no-img-element -- the API serves it, sized by the header
        <img
          src={logoAddress(logo)}
          alt={fill(t.billing.contract.logoAlt, { name })}
          className="hidden h-8 max-w-28 object-contain md:block"
          data-testid="header-logo"
        />
      ) : null}
      <Link
        href={routes.billing()}
        aria-label={`${t.shell.enterprise} · ${t.shell.contract}`}
        data-testid="enterprise-badge"
        className={`${BADGE} hover:bg-brand-violet/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40`}
      >
        <BadgeCheck className="size-4" aria-hidden="true" />
        <span>{t.shell.enterprise}</span>
      </Link>
    </span>
  );
}

/** The workspace's plan, as metering reads it; the plans compared
 * (LEKA-466) — every member reads them, who pays changes them there.
 * Nothing until it is known: never a plan guessed. */
function PlanBadge() {
  const t = useDictionary();
  const plan = useCredits().data?.plan;
  if (!plan) return null;
  return (
    <Link
      href={routes.billingPlans()}
      aria-label={`${t.shell.plan} ${plan}`}
      data-testid="plan-badge"
      className={`${BADGE} hover:bg-brand-violet/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40`}
    >
      <Crown className="size-4" aria-hidden="true" />
      {/* Its name only where the header has room beside its pages. */}
      <span className="hidden sm:inline xl:hidden 2xl:inline">{plan}</span>
    </Link>
  );
}
