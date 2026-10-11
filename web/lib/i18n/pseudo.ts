/**
 * The QA pseudo-languages: English, made to look like what a real
 * translation will do to the screens, before any exists.
 *
 *   en-XA   accented and about 40 % longer — [Ŝîĝñ îñ ţö ĻÉĶÅ ·····] — so
 *           a label that will not fit a German or a Finnish translation
 *           shows now, and a word not taken from a dictionary stands out
 *           unaccented
 *   ar-XB   right to left: the layout mirrors as it will for Arabic,
 *           Hebrew, Persian or Urdu, the words still readable
 *
 * Never in the language picker, never saved: `?qa-language=en-XA` on any
 * page turns one on for that tab (lib/i18n/resolve.ts). The ICU names are
 * Android's and Chrome's, for the same tool.
 */

import type { Dictionary } from "@/lib/i18n/dictionaries";

export const PSEUDO = ["en-XA", "ar-XB"] as const;
export type Pseudo = (typeof PSEUDO)[number];

export function isPseudo(tag: unknown): tag is Pseudo {
  return typeof tag === "string" && (PSEUDO as readonly string[]).includes(tag);
}

const ACCENTED: Record<string, string> = Object.fromEntries(
  [..."abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"].map((letter, i) => [
    letter,
    [..."åƀçđéƒĝĥîĵķļɱñöþǫŕšţûṽŵẋýžÅƁÇĐÉƑĜĤÎĴĶĻṀÑÖÞǪŔŠŢÛṼŴẊÝŽ"][i],
  ]),
);

// Placeholders ({n}), markup-like spans and URLs are left as they are:
// fill() and the code that reads them must still find them.
const KEPT = /(\{\w+\}|https?:\/\/\S+|<[^>]+>)/;

function accented(text: string): string {
  const parts = text.split(KEPT);
  const changed = parts
    .map((part, i) => (i % 2 === 1 ? part : [...part].map((c) => ACCENTED[c] ?? c).join("")))
    .join("");
  const padding = "·".repeat(Math.ceil(text.length * 0.4));
  return `[${changed} ${padding}]`;
}

// RLM, then a right-to-left override: the paragraph is right to left, and
// the English inside it is drawn as Arabic would be.
function mirrored(text: string): string {
  return `‏‮${text}‬‏`;
}

function each(value: unknown, change: (text: string) => string): unknown {
  if (typeof value === "string") return change(value);
  if (typeof value === "function") {
    return (...args: unknown[]) => each((value as (...a: unknown[]) => unknown)(...args), change);
  }
  if (Array.isArray(value)) return value.map((item) => each(item, change));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, each(item, change)]));
  }
  return value;
}

const made = new Map<Pseudo, Dictionary>();

export function pseudoDictionary(tag: Pseudo, english: Dictionary): Dictionary {
  const kept = made.get(tag);
  if (kept) return kept;
  const dictionary = each(english, tag === "en-XA" ? accented : mirrored) as Dictionary;
  made.set(tag, dictionary);
  return dictionary;
}
