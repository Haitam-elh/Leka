"use client";

import { Menu as MenuPrimitive } from "@base-ui/react/menu";
import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { cn } from "cn";

import { SidebarNavItem } from "@/components/shell/sidebar-nav-item";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { BadgeKey } from "@/config/routes";
import type { NavLeaf, NavSection } from "@/config/navigation";
import { hrefOf } from "@/lib/navigation/tree";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

interface SectionProps {
  section: NavSection;
  /** The line that is the current page, when it is in this section. */
  activeLeaf?: NavLeaf;
  badges?: Partial<Record<BadgeKey, number>>;
  onNavigate?: () => void;
}

/** What waits in a section's lines — À valider's count, in Intentions. */
export function waitingIn(
  section: NavSection,
  badges: Partial<Record<BadgeKey, number>> | undefined,
): number {
  return section.children.reduce(
    (sum, child) => sum + (child.badgeKey ? (badges?.[child.badgeKey] ?? 0) : 0),
    0,
  );
}

/**
 * A part of the product that folds (LEKA-428): its name — and, for the
 * three pillars, what it is for — and its lines under it. A disclosure, not
 * a link: the name opens and closes, the lines go. The section holding the
 * current page says so, folded or not.
 */
export function SidebarSection({
  section,
  activeLeaf,
  badges,
  onNavigate,
  open,
  onToggle,
}: SectionProps & { open: boolean; onToggle: () => void }) {
  const t = useDictionary();
  const Icon = section.icon;
  const holds = activeLeaf !== undefined;
  const listId = `nav-section-${section.id}-lines`;
  const pillar = section.tier === "pillar";
  // Folded, the section says what waits in it: its lines cannot.
  const waiting = open ? 0 : waitingIn(section, badges);

  const home = section.home;
  if (home) {
    // Its name opens its page — and unfolds it; the chevron alone folds
    // (2026-10-14).
    const here = activeLeaf?.id === home.id;
    return (
      <div data-testid={`nav-section-${section.id}`} data-active={holds || undefined}>
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start rounded-lg transition-colors hover:bg-brand-violet-soft/60">
          <Link
            href={hrefOf(home)}
            aria-current={here ? "page" : undefined}
            data-testid={`nav-${home.id}`}
            onClick={() => {
              if (!open) onToggle();
              onNavigate?.();
            }}
            className="grid grid-cols-[22px_minmax(0,1fr)] items-center gap-x-5 rounded-lg py-[10px] ps-4 text-start outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          >
            <Icon
              className={cn(
                "size-[22px] shrink-0",
                holds ? "text-shell-nav-active" : pillar ? "text-shell-icon" : "text-shell-muted",
              )}
              aria-hidden="true"
            />
            <span
              className={cn(
                "text-[0.8125rem] leading-5 tracking-[-0.015em]",
                pillar ? "font-semibold" : "font-medium",
                holds ? "text-shell-nav-active" : pillar ? "text-shell-nav" : "text-shell-muted",
              )}
            >
              {t.nav[section.labelKey]}
            </span>
            {section.hintKey ? (
              <span className="col-start-2 mt-0.5 text-[0.6875rem] leading-4 text-shell-muted">
                {t.pillars[section.hintKey]}
              </span>
            ) : null}
          </Link>
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            aria-controls={listId}
            aria-label={t.nav[section.labelKey]}
            data-testid={`nav-section-${section.id}-toggle`}
            className="mt-[10px] me-1 rounded p-1 outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          >
            <ChevronDown
              className={cn("size-3.5 shrink-0 text-shell-muted transition-transform", !open && "-rotate-90")}
              aria-hidden="true"
            />
          </button>
        </div>
        <Lines
          section={section}
          listId={listId}
          open={open}
          activeLeaf={activeLeaf}
          badges={badges}
          onNavigate={onNavigate}
        />
      </div>
    );
  }

  return (
    <div data-testid={`nav-section-${section.id}`} data-active={holds || undefined}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={listId}
        data-testid={`nav-section-${section.id}-toggle`}
        // The icon and the name where a line's are — 22px, at 70px from the
        // edge — the chevron in what is left, and what the pillar is for
        // under the name, as wide as the row allows.
        className="grid w-full grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-x-5 rounded-lg py-[10px] pe-1 ps-4 text-start transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        <Icon
          className={cn(
            "size-[22px] shrink-0",
            holds ? "text-shell-nav-active" : pillar ? "text-shell-icon" : "text-shell-muted",
          )}
          aria-hidden="true"
        />
        <span
          className={cn(
            "text-[0.8125rem] leading-5 tracking-[-0.015em]",
            pillar ? "font-semibold" : "font-medium",
            holds ? "text-shell-nav-active" : pillar ? "text-shell-nav" : "text-shell-muted",
          )}
        >
          {t.nav[section.labelKey]}
        </span>
        <span className="-ms-4 flex items-center gap-1.5">
          {waiting > 0 ? (
            <>
              <span className="sr-only">{`, ${fill(t.shell.pendingApprovals, { count: waiting })}`}</span>
              <span
                aria-hidden="true"
                data-testid={`nav-section-${section.id}-badge`}
                className="rounded-full bg-shell-badge px-2 py-0.5 text-xs font-semibold text-shell-badge-foreground"
              >
                {waiting}
              </span>
            </>
          ) : null}
          <ChevronDown
            className={cn(
              "size-3.5 shrink-0 text-shell-muted transition-transform",
              !open && "-rotate-90",
            )}
            aria-hidden="true"
          />
        </span>
        {section.hintKey ? (
          <span className="col-span-2 col-start-2 mt-0.5 text-[0.6875rem] leading-4 text-shell-muted">
            {t.pillars[section.hintKey]}
          </span>
        ) : null}
      </button>
      <Lines
        section={section}
        listId={listId}
        open={open}
        activeLeaf={activeLeaf}
        badges={badges}
        onNavigate={onNavigate}
      />
    </div>
  );
}

