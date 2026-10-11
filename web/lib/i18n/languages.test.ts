/**
 * The catalogue as the web reads it, and the same rules as the API
 * (api/tests/test_languages.py): 140 languages, each once; a tag matched as
 * a browser says it; a missing translation falling back along its chain; a
 * language and a region kept apart; a search by any of a language's names.
 */

import { describe, expect, it } from "vitest";

import { DICTIONARIES, PARTIAL } from "@/lib/i18n/dictionaries";
import {
  answers,
  canonical,
  chain,
  direction,
  formatLocale,
  language,
  LANGUAGES,
  match,
  negotiate,
  regionOf,
  shown,
} from "@/lib/i18n/languages";

describe("the catalogue", () => {
  it("offers 140 languages, each once, in canonical BCP 47", () => {
    expect(LANGUAGES).toHaveLength(140);
    expect(new Set(LANGUAGES.map((one) => one.tag)).size).toBe(140);
    for (const one of LANGUAGES) expect(canonical(one.tag)).toBe(one.tag);
  });

  it("says translated only what the interface has words for", () => {
    const said = LANGUAGES.filter((one) => one.ui.app).map((one) => one.tag).sort();
    expect(said).toEqual([...Object.keys(DICTIONARIES), ...Object.keys(PARTIAL)].sort());
    // Whole and approved: French and English, nothing more yet.
    expect(said).toEqual(["en", "fr"]);
  });

  it("knows which way each is written", () => {
    expect(direction("ar")).toBe("rtl");
    expect(direction("ckb")).toBe("rtl");
    expect(direction("kmr")).toBe("ltr");
    expect(direction("ja")).toBe("ltr");
  });
});

describe("a tag as a browser says it", () => {
  it.each([
    ["fr-CA", "fr", "CA"],
    ["pt-BR", "pt", "BR"],
    ["pt_PT", "pt", "PT"],
    ["EN-us", "en", "US"],
    ["zh-CN", "zh-Hans", "CN"],
    ["zh-TW", "zh-Hant", "TW"],
    ["zh-Hant-HK", "zh-Hant", "HK"],
    ["fa-AF", "prs", "AF"],
    ["iw", "he", undefined],
    ["no", "nb", undefined],
    ["sr-Latn-RS", "sr", "RS"],
    ["xx", undefined, undefined],
    ["not a tag", undefined, undefined],
  ])("%s → %s, region %s", (said, offered, region) => {
    expect(match(said)?.tag).toBe(offered);
    expect(regionOf(said)).toBe(region);
  });

  it("takes the first of a browser's languages LEKA offers", () => {
    expect(negotiate(["tlh", "xx-YY", "pt-BR", "en"])?.tag).toBe("pt");
    expect(negotiate(["tlh"])).toBeUndefined();
  });
});

describe("the fallback chain", () => {
  it("goes to the parents, the base, the workspace's, then English", () => {
    expect(chain("prs", "fr")).toEqual(["prs", "fa", "fr", "en"]);
    expect(chain("yue", "de")).toEqual(["yue", "zh-Hant", "de", "en"]);
    expect(chain("nn")).toEqual(["nn", "nb", "en"]);
  });

  it("never leaves a surface without words", () => {
    expect(shown("app", "ja")).toBe("en");
    expect(shown("app", "de", "fr")).toBe("fr");
    expect(shown("site", "de", "fr")).toBe("de");
    expect(shown("app", "unknown", "fr")).toBe("fr");
    expect(shown("app", null)).toBe("en");
  });
});

describe("a language and a region", () => {
  it("make the formatting locale together, and never one another", () => {
    expect(formatLocale("fr", "CA")).toBe("fr-CA");
    expect(formatLocale("zh-Hant", "HK")).toBe("zh-Hant-HK");
    expect(formatLocale("en")).toBe("en");
    // Dates in Canadian French, the words still French.
    const day = new Date(Date.UTC(2026, 9, 11, 12));
    expect(new Intl.DateTimeFormat(formatLocale("fr", "CA"), { timeZone: "UTC" }).format(day)).toBe(
      "2026-10-11",
    );
    expect(new Intl.DateTimeFormat(formatLocale("fr", "FR"), { timeZone: "UTC" }).format(day)).toBe(
      "11/10/2026",
    );
  });
});

describe("searching", () => {
  const ja = language("ja")!;
  const fr = language("fr")!;
  const tr = language("tr")!;

  it("finds a language by its own name, its English name or its tag", () => {
    expect(answers(ja, "日本")).toBe(true);
    expect(answers(ja, "japan")).toBe(true);
    expect(answers(ja, "ja")).toBe(true);
    expect(answers(ja, "korean")).toBe(false);
  });

  it("sets accents and case aside", () => {
    expect(answers(fr, "francais")).toBe(true);
    expect(answers(tr, "TURKCE")).toBe(true);
  });

  it("finds it by its name in the interface's language", () => {
    expect(answers(language("de")!, "allemand", "allemand")).toBe(true);
  });
});
