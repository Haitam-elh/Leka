"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AppHeader } from "@/components/shell/app-header";
import { AppSidebar } from "@/components/shell/app-sidebar";
import { CommandPalette, useCommandShortcut } from "@/components/shell/command-palette";
import { SkipLink } from "@/components/shell/skip-link";
import { useShell } from "@/components/shell/shell-provider";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import type { BadgeKey } from "@/config/routes";
import { useDictionary } from "@/lib/i18n/locale-provider";
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
  const state = useShell();
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

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
    <div className="flex h-screen overflow-hidden bg-shell-canvas">
      <SkipLink />

      <aside
        id="app-sidebar"
        className={cn(
          "hidden shrink-0 border-r border-shell-line lg:block",
          collapsed ? "w-rail" : "w-sidebar",
        )}
      >
        <AppSidebar collapsed={collapsed} onToggle={toggle} badges={badges} />
      </aside>

      {/* Under 1024px. Escape closes it and the focus returns to the button
          that opened it — base-ui's dialog does both. */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent
          side="left"
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
          finalFocus={searchTrigger}
        />

        {/* tabIndex={-1} so the skip link can actually move focus here. */}
        <main id="main-content" tabIndex={-1} className="flex-1 overflow-y-auto outline-none">
          {state.status === "loading" && <Centred>{t.shell.loading}</Centred>}
          {state.status === "unreachable" && (
            <Centred>
              <p className="font-medium text-destructive">{t.shell.unreachableTitle}</p>
              <p className="mt-2 text-sm text-shell-muted">{state.detail}</p>
            </Centred>
          )}
          {state.status === "failed" && (
            <Centred>
              <p className="font-medium text-destructive">{state.detail}</p>
            </Centred>
          )}
          {state.status === "ready" && children}
        </main>
      </div>
    </div>
  );
}

function Centred({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center px-4 text-center text-sm text-shell-muted">
      <div className="max-w-md">{children}</div>
    </div>
  );
}
