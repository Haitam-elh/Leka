"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { usePathname, useSearchParams } from "next/navigation";
import { Fragment, Suspense, useEffect, useRef, useState } from "react";
import { cn } from "cn";

import { Wordmark } from "@/components/brand/logo";
import { RailSection, SidebarSection } from "@/components/shell/sidebar-section";
import { SidebarNavItem } from "@/components/shell/sidebar-nav-item";
import { UserMenu } from "@/components/shell/user-menu";
import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher";
import type { NavGroup, NavSection } from "@/config/navigation";
import type { BadgeKey } from "@/config/routes";
import { usePermissions } from "@/components/shell/shell-provider";
import { activeNav, hrefOf, visibleNavigation } from "@/lib/navigation/tree";
import { useDictionary } from "@/lib/i18n/locale-provider";

/** Remembered per browser: the sections a person opened or closed. */
export const SECTIONS_KEY = "leka.sidebar.sections";

interface AppSidebarProps {
  collapsed: boolean;
  /** Absent inside the drawer, where folding makes no sense. */
  onToggle?: () => void;
  onNavigate?: () => void;
  badges?: Partial<Record<BadgeKey, number>>;
}

/**
 * The navigation (LEKA-428): the logo; the way home; the three pillars —
 * Intentions, Mon environnement, Capacités — each with what it is for and
 * its pages under it; what happened and what waits, across all three; and
 * Administration. Who you are at the foot.
 *
 * A section shows its pages when the person opened it, or when the page
 * they are on is in it; Intentions starts open. Short enough, closed, to
 * hold on a 13-inch screen whole.
 *
 * The hierarchy is config/navigation.ts's, the pages config/routes.ts's: no
 * entry, route, icon or label is named here, so changing the information
 * architecture means editing those and the dictionary — never a component.
 */
