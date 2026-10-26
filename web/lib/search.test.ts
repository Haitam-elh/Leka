/**
 * The palette's search (LEKA-369): the company model's, behind the seam.
 *
 * What these protect: each hit goes to its own page, named with where it
 * is and its kind in words; nothing is asked under two letters; a failure
 * finds nothing rather than breaking the palette; and what reads as a
 * question is told apart from a lookup.
 */

import { describe, expect, it, vi } from "vitest";

import { knowledgeSearchProvider, looksLikeAQuestion } from "@/lib/search";

const label = (type: string) => ({ service: "Service", team: "Équipe" })[type] ?? type;
const href = (entity: { id: string; type: string }) => `/environment/${entity.type}s/${entity.id}`;

const FOUND = {
  entities: [
    {
      entity: { id: "s1", type: "service", name: "Payment API" },
      holder: { name: "Shop" },
    },
    { entity: { id: "t1", type: "team", name: "Payments" }, holder: null },
  ],
};

describe("the knowledge search provider", () => {
  it("offers each hit, named with where it is and its kind, to its own page", async () => {
    const search = vi.fn().mockResolvedValue(FOUND);
    const provider = knowledgeSearchProvider(label, href, search);

    expect(await provider("  pay ")).toEqual([
      { id: "s1", label: "Payment API · Shop", kind: "Service", href: "/environment/services/s1" },
      { id: "t1", label: "Payments", kind: "Équipe", href: "/environment/teams/t1" },
    ]);
    expect(search).toHaveBeenCalledWith("pay");
  });

  it("asks nothing under two letters", async () => {
    const search = vi.fn();
    const provider = knowledgeSearchProvider(label, href, search);

    expect(await provider(" p ")).toEqual([]);
    expect(search).not.toHaveBeenCalled();
  });

  it("finds nothing when the search fails, rather than breaking the palette", async () => {
    const provider = knowledgeSearchProvider(
      label,
      href,
      vi.fn().mockRejectedValue(new Error("offline")),
    );

    expect(await provider("payment")).toEqual([]);
  });
});

describe("a question, told apart from a lookup", () => {
  it.each([
    ["pourquoi le paiement est lent", true],
    ["payment api ?", true],
    ["what depends on billing", true],
    ["payment api", false],
    ["Équipe Données", false],
    ["", false],
  ])("%s → %s", (typed, question) => {
    expect(looksLikeAQuestion(typed)).toBe(question);
  });
});
