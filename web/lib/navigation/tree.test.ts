/**
 * Reading the hierarchy (LEKA-428): where a line goes, what a person is
 * offered, and the ONE line marked as where they are.
 */

import { describe, expect, it } from "vitest";

import { activeNav, hrefOf, navLeaves, visibleNavigation } from "@/lib/navigation/tree";

const OWNER = [
  "workspace:read", "workspace:update", "member:read", "member:invite",
  "source:read", "source:manage", "intention:read", "intention:create", "intention:approve",
];
const MEMBER = ["workspace:read", "member:read", "source:read", "intention:read", "intention:create"];

const leaf = (id: string) => {
  const found = navLeaves().find((placed) => placed.leaf.id === id);
  if (found === undefined) throw new Error(`no line ${id}`);
  return found.leaf;
};

const ids = (permissions: string[]) =>
  navLeaves(visibleNavigation(permissions)).map((placed) => placed.leaf.id);

describe("where a line goes", () => {
  it("is its page's path", () => {
    expect(hrefOf(leaf("intentions"))).toBe("/intentions");
    expect(hrefOf(leaf("intention-new"))).toBe("/intentions/new");
    expect(hrefOf(leaf("environment-overview"))).toBe("/environment");
  });

  it("and, for a view of a page, the view it asks for", () => {
    expect(hrefOf(leaf("environment-applications"))).toBe("/environment?tab=applications");
    expect(hrefOf(leaf("environment-organisation"))).toBe("/environment?tab=organisation");
    expect(hrefOf(leaf("capabilities-mine"))).toBe("/capabilities?tab=mine");
  });
});

describe("what a person is offered", () => {
  it("is everything, to an owner", () => {
    expect(ids(OWNER)).toEqual([
      "overview",
      "intention-new",
      "intentions",
      "approvals",
      "environment-overview",
      "environment-applications",
      "environment-infrastructure",
      "environment-data",
      "environment-dependencies",
      "environment-organisation",
      "environment-events",
      "environment-domains",
      "environment-quality",
      "activity",
      "capabilities-available",
      "capabilities-mine",
      "capabilities-configuration",
      "sources",
      "governance",
      "team",
      "billing",
      "settings",
    ]);
  });

  it("is what a member may open, and the section still there", () => {
    const offered = ids(MEMBER);

    // Approving, inviting, paying, governing are an admin's business.
    for (const id of ["approvals", "governance", "team", "billing"]) {
      expect(offered).not.toContain(id);
    }
    // The product is theirs.
    expect(offered).toContain("intention-new");
    expect(offered).toContain("environment-applications");
    expect(offered).toContain("sources");
  });

  it("drops a section with nothing left in it, and a group with nothing at all", () => {
    const groups = visibleNavigation(["intention:read"]);

    expect(groups.map((group) => group.id)).toEqual(["pillars"]);
    expect(groups[0].nodes.map((node) => node.id)).toEqual(["intentions"]);
  });

  it("is nothing without a permission", () => {
    expect(visibleNavigation([])).toEqual([]);
  });
});

describe("where a person is", () => {
  const at = (path: string, search: string | URLSearchParams = "") => {
    const active = activeNav(path, search);
    return [active.leaf?.id, active.section?.id];
  };

  it("is the line of the page, and the section it is in", () => {
    expect(at("/intentions")).toEqual(["intentions", "intentions"]);
    // What happened is the environment's; what waits, the intentions'.
    expect(at("/activity")).toEqual(["activity", "environment"]);
    expect(at("/approvals")).toEqual(["approvals", "intentions"]);
    expect(at("/settings")).toEqual(["settings", "administration"]);
  });

  it("is the composer's own line on the composer, not « Mes intentions »", () => {
    expect(at("/intentions/new")).toEqual(["intention-new", "intentions"]);
  });

  it("is the line of the view the address asks for", () => {
    expect(at("/environment", "tab=applications")).toEqual([
      "environment-applications",
      "environment",
    ]);
    expect(at("/environment", new URLSearchParams("tab=events&x=1")).at(0)).toBe(
      "environment-events",
    );
    expect(at("/capabilities", "tab=configuration")).toEqual([
      "capabilities-configuration",
      "capabilities",
    ]);
  });

  it("is the page's own line with no view asked, or one no line opens", () => {
    expect(at("/environment")).toEqual(["environment-overview", "environment"]);
    expect(at("/environment", "tab=architecture")).toEqual(["environment-overview", "environment"]);
    expect(at("/environment", "tab=nonsense")).toEqual(["environment-overview", "environment"]);
  });

  it("is the line of the page a detail page belongs to", () => {
    expect(at("/intentions/42/evidence")).toEqual(["intentions", "intentions"]);
    expect(at("/environment/services/payment-api")).toEqual(["environment-overview", "environment"]);
    expect(at("/environment/graph")).toEqual(["environment-overview", "environment"]);
    expect(at("/sources/github")).toEqual(["sources", "administration"]);
    expect(at("/approvals/7")).toEqual(["approvals", "intentions"]);
    // The view asked of a detail page is its own business, not a line's.
    expect(at("/capabilities/x", "tab=mine")).toEqual(["capabilities-available", "capabilities"]);
  });

  it("is nowhere on a page the navigation does not hold, or an unknown one", () => {
    expect(at("/welcome")).toEqual([undefined, undefined]);
    expect(at("/nope")).toEqual([undefined, undefined]);
  });
});
