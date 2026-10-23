/**
 * Every agent's deliverable ends on an action that settles it (Karim,
 * 2026-10-23) — « Régler maintenant ».
 *
 * What these protect:
 * - Every agent on sale has its own steps, never the fallback; the first is
 *   its own; each said in French and in English.
 * - A step that writes code or tests says what the writing agent is asked.
 * - Only agents of the registry are listed.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { NEXT_STEPS, nextStepsOf } from "@/lib/agent-products/actions";

const ROOT = join(__dirname, "../../..");

function onSale(): string[] {
  const yaml = readFileSync(join(ROOT, "api/leka/billing/catalogue.yaml"), "utf8");
  const block = yaml.split(/\n {2}agents:\n/)[1].split(/\n {2}[a-z_]+:/)[0];
  return [...block.matchAll(/^ {4}([a-z][a-z-]+): \{ tier:/gm)].map((m) => m[1]);
}

function registry(): string[] {
  const yaml = readFileSync(join(ROOT, "agents/registry.yaml"), "utf8");
  return [...yaml.matchAll(/name: ([a-z-]+)/g)].map((m) => m[1]);
}

describe("what every deliverable leads to", () => {
  it("every agent on sale has its own steps, each said in both languages", () => {
    const sold = onSale();
    expect(sold.length).toBeGreaterThan(25);
    expect(sold.filter((key) => !NEXT_STEPS[key])).toEqual([]);
    for (const key of sold) {
      const steps = nextStepsOf(key);
      expect(steps.length, key).toBeGreaterThan(0);
      for (const step of steps) {
        for (const said of [step.title, step.body]) {
          expect(said.fr.trim(), key).not.toBe("");
          expect(said.en.trim(), key).not.toBe("");
        }
        if (step.kind === "fix" || step.kind === "tests") {
          expect(step.focus?.fr.trim(), key).toBeTruthy();
          expect(step.focus?.en.trim(), key).toBeTruthy();
        }
      }
    }
  });

  it("lists only agents of the registry, and still ends any other on an action", () => {
    const known = registry();
    expect(Object.keys(NEXT_STEPS).filter((key) => !known.includes(key))).toEqual([]);
    expect(nextStepsOf("not-an-agent").map((step) => step.kind)).toEqual(["issues", "pages"]);
  });

  it("puts the agent's own action first", () => {
    expect(nextStepsOf("code-review")[0].kind).toBe("fix");
    expect(nextStepsOf("test-analysis")[0].kind).toBe("tests");
    expect(nextStepsOf("migration-planning")[0].kind).toBe("issues");
    expect(nextStepsOf("incident-investigation")[0].kind).toBe("pages");
    expect(nextStepsOf("code-change")[0].kind).toBe("change");
  });
});
