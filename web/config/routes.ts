/**
 * Every route of the product, in one place.
 *
 * This is the information architecture of LEKA, and it is a value, not a set
 * of files: the breadcrumb, the document title and the default page title
 * are generated from it, and the sidebar and the palette draw
 * config/navigation.ts, whose every line names a route here. A route that is
 * not here does not exist as far as navigation is concerned.
 *
 * WHAT A ROUTE MUST DECLARE, and why:
 *
 *   path            a pattern, `:like` this, so a link is built by a helper
 *                   and never spelled out in a component
 *   labelKey        a key, never a word: the interface has a dictionary
 *   parentId        what the breadcrumb climbs
 *   requiredPermission
 *                   a REAL permission, from the API's own vocabulary — the
 *                   list a signed-in person has comes from
 *                   GET /api/v1/workspaces/current, so nothing here
 *                   duplicates the matrix in docs/permissions.md
 *   availability    whether the page is built yet, and what to say if not
 *
 * THE SIDEBAR IS NOT A SECURITY BOUNDARY. Hiding an entry hides a link, not
 * the data behind it; the API refuses the request. See
 * docs/product/information-architecture.md.
 */

import type { NavKey } from "@/lib/i18n/dictionaries";

/** What the API calls a permission. Kept in the API's spelling on purpose. */
export type Permission =
  | "workspace:read"
  | "workspace:update"
  | "workspace:delete"
  | "workspace:transfer"
  | "member:read"
  | "member:invite"
  | "member:update_role"
  | "member:remove"
  | "source:read"
  | "source:manage"
  | "intention:read"
  | "intention:create"
  | "intention:approve"
  | "job:read"
  | "context:manage"
  | "entity:restrict"
  | "entity:read_restricted"
  | "access:read";

/**
 * Whether the page behind the entry exists yet.
 *
 * "soon" and "plan-gated" are shown rather than hidden: an entry that
 * disappears teaches nothing, while one that says "bientôt" tells a customer
 * what the product is becoming. Hiding is for what they may never see.
 */
export type Availability = "available" | "soon" | "plan-gated";

export type BadgeKey = "approvals";

export interface RouteEntry {
  id: string;
  /** `/environment/:entityType/:entityId` — parameters are `:named`. */
  path: string;
  labelKey: NavKey;
  parentId?: string;
  requiredPermission?: Permission;
  availability?: Availability;
  /** Tab segments this route accepts, in the order they are shown. */
  tabs?: readonly string[];
  /** The views it opens in by its query, `?tab=` — the first is the
   * address without one. What the sidebar's lines may ask (LEKA-428). */
  views?: readonly string[];
}

/** The tabs of an intention, straight from the mockups. */
export const INTENTION_TABS = [
  "overview",
  "analysis",
  "results",
  "decision",
  "actions",
  "evidence",
  "history",
  // What its agents delivered (2026-10-14).
  "deliverable",
] as const;

/** And of an entity sheet — the eight of the Payment API screen, then what
 * LEKA assembles around it (LEKA-370), and its course (LEKA-383). */
export const ENTITY_TABS = [
  "overview",
  "metrics",
  "dependencies",
  "incidents",
  "deployments",
  "logs",
  "configuration",
  "documentation",
  "context",
  "history",
] as const;

/** The views of "Mon environnement" (LEKA-369), by `?tab=`. */
export const ENVIRONMENT_VIEWS = [
  "architecture",
  "applications",
  "infrastructure",
  "data",
  "dependencies",
  "organisation",
  "events",
  "domains",
  "quality",
] as const;

/** And of Capacités: the sidebar opens them already; the catalogue, when
 * it is built (LEKA-393 on), reads them. */
export const CAPABILITY_VIEWS = ["available", "mine", "configuration"] as const;

