/**
 * The languages LEKA offers, as the API does (api/leka/core/languages.py):
 * the same catalogue — public/languages.json, written from
 * api/leka/core/languages.yaml and held equal to it by a test — and the
 * same rules.
 *
 *   match(tag)        the language LEKA offers for a tag as a browser says
 *                     it: zh-TW is Traditional Chinese, pt-BR Portuguese
 *   negotiate(tags)   the first of a browser's languages LEKA offers
 *   chain(tag, ws)    where a missing translation is looked up: the
 *                     language, its parents, its base, the workspace's,
 *                     English
 *   shown(surface…)   the language a surface actually speaks
 *   formatLocale(…)   what dates, numbers and currencies are written in
 *
 * A language and a region are two settings. The region formats; it never
 * chooses the language.
 */

import catalogueJson from "@/public/languages.json";

export type Surface = "app" | "site" | "emails";
export type Status = "reviewed" | "translated" | "partial";
export type Direction = "ltr" | "rtl";

export interface Language {
  tag: string;
  english: string;
  native: string;
  script: string;
  dir: Direction;
  parent: string | null;
  ai: "strong" | "good" | "limited";
  ui: Partial<Record<Surface, Status>>;
}

interface Catalogue {
  version: string;
  default: string;
  languages: Language[];
  aliases: Record<string, string>;
  regions: string[];
}

export const CATALOGUE = catalogueJson as unknown as Catalogue;
export const LANGUAGES: readonly Language[] = CATALOGUE.languages;
export const DEFAULT_LANGUAGE = CATALOGUE.default;
export const REGIONS: readonly string[] = CATALOGUE.regions;

const BY_TAG = new Map(LANGUAGES.map((language) => [language.tag, language]));

// A language (2 or 3 letters), a script (4), a region (2 letters or 3
// digits), then variants: 1, 2 and 3 below.
const TAG = /^([a-z]{2,3})(?:-([a-z]{4}))?(?:-([a-z]{2}|\d{3}))?(?:-(?:[a-z\d]{5,8}|\d[a-z\d]{3}))*$/;

/** A tag in BCP 47's canonical case — fr, zh-Hant, pt-BR — or null. */
export function canonical(tag: string): string | null {
  const lowered = tag.trim().replaceAll("_", "-").toLowerCase();
  const parts = TAG.exec(lowered);
  if (!parts) return null;
  const [, base, script, region] = parts;
  const out = [base];
  let rest = lowered.split("-").slice(1);
  if (script) {
    out.push(script[0].toUpperCase() + script.slice(1));
    rest = rest.slice(1);
  }
  if (region) {
    out.push(region.toUpperCase());
    rest = rest.slice(1);
  }
  return [...out, ...rest].join("-");
}

export function language(tag: string | null | undefined): Language | undefined {
  return tag ? BY_TAG.get(tag) : undefined;
}

export function isListed(tag: unknown): tag is string {
  return typeof tag === "string" && BY_TAG.has(tag);
}

/** The language LEKA offers for a tag as said anywhere, or undefined. Longest
 * first, an alias before the tag's own base: fa-AF is Dari, zh-TW
 * Traditional Chinese. */
export function match(tag: string): Language | undefined {
  const said = canonical(tag);
  if (!said) return undefined;
  const parts = said.split("-");
  for (let length = parts.length; length > 0; length -= 1) {
    const candidate = parts.slice(0, length).join("-");
    const alias = CATALOGUE.aliases[candidate];
    if (alias) return BY_TAG.get(alias);
    const found = BY_TAG.get(candidate);
    if (found) return found;
  }
  return undefined;
}

/** The region a tag carries, when it is one LEKA lists: pt-BR → BR. */
export function regionOf(tag: string): string | undefined {
  const said = canonical(tag);
  const region = said ? TAG.exec(said.toLowerCase())?.[3]?.toUpperCase() : undefined;
  return region && REGIONS.includes(region) ? region : undefined;
}

/** The first of a person's languages — a browser's, most wanted first —
 * LEKA offers. */
export function negotiate(tags: readonly string[]): Language | undefined {
  for (const tag of tags) {
    const found = match(tag);
    if (found) return found;
  }
  return undefined;
}

/** Where a missing translation is looked up, in order, each once. */
export function chain(tag: string, workspace?: string | null): string[] {
  const out: string[] = [];
  const add = (start: string | null | undefined) => {
    let candidate = start ?? null;
    while (candidate && !out.includes(candidate) && BY_TAG.has(candidate)) {
      out.push(candidate);
      candidate = BY_TAG.get(candidate)?.parent ?? null;
    }
  };
  add(tag);
  add(tag.split("-")[0]);
  add(workspace);
  add(DEFAULT_LANGUAGE);
  return out;
}

/** The language a surface speaks to someone who chose `tag`: the first of
 * its chain translated there. Never empty: English is everywhere. */
export function shown(surface: Surface, tag: string | null | undefined, workspace?: string | null): string {
  const start = isListed(tag) ? tag : (workspace ?? DEFAULT_LANGUAGE);
  return chain(start, workspace).find((candidate) => BY_TAG.get(candidate)?.ui[surface]) ?? DEFAULT_LANGUAGE;
}

export function direction(tag: string): Direction {
  return BY_TAG.get(tag)?.dir ?? "ltr";
}

/** What dates, numbers and currencies are written in: the language the
 * screen speaks, in the person's region — fr + CA → fr-CA. A locale the
 * browser does not know falls back to the language alone. */
export function formatLocale(tag: string, region?: string | null): string {
  if (!region) return tag;
  const candidate = `${tag}-${region}`;
  try {
    return Intl.getCanonicalLocales(candidate)[0] ?? tag;
  } catch {
    return tag;
  }
}

/** Accents and case set aside, so « francais » finds Français and « Turkce »
 * Türkçe. */
export function folded(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Whether a language answers a search: by its own name, its English name,
 * its name in the interface's language, or its tag. */
export function answers(language: Language, query: string, named?: string): boolean {
  const wanted = folded(query.trim());
  if (!wanted) return true;
  return [language.native, language.english, named ?? "", language.tag].some((name) =>
    folded(name).includes(wanted),
  );
}
