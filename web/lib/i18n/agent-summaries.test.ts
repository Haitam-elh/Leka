/**
 * Every agent says what it does in French: without its line here the
 * catalogue falls back on the SKILL.md description, written in English.
 */

import { readdirSync, existsSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { DICTIONARIES } from "@/lib/i18n/dictionaries";

const ROOT = join(__dirname, "../../../agents");
const AGENTS = readdirSync(ROOT, { withFileTypes: true })
  .filter((d) => d.isDirectory() && !d.name.startsWith("_"))
  .flatMap((d) => readdirSync(join(ROOT, d.name)).filter((a) => existsSync(join(ROOT, d.name, a, "SKILL.md"))));

describe("the agents' summaries", () => {
  it("say every agent in French and in English", () => {
    expect(AGENTS.length).toBeGreaterThan(20);
    for (const tag of ["fr", "en"]) {
      const said = DICTIONARIES[tag].catalogue.summaries as Record<string, string>;
      expect(AGENTS.filter((a) => !said[a]), tag).toEqual([]);
    }
  });
});
