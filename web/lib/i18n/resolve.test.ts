/**
 * Which language LEKA speaks to someone, in the ticket's order: a choice
 * made just now, the account's, the device's, the browser's, the country's
 * hint, English. A country never wins over a browser that says a language.
 */

import { afterEach, describe, expect, it } from "vitest";

import { browserSignals, countryLanguage, qaFromAddress, remember, resolve, settled } from "@/lib/i18n/resolve";

afterEach(() => {
  document.cookie = "leka-lang=; Path=/; Max-Age=0";
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("the order", () => {
  const all = {
    qa: null,
    now: "es",
    account: "de",
    device: "it",
    browser: ["pt-BR"],
    country: "JP",
  };

  it("takes the first that says a language LEKA offers", () => {
    expect(resolve(all)).toEqual({ language: "es", source: "now" });
    expect(resolve({ ...all, now: null })).toEqual({ language: "de", source: "account" });
    expect(resolve({ ...all, now: null, account: null })).toEqual({ language: "it", source: "device" });
    expect(resolve({ ...all, now: null, account: null, device: null })).toEqual({
      language: "pt",
      source: "browser",
    });
    expect(resolve({ browser: [], country: "JP" })).toEqual({ language: "ja", source: "country" });
    expect(resolve({})).toEqual({ language: "en", source: "default" });
  });

  it("never lets a country decide when the browser says a language", () => {
    // Someone in France whose browser speaks English reads English.
    expect(resolve({ browser: ["en-US"], country: "FR" }).language).toBe("en");
  });

  it("skips what it does not offer, and falls back on English", () => {
    expect(resolve({ browser: ["tlh", "xx"], country: null })).toEqual({ language: "en", source: "default" });
    expect(resolve({ account: "xx", browser: ["fr-FR"] }).language).toBe("fr");
  });

  it("puts a QA pseudo-language before everything", () => {
    expect(resolve({ ...all, qa: "ar-XB" })).toEqual({ language: "ar-XB", source: "qa" });
  });
});

describe("a country, as a hint", () => {
  it.each([
    ["JP", "ja"],
    ["CH", "de"],
    ["FR", "fr"],
    ["BR", "pt"],
    ["EG", "ar"],
    ["zz", undefined],
    ["France", undefined],
    [null, undefined],
  ])("%s → %s", (country, said) => {
    expect(countryLanguage(country)).toBe(said);
  });
});

describe("where a choice is kept", () => {
  it("on the device, and as just made until the account takes it", () => {
    remember("ja");
    expect(document.cookie).toContain("leka-lang=ja");
    expect(window.localStorage.getItem("leka-lang")).toBe("ja");
    expect(browserSignals()).toMatchObject({ now: "ja", device: "ja" });

    settled();
    expect(browserSignals()).toMatchObject({ now: null, device: "ja" });
  });

  it("reads the application's old key", () => {
    window.localStorage.setItem("leka.locale", "en");
    expect(browserSignals().device).toBe("en");
  });

  it("turns the QA pseudo-languages on and off from the address", () => {
    qaFromAddress("?qa-language=ar-XB");
    expect(browserSignals().qa).toBe("ar-XB");
    qaFromAddress("?qa-language=");
    expect(browserSignals().qa).toBeNull();
  });
});
