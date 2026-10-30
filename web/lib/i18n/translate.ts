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

function overlay(base: unknown, over: unknown, path: string, missing: string[]): unknown {
  if (Array.isArray(base)) {
    // A list's words, by index: a translation sent flat keeps them so.
    const said = (over && typeof over === "object" ? over : {}) as Record<number, unknown>;
    return base.map((value, at) => overlay(value, said[at], `${path}.${at}`, missing));
  }
  if (base && typeof base === "object") {
    const said = (over && typeof over === "object" ? over : {}) as Tree;
    const out: Tree = {};
    for (const [key, value] of Object.entries(base as Tree)) {
      out[key] = overlay(value, said[key], path ? `${path}.${key}` : key, missing);
    }
    return out;
  }
  if (typeof over === "string" && over.trim()) return over;
  missing.push(path);
  return base;
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
