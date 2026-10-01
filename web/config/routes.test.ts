/**
 * The registry is the information architecture. These are its invariants.
 *
 * Every one of them exists because breaking it is silent: a route with no
 * translation renders `undefined`, a parent that does not exist makes a
 * breadcrumb stop halfway, two routes with the same path make the active
 * entry depend on declaration order.
 */

import { describe, expect, it } from "vitest";

import { ROUTES, routes } from "@/config/routes";
import { DICTIONARIES, type Locale } from "@/lib/i18n/dictionaries";

describe("the route registry", () => {
  it("gives every route a unique id and a unique path", () => {
    const ids = ROUTES.map((route) => route.id);
    const paths = ROUTES.map((route) => route.path);

    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it("has a translation for every label, in every language", () => {
    const missing: string[] = [];
    for (const [locale, dictionary] of Object.entries(DICTIONARIES) as [Locale, (typeof DICTIONARIES)[Locale]][]) {
      for (const route of ROUTES) {
        if (!dictionary.nav[route.labelKey]) missing.push(`${locale}: ${route.labelKey}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("points every parentId at a route that exists", () => {
    const ids = new Set(ROUTES.map((route) => route.id));
    const orphans = ROUTES.filter(
      (route) => route.parentId !== undefined && !ids.has(route.parentId),
    );

    expect(orphans.map((route) => route.id)).toEqual([]);
  });

  it("gives every sidebar entry an icon", () => {
    // Without one the row collapses to a label and the rail shows nothing.
    const iconless = ROUTES.filter((route) => route.showInSidebar && route.icon === undefined);

    expect(iconless.map((route) => route.id)).toEqual([]);
  });

  it("declares a permission on every route", () => {
    // A route with none is a route nobody decided about. Public pages live
    // outside the shell, under (auth).
    const undecided = ROUTES.filter((route) => route.requiredPermission === undefined);

    expect(undecided.map((route) => route.id)).toEqual([]);
  });

  it("keeps the link helpers in step with the registry", () => {
    // A helper pointing at a path the registry does not declare is a 404
    // waiting for the first person to click it.
    const declared = new Set(ROUTES.map((route) => route.path));
    const built = [
      routes.overview(),
      routes.intentions(),
      routes.intentionNew(),
      routes.approvals(),
      routes.activity(),
      routes.environment(),
      routes.sources(),
      routes.welcome(),
      routes.capabilities(),
      routes.governance(),
      routes.team(),
      routes.billing(),
      routes.settings(),
    ];

    expect(built.filter((path) => !declared.has(path))).toEqual([]);
  });

  it("nests the parameterised routes under a page that lists them", () => {
    const parameterised = ROUTES.filter((route) => route.path.includes(":"));

    expect(parameterised.length).toBeGreaterThan(0);
    expect(parameterised.filter((route) => route.parentId === undefined)).toEqual([]);
  });
});
