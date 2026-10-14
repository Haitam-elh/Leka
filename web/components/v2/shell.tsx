"use client";

import Link from "next/link";

import { Mark } from "@/components/brand/logo";
import { AvatarMenu } from "@/components/v2/avatar-menu";
import { HealthDot } from "@/components/v2/health";
import { V2 } from "@/config/v2-routes";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * The new interface's frame (2026-10-14, the product call's Lot 6): no
 * sidebar, no dashboard. Two screens — the home and its bar, the agents —
 * and, top right, the environment's health and the avatar's menu. The rest
 * of LEKA — sources, team, billing — opens from the menu, as it is today.
 */
export function V2Shell({ children }: { children: React.ReactNode }) {
  const t = useDictionary();
  return (
    <div className="flex min-h-dvh flex-col bg-shell-canvas" data-testid="v2-shell">
      <a
        href="#v2-main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:start-2 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2 focus:text-sm"
      >
        {t.shell.skipToContent}
      </a>
      <header className="flex items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <Link
          href={V2.home}
          className="flex items-center gap-2 rounded-md outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          aria-label={t.v2.home}
        >
          <Mark className="h-6" />
          <span className="rounded-full bg-brand-violet-soft px-2 py-0.5 text-xs font-medium text-brand-violet">
            {t.v2.beta}
          </span>
        </Link>
        <div className="flex items-center gap-2">
          <HealthDot />
          <AvatarMenu />
        </div>
      </header>
      <main id="v2-main" tabIndex={-1} className="flex-1 px-4 pb-16 outline-none sm:px-6">
        {children}
      </main>
    </div>
  );
}
