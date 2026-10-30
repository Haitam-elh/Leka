/**
 * The whole interface in a language without a dictionary (2026-10-30):
 * chosen, LEKA translates it; its words arrive as it goes and the screens
 * switch to them without a reload; how far it is, said in a corner.
 */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TranslatingNotice } from "@/components/language/translating-notice";
import { DICTIONARIES, PARTIAL } from "@/lib/i18n/dictionaries";
import { LocaleProvider, useDictionary, useLanguage, useLocale } from "@/lib/i18n/locale-provider";
import { flatWords, nestedWords, translatedByLeka } from "@/lib/i18n/remote";
import { forgetWords, wordsFor } from "@/lib/i18n/translate";

function Screen() {
  const t = useDictionary();
  const { setLocale } = useLocale();
  const { translating } = useLanguage();
  return (
    <>
      <p data-testid="home">{t.nav.overview}</p>
      <p data-testid="new">{t.nav.newIntention}</p>
      <p data-testid="progress">{translating ? `${translating.status} ${translating.done}` : "none"}</p>
      <button type="button" onClick={() => setLocale("es")}>
        es
      </button>
      <TranslatingNotice />
    </>
  );
}

/** The API, as it answers while it translates: each ask, the next answer. */
function answers(said: object[]) {
  const asked: string[] = [];
  const fetch = vi.fn(async (address: string) => {
    asked.push(address);
    const next = said.length > 1 ? said.shift()! : said[0];
    return new Response(JSON.stringify(next), { status: 200 });
  });
  vi.stubGlobal("fetch", fetch);
  return asked;
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  delete PARTIAL.es;
  forgetWords();
});

describe("the interface's words, flat", () => {
  it("go and come back as the dictionary is shaped, lists by index", () => {
    const tree = { nav: { home: "Home" }, steps: ["One", "Two"] };
    const flat = flatWords(tree);
    expect(flat).toEqual({ "nav.home": "Home", "steps.0": "One", "steps.1": "Two" });
    expect(nestedWords(flat)).toEqual({ nav: { home: "Home" }, steps: { 0: "One", 1: "Two" } });
  });

  it("translate a list's items too", () => {
    const english = DICTIONARIES.en.billing.compare.features.free;
    PARTIAL.es = nestedWords({ "billing.compare.features.free.0": "Uno" }) as typeof PARTIAL.es;
    forgetWords();
    const words = wordsFor("es");
    expect(Array.isArray(words.dictionary.billing.compare.features.free)).toBe(true);
    expect(words.dictionary.billing.compare.features.free[0]).toBe("Uno");
    expect(words.dictionary.billing.compare.features.free.slice(1)).toEqual(english.slice(1));
    expect(words.shown).toBe("es");
  });

  it("are LEKA's to translate only where there is no dictionary", () => {
    expect(translatedByLeka("es")).toBe(true);
    expect(translatedByLeka("ja")).toBe(true);
    expect(translatedByLeka("fr")).toBe(false);
    expect(translatedByLeka("en")).toBe(false);
    expect(translatedByLeka("en-XA")).toBe(false);
    expect(translatedByLeka("klingon")).toBe(false);
  });
});

describe("choosing a language without a dictionary", () => {
  it("switches the whole interface as its words arrive, without a reload", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const asked = answers([
      { tag: "es", status: "translating", done: 1, total: 2, model: null, words: { "nav.overview": "Mi panel" } },
      { tag: "es", status: "ready", done: 2, total: 2, model: null, words: {} },
      {
        tag: "es",
        status: "ready",
        done: 2,
        total: 2,
        model: "mistral:mistral-medium-latest",
        words: { "nav.overview": "Mi panel", "nav.newIntention": "Nueva intención" },
      },
    ]);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(
      <LocaleProvider initial={{ language: "en", source: "browser" }}>
        <Screen />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("home")).not.toHaveTextContent("Mi panel");

    await user.click(screen.getByRole("button", { name: "es" }));
    // Its first words: the screens read them at once, the rest still English.
    expect(await screen.findByText("Mi panel")).toBeInTheDocument();
    // The rest in English meanwhile, the chain's last language.
    expect(screen.getByTestId("new")).toHaveTextContent("New intention");
    expect(screen.getByTestId("interface-translating")).toHaveTextContent("Español: 50%");
    expect(document.documentElement.lang).toBe("es");
    expect(asked[0]).toMatch(/\/api\/v1\/interface\/es$/);

    // How far, looked at again; done: its last words read, the notice gone.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000);
    });
    expect(await screen.findByText("Nueva intención")).toBeInTheDocument();
    expect(asked[1]).toMatch(/\/api\/v1\/interface\/es\?words=false$/);
    expect(screen.queryByTestId("interface-translating")).not.toBeInTheDocument();
    expect(screen.getByTestId("progress")).toHaveTextContent("ready 2");
  });

  it("starts in the words this device kept, the next visit", async () => {
    window.localStorage.setItem(
      "leka.interface.es",
      JSON.stringify({ tag: "es", status: "ready", done: 1, total: 1, model: null, words: { "nav.overview": "Mi panel" } }),
    );
    answers([{ tag: "es", status: "ready", done: 1, total: 1, model: null, words: { "nav.overview": "Mi panel" } }]);
    const user = userEvent.setup();
    render(
      <LocaleProvider initial={{ language: "en", source: "browser" }}>
        <Screen />
      </LocaleProvider>,
    );
    await user.click(screen.getByRole("button", { name: "es" }));
    expect(await screen.findByText("Mi panel")).toBeInTheDocument();
    expect(screen.queryByTestId("interface-translating")).not.toBeInTheDocument();
  });

  it("stays readable when the API cannot be reached", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    const user = userEvent.setup();
    render(
      <LocaleProvider initial={{ language: "en", source: "browser" }}>
        <Screen />
      </LocaleProvider>,
    );
    await user.click(screen.getByRole("button", { name: "es" }));
    expect(screen.getByTestId("home")).toHaveTextContent("My Dashboard");
    expect(screen.getByTestId("progress")).toHaveTextContent("none");
    expect(screen.queryByTestId("interface-translating")).not.toBeInTheDocument();
  });
});
