/**
 * The sidebar, as LEKA-428 draws it: what a customer can do with LEKA, at a
 * glance.
 *
 *   Vue d'ensemble                 the way home
 *   Intentions                     Dites à LEKA ce que vous voulez accomplir.
 *     Nouvelle intention · Mes intentions
 *   Mon environnement              Le système vivant de votre entreprise.
 *     Vue globale · Applications · Infrastructure · Données · Dépendances
 *     · Équipes · Événements · Domaines
 *   Capacités                      Votre équipe technologique à la demande.
 *     Capacités disponibles · Mes capacités · Configuration
 *   Activité · À valider           across all three: what happened, what
 *                                  waits on someone
 *   Administration                 Sources · Sécurité & gouvernance
 *                                  · Équipe & accès · Facturation · Paramètres
 *
 * THREE PILLARS, nothing technical: the knowledge graph, agents, skills are
 * how LEKA does it, not what a customer comes for — they show through the
 * pillars, never beside them.
 *
 * This file is the HIERARCHY. Which pages exist, their paths, who may open
 * them, their breadcrumb, stay config/routes.ts's: an entry here names the
 * route it opens (`routeId`) and, for a view of a page, the `query` that
 * opens that view — `/environment?tab=applications`. No route was added,
 * renamed or removed for it; every page keeps its address.
 *
 * No component names an entry, a label or a path: lib/navigation/tree.ts
 * reads this, the sidebar and the palette draw it.
 */

import { Home, Layers, type LucideIcon, ShieldCheck, SlidersHorizontal } from "lucide-react";

import type { BadgeKey } from "@/config/routes";
import { ActivityIcon, CapabilitiesIcon, EnvironmentIcon } from "@/components/shell/nav-icons";
import type { NavKey, PillarKey } from "@/lib/i18n/dictionaries";

/** A line that opens a page — or a view of one. */
export interface NavLeaf {
  kind: "leaf";
  id: string;
  labelKey: NavKey;
  /** The page it opens, in config/routes.ts: its path, permission, availability. */
  routeId: string;
  /** The view of that page it opens: `{ tab: "applications" }`. */
  query?: Readonly<Record<string, string>>;
  /** Top-level lines only: nested ones are drawn without. */
  icon?: LucideIcon;
  badgeKey?: BadgeKey;
}

/** A part of the product that folds: its lines under it. */
export interface NavSection {
  kind: "section";
  id: string;
  labelKey: NavKey;
  /** What it is for, in a sentence: the three pillars say it. */
  hintKey?: PillarKey;
  icon: LucideIcon;
  /** A pillar is the product; administration is about running it. */
  tier: "pillar" | "administration";
  /** Open for someone who never opened or closed it. The rest open when
   * the page you are on is in them, so a 13-inch screen holds the whole
   * navigation, Activité and À valider included. */
  defaultOpen?: boolean;
  children: readonly NavLeaf[];
}

export type NavNode = NavLeaf | NavSection;

/** Lines drawn together; groups are set apart from one another. */
export interface NavGroup {
  id: "home" | "pillars" | "operational" | "administration";
  nodes: readonly NavNode[];
}

const leaf = (
  id: string,
  labelKey: NavKey,
  routeId: string,
  more: Partial<Pick<NavLeaf, "query" | "icon" | "badgeKey">> = {},
): NavLeaf => ({ kind: "leaf", id, labelKey, routeId, ...more });

/** A view of "Mon environnement": its tab, in the URL. */
const environmentView = (tab: string, labelKey: NavKey) =>
  leaf(`environment-${tab}`, labelKey, "environment", { query: { tab } });

export const NAVIGATION: readonly NavGroup[] = [
  { id: "home", nodes: [leaf("overview", "overview", "overview", { icon: Home })] },
  {
    id: "pillars",
    nodes: [
      {
        kind: "section",
        id: "intentions",
        labelKey: "intentions",
        hintKey: "intentions",
        icon: Layers,
        tier: "pillar",
        // The way to act: two lines, always at hand.
        defaultOpen: true,
        children: [
          leaf("intention-new", "newIntention", "intention-new"),
          leaf("intentions", "myIntentions", "intentions"),
        ],
      },
      {
        kind: "section",
        id: "environment",
        labelKey: "environment",
        hintKey: "environment",
        icon: EnvironmentIcon,
        tier: "pillar",
        children: [
          leaf("environment-overview", "environmentOverview", "environment"),
          environmentView("applications", "environmentApplications"),
          environmentView("infrastructure", "environmentInfrastructure"),
          environmentView("data", "environmentData"),
          environmentView("dependencies", "environmentDependencies"),
          environmentView("organisation", "environmentTeams"),
          environmentView("events", "environmentEvents"),
          environmentView("domains", "environmentDomains"),
          // How far what LEKA knows can be trusted (LEKA-381).
          environmentView("quality", "environmentQuality"),
        ],
      },
      {
        kind: "section",
        id: "capabilities",
        labelKey: "capabilities",
        hintKey: "capabilities",
        icon: CapabilitiesIcon,
        tier: "pillar",
        children: [
          leaf("capabilities-available", "capabilitiesAvailable", "capabilities"),
          leaf("capabilities-mine", "capabilitiesMine", "capabilities", {
            query: { tab: "mine" },
          }),
          leaf("capabilities-configuration", "capabilitiesConfiguration", "capabilities", {
            query: { tab: "configuration" },
          }),
        ],
      },
    ],
  },
  {
    // Across the three: what happened, what waits on someone.
    id: "operational",
    nodes: [
      leaf("activity", "activity", "activity", { icon: ActivityIcon }),
      leaf("approvals", "approvals", "approvals", { icon: ShieldCheck, badgeKey: "approvals" }),
    ],
  },
  {
    id: "administration",
    nodes: [
      {
        kind: "section",
        id: "administration",
        labelKey: "administration",
        icon: SlidersHorizontal,
        tier: "administration",
        children: [
          leaf("sources", "sources", "sources"),
          leaf("governance", "governance", "governance"),
          leaf("team", "team", "team"),
          leaf("billing", "billing", "billing"),
          leaf("settings", "settings", "settings"),
        ],
      },
    ],
  },
];
