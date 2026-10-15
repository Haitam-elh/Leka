"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { DemoBanner } from "@/components/demo/demo";
import { entityHref, typeLabel } from "@/components/environment/parts";
import { AppHeader } from "@/components/shell/app-header";
import { LanguageNotice } from "@/components/language/account-language";
import { AppSidebar } from "@/components/shell/app-sidebar";
import { CommandPalette, useCommandShortcut } from "@/components/shell/command-palette";
import { SkipLink } from "@/components/shell/skip-link";
import { useShell, useShellRetry } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { OfflineBanner } from "@/components/states/offline-banner";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import type { BadgeKey } from "@/config/routes";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { knowledgeGraph } from "@/lib/knowledge-graph";
import { knowledgeSearchProvider } from "@/lib/search";

/**
 * The frame every authenticated page sits in (LEKA-455, the sprint's
 * mockups): a header across the top — the logo, the workspace, the plan,
 * who you are — and no permanent sidebar. Every page stays one click away:
 * the header's menu opens the whole navigation in a drawer, at every width.
 *
 * The header does not scroll; the content does. That is what `h-screen
 * overflow-hidden` on the frame and `overflow-y-auto` on <main> buy, and it
 * is why no page needs to think about it.
 */
export function AppShell({
  children,
  badges,
}: {
  children: React.ReactNode;
  badges?: Partial<Record<BadgeKey, number>>;
}) {
  const t = useDictionary();
  const { dir } = useLocale();
  const state = useShell();
  const retry = useShellRetry();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  // ⌘K finds what the company model knows (LEKA-369).
  const search = useMemo(
    () =>
      knowledgeSearchProvider(
        (type) => typeLabel(t, type),
        entityHref,
        (q) => knowledgeGraph.search(q, { limit: 8 }),
      ),
    [t],
  );

  const searchTrigger = useRef<HTMLButtonElement>(null);

  useCommandShortcut(useCallback(() => setSearchOpen(true), []));

  return (
    // `relative` on the frame and on <main>: what a page positions absolutely
    // — a label only screen readers read, a menu — is held inside them. Not
    // held, it is placed against the document, makes it taller than the
    // window, and the whole frame scrolls away, white below (2026-10-14).
    <div className="relative flex h-screen overflow-hidden bg-shell-page">
      <SkipLink />

      {/* Every page, from the header's menu. Escape closes it and the focus returns to the button
          that opened it — base-ui's dialog does both. */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent
          side={dir === "rtl" ? "right" : "left"}
          showCloseButton={false}
          className="w-sidebar max-w-[85vw] p-0"
        >
          <SheetTitle className="sr-only">{t.shell.mainNavigation}</SheetTitle>
          <AppSidebar collapsed={false} onNavigate={() => setDrawerOpen(false)} badges={badges} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader
          onOpenNavigation={() => setDrawerOpen(true)}
          onOpenSearch={() => setSearchOpen(true)}
          searchTriggerRef={searchTrigger}
        />

        <CommandPalette
          open={searchOpen}
          onOpenChange={setSearchOpen}
          search={search}
          finalFocus={searchTrigger}
        />

        {/* tabIndex={-1} so the skip link can actually move focus here.
            aria-busy while the session is being asked for: assistive
            technology waits rather than reading a half-drawn page. */}
        <main
          id="main-content"
          tabIndex={-1}
          aria-busy={state.status === "loading" || undefined}
          className="relative flex-1 overflow-y-auto outline-none"
        >
          {/* First in the content and pinned to its top: above what is on
              screen rather than over it — that stays readable, it just may
              be out of date — and inside the main landmark, where a screen
              reader navigating by region will find it. */}
          <div className="sticky top-0 z-10">
            <OfflineBanner />
            {/* In a demonstration: fictive, reaching nothing — said, with the way out. */}
            {state.status === "ready" && <DemoBanner />}
            {/* An account with no language yet: the one found, kept or changed. */}
            {state.status === "ready" && <LanguageNotice />}
          </div>
          {state.status === "loading" && <LoadingState />}
          {state.status === "failed" && (
            <ErrorState error={state.error} onRetry={retry} headingLevel={1} />
          )}
          {state.status === "ready" && children}
        </main>
      </div>
    </div>
  );
}
