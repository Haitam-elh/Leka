"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { usePathname } from "next/navigation";
import { cn } from "cn";

import { NewIntentionButton } from "@/components/shell/new-intention-button";
import { SidebarNavItem } from "@/components/shell/sidebar-nav-item";
import { UserMenu } from "@/components/shell/user-menu";
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher";
import { type BadgeKey, NAV_GROUPS, type RouteEntry, ROUTES } from "@/config/routes";
import { PRIMARY_ACTION_ID, resolveActiveNavItem } from "@/lib/navigation/active";
import { useDictionary } from "@/lib/i18n/locale-provider";

interface AppSidebarProps {
  collapsed: boolean;
  /** Absent inside the drawer, where folding makes no sense. */
  onToggle?: () => void;
  onNavigate?: () => void;
  badges?: Partial<Record<BadgeKey, number>>;
}

/**
 * The navigation: the way home, the way to act, and three groups of places.
 *
 * Every line comes from config/routes.ts. No entry, route, icon or label is
 * named here, so changing the information architecture means editing the
 * registry and the dictionary — never a component.
 */
export function AppSidebar({ collapsed, onToggle, onNavigate, badges }: AppSidebarProps) {
  const t = useDictionary();
  const pathname = usePathname() ?? "/";
  const active = resolveActiveNavItem(pathname);

  const inSidebar = ROUTES.filter((route) => route.showInSidebar);
  const standalone = inSidebar.filter((route) => route.group === undefined);
  const grouped = (group: string): RouteEntry[] =>
    inSidebar.filter((route) => route.group === group);

  function item(route: RouteEntry) {
    return (
      <SidebarNavItem
        key={route.id}
        entry={route}
        active={active?.id === route.id}
        collapsed={collapsed}
        badge={route.badgeKey ? badges?.[route.badgeKey] : undefined}
        onNavigate={onNavigate}
      />
    );
  }

  return (
    <div className="flex h-full flex-col bg-shell-surface">
      <div className={cn("flex items-center gap-2 px-4 py-5", collapsed && "justify-center px-0")}>
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

      <div className={cn("px-3 pb-3", collapsed && "px-2")}>
        <NewIntentionButton
          collapsed={collapsed}
          active={active?.id === PRIMARY_ACTION_ID}
          onNavigate={onNavigate}
        />
      </div>

      <nav
        aria-label={t.shell.mainNavigation}
        className={cn("flex-1 overflow-y-auto px-3 pb-4", collapsed && "px-2")}
      >
        <div className="space-y-0.5">{standalone.map(item)}</div>

        {NAV_GROUPS.map((group) => {
          const entries = grouped(group);
          if (entries.length === 0) return null;
          return (
            <div key={group} className="mt-5 space-y-0.5">
              {/* A quiet title, no rule across the sidebar: the mockups have
                  no separators, and a group is a hint, not a wall. */}
              <p
                className={cn(
                  "px-3 pb-1 text-[0.6875rem] font-semibold tracking-wide text-shell-muted uppercase",
                  collapsed && "sr-only",
                )}
              >
                {t.groups[group]}
              </p>
              {entries.map(item)}
            </div>
          );
        })}
      </nav>

      <div className={cn("space-y-1 border-t border-shell-line px-3 py-3", collapsed && "px-2")}>
        <UserMenu variant="sidebar" collapsed={collapsed} />
        <WorkspaceSwitcher collapsed={collapsed} />
      </div>
    </div>
  );
}
