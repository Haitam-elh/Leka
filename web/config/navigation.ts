/**
 * The sidebar, as LEKA-428 draws it: what a customer can do with LEKA, at a
 * glance.
 *
 *   Mon Dashboard                  the way home
 *   Intentions                     Dites à LEKA ce que vous voulez accomplir.
 *     Nouvelle intention · Mes intentions · À valider
 *   Mon environnement              Le système vivant de votre entreprise.
 *     Vue globale · Applications · Infrastructure · Données · Dépendances
 *     · Équipes · Événements · Domaines · Qualité · Activité
 *   Compétences                    Votre équipe technologique à la demande.
 *     Compétences disponibles · Mes compétences · Réglages
 *   ─────────────────────────────  fixed at the foot of the sidebar
 *   Configuration                  Sources · Sécurité · Équipe · Facturation
 *                                  · Paramètres
 *
 * À valider sits with the intentions — what waits on a decision — and
 * Activité with the environment — what happened in it: Karim's call,
 * 2026-10-07. A folded section says what waits in it. Configuration is
 * always in reach at the foot, out of the pillars' way (the product call,
 * 2026-10-14); its section id stays `administration`, kept in browsers.
 *
 * THREE PILLARS, nothing technical: the knowledge graph, agents, skills are
 * how LEKA does it, not what a customer comes for — they show through the
 * pillars, never beside them.
 *
 * This file is the HIERARCHY. Which pages exist, their paths, who may open
 * them, their breadcrumb, stay config/routes.ts's: an entry here names the
 * route it opens (`routeId`) and, for a view of a page, the `query` that
 * opens that view. No route was added, renamed or removed for it; every
 * page keeps its address. A section may have a `home`: the page its name
 * opens — Mon environnement's overview, its views chosen on the page.
 *
 * No component names an entry, a label or a path: lib/navigation/tree.ts
 * reads this, the sidebar and the palette draw it.
 */

import { Home, Layers, type LucideIcon, SlidersHorizontal } from "lucide-react";

import type { BadgeKey } from "@/config/routes";
import { CapabilitiesIcon, EnvironmentIcon } from "@/components/shell/nav-icons";
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
   * navigation. */
  defaultOpen?: boolean;
  /** The page its name opens, besides opening it (2026-10-14: « quand je
   * clique sur Mon environnement, je suis direct dans la vue globale »):
   * the section's own page, not listed among its lines. */
  home?: NavLeaf;
  /** Its views chosen on its page, not drawn in the sidebar: the palette
   * (⌘K) still finds them. */
  views?: readonly NavLeaf[];
  children: readonly NavLeaf[];
}

export type NavNode = NavLeaf | NavSection;

/** Lines drawn together; groups are set apart from one another. */
export interface NavGroup {
  id: "home" | "pillars" | "administration";
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
        // The way to act, and what waits on a decision: always at hand.
        defaultOpen: true,
        children: [
          leaf("intention-new", "newIntention", "intention-new"),
          leaf("intentions", "myIntentions", "intentions"),
          leaf("approvals", "approvals", "approvals", { badgeKey: "approvals" }),
        ],
      },
      {
        kind: "section",
        id: "environment",
        labelKey: "environment",
        hintKey: "environment",
        icon: EnvironmentIcon,
        tier: "pillar",
        // Its name opens its overview; its views — applications to quality
        // — are chosen on the page, top right (2026-10-14, Haitam): the
        // sidebar keeps what happened in it.
        home: leaf("environment-overview", "environmentOverview", "environment"),
        views: [
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
        children: [
          // What happened in it, and what LEKA did (LEKA-383).
          leaf("activity", "activity", "activity"),
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
