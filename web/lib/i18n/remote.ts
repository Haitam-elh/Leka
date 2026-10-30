/**
 * The interface in a language that has no dictionary (2026-10-30): « quand
 * on clique sur une langue, ce n'est pas que la réponse de LEKA dans la
 * langue choisie, mais toute l'interface ».
 *
 * English and French have their dictionaries. Any other language of the
 * catalogue is translated by LEKA's model the first time someone chooses
 * it (GET /interface/{tag} starts it), kept for everyone after. Its words
 * arrive flat — "nav.home": "Inicio" — and are laid over the screens'
 * words as a partial translation (PARTIAL): what is not translated yet
 * falls back, as any partial translation does. The screens switch as the
 * words arrive, without a reload; this device keeps the last words it
 * read, so the next visit starts in the language.
 */

import { apiAddress } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { DICTIONARIES, PARTIAL } from "@/lib/i18n/dictionaries";
import { language as languageOf } from "@/lib/i18n/languages";
import { isPseudo } from "@/lib/i18n/pseudo";
import { forgetWords } from "@/lib/i18n/translate";

/** A language's words so far, as GET /interface/{tag} answers. */
export type RemoteInterface = components["schemas"]["InterfaceWordsRead"];
export type RemoteStatus = RemoteInterface["status"];

/** How far a language's translation is: what the screens say of it. */
export type RemoteProgress = components["schemas"]["InterfaceLanguageRead"];

type Tree = { [key: string]: unknown };

/** A dictionary's words, flat by key: "nav.home", "billing.features.0". */
export function flatWords(tree: Tree, path = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(tree)) {
    const here = path ? `${path}.${key}` : key;
    if (value && typeof value === "object") Object.assign(out, flatWords(value as Tree, here));
    else if (typeof value === "string") out[here] = value;
  }
  return out;
}

/** Flat words as a dictionary is shaped. A list's words are kept by their
 * index: the overlay reads them that way. */
export function nestedWords(flat: Record<string, string>): Tree {
  const out: Tree = {};
  for (const [key, said] of Object.entries(flat)) {
    const parts = key.split(".");
    let node = out;
    for (const part of parts.slice(0, -1)) {
      const next = node[part];
      if (!next || typeof next !== "object") node[part] = {};
      node = node[part] as Tree;
    }
    node[parts[parts.length - 1]] = said;
  }
  return out;
}

/** A language LEKA translates the interface into itself: listed, not a QA
 * pseudo-language, without a dictionary of its own. */
export function translatedByLeka(tag: string): boolean {
  const found = languageOf(tag);
  return Boolean(found && !found.ui.app && !DICTIONARIES[tag] && !isPseudo(tag));
}

/** A language's words laid over the screens' — they read them at once. */
export function applyInterface(tag: string, words: Record<string, string>): void {
  PARTIAL[tag] = nestedWords(words) as (typeof PARTIAL)[string];
  forgetWords();
}

/** What the API has of a language's interface; the first ask starts its
 * translation. `words: false`: how far only. None when unreachable. */
export async function readInterface(tag: string, words = true): Promise<RemoteInterface | null> {
  const address = apiAddress(`/interface/${encodeURIComponent(tag)}${words ? "" : "?words=false"}`);
  const answer = await fetch(address, { headers: { Accept: "application/json" } });
  if (!answer.ok) return null;
  return (await answer.json()) as RemoteInterface;
}

/** How far LEKA translated each language it translates: the picker says it. */
export async function readInterfaces(): Promise<RemoteProgress[]> {
  try {
    const answer = await fetch(apiAddress("/interface"), { headers: { Accept: "application/json" } });
    return answer.ok ? ((await answer.json()) as RemoteProgress[]) : [];
  } catch {
    return [];
  }
}

const KEPT = "leka.interface.";

/** The words this device read last for a language — none in a private
 * window, or after its storage was cleared. */
export function keptInterface(tag: string): RemoteInterface | null {
  try {
    const raw = window.localStorage.getItem(KEPT + tag);
    return raw ? (JSON.parse(raw) as RemoteInterface) : null;
  } catch {
    return null;
  }
}

export function keepInterface(found: RemoteInterface): void {
  try {
    window.localStorage.setItem(KEPT + found.tag, JSON.stringify(found));
  } catch {
    // Full, or refused: the next visit reads the API again.
  }
}

/** How far it is, as a share: 0 to 100. */
export function percentOf(progress: Pick<RemoteProgress, "done" | "total">): number {
  return progress.total ? Math.floor((progress.done / progress.total) * 100) : 0;
}
