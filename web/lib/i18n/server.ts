import { cookies, headers } from "next/headers";

import { canonical, regionOf } from "@/lib/i18n/languages";
import type { Initial } from "@/lib/i18n/locale-provider";
import { DEVICE_KEY, resolve } from "@/lib/i18n/resolve";

/**
 * The language of the first paint, from what the request says: the
 * device's choice (the leka-lang cookie), the browser's Accept-Language,
 * and — only when neither says one LEKA offers — the country a CDN in
 * front of LEKA put in a header. Nothing is asked of the browser, nothing
 * is looked up: no location, no service, no delay.
 *
 * Production has no CDN today, so no country header: the browser's
 * language, then English (docs/languages.md).
 */

// What CDNs call the country they saw the request come from.
const COUNTRY_HEADERS = ["cf-ipcountry", "cloudfront-viewer-country", "x-vercel-ip-country"];

export function accepted(header: string | null): string[] {
  return (header ?? "")
    .split(",")
    .map((part) => {
      const [tag, ...parameters] = part.trim().split(";");
      const q = parameters.find((p) => p.trim().startsWith("q="));
      return { tag: tag.trim(), q: q ? Number(q.trim().slice(2)) : 1 };
    })
    .filter(({ tag, q }) => tag && tag !== "*" && Number.isFinite(q) && q > 0 && canonical(tag))
    .sort((a, b) => b.q - a.q)
    .map(({ tag }) => tag);
}

export async function initialLanguage(): Promise<Initial> {
  const [jar, said] = await Promise.all([cookies(), headers()]);
  const browser = accepted(said.get("accept-language"));
  const country =
    COUNTRY_HEADERS.map((name) => said.get(name)).find((value) => value && /^[A-Za-z]{2}$/.test(value)) ??
    null;
  const found = resolve({ device: jar.get(DEVICE_KEY)?.value ?? null, browser, country });
  return {
    ...found,
    region: browser.map((tag) => regionOf(tag)).find(Boolean) ?? null,
    country: country?.toUpperCase() ?? null,
  };
}
