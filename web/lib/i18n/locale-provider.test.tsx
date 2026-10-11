/**
 * The language a person reads, as the provider settles it: the server's first
 * guess, then the browser's own signals, then the account once signed in —
 * its language winning over the device's, a choice made just now winning
 * over both and handed to the account. The document says the language the
 * screens speak, and which way it reads.
 */

import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { type AccountLanguage, LocaleProvider, useLanguage } from "@/lib/i18n/locale-provider";
import { remember } from "@/lib/i18n/resolve";

let probe: ReturnType<typeof useLanguage> | null = null;

function Probe() {
  probe = useLanguage();
  return (
    <p data-testid="said">
      {probe.language} {probe.locale} {probe.format} {probe.dictionary.nav.settings}
    </p>
  );
}

function show(initial = { language: "fr", source: "browser" as const }) {
  return render(
    <LocaleProvider initial={initial}>
      <Probe />
    </LocaleProvider>,
  );
}

function adopt(account: AccountLanguage | null, workspace: string | null = null): string | null {
  let keep: string | null = null;
  act(() => {
    keep = probe!.adopt(account, workspace);
  });
  return keep;
}

afterEach(() => {
  document.cookie = "leka-lang=; Path=/; Max-Age=0";
  window.localStorage.clear();
  window.sessionStorage.clear();
  probe = null;
});

describe("the language a person reads", () => {
  it("is the browser's when nothing else says one", () => {
    show();
    expect(screen.getByTestId("said")).toHaveTextContent("fr fr fr-FR Paramètres");
    expect(document.documentElement.lang).toBe("fr");
    expect(document.documentElement.dir).toBe("ltr");
  });

  it("follows the account once signed in, over the device", () => {
    window.localStorage.setItem("leka-lang", "de");
    show();
    expect(probe!.language).toBe("de");
    expect(adopt({ language: "en" })).toBeNull();
    expect(probe!.language).toBe("en");
    expect(probe!.dictionary.nav.settings).toBe("Settings");
  });

  it("hands the account a choice made just now", () => {
    show();
    act(() => remember("ja"));
    expect(adopt({ language: "en" })).toBe("ja");
    expect(probe!.language).toBe("ja");
    act(() => probe!.saved("ja"));
    expect(probe!.unconfirmed).toBe(false);
  });

  it("hands the account the device's choice when it has none", () => {
    document.cookie = "leka-lang=es; Path=/";
    show();
    expect(adopt({ language: null })).toBe("es");
  });

  it("asks once when the language was only found, not chosen", () => {
    show();
    expect(adopt({ language: null })).toBeNull();
    expect(probe!.unconfirmed).toBe(true);
  });

  it("shows an untranslated language's screens in the workspace's language", () => {
    show();
    adopt({ language: "ja" }, "fr");
    expect(probe!.language).toBe("ja");
    expect(probe!.locale).toBe("fr");
    expect(probe!.dictionary.nav.settings).toBe("Paramètres");
    expect(document.documentElement.lang).toBe("fr");
    expect(document.documentElement.dataset.language).toBe("ja");
  });

  it("formats in the person's region, never changing the language", () => {
    show();
    adopt({ language: "fr", region: "CA" });
    expect(probe!.format).toBe("fr-CA");
    expect(probe!.dictionary.nav.settings).toBe("Paramètres");
  });

  it("reads right to left in the RTL pseudo-language", () => {
    window.sessionStorage.setItem("leka.qa-language", "ar-XB");
    show();
    expect(probe!.language).toBe("ar-XB");
    expect(document.documentElement.dir).toBe("rtl");
    expect(probe!.dictionary.nav.settings).toBe("‏‮Settings‬‏");
  });

  it("refuses a language LEKA does not offer", () => {
    show();
    act(() => probe!.setLanguage("tlh"));
    expect(probe!.language).toBe("fr");
  });
});
