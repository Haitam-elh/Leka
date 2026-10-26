/**
 * Every agent on sale has its product page, whole, in French and in English
 * (LEKA-471) — and an agent not on sale has none: it is never presented as
 * something to buy. A dedicated agent (2026-10-25), never sold, has one too:
 * the organisations it is made for read it.
 *
 * The agents on sale are read from the server's catalogue itself
 * (api/leka/billing/catalogue.yaml), the agents from the registry
 * (agents/registry.yaml): a new agent put on sale without its page fails
 * here, not in front of a buyer.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { AGENT_PRODUCTS, type AgentProduct, type Words } from "@/lib/agent-products";

const ROOT = join(__dirname, "../../..");

/** The keys under add_ons.agents in the server's catalogue. */
function onSale(): string[] {
  const yaml = readFileSync(join(ROOT, "api/leka/billing/catalogue.yaml"), "utf8");
  const block = yaml.split(/\n {2}agents:\n/)[1].split(/\n {2}[a-z_]+:/)[0];
  return [...block.matchAll(/^ {4}([a-z][a-z-]+): \{ tier:/gm)].map((m) => m[1]);
}

/** The agents made for some organisations: `dedicated: true` in their file. */
function dedicated(): string[] {
  const yaml = readFileSync(join(ROOT, "agents/registry.yaml"), "utf8");
  return [...yaml.matchAll(/^ {2}- path: (\S+)\n {4}name: ([a-z-]+)/gm)]
    .filter(([, path]) => /^dedicated: true$/m.test(readFileSync(join(ROOT, "agents", path), "utf8")))
    .map(([, , name]) => name);
}

/** The registry's agents and their status. */
function registry(): Map<string, string> {
  const yaml = readFileSync(join(ROOT, "agents/registry.yaml"), "utf8");
  const found = new Map<string, string>();
  for (const entry of yaml.split(/\n {2}- path: /).slice(1)) {
    const name = /name: ([a-z-]+)/.exec(entry)?.[1];
    const status = /status: ([a-z]+)/.exec(entry)?.[1];
    if (name && status) found.set(name, status);
  }
  return found;
}

function words(product: AgentProduct): Words[] {
  return [
    product.promise,
    product.problem,
    product.does,
    ...product.benefits.flatMap((b) => [b.title, b.body]),
    ...product.features,
    ...product.useCases.flatMap((u) => [u.title, u.body, u.ask]),
    ...product.outline,
    ...product.examples.flatMap((e) => [
      e.title,
      ...(e.kind === "levels" ? e.items.map((i) => i.text) : e.items),
    ]),
    ...product.limits,
  ];
}

describe("the agents' product pages", () => {
  const sold = onSale();
  const made = dedicated();

  it("every agent on sale has one, every dedicated one too, and only those", () => {
    expect(sold.length).toBeGreaterThan(20);
    expect(made).toEqual(["application-architecture"]);
    expect(sold.filter((key) => made.includes(key))).toEqual([]);
    expect([...sold, ...made].filter((key) => !AGENT_PRODUCTS[key])).toEqual([]);
    expect(Object.keys(AGENT_PRODUCTS).filter((key) => !sold.includes(key) && !made.includes(key))).toEqual([]);
  });

  it("no draft is presented as something to buy", () => {
    const agents = registry();
    const drafts = [...agents].filter(([, status]) => status !== "active").map(([name]) => name);
    expect(drafts.length).toBeGreaterThan(0);
    expect(drafts.filter((name) => AGENT_PRODUCTS[name])).toEqual([]);
    // What is on sale is live.
    expect(sold.filter((key) => agents.get(key) !== "active")).toEqual([]);
  });

  it("is whole — the same structure for every agent", () => {
    for (const [key, product] of Object.entries(AGENT_PRODUCTS)) {
      expect(product.benefits, key).toHaveLength(3);
      expect(product.features.length, key).toBeGreaterThanOrEqual(5);
      expect(product.features.length, key).toBeLessThanOrEqual(8);
      expect(product.useCases, key).toHaveLength(4);
      expect(product.outline.length, key).toBeGreaterThanOrEqual(4);
      expect(product.examples, key).toHaveLength(2);
      expect(product.limits.length, key).toBeGreaterThanOrEqual(1);
    }
  });

  it("says everything in French and in English", () => {
    for (const [key, product] of Object.entries(AGENT_PRODUCTS)) {
      for (const said of words(product)) {
        expect(said.fr.trim(), `${key}: ${said.en}`).not.toBe("");
        expect(said.en.trim(), `${key}: ${said.fr}`).not.toBe("");
      }
    }
  });

  it("promises nothing undemonstrated: no figure, no « guaranteed », no speed", () => {
    for (const [key, product] of Object.entries(AGENT_PRODUCTS)) {
      // What it says of itself — the examples are said to be examples.
      const promised = [
        product.promise,
        product.does,
        ...product.benefits.flatMap((b) => [b.title, b.body]),
        ...product.features,
        ...product.useCases.flatMap((u) => [u.title, u.body]),
      ];
      for (const said of promised) {
        expect(said.fr, key).not.toMatch(/%|garanti|instantan|immédiat|minutes?\b|heures?\b|rapide|vite\b/i);
        expect(said.en, key).not.toMatch(/%|guarantee|instant|immediate|minutes?\b|hours?\b|\bfast|quick/i);
      }
    }
  });
});