export function AppSidebar({ collapsed, onToggle, onNavigate, badges }: AppSidebarProps) {
  const t = useDictionary();
  // Where the rail's section menus are drawn: inside the landmark.
  const navigation = useRef<HTMLElement>(null);

  return (
    <div className="group/sidebar flex h-full flex-col bg-shell-surface">
      <div
        className={cn(
          "flex items-start gap-2 pt-7 pe-3 pb-6 ps-7",
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
        ref={navigation}
        aria-label={t.shell.mainNavigation}
        // 8px on the right, not 12: « Mon environnement » holds on one line
        // beside its chevron in the mockup's 224px.
        className={cn("flex-1 overflow-y-auto pe-2 pb-4 ps-3", collapsed && "px-2")}
      >
        {/* The view a line opens is in the query (`?tab=`), and reading the
            query needs a boundary for static rendering. Until it is read,
            the page is marked from its path alone. */}
        <Suspense
          fallback={
            <NavigationTree
              collapsed={collapsed}
              search=""
              onNavigate={onNavigate}
              badges={badges}
              container={navigation}
            />
          }
        >
          <LiveNavigationTree
            collapsed={collapsed}
            onNavigate={onNavigate}
            badges={badges}
            container={navigation}
          />
        </Suspense>
      </nav>

      <div className={cn("border-t border-shell-line px-3.5 py-3", collapsed && "px-2")}>
        <UserMenu variant="sidebar" collapsed={collapsed} />
        <div className="my-2 border-t border-shell-line" aria-hidden="true" />
        <WorkspaceSwitcher collapsed={collapsed} />
      </div>
    </div>
  );
}

type TreeProps = Pick<AppSidebarProps, "collapsed" | "onNavigate" | "badges"> & {
  container: React.RefObject<HTMLElement | null>;
};

function LiveNavigationTree(props: TreeProps) {
  const search = useSearchParams();
  return <NavigationTree {...props} search={search?.toString() ?? ""} />;
}

function readOpenSections(): Record<string, boolean> {
  try {
    const stored: unknown = JSON.parse(window.localStorage.getItem(SECTIONS_KEY) ?? "{}");
    if (stored === null || typeof stored !== "object" || Array.isArray(stored)) return {};
    return Object.fromEntries(
      Object.entries(stored).filter(
        (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
      ),
    );
  } catch {
    // Storage refused, or holding something else: the defaults, every time.
    return {};
  }
}

function NavigationTree({
  collapsed,
  search,
  onNavigate,
  badges,
  container,
}: TreeProps & { search: string }) {
  const t = useDictionary();
  const pathname = usePathname() ?? "/";
  const active = activeNav(pathname, search);
  // Only what this person may open: a list of links that refuse is a list
  // nobody trusts. The API refuses them too — see lib/navigation/access.ts.
  // Empty while the permissions are unknown, rather than the handful of
  // entries that happen to need none: half a navigation looks like a
  // product missing features, not like one still loading.
  const permissions = usePermissions();
  const groups: NavGroup[] = permissions === null ? [] : visibleNavigation(permissions);

  // What the person chose, section by section, remembered; a section never
  // touched follows its `defaultOpen` (config/navigation.ts). Read after
  // mount, never during render: the server has no localStorage, and
  // guessing is a hydration mismatch.
  const [chosen, setChosen] = useState<Record<string, boolean>>({});
  useEffect(() => {
    const remembered = readOpenSections();
    setChosen((current) => ({ ...remembered, ...current }));
  }, []);

  // Arriving on a page opens the section it is in, whatever was chosen:
  // the mark of where you are is never folded away on arrival. Not
  // remembered — and closed again if the person closes it.
  const activeSectionId = active.section?.id;
  const [arrivedIn, setArrivedIn] = useState(activeSectionId);
  const [seen, setSeen] = useState(activeSectionId);
  if (seen !== activeSectionId) {
    setSeen(activeSectionId);
    setArrivedIn(activeSectionId);
  }

  // The line you are on, in sight: on a short screen, a page low in the
  // list would otherwise be marked below the fold. The navigation scrolls,
  // not the line: Chrome moves where the next Tab starts to an element
  // scrolled into view, and Tab would land in the sidebar, skipping the
  // skip link.
  const activeLeafId = active.leaf?.id;
  useEffect(() => {
    const navigation = container.current;
    const line = navigation?.querySelector('[aria-current="page"]');
    if (!navigation || !line) return;
    const box = line.getBoundingClientRect();
    const view = navigation.getBoundingClientRect();
    if (box.bottom > view.bottom) navigation.scrollTop += box.bottom - view.bottom;
    else if (box.top < view.top) navigation.scrollTop -= view.top - box.top;
    // Once there are lines at all: the permissions arrive after the page.
  }, [activeLeafId, collapsed, container, groups.length]);

  function isOpen(section: NavSection): boolean {
    return section.id === arrivedIn || (chosen[section.id] ?? section.defaultOpen === true);
  }

  function toggle(section: NavSection) {
    const next = { ...chosen, [section.id]: !isOpen(section) };
    if (section.id === arrivedIn) setArrivedIn(undefined);
    setChosen(next);
    try {
      window.localStorage.setItem(SECTIONS_KEY, JSON.stringify(next));
    } catch {
      // It still folds for this visit.
    }
  }

  return (
    <>
      {groups.map((group, index) => (
        <Fragment key={group.id}>
          {index > 0 && (
            <div
              aria-hidden="true"
              className={cn("my-3 border-t border-shell-line", collapsed ? "mx-2" : "mx-4")}
            />
          )}
          <div className="space-y-1" data-testid={`nav-group-${group.id}`}>
            {group.nodes.map((node) => {
              if (node.kind === "leaf") {
                return (
                  <SidebarNavItem
                    key={node.id}
                    id={node.id}
                    label={t.nav[node.labelKey]}
                    href={hrefOf(node)}
                    icon={node.icon}
                    active={active.leaf?.id === node.id}
                    collapsed={collapsed}
                    badge={node.badgeKey ? badges?.[node.badgeKey] : undefined}
                    onNavigate={onNavigate}
                  />
                );
              }
              const activeLeaf = active.section?.id === node.id ? active.leaf : undefined;
              return collapsed ? (
                <RailSection
                  key={node.id}
                  section={node}
                  activeLeaf={activeLeaf}
                  badges={badges}
                  onNavigate={onNavigate}
                  container={container}
                />
              ) : (
                <SidebarSection
                  key={node.id}
                  section={node}
                  activeLeaf={activeLeaf}
                  badges={badges}
                  onNavigate={onNavigate}
                  open={isOpen(node)}
                  onToggle={() => toggle(node)}
                />
              );
            })}
          </div>
        </Fragment>
      ))}
    </>
  );
}
