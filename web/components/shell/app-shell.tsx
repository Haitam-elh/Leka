"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
import { cn } from "cn";

/** Remembered per browser, so folding the sidebar survives a reload. */
const COLLAPSED_KEY = "leka.sidebar.collapsed";

/** Below this, there is no room for labels beside the icons. */
const RAIL_BELOW = 1280;

/** And below this, no room for the sidebar at all: it becomes a drawer. */
const DRAWER_BELOW = 1024;

/**
 * The frame every authenticated page sits in.
 *
 * Three shapes, one component:
 *
 *   ≥ 1280px   sidebar with labels, foldable to the rail by hand
 *   1024–1279  the rail by default, unfoldable by hand
 *   < 1024px   a drawer behind the header's menu button
 *
 * The sidebar and the header do not scroll; the content does. That is what
 * `h-screen overflow-hidden` on the frame and `overflow-y-auto` on <main>
 * buy, and it is why no page needs to think about it.
 */
export function AppShell({
  children,
  badges,
  notificationCount = 0,
}: {
  children: React.ReactNode;
  badges?: Partial<Record<BadgeKey, number>>;
  notificationCount?: number;
}) {
  const t = useDictionary();
  const { dir } = useLocale();
  const state = useShell();
  const retry = useShellRetry();
  const [collapsed, setCollapsed] = useState(false);
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

  useEffect(() => {
    // The stored choice wins; without one, the viewport decides. Read after
    // mount, never during render: the server has neither a window nor a
    // localStorage, and guessing here is a hydration mismatch.
    let remembered: string | null = null;
    try {
      remembered = window.localStorage.getItem(COLLAPSED_KEY);
    } catch {
      // Storage refused. The viewport decides, every time.
    }
    setCollapsed(
      remembered === null ? window.innerWidth < RAIL_BELOW : remembered === "true",
    );
  }, []);

  useEffect(() => {
    // A drawer left open while the viewport grows becomes an overlay over a
    // sidebar that is already there.
    function onResize() {
      if (window.innerWidth >= DRAWER_BELOW) setDrawerOpen(false);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  function toggle() {
    setCollapsed((folded) => {
      const next = !folded;
      try {
        window.localStorage.setItem(COLLAPSED_KEY, String(next));
      } catch {
        // It still folds for this visit.
      }
      return next;
    });
  }

  return (
    <div className="flex h-screen overflow-hidden bg-shell-page">
      <SkipLink />

      {/* Named: a page with a side panel of its own used to have two
          unnamed "complementary" regions, and someone listing landmarks
          could not tell the sidebar from the panel. */}
      <aside
        id="app-sidebar"
        aria-label={t.shell.sidebar}
        className={cn(
          "hidden shrink-0 border-e border-shell-line lg:block",
          collapsed ? "w-rail" : "w-sidebar",
        )}
      >
        <AppSidebar collapsed={collapsed} onToggle={toggle} badges={badges} />
      </aside>

      {/* Under 1024px. Escape closes it and the focus returns to the button
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
          notificationCount={notificationCount}
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
          className="flex-1 overflow-y-auto outline-none"
        >
          {/* First in the content and pinned to its top: above what is on
              screen rather than over it — that stays readable, it just may
              be out of date — and inside the main landmark, where a screen
              reader navigating by region will find it. */}
          <div className="sticky top-0 z-10">
            <OfflineBanner />
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
