/**
 * Which route a URL is. Which line of the sidebar it marks is
 * lib/navigation/tree.ts's.
 *
 * Pure functions over the registry: no React, no router, so the rules can be
 * tested in a millisecond and read without running anything.
 */

import { type RouteEntry, ROUTES } from "@/config/routes";

export interface RouteMatch {
  route: RouteEntry;
  /** `{ entityType: "services", entityId: "payment-api" }` */
  params: Readonly<Record<string, string>>;
  /** The tab segment, when the route declares tabs and the URL carries one. */
  tab?: string;
}

interface Candidate {
  route: RouteEntry;
  segments: readonly string[];
}

const CANDIDATES: readonly Candidate[] = ROUTES.map((route) => ({
  route,
  segments: route.path.split("/").filter(Boolean),
}));

function normalise(pathname: string): string[] {
  return pathname.split("?")[0].split("#")[0].split("/").filter(Boolean);
}

/**
 * The route a URL belongs to, if any.
 *
 * A static segment beats a parameter: `/intentions/new` is the composer, not
 * an intention whose id happens to be "new". That is why matches are scored
 * rather than taken in declaration order — order is a thing that changes when
 * somebody sorts a list alphabetically.
 */
export function matchRoute(pathname: string): RouteMatch | undefined {
  const parts = normalise(pathname);
  let best: { match: RouteMatch; score: number } | undefined;

  for (const { route, segments } of CANDIDATES) {
    const tabs = route.tabs ?? [];
    const extra = parts.length - segments.length;
    // Exactly the route, or the route plus one tab segment it declares.
    if (extra !== 0 && !(extra === 1 && tabs.length > 0)) continue;

    const params: Record<string, string> = {};
    let score = 0;
    let fits = true;

    for (const [index, segment] of segments.entries()) {
      const part = parts[index];
      if (segment.startsWith(":")) {
        params[segment.slice(1)] = decodeURIComponent(part);
        score += 1; // a parameter matches, but weakly
      } else if (segment === part) {
        score += 10; // a literal segment is a much stronger signal
      } else {
        fits = false;
        break;
      }
    }
    if (!fits) continue;

    let tab: string | undefined;
    if (extra === 1) {
      tab = parts[parts.length - 1];
      if (!tabs.includes(tab)) continue;
      score += 10;
    }

    if (best === undefined || score > best.score) {
      best = { match: { route, params, tab }, score };
    }
  }

  return best?.match;
}