function Lines({
  section,
  listId,
  open,
  activeLeaf,
  badges,
  onNavigate,
}: SectionProps & { listId: string; open: boolean }) {
  const t = useDictionary();
  return (
    <ul id={listId} hidden={!open} className="mt-0.5 space-y-0.5">
      {section.children.map((child) => (
        <li key={child.id}>
          <SidebarNavItem
            id={child.id}
            label={t.nav[child.labelKey]}
            href={hrefOf(child)}
            active={activeLeaf?.id === child.id}
            collapsed={false}
            nested
            badge={child.badgeKey ? badges?.[child.badgeKey] : undefined}
            onNavigate={onNavigate}
          />
        </li>
      ))}
    </ul>
  );
}

/**
 * A section on the rail: its icon, and its lines in a menu beside it. The
 * section holding the current page is marked, and, opened, so is the line.
 *
 * The menu is drawn inside the navigation landmark (`container`), not at the
 * end of the page: its links are the navigation's, and a screen reader
 * listing landmarks finds them there. Positioned `fixed`, the rail's
 * scrolling does not clip it.
 */
export function RailSection({
  section,
  activeLeaf,
  badges,
  onNavigate,
  container,
}: SectionProps & { container?: React.RefObject<HTMLElement | null> }) {
  const t = useDictionary();
  const Icon = section.icon;
  const holds = activeLeaf !== undefined;
  const waiting = waitingIn(section, badges);
  const label = t.nav[section.labelKey];
  const hint = section.hintKey ? t.pillars[section.hintKey] : null;
  const [menuOpen, setMenuOpen] = useState(false);
  const [tipOpen, setTipOpen] = useState(false);

  return (
    <MenuPrimitive.Root open={menuOpen} onOpenChange={setMenuOpen}>
      {/* The name on hover, until the menu says it itself. */}
      <Tooltip open={tipOpen && !menuOpen} onOpenChange={setTipOpen}>
        <TooltipTrigger
          render={
            <MenuPrimitive.Trigger
              // The name on its own: the icon says nothing to a screen reader.
              aria-label={[
                label,
                holds ? t.shell.currentSection : null,
                waiting > 0 ? fill(t.shell.pendingApprovals, { count: waiting }) : null,
              ]
                .filter(Boolean)
                .join(", ")}
              data-testid={`nav-section-${section.id}-toggle`}
              data-active={holds || undefined}
              className={cn(
                "relative flex w-full justify-center rounded-lg py-[10px] transition-colors outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                holds
                  ? "bg-brand-violet-soft text-shell-nav-active"
                  : "text-shell-icon hover:bg-brand-violet-soft/60",
              )}
            />
          }
        >
          <Icon className="size-[22px] shrink-0" aria-hidden="true" />
          {waiting > 0 ? (
            <span
              aria-hidden="true"
              className="absolute top-1.5 end-3 size-1.5 rounded-full bg-shell-badge-foreground"
            />
          ) : null}
        </TooltipTrigger>
        <TooltipContent side="right">{hint ? `${label} — ${hint}` : label}</TooltipContent>
      </Tooltip>
      <MenuPrimitive.Portal container={container}>
        <MenuPrimitive.Positioner
          side="right"
          align="start"
          sideOffset={8}
          positionMethod="fixed"
          className="isolate z-50 outline-none"
        >
          <MenuPrimitive.Popup
            data-testid={`nav-section-${section.id}-menu`}
            className="z-50 max-h-(--available-height) w-64 origin-(--transform-origin) overflow-y-auto rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95"
          >
            <MenuPrimitive.Group>
              <MenuPrimitive.GroupLabel className="px-1.5 py-1 text-xs font-semibold text-brand-navy">
                {label}
                {hint ? (
                  <span className="block font-normal text-shell-muted">{hint}</span>
                ) : null}
              </MenuPrimitive.GroupLabel>
              {[...(section.home ? [section.home] : []), ...section.children].map((child) => {
                const current = activeLeaf?.id === child.id;
                return (
                  // A link, not a button that navigates: it opens in a new
                  // tab, shows where it goes, and says it is the current page.
                  <MenuPrimitive.LinkItem
                    key={child.id}
                    closeOnClick
                    data-testid={`nav-${child.id}`}
                    aria-current={current ? "page" : undefined}
                    render={<Link href={hrefOf(child)} onClick={onNavigate} />}
                    className={cn(
                      "flex items-center rounded-md px-1.5 py-1.5 text-sm outline-hidden select-none focus:bg-accent focus:text-accent-foreground",
                      current ? "font-semibold text-shell-nav-active" : "text-shell-nav",
                    )}
                  >
                    <span className="flex-1">{t.nav[child.labelKey]}</span>
                    {child.badgeKey && (badges?.[child.badgeKey] ?? 0) > 0 ? (
                      <span className="rounded-full bg-shell-badge px-2 py-0.5 text-xs font-semibold text-shell-badge-foreground">
                        {badges?.[child.badgeKey]}
                      </span>
                    ) : null}
                  </MenuPrimitive.LinkItem>
                );
              })}
            </MenuPrimitive.Group>
          </MenuPrimitive.Popup>
        </MenuPrimitive.Positioner>
      </MenuPrimitive.Portal>
    </MenuPrimitive.Root>
  );
}
