/**
 * Which language LEKA speaks to someone, and where that choice is kept
 * (docs/languages.md).
 *
 * In this order, the first that says one:
 *
 *   1. a choice made just now, in this tab — on the site, the sign-in or
 *      in the application: it wins, and is saved to the account
 *   2. the account's language, once signed in: every device the same
 *   3. a choice made on this device before (the leka-lang cookie)
 *   4. the browser's languages, most wanted first
 *   5. the country the request came from — a hint, when a CDN in front of
 *      LEKA says one; never precise, never asked of the browser
 *   6. English
 *
 * A country never decides when the browser does: someone in France whose
 * browser speaks English reads English.
 */

import { DEFAULT_LANGUAGE, isListed, match, negotiate, REGIONS } from "@/lib/i18n/languages";

export type Source = "qa" | "now" | "account" | "device" | "browser" | "country" | "default";

export interface Signals {
  qa?: string | null;
  now?: string | null;
  account?: string | null;
  device?: string | null;
  browser?: readonly string[];
  country?: string | null;
}

export interface Resolved {
  language: string;
  source: Source;
}

/** The language a country most likely speaks, by CLDR's likely subtags —
 * und-JP is Japanese, und-CH German. A hint, nothing more. */
export function countryLanguage(country: string | null | undefined): string | undefined {
  const region = country?.toUpperCase();
  // A real country only: an unknown one (ZZ) would "maximize" to English.
  if (!region || !REGIONS.includes(region)) return undefined;
  try {
    return match(new Intl.Locale(`und-${region}`).maximize().language)?.tag;
  } catch {
    return undefined;
  }
}

export function resolve(signals: Signals): Resolved {
  if (signals.qa) return { language: signals.qa, source: "qa" };
  for (const source of ["now", "account", "device"] as const) {
    const said = signals[source];
    if (isListed(said)) return { language: said, source };
  }
  const browser = negotiate(signals.browser ?? []);
  if (browser) return { language: browser.tag, source: "browser" };
  const country = countryLanguage(signals.country);
  if (country) return { language: country, source: "country" };
  return { language: DEFAULT_LANGUAGE, source: "default" };
}

// ── where it is kept ────────────────────────────────────────────────────────

/** The choice made on this device: a first-party cookie, so the sign-in's
 * server reads it on the very first paint, and localStorage, which the
 * site's own pages read (public/i18n.js). */
export const DEVICE_KEY = "leka-lang";
/** The application's key before languages came from the catalogue. */
const LEGACY_KEY = "leka.locale";
/** A choice made in this tab, not yet saved to the account. */
const NOW_KEY = "leka-lang-now";
/** The QA pseudo-languages (lib/i18n/pseudo.ts), for this tab. */
const QA_KEY = "leka.qa-language";
/** A year: a preference, not a session. */
const YEAR = 60 * 60 * 24 * 365;

function cookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const found = document.cookie.split("; ").find((pair) => pair.startsWith(`${name}=`));
  return found ? decodeURIComponent(found.slice(name.length + 1)) : null;
}

function read(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    // Private browsing, or storage refused.
    return null;
  }
}

function write(storage: () => Storage, key: string, value: string | null): void {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    // The choice still holds for this page; it will not persist.
  }
}

const local = () => window.localStorage;
const session = () => window.sessionStorage;

/** Everything this browser says, for resolve() — and the country the
 * server read from the request, when it read one. */
export function browserSignals(country: string | null = null): Signals {
  const device = cookie(DEVICE_KEY) ?? read(local, DEVICE_KEY) ?? read(local, LEGACY_KEY);
  return {
    qa: read(session, QA_KEY),
    now: read(session, NOW_KEY),
    device: device ? (match(device)?.tag ?? null) : null,
    browser: typeof navigator === "undefined" ? [] : [...(navigator.languages ?? [navigator.language])],
    country,
  };
}

/** A person's choice: kept on this device, and marked as just made — the
 * account takes it at the next sign-in, or now if one is open. */
export function remember(language: string): void {
  if (typeof document !== "undefined") {
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${DEVICE_KEY}=${encodeURIComponent(language)}; Path=/; Max-Age=${YEAR}; SameSite=Lax${secure}`;
  }
  write(local, DEVICE_KEY, language);
  write(local, LEGACY_KEY, null);
  write(session, NOW_KEY, language);
}

/** Once the account holds it, the choice is no longer "just made". */
export function settled(): void {
  write(session, NOW_KEY, null);
}

/** `?qa-language=ar-XB` on any page: the QA pseudo-languages, for this tab.
 * `?qa-language=` alone turns them off. */
export function qaFromAddress(search: string): void {
  const said = new URLSearchParams(search).get("qa-language");
  if (said === null) return;
  write(session, QA_KEY, said || null);
}
