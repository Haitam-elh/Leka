/**
 * The sidebar's hierarchy (LEKA-428). These are its invariants.
 *
 * What these protect: three pillars and only three, named for what a
 * customer does — never for how LEKA does it; every line opens a page the
 * registry declares, in a view that page has; every page is reachable from
 * the navigation — no route was lost by the reorganisation; every word is
 * translated.
 */

import { describe, expect, it } from "vitest";

import { NAVIGATION, type NavLeaf, type NavSection } from "@/config/navigation";
import { ROUTES, routeById } from "@/config/routes";
import { DICTIONARIES, type Locale } from "@/lib/i18n/dictionaries";
import { hrefOf, navLeaves } from "@/lib/navigation/tree";

const sections = NAVIGATION.flatMap((group) =>
  group.nodes.filter((node): node is NavSection => node.kind === "section"),
);
const leaves = navLeaves().map(({ leaf }) => leaf);

describe("the navigation", () => {
  it("has exactly three pillars: Intentions, Mon environnement, Capacités", () => {
    const pillars = sections.filter((section) => section.tier === "pillar");

    expect(pillars.map((pillar) => DICTIONARIES.fr.nav[pillar.labelKey])).toEqual([
      "Intentions",
      "Mon environnement",
      "Capacités",
    ]);
    // Each says what it is for.
    expect(pillars.every((pillar) => pillar.hintKey !== undefined)).toBe(true);
  });

  it("names nothing technical at its top level", () => {
    const top = NAVIGATION.flatMap((group) => group.nodes).map(
      (node) => DICTIONARIES.fr.nav[node.labelKey],
    );

    for (const word of [/graph/i, /agent/i, /skill/i, /connecteur/i, /mod[eè]le/i]) {
      expect(top.filter((label) => word.test(label))).toEqual([]);
    }
  });

  it("opens, from every line, a page the registry declares", () => {
    const unknown = leaves.filter((leaf) => routeById(leaf.routeId) === undefined);

    expect(unknown.map((leaf) => leaf.id)).toEqual([]);
  });

  it("asks a page only for a view it has", () => {
    const wrong = leaves.filter((leaf: NavLeaf) => {
      const tab = leaf.query?.tab;
      if (tab === undefined) return Object.keys(leaf.query ?? {}).length > 0;
      const views = routeById(leaf.routeId)?.views ?? [];
      // The first view is the address without a tab: a line asking for it
      // would be a second line for the same place.
      return !views.includes(tab) || views[0] === tab;
    });

    expect(wrong.map((leaf) => leaf.id)).toEqual([]);
  });

  it("gives every line its own id and its own address", () => {
    const ids = leaves.map((leaf) => leaf.id);
    const hrefs = leaves.map(hrefOf);

    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("reaches every page of the product — none lost by the reorganisation", () => {
    const opened = new Set(leaves.map((leaf) => leaf.routeId));
    // Reached from the workspace gate, by a new workspace, not from the
    // sidebar: its place is before there is anything to navigate.
    const elsewhere = new Set(["welcome"]);
    const reachable = (id: string | undefined): boolean => {
      if (id === undefined) return false;
      if (opened.has(id)) return true;
      return reachable(routeById(id)?.parentId);
    };

    const lost = ROUTES.filter((route) => !elsewhere.has(route.id) && !reachable(route.id));
    expect(lost.map((route) => route.id)).toEqual([]);
  });

  it("draws an icon for every top-level line and every section", () => {
    // Without one the rail shows nothing for it.
    const top = NAVIGATION.flatMap((group) => group.nodes);

    expect(top.filter((node) => node.icon === undefined).map((node) => node.id)).toEqual([]);
  });

  it("has every label and every pillar's sentence, in every language", () => {
    const missing: string[] = [];
    for (const [locale, dictionary] of Object.entries(DICTIONARIES) as [
      Locale,
      (typeof DICTIONARIES)[Locale],
    ][]) {
      for (const node of [...leaves, ...sections]) {
        if (!dictionary.nav[node.labelKey]) missing.push(`${locale}: ${node.labelKey}`);
      }
      for (const section of sections) {
        if (section.hintKey && !dictionary.pillars[section.hintKey]) {
          missing.push(`${locale}: pillars.${section.hintKey}`);
        }
      }
    }

    expect(missing).toEqual([]);
  });
});
