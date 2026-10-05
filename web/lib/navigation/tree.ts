/**
 * The sidebar's hierarchy, read (LEKA-428): what a person is offered, where
 * each line goes, and where they are.
 *
 * Pure functions over config/navigation.ts and config/routes.ts: no React,
 * no router, so the rules are tested in a millisecond.
 *
 *   visibleNavigation   the groups, sections and lines a person may open —
 *                       a section with nothing left is not drawn
 *   hrefOf              where a line goes: its page's path, and its view
 *   activeNav           the ONE line marked as the current page, and the
 *                       section it is in
 *   navLeaves           every line, for the palette
 *
 * THE SIDEBAR IS NOT A SECURITY BOUNDARY: hiding a line hides a link; the
 * API refuses the request (lib/navigation/access.ts).
 */

import {
  NAVIGATION,
  type NavGroup,
  type NavLeaf,
  type NavNode,
  type NavSection,
} from "@/config/navigation";
import { routeById, type RouteEntry } from "@/config/routes";
import { canOpen } from "@/lib/navigation/access";
import { matchRoute } from "@/lib/navigation/active";

export interface ActiveNav {
  /** The line that is the current page — at most one. */
  leaf?: NavLeaf;
  /** The section it is in, when it is in one. */
  section?: NavSection;
}

/** A line, and the section it is in when it is in one. */
export interface PlacedLeaf {
  leaf: NavLeaf;
  section?: NavSection;
}

function flatten(groups: readonly NavGroup[]): PlacedLeaf[] {
  return groups.flatMap((group) =>
    group.nodes.flatMap((node): PlacedLeaf[] =>
      node.kind === "leaf"
        ? [{ leaf: node }]
        : node.children.map((child) => ({ leaf: child, section: node })),
    ),
  );
}

const LEAVES: readonly PlacedLeaf[] = flatten(NAVIGATION);

/** Where a line goes. */
export function hrefOf(leaf: NavLeaf): string {
  const route = routeById(leaf.routeId);
  const path = route?.path ?? "/";
  const query = leaf.query ? new URLSearchParams(leaf.query).toString() : "";
  return query ? `${path}?${query}` : path;
}

/** Every line, with the section it is in — what the palette lists. */
export function navLeaves(groups: readonly NavGroup[] = NAVIGATION): PlacedLeaf[] {
  return flatten(groups);
}

/** What a person may be offered: the lines they may open, the sections
 * that still hold one, the groups that still hold anything. */
export function visibleNavigation(permissions: readonly string[]): NavGroup[] {
  const opens = (leaf: NavLeaf) => {
    const route = routeById(leaf.routeId);
    return route !== undefined && canOpen(route, permissions);
  };
  return NAVIGATION.map((group) => ({
    ...group,
    nodes: group.nodes.flatMap((node): NavNode[] => {
      if (node.kind === "leaf") return opens(node) ? [node] : [];
      const children = node.children.filter(opens);
      return children.length > 0 ? [{ ...node, children }] : [];
    }),
  })).filter((group) => group.nodes.length > 0);
}

/**
 * Where a person is: the line that is the current page, and its section.
 *
 * The page the URL is, or the nearest page above it that a line opens —
 * reading an intention is being in « Mes intentions ». On a page some lines
 * open in several views, the view the URL asks (`?tab=`) picks the line; a
 * view no line opens, or none asked, is the page's own line. A detail
 * page — an entity's sheet, a source — marks the line of the page it
 * belongs to.
 */
export function activeNav(pathname: string, search: string | URLSearchParams = ""): ActiveNav {
  const match = matchRoute(pathname);
  if (match === undefined) return {};
  const asked = typeof search === "string" ? new URLSearchParams(search) : search;
  let route: RouteEntry | undefined = match.route;
  let own = true;
  while (route !== undefined) {
    const id = route.id;
    const lines = LEAVES.filter(({ leaf }) => leaf.routeId === id);
    if (lines.length > 0) {
      const viewed = own
        ? lines
            .filter(({ leaf }) =>
              Object.entries(leaf.query ?? {}).every(([key, value]) => asked.get(key) === value),
            )
            .sort(
              (a, b) =>
                Object.keys(b.leaf.query ?? {}).length - Object.keys(a.leaf.query ?? {}).length,
            )
        : lines.filter(({ leaf }) => leaf.query === undefined);
      const found = viewed[0] ?? lines.find(({ leaf }) => leaf.query === undefined) ?? lines[0];
      return { leaf: found.leaf, section: found.section };
    }
    route = route.parentId ? routeById(route.parentId) : undefined;
    own = false;
  }
  return {};
}
