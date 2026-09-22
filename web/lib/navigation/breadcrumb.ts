/**
 * The trail above a page title: "Mon environnement › Payment API".
 *
 * Built from `parentId` in the registry, so a page cannot invent its own
 * ancestry and two pages cannot disagree about where they sit.
 *
 * The last crumb is the page you are on: it is not a link, and it carries
 * aria-current. Anything else would offer a link to here, from here.
 */

import { matchRoute, type RouteMatch } from "@/lib/navigation/active";
import { ROUTES, type RouteEntry } from "@/config/routes";
import type { Dictionary } from "@/lib/i18n/dictionaries";

export interface Crumb {
  label: string;
  /** Absent on the last crumb. */
  href?: string;
}

/**
 * What a dynamic segment is called on screen.
 *
 * `payment-api` is not a name, it is an identifier. Until the pages that own
 * these entities can say what they are called — LEKA-369 for the environment,
 * the intention screens for the rest — this turns the identifier into
 * something readable rather than printing a slug at a customer.
 */
export type EntityLabelResolver = (match: RouteMatch) => string | undefined;

export function humaniseIdentifier(identifier: string): string {
  return identifier
    .split(/[-_]/)
    .filter(Boolean)
    .map((word) => (word.length <= 3 ? word.toUpperCase() : word[0].toUpperCase() + word.slice(1)))
    .join(" ");
}

/** The default: read the last parameter of the URL and make it presentable. */
export const defaultEntityLabel: EntityLabelResolver = ({ route, params }) => {
  const names = route.path
    .split("/")
    .filter((segment) => segment.startsWith(":"))
    .map((segment) => segment.slice(1));
  const last = names.at(-1);
  return last ? humaniseIdentifier(params[last] ?? "") : undefined;
};

function labelFor(
  route: RouteEntry,
  match: RouteMatch,
  dictionary: Dictionary,
  resolve: EntityLabelResolver,
): string {
  // A dynamic route is named after the thing it shows, not after its pattern.
  if (route.id === match.route.id && route.path.includes(":")) {
    return resolve(match) ?? dictionary.nav[route.labelKey];
  }
  return dictionary.nav[route.labelKey];
}

function hrefFor(route: RouteEntry, match: RouteMatch): string {
  return route.path
    .split("/")
    .map((segment) => (segment.startsWith(":") ? match.params[segment.slice(1)] : segment))
    .join("/");
}

export function buildBreadcrumb(
  pathname: string,
  dictionary: Dictionary,
  resolve: EntityLabelResolver = defaultEntityLabel,
): readonly Crumb[] {
  const match = matchRoute(pathname);
  if (match === undefined) return [];

  const chain: RouteEntry[] = [];
  let current: RouteEntry | undefined = match.route;
  while (current !== undefined) {
    chain.unshift(current);
    const parentId: string | undefined = current.parentId;
    current = parentId ? ROUTES.find((route) => route.id === parentId) : undefined;
  }

  // A single crumb is the page's own title, which the header already shows.
  if (chain.length < 2) return [];

  return chain.map((route, index) => ({
    label: labelFor(route, match, dictionary, resolve),
    href: index === chain.length - 1 ? undefined : hrefFor(route, match),
  }));
}

/** `"Payment API · LEKA"` — what a browser tab and a bookmark show. */
export function documentTitle(pathname: string, dictionary: Dictionary): string {
  const match = matchRoute(pathname);
  if (match === undefined) return `${dictionary.shell.notFoundTitle} · LEKA`;
  const crumbs = buildBreadcrumb(pathname, dictionary);
  const last = crumbs.at(-1)?.label ?? dictionary.nav[match.route.labelKey];
  return `${last} · LEKA`;
}
