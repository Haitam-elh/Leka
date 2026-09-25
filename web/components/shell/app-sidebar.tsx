"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { usePathname } from "next/navigation";
import { cn } from "cn";

import { Wordmark } from "@/components/brand/logo";
import { NewIntentionButton } from "@/components/shell/new-intention-button";
import { SidebarNavItem } from "@/components/shell/sidebar-nav-item";
import { UserMenu } from "@/components/shell/user-menu";
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher";
import { type BadgeKey, type RouteEntry } from "@/config/routes";
import { usePermissions } from "@/components/shell/shell-provider";
import { visibleRoutes } from "@/lib/navigation/access";
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
 * The navigation, as the mockups draw it: the logo, then ONE list — the way
 * home, the way to act, then every place — and who you are at the foot.
 * No group titles, no separators in the list (docs/product/mockups/01).
 *
 * Every line comes from config/routes.ts, in its order. No entry, route,
 * icon or label is named here, so changing the information architecture
 * means editing the registry and the dictionary — never a component.
 */
export function AppSidebar({ collapsed, onToggle, onNavigate, badges }: AppSidebarProps) {
  const t = useDictionary();
  const pathname = usePathname() ?? "/";
  const active = resolveActiveNavItem(pathname);
  // Only what this person may open: a list of links that refuse is a list
  // nobody trusts. The API refuses them too — see lib/navigation/access.ts.
  // Empty while the permissions are unknown, rather than the handful of
  // entries that happen to need none: half a navigation looks like a
  // product missing features, not like one still loading.
  const permissions = usePermissions();
  const inSidebar = permissions === null ? [] : visibleRoutes(permissions);
  // Home first; "Nouvelle intention" goes right under it, as on the mockup.
  const home = inSidebar.find((route) => route.id === "overview");
  const places = inSidebar.filter((route) => route !== home);

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
    <div className="group/sidebar flex h-full flex-col bg-shell-surface">
      <div
        className={cn(
          "flex items-start gap-2 pt-7 pr-3 pb-6 pl-7",
          collapsed && "justify-center px-0 pt-5 pb-4",
        )}
      >
        <div className={cn("min-w-0 flex-1", collapsed && "sr-only")}>
          <Wordmark className="h-[23px]" priority />
          <p className="mt-2.5 truncate text-[0.8125rem] text-shell-muted">{t.shell.tagline}</p>
        </div>
        {onToggle && (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={!collapsed}
            aria-controls="app-sidebar"
            aria-label={collapsed ? t.shell.expandSidebar : t.shell.collapseSidebar}
            data-testid="sidebar-toggle"
            className={cn(
              "rounded-lg p-1.5 text-shell-muted transition outline-none hover:bg-brand-violet-soft/60 hover:text-brand-violet focus-visible:opacity-100 focus-visible:ring-3 focus-visible:ring-brand-violet/40",
              // The mockup has no button here. It stays — folding is a real
              // feature — but out of sight until the sidebar is pointed at
              // or reached with the keyboard. Folded, it is the only way
              // back, so it shows.
              !collapsed && "opacity-0 group-hover/sidebar:opacity-100",
            )}
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
        className={cn("flex-1 space-y-1 overflow-y-auto px-3 pb-4", collapsed && "px-2")}
      >
        {home && item(home)}
        <NewIntentionButton
          collapsed={collapsed}
          active={active?.id === PRIMARY_ACTION_ID}
          onNavigate={onNavigate}
        />
        {places.map(item)}
      </nav>

      <div className={cn("border-t border-shell-line px-3.5 py-3", collapsed && "px-2")}>
        <UserMenu variant="sidebar" collapsed={collapsed} />
        <div className="my-2 border-t border-shell-line" aria-hidden="true" />
        <WorkspaceSwitcher collapsed={collapsed} />
      </div>
    </div>
  );
}
