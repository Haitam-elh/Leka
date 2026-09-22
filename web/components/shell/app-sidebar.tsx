"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { usePathname } from "next/navigation";
import { cn } from "cn";

import { UserMenu } from "@/components/shell/user-menu";
import { SidebarNavItem } from "@/components/shell/sidebar-nav-item";
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher";
import { activeEntry, NAVIGATION } from "@/config/navigation";
import { useDictionary } from "@/lib/i18n/locale-provider";

interface AppSidebarProps {
  collapsed: boolean;
  /** Absent inside the drawer, where folding makes no sense. */
  onToggle?: () => void;
  onNavigate?: () => void;
  /** Counts the entries ask for by `badgeKey`. Mocked until their features exist. */
  badges?: Partial<Record<string, number>>;
}

/**
 * The navigation, the logo above it, and the person at the foot of it.
 *
 * Renders config/navigation.ts and nothing else: no entry, route or icon is
 * named here, so LEKA-338 reshapes the product's navigation without opening
 * this file.
 */
export function AppSidebar({ collapsed, onToggle, onNavigate, badges }: AppSidebarProps) {
  const t = useDictionary();
  const pathname = usePathname();
  const current = activeEntry(pathname ?? "/");

  return (
    <div className="flex h-full flex-col bg-shell-surface">
      <div
        className={cn(
          "flex items-center gap-2 px-4 py-5",
          collapsed && "justify-center px-0",
        )}
      >
        <div className={cn("min-w-0 flex-1", collapsed && "sr-only")}>
          <p className="text-xl font-bold tracking-tight text-brand-navy">
            LE<span className="text-brand-violet">KA</span>
          </p>
          <p className="mt-0.5 truncate text-xs text-shell-muted">{t.shell.tagline}</p>
        </div>
        {onToggle && (
          <button
            type="button"
            onClick={onToggle}
            // The pair a screen reader needs to announce what this does and
            // what state it is in. aria-controls names the region it folds.
            aria-expanded={!collapsed}
            aria-controls="app-sidebar"
            aria-label={collapsed ? t.shell.expandSidebar : t.shell.collapseSidebar}
            data-testid="sidebar-toggle"
            className="rounded-lg p-1.5 text-shell-muted transition-colors outline-none hover:bg-brand-violet-soft/60 hover:text-brand-violet focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          >
            {collapsed ? (
              <PanelLeftOpen className="size-4" aria-hidden="true" />
            ) : (
              <PanelLeftClose className="size-4" aria-hidden="true" />
            )}
          </button>
        )}
      </div>

      <nav
        aria-label={t.shell.mainNavigation}
        className={cn("flex-1 space-y-0.5 overflow-y-auto px-3 pb-4", collapsed && "px-2")}
      >
        {NAVIGATION.map((entry) => (
          <SidebarNavItem
            key={entry.id}
            entry={entry}
            active={current?.id === entry.id}
            collapsed={collapsed}
            badge={entry.badgeKey ? badges?.[entry.badgeKey] : undefined}
            onNavigate={onNavigate}
          />
        ))}
      </nav>

      <div
        className={cn(
          "space-y-1 border-t border-shell-line px-3 py-3",
          collapsed && "px-2",
        )}
      >
        <UserMenu variant="sidebar" collapsed={collapsed} />
        <WorkspaceSwitcher collapsed={collapsed} />
      </div>
    </div>
  );
}
