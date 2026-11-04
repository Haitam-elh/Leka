/**
 * Every bundle on sale has its page's words, whole, in French and in English
 * (LEKA-531): its promise, for whom, the problem, three reasons, three
 * situations — and none for a bundle the catalogue does not sell.
 *
 * The bundles are read from the server's catalogue itself
 * (api/leka/billing/catalogue.yaml): a bundle added without its words fails
 * here, not in front of a buyer.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { Words } from "@/lib/agent-products";
import { BUNDLE_PRODUCTS, type BundleProduct } from "@/lib/bundle-products";

const ROOT = join(__dirname, "../..");

/** The keys under add_ons.bundles in the server's catalogue. */
function onSale(): string[] {
  const yaml = readFileSync(join(ROOT, "api/leka/billing/catalogue.yaml"), "utf8");
  const block = yaml.split(/\n {2}bundles:\n/)[1].split(/\n {2}[a-z_]+:/)[0];
  return [...block.matchAll(/^ {4}- key: ([a-z][a-z-]+)$/gm)].map((m) => m[1]);
}

function words(product: BundleProduct): Words[] {
  return [
    product.promise,
    product.audience,
    product.problem,
    ...product.benefits.flatMap((b) => [b.title, b.body]),
    ...product.useCases.flatMap((u) => [u.title, u.body]),
  ];
}

describe("the bundles' words", () => {
  it("every bundle on sale has them, and only those", () => {
    const keys = onSale();
    expect(keys).toHaveLength(5);
    expect(Object.keys(BUNDLE_PRODUCTS).sort()).toEqual([...keys].sort());
  });

  it("are whole: three reasons, three situations, French and English each", () => {
    for (const [key, product] of Object.entries(BUNDLE_PRODUCTS)) {
      expect(product.benefits, key).toHaveLength(3);
      expect(product.useCases, key).toHaveLength(3);
      for (const said of words(product)) {
        expect(said.fr.trim().length, `${key}: ${said.en}`).toBeGreaterThan(3);
        expect(said.en.trim().length, `${key}: ${said.fr}`).toBeGreaterThan(3);
        expect(said.fr, key).not.toEqual(said.en);
        // No em dash in what a person reads (2026-10-26).
        expect(`${said.fr}${said.en}`, key).not.toMatch(/—/);
      }
    }
  });
});
