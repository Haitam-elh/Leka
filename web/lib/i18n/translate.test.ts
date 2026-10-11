/**
 * The words a person reads: their language's, the next of its chain where it
 * has none — never an empty string, never a key — and what fell back said.
 * Then plurals, numbers, dates, time zones and currencies by the language's
 * own rules, and the QA pseudo-languages.
 */

import { afterEach, describe, expect, it } from "vitest";

import { DICTIONARIES, fill, PARTIAL } from "@/lib/i18n/dictionaries";
import { plural } from "@/lib/i18n/format";
import { pseudoDictionary } from "@/lib/i18n/pseudo";
import { forgetWords, wordsFor } from "@/lib/i18n/translate";

afterEach(() => {
  for (const key of Object.keys(PARTIAL)) delete PARTIAL[key];
  forgetWords();
});

describe("the fallback", () => {
  it("speaks a translated language whole", () => {
    expect(wordsFor("fr").shown).toBe("fr");
    expect(wordsFor("fr").dictionary.nav.settings).toBe("Paramètres");
    expect(wordsFor("en").dictionary.nav.settings).toBe("Settings");
  });

  it("falls to the workspace's language, then English", () => {
    expect(wordsFor("de", "fr").shown).toBe("fr");
    expect(wordsFor("ja").shown).toBe("en");
    expect(wordsFor("ar", "en").dictionary.nav.settings).toBe("Settings");
  });

  it("fills a partial translation key by key, and says what is missing", () => {
    PARTIAL.de = { nav: { settings: "Einstellungen" } };
    forgetWords();
    const words = wordsFor("de", "en");
    expect(words.shown).toBe("de");
    expect(words.dictionary.nav.settings).toBe("Einstellungen");
    expect(words.dictionary.nav.billing).toBe("Billing");
    expect(words.missing).toContain("nav.billing");
    expect(words.missing).not.toContain("nav.settings");
    // Then the workspace's French before English.
    forgetWords();
    expect(wordsFor("de", "fr").dictionary.nav.billing).toBe("Facturation");
  });

  it("never shows an empty string, even one a partial translation left blank", () => {
    PARTIAL.it = { nav: { settings: "  " } };
    forgetWords();
    expect(wordsFor("it", "en").dictionary.nav.settings).toBe("Settings");
  });
});

describe("plurals", () => {
  const files = { one: "{n} fichier", other: "{n} fichiers" };
  it("follows each language's rules", () => {
    // French: 0 and 1 are singular.
    expect(plural("fr", 0, files)).toBe("0 fichier");
    expect(plural("fr", 1, files)).toBe("1 fichier");
    expect(plural("fr", 2, files)).toBe("2 fichiers");
    // English: 0 is plural.
    expect(plural("en", 0, { one: "{n} file", other: "{n} files" })).toBe("0 files");
    // Polish: one, few, many.
    const pl = { one: "{n} plik", few: "{n} pliki", many: "{n} plików", other: "{n} pliku" };
    expect([1, 2, 5, 22, 25].map((n) => plural("pl", n, pl))).toEqual([
      "1 plik",
      "2 pliki",
      "5 plików",
      "22 pliki",
      "25 plików",
    ]);
    // Arabic: six forms, and its own digits.
    const ar = { zero: "zero", one: "one", two: "two", few: "few", many: "many", other: "other" };
    expect([0, 1, 2, 3, 11, 100].map((n) => plural("ar", n, ar))).toEqual([
      "zero",
      "one",
      "two",
      "few",
      "many",
      "other",
    ]);
    expect(plural("ar-EG", 12, { other: "{n}" })).toBe("١٢");
  });
});

describe("numbers, dates, time zones and currencies", () => {
  const moment = new Date(Date.UTC(2026, 9, 11, 22, 30));

  // French groups digits with a narrow no-break space, and puts a no-break
  // space before €: compared as plain spaces.
  const plain = (text: string) => text.replace(/[\u202f\u00a0]/g, " ");

  it("writes numbers and amounts as each region does", () => {
    expect(plain(new Intl.NumberFormat("fr-FR").format(1234567.5))).toBe("1 234 567,5");
    expect(new Intl.NumberFormat("en-US").format(1234567.5)).toBe("1,234,567.5");
    expect(new Intl.NumberFormat("de-CH").format(1234567.5)).toBe("1’234’567.5");
    expect(new Intl.NumberFormat("hi-IN").format(1234567)).toBe("12,34,567");
    expect(new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY" }).format(1234)).toBe("￥1,234");
    expect(plain(new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(125.3))).toBe(
      "125,30 €",
    );
  });

  it("says the same moment in each time zone", () => {
    const at = (zone: string) =>
      new Intl.DateTimeFormat("en-GB", { timeZone: zone, dateStyle: "short", timeStyle: "short" }).format(moment);
    expect(at("Europe/Paris")).toBe("12/10/2026, 00:30");
    expect(at("America/New_York")).toBe("11/10/2026, 18:30");
    expect(at("Asia/Tokyo")).toBe("12/10/2026, 07:30");
  });

  it("writes dates in each script", () => {
    const day = (locale: string) => new Intl.DateTimeFormat(locale, { dateStyle: "long", timeZone: "UTC" }).format(moment);
    expect(day("ja-JP")).toBe("2026年10月11日");
    expect(day("ru-RU")).toContain("октября");
    expect(day("ar-EG")).toContain("أكتوبر");
    expect(day("th-TH")).toContain("2569"); // the Buddhist era
  });
});

describe("the QA pseudo-languages", () => {
  const en = DICTIONARIES.en;

  it("en-XA: longer, accented, placeholders kept", () => {
    const xa = pseudoDictionary("en-XA", en);
    expect(xa.nav.settings).toMatch(/^\[Šéţţîñĝš ·+\]$/);
    expect(xa.nav.settings.length).toBeGreaterThan(en.nav.settings.length * 1.3);
    const template = xa.language.saved;
    expect(template).toContain("{name}");
    expect(fill(template, { name: "日本語" })).toContain("日本語");
  });

  it("ar-XB: right to left, the words still English", () => {
    const xb = pseudoDictionary("ar-XB", en);
    expect(xb.nav.settings).toBe("‏‮Settings‬‏");
  });
});
