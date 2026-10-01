/**
 * Every route of the product, in one place.
 *
 * This is the information architecture of LEKA, and it is a value, not a set
 * of files: the sidebar, the breadcrumb, the document title, the command
 * palette and the default page title are all generated from it. A route that
 * is not here does not exist as far as navigation is concerned.
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

import {
  Home,
  Layers,
  type LucideIcon,
  Search,
  Settings,
  ShieldCheck,
  UserRoundKey,
} from "lucide-react";

import {
  ActivityIcon,
  BillingIcon,
  CapabilitiesIcon,
  EnvironmentIcon,
} from "@/components/shell/nav-icons";
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
  | "job:read";

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
  icon?: LucideIcon;
  parentId?: string;
  showInSidebar: boolean;
  requiredPermission?: Permission;
  availability?: Availability;
  badgeKey?: BadgeKey;
  /** Tab segments this route accepts, in the order they are shown. */
  tabs?: readonly string[];
}

/** The tabs of an intention, straight from the mockups. */
export const INTENTION_TABS = ["overview", "analysis", "evidence", "actions", "history"] as const;

/** And of an entity sheet — eight, as on the Payment API screen. */
export const ENTITY_TABS = [
  "overview",
  "metrics",
  "dependencies",
  "incidents",
  "deployments",
  "logs",
  "configuration",
  "documentation",
] as const;

export const ROUTES: readonly RouteEntry[] = [
  // In the order of the mockups' sidebar (docs/product/mockups/01), which is
  // the order everything generated from this list follows: one flat list,
  // no group titles. "Nouvelle intention" is its second line; it is drawn by
  // components/shell/new-intention-button.tsx, not from this entry, because
  // on /intentions/new it — not Intentions — is the place you are.
  {
    id: "overview",
    path: "/overview",
    labelKey: "overview",
    icon: Home,
    showInSidebar: true,
    requiredPermission: "workspace:read",
  },
  {
    id: "intention-new",
    path: "/intentions/new",
    labelKey: "newIntention",
    parentId: "intentions",
    showInSidebar: false,
    requiredPermission: "intention:create",
  },
  {
    id: "intentions",
    path: "/intentions",
    labelKey: "intentions",
    icon: Layers,
    showInSidebar: true,
    requiredPermission: "intention:read",
  },
  {
    id: "intention-detail",
    path: "/intentions/:intentionId",
    labelKey: "intentionDetail",
    parentId: "intentions",
    showInSidebar: false,
    requiredPermission: "intention:read",
    tabs: INTENTION_TABS,
  },
  {
    id: "environment",
    path: "/environment",
    labelKey: "environment",
    icon: EnvironmentIcon,
    showInSidebar: true,
    requiredPermission: "workspace:read",
  },
  {
    id: "entity-detail",
    path: "/environment/:entityType/:entityId",
    labelKey: "entityDetail",
    parentId: "environment",
    showInSidebar: false,
    requiredPermission: "workspace:read",
    tabs: ENTITY_TABS,
  },
  {
    id: "activity",
    path: "/activity",
    labelKey: "activity",
    icon: ActivityIcon,
    showInSidebar: true,
    requiredPermission: "workspace:read",
  },
  {
    id: "approvals",
    path: "/approvals",
    labelKey: "approvals",
    icon: ShieldCheck,
    showInSidebar: true,
    // A member reads and creates intentions; approving is an admin's job, so
    // the entry is hidden rather than shown and refused.
    requiredPermission: "intention:approve",
    badgeKey: "approvals",
  },
  {
    id: "approval-detail",
    path: "/approvals/:approvalId",
    labelKey: "approvalDetail",
    parentId: "approvals",
    showInSidebar: false,
    requiredPermission: "intention:approve",
  },
  {
    id: "capabilities",
    path: "/capabilities",
    labelKey: "capabilities",
    icon: CapabilitiesIcon,
    showInSidebar: true,
    requiredPermission: "workspace:read",
    // The catalogue is LEKA-393 and after. Shown, labelled, and honest.
    availability: "soon",
  },
  {
    id: "capability-detail",
    path: "/capabilities/:capabilityId",
    labelKey: "capabilityDetail",
    parentId: "capabilities",
    showInSidebar: false,
    requiredPermission: "workspace:read",
    availability: "soon",
  },
  {
    id: "sources",
    path: "/sources",
    labelKey: "sources",
    icon: Search,
    showInSidebar: true,
    requiredPermission: "source:read",
  },
  {
    id: "source-detail",
    path: "/sources/:sourceId",
    labelKey: "sourceDetail",
    parentId: "sources",
    showInSidebar: false,
    requiredPermission: "source:read",
  },
  {
    // Where a new workspace starts: choosing the tools to connect, then
    // connecting them. Reached from the workspace gate, not the sidebar.
    id: "welcome",
    path: "/welcome",
    labelKey: "welcome",
    showInSidebar: false,
    requiredPermission: "source:manage",
  },
  {
    id: "governance",
    path: "/governance",
    labelKey: "governance",
    icon: ShieldCheck,
    showInSidebar: true,
    requiredPermission: "workspace:update",
    // Policies, audit and compliance are what an enterprise plan is for.
    // A placeholder decision — Karim owns it, and changing it is one word.
    availability: "plan-gated",
  },
  {
    id: "team",
    path: "/team",
    labelKey: "team",
    icon: UserRoundKey,
    showInSidebar: true,
    requiredPermission: "member:invite",
  },
  {
    id: "billing",
    path: "/billing",
    labelKey: "billing",
    icon: BillingIcon,
    showInSidebar: true,
    // There is no billing:* permission: paying for the workspace is part of
    // administering it, and workspace:update is what an admin has.
    requiredPermission: "workspace:update",
  },
  {
    id: "settings",
    path: "/settings",
    labelKey: "settings",
    icon: Settings,
    showInSidebar: true,
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
