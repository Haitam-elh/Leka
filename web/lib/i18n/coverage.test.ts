/**
 * How far the interface is translated, language by language — what the
 * catalogue may say about it, and what QA reads (`npm run i18n:report`
 * prints the table: words translated, words falling back, and which).
 *
 * The rule it holds: the catalogue never says more than the dictionaries
 * have. "reviewed" or "translated" means every word; "partial", some;
 * nothing said, none.
 */

import { describe, expect, it } from "vitest";

import { DICTIONARIES, PARTIAL } from "@/lib/i18n/dictionaries";
import { LANGUAGES } from "@/lib/i18n/languages";

type Tree = { [key: string]: unknown };

function keys(tree: Tree, path = ""): string[] {
  return Object.entries(tree).flatMap(([key, value]) => {
    const here = path ? `${path}.${key}` : key;
    return value && typeof value === "object" ? keys(value as Tree, here) : [here];
  });
}

const ALL = keys(DICTIONARIES.en as unknown as Tree);

function coverage(tag: string): { have: number; missing: string[] } {
  const own = DICTIONARIES[tag] ?? PARTIAL[tag];
  if (!own) return { have: 0, missing: ALL };
  const said = new Set(keys(own as unknown as Tree));
  const missing = ALL.filter((key) => !said.has(key));
  return { have: ALL.length - missing.length, missing };
}

describe("the interface's translations", () => {
  it("are what the catalogue says, never more", () => {
    for (const language of LANGUAGES) {
      const { have } = coverage(language.tag);
      const status = language.ui.app;
      if (status === "reviewed" || status === "translated") expect(have, language.tag).toBe(ALL.length);
      else if (status === "partial") expect(have, language.tag).toBeGreaterThan(0);
      else expect(have, language.tag).toBe(0);
    }
  });

  it("has every word in French and English", () => {
    expect(coverage("fr").missing).toEqual([]);
    expect(coverage("en").missing).toEqual([]);
  });

  it.runIf(process.env.I18N_REPORT)("prints the report", () => {
    const lines = LANGUAGES.map((language) => {
      const { have, missing } = coverage(language.tag);
      const percent = `${Math.round((100 * have) / ALL.length)} %`.padStart(6);
      const status = (language.ui.app ?? "—").padEnd(10);
      return `${language.tag.padEnd(8)} ${status} ${percent}  ${missing.length} falling back  ${language.native}`;
    });
    process.stdout.write(
      [`The interface has ${ALL.length} words.`, "tag      status    translated", ...lines, ""].join("\n"),
    );
  });
});