export const ROUTES: readonly RouteEntry[] = [
  // Every page, whether the sidebar shows it or not: what the sidebar shows,
  // and in which section, is config/navigation.ts's (LEKA-428).
  {
    id: "overview",
    path: "/overview",
    labelKey: "overview",
    requiredPermission: "workspace:read",
  },
  {
    id: "intention-new",
    path: "/intentions/new",
    labelKey: "newIntention",
    parentId: "intentions",
    requiredPermission: "intention:create",
  },
  {
    id: "intentions",
    path: "/intentions",
    labelKey: "intentions",
    requiredPermission: "intention:read",
  },
  {
    id: "intention-detail",
    path: "/intentions/:intentionId",
    labelKey: "intentionDetail",
    parentId: "intentions",
    requiredPermission: "intention:read",
    tabs: INTENTION_TABS,
  },
  {
    id: "environment",
    path: "/environment",
    labelKey: "environment",
    requiredPermission: "workspace:read",
    views: ENVIRONMENT_VIEWS,
  },
  {
    // The graph explored: the dependency view, or what surrounds one thing
    // (LEKA-369).
    id: "environment-graph",
    path: "/environment/graph",
    labelKey: "environmentGraph",
    parentId: "environment",
    requiredPermission: "workspace:read",
  },
  {
    id: "entity-detail",
    path: "/environment/:entityType/:entityId",
    labelKey: "entityDetail",
    parentId: "environment",
    requiredPermission: "workspace:read",
    tabs: ENTITY_TABS,
  },
  {
    id: "activity",
    path: "/activity",
    labelKey: "activity",
    requiredPermission: "workspace:read",
  },
  {
    id: "approvals",
    path: "/approvals",
    labelKey: "approvals",
    // A member reads and creates intentions; approving is an admin's job, so
    // the entry is hidden rather than shown and refused.
    requiredPermission: "intention:approve",
  },
  {
    id: "approval-detail",
    path: "/approvals/:approvalId",
    labelKey: "approvalDetail",
    parentId: "approvals",
    requiredPermission: "intention:approve",
  },
  {
    id: "capabilities",
    path: "/capabilities",
    labelKey: "capabilities",
    requiredPermission: "workspace:read",
    views: CAPABILITY_VIEWS,
    // The catalogue (LEKA-393): what LEKA can do, and whether it can here.
    availability: "available",
  },
  {
    id: "capability-detail",
    path: "/capabilities/:capabilityId",
    labelKey: "capabilityDetail",
    parentId: "capabilities",
    requiredPermission: "workspace:read",
    availability: "available",
  },
  {
    id: "sources",
    path: "/sources",
    labelKey: "sources",
    requiredPermission: "source:read",
  },
  {
    id: "source-detail",
    path: "/sources/:sourceId",
    labelKey: "sourceDetail",
    parentId: "sources",
    requiredPermission: "source:read",
  },
  {
    // Where a new workspace starts: choosing the tools to connect, then
    // connecting them. Reached from the workspace gate, not the sidebar.
    id: "welcome",
    path: "/welcome",
    labelKey: "welcome",
    requiredPermission: "source:manage",
  },
  {
    id: "governance",
    path: "/governance",
    labelKey: "governance",
    // Who may do what, the restricted entities, the trail of access
    // decisions (LEKA-402): the administrators'.
    requiredPermission: "access:read",
  },
  {
    id: "team",
    path: "/team",
    labelKey: "team",
    requiredPermission: "member:invite",
  },
  {
    id: "billing",
    path: "/billing",
    labelKey: "billing",
    // There is no billing:* permission: paying for the workspace is part of
    // administering it, and workspace:update is what an admin has.
    requiredPermission: "workspace:update",
  },
  {
    id: "settings",
    path: "/settings",
    labelKey: "settings",
    requiredPermission: "workspace:read",
  },
];

const BY_ID = new Map(ROUTES.map((route) => [route.id, route]));

export function routeById(id: string): RouteEntry | undefined {
  return BY_ID.get(id);
}

/**
 * The links, built here and nowhere else.
 *
 * A URL spelled out in a component is a URL that survives a rename of the
 * route it points at. `tests/no-hard-coded-routes` looks for those.
 */
export const routes = {
  overview: () => "/overview",
  intentions: () => "/intentions",
  intentionNew: () => "/intentions/new",
  intention: (intentionId: string, tab?: (typeof INTENTION_TABS)[number]) =>
    tab ? `/intentions/${intentionId}/${tab}` : `/intentions/${intentionId}`,
  approvals: () => "/approvals",
  approval: (approvalId: string) => `/approvals/${approvalId}`,
  activity: () => "/activity",
  environment: () => "/environment",
  /** The detailed map — centred on one thing when given. */
  environmentGraph: (entityId?: string) =>
    entityId ? `/environment/graph?entity=${encodeURIComponent(entityId)}` : "/environment/graph",
  entity: (entityType: string, entityId: string, tab?: (typeof ENTITY_TABS)[number]) =>
    tab
      ? `/environment/${entityType}/${entityId}/${tab}`
      : `/environment/${entityType}/${entityId}`,
  sources: () => "/sources",
  source: (sourceId: string) => `/sources/${sourceId}`,
  welcome: () => "/welcome",
  capabilities: () => "/capabilities",
  capability: (capabilityId: string) => `/capabilities/${capabilityId}`,
  governance: () => "/governance",
  team: () => "/team",
  billing: () => "/billing",
  settings: () => "/settings",
} as const;
