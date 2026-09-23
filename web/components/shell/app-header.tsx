"use client";

import { Bell, Menu, Search } from "lucide-react";

import { UserMenu } from "@/components/shell/user-menu";
import { useDictionary } from "@/lib/i18n/locale-provider";

interface AppHeaderProps {
  /** Opens the drawer, below 1024px where the sidebar is not on screen. */
  onOpenNavigation: () => void;
  /** Opens the command palette — the same thing ⌘K does. */
  onOpenSearch: () => void;
  /** So the palette can hand the keyboard back to the button that opened it. */
  searchTriggerRef?: React.RefObject<HTMLButtonElement | null>;
  /**
   * What sits in the middle of the header. LEKA-338 puts the real search and
   * its ⌘K palette here; until then the default is a picture of one.
   */
  search?: React.ReactNode;
  /** Mocked until notifications exist. Zero shows no dot. */
  notificationCount?: number;
}

export function AppHeader({
  onOpenNavigation,
  onOpenSearch,
  searchTriggerRef,
  search,
  notificationCount = 0,
}: AppHeaderProps) {
  const t = useDictionary();

  return (
    <header className="flex h-header shrink-0 items-center gap-3 border-b border-shell-line bg-white px-4 lg:px-6">
      <button
        type="button"
        onClick={onOpenNavigation}
        aria-label={t.shell.openNavigation}
        data-testid="open-navigation"
        className="rounded-lg p-2 text-shell-nav transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40 lg:hidden"
      >
        <Menu className="size-5" aria-hidden="true" />
      </button>

      <div className="min-w-0 flex-1">
        {search ?? <SearchTrigger onOpen={onOpenSearch} triggerRef={searchTriggerRef} />}
      </div>

      <button
        type="button"
        aria-label={t.shell.notifications}
        data-testid="notifications"
        className="relative rounded-lg p-2 text-shell-nav transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        <Bell className="size-5" aria-hidden="true" />
        {notificationCount > 0 && (
          <>
            <span
              aria-hidden="true"
              className="absolute top-1.5 right-1.5 size-2 rounded-full bg-shell-badge-foreground"
            />
            <span className="sr-only">{notificationCount}</span>
          </>
        )}
      </button>

      <UserMenu variant="header" />
    </header>
  );
}

/**
 * Looks like a search field, and is a button.
 *
 * It opens the palette; it does not accept text. A real input here would be
 * a second place to type, competing with the one the product is about — and
 * the palette it opens is where typing belongs.
 */
function SearchTrigger({
  onOpen,
  triggerRef,
}: {
  onOpen: () => void;
  triggerRef?: React.RefObject<HTMLButtonElement | null>;
}) {
  const t = useDictionary();

  return (
    <button
      ref={triggerRef}
      type="button"
      onClick={onOpen}
      data-testid="open-search"
      className="flex h-9 w-full max-w-xl items-center gap-2 rounded-lg bg-shell-canvas px-3 text-left text-sm text-shell-muted transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
    >
      <Search className="size-4 shrink-0" aria-hidden="true" />
      <span className="flex-1 truncate">{t.shell.searchPlaceholder}</span>
      <kbd className="rounded border border-shell-line bg-white px-1.5 py-0.5 text-xs">⌘K</kbd>
    </button>
  );
}
