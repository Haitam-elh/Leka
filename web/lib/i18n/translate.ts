/**
 * The words a person reads: the dictionary of the language they chose,
 * and — where that language is not translated, or only partly — the
 * words of the next language of its chain (lib/i18n/languages.ts):
 * its parents, its base language, the workspace's, then English. Never an
 * empty string, never a key on screen.
 *
 * What fell back is said, not hidden: `missing` lists the keys, the
 * browser console says them once in development, and `npm run
 * i18n:report` counts them per language for QA.
 */

import { DICTIONARIES, type Dictionary, PARTIAL } from "@/lib/i18n/dictionaries";
import { chain, DEFAULT_LANGUAGE } from "@/lib/i18n/languages";
import { isPseudo, pseudoDictionary } from "@/lib/i18n/pseudo";

export interface Words {
  dictionary: Dictionary;
  /** The language the screens actually speak: the first of the chain with
   * any translation. */
  shown: string;
  /** Keys of `shown` that fell back further down the chain. */
  missing: string[];
}

type Tree = { [key: string]: unknown };

function overlay(base: Tree, over: Tree, path: string, missing: string[]): Tree {
  const out: Tree = {};
  for (const [key, value] of Object.entries(base)) {
    const here = path ? `${path}.${key}` : key;
    const said = over[key];
    if (value && typeof value === "object" && !Array.isArray(value)) {
      out[key] = overlay(value as Tree, (said as Tree | undefined) ?? {}, here, missing);
    } else if (typeof said === "string" && said.trim()) {
      out[key] = said;
    } else {
      out[key] = value;
      missing.push(here);
    }
  }
  return out;
}

const made = new Map<string, Words>();

/** For tests that change PARTIAL: what was worked out before is forgotten. */
export function forgetWords(): void {
  made.clear();
}

export function wordsFor(language: string, workspace?: string | null): Words {
  const key = `${language}|${workspace ?? ""}`;
  const kept = made.get(key);
  if (kept) return kept;

  let words: Words;
  if (isPseudo(language)) {
    words = { dictionary: pseudoDictionary(language, DICTIONARIES.en), shown: language, missing: [] };
  } else {
    const order = chain(language, workspace).filter((tag) => DICTIONARIES[tag] || PARTIAL[tag]);
    const whole = order.find((tag) => DICTIONARIES[tag]) ?? DEFAULT_LANGUAGE;
    // The partial translations before the first whole one, nearest last.
    const partial = order.slice(0, order.indexOf(whole)).reverse();
    const missing: string[] = [];
    let dictionary = DICTIONARIES[whole];
    for (const tag of partial) {
      missing.length = 0;
      dictionary = overlay(dictionary as unknown as Tree, PARTIAL[tag] as Tree, "", missing) as unknown as Dictionary;
    }
    words = { dictionary, shown: order[0] ?? DEFAULT_LANGUAGE, missing: [...missing] };
  }
  made.set(key, words);
  return words;
}
