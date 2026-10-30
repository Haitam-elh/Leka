/**
 * The interface's English words, as the API translates them (2026-10-30):
 * api/leka/core/interface_en.json holds every one, flat — "nav.home":
 * "Home" — for LEKA to translate the whole interface into a language that
 * has no dictionary. It is the dictionary itself, never edited by hand:
 * `npm run i18n:export` writes it again after a word changed.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { flatWords } from "@/lib/i18n/remote";

const EXPORTED = resolve(__dirname, "../../../api/leka/core/interface_en.json");

function written(): string {
  // In the dictionary's order: LEKA translates the first screens first.
  const flat = flatWords(DICTIONARIES.en as unknown as Record<string, unknown>);
  return `${JSON.stringify(flat, null, 1)}\n`;
}

describe("the interface's English words the API translates", () => {
  it("are the English dictionary, word for word", () => {
    if (process.env.I18N_WRITE) writeFileSync(EXPORTED, written());
    expect(
      readFileSync(EXPORTED, "utf8") === written(),
      "api/leka/core/interface_en.json is not the English dictionary: run `npm run i18n:export` in web/",
    ).toBe(true);
  });
});
