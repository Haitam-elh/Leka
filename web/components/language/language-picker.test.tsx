/**
 * The language picker (docs/languages.md): every one of the 140 languages,
 * found by its own name, its English name or its name in the interface's
 * language, accents aside; the translated ones first; each saying honestly
 * what choosing it gives; chosen by the keyboard as well as the mouse.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguagePicker } from "@/components/language/language-picker";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

afterEach(() => vi.unstubAllGlobals());

/** What GET /interface says: how far LEKA translated each language. */
function translatedByLeka(said: { tag: string; status: string; done: number; total: number }[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(said.map((one) => ({ ...one, model: null }))), { status: 200 })),
  );
}

const option = (tag: string) => screen.getAllByRole("option").find((o) => o.dataset.tag === tag)!;

function show(onChoose = vi.fn(), value = "fr", workspace: string | null = null) {
  render(
    <LocaleProvider initial={{ language: "fr", source: "browser" }}>
      <LanguagePicker value={value} onChoose={onChoose} workspace={workspace} />
    </LocaleProvider>,
  );
  return onChoose;
}

describe("the language picker", () => {
  it("offers all 140, the translated ones first", () => {
    show();
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(140);
    expect(options.slice(0, 2).map((o) => o.dataset.tag)).toEqual(["en", "fr"]);
    expect(screen.getByRole("option", { selected: true })).toHaveAttribute("data-tag", "fr");
  });

  it.each([
    ["日本", "ja"],
    ["japanese", "ja"],
    ["japonais", "ja"],
    ["francais", "fr"],
    ["TURKCE", "tr"],
    ["العربية", "ar"],
    ["kurmanji", "kmr"],
  ])("finds « %s »", async (query, tag) => {
    const user = userEvent.setup();
    show();
    await user.type(screen.getByRole("combobox"), query);
    expect(screen.getAllByRole("option").map((o) => o.dataset.tag)).toContain(tag);
  });

  it("says when nothing matches", async () => {
    const user = userEvent.setup();
    show();
    await user.type(screen.getByRole("combobox"), "klingon");
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByRole("status")).toHaveTextContent("Aucune langue ne correspond à « klingon ».");
  });

  it("says honestly what choosing each one gives", async () => {
    const user = userEvent.setup();
    show(vi.fn(), "fr", "fr");
    const fr = option("fr");
    expect(within(fr).getByTestId("language-status")).toHaveTextContent("Interface traduite et relue");

    await user.type(screen.getByRole("combobox"), "japan");
    const ja = option("ja");
    // No dictionary: LEKA translates the whole interface once it is chosen,
    // and answers in Japanese.
    expect(within(ja).getByTestId("language-status")).toHaveTextContent(
      "Interface traduite par LEKA dès que vous la choisissez, en quelques minutes · LEKA vous répond en 日本語",
    );
    // Its own name in its own language, for a screen reader's voice.
    expect(within(ja).getByText("日本語")).toHaveAttribute("lang", "ja");
  });

  it("says how far LEKA translated a language it translates itself", async () => {
    translatedByLeka([
      { tag: "ja", status: "ready", done: 7000, total: 7000 },
      { tag: "de", status: "translating", done: 2100, total: 7000 },
    ]);
    const user = userEvent.setup();
    show();
    await user.type(screen.getByRole("combobox"), "japan");
    expect(await within(option("ja")).findByText(/Interface traduite automatiquement par LEKA/)).toBeInTheDocument();
    await user.clear(screen.getByRole("combobox"));
    await user.type(screen.getByRole("combobox"), "deutsch");
    expect(within(option("de")).getByTestId("language-status")).toHaveTextContent(
      "Traduction de l'interface en cours : 30 %",
    );
  });

  it("says a model's answers may be weaker where they are", async () => {
    const user = userEvent.setup();
    show();
    await user.type(screen.getByRole("combobox"), "bodo");
    expect(within(screen.getByRole("option")).getByTestId("language-status")).toHaveTextContent(
      "Réponses en बड़ो : qualité variable selon le modèle",
    );
  });

  it("writes a right-to-left name right to left", async () => {
    const user = userEvent.setup();
    show();
    await user.type(screen.getByRole("combobox"), "urdu");
    expect(screen.getByText("اردو")).toHaveAttribute("dir", "rtl");
  });

  it("is chosen by the keyboard", async () => {
    const user = userEvent.setup();
    const onChoose = show();
    await user.type(screen.getByRole("combobox"), "deutsch");
    await user.keyboard("{ArrowDown}{ArrowUp}{Enter}");
    expect(onChoose).toHaveBeenCalledWith("de");
  });

  it("is chosen by a click", async () => {
    const user = userEvent.setup();
    const onChoose = show();
    await user.type(screen.getByRole("combobox"), "swahili");
    await user.click(option("sw"));
    expect(onChoose).toHaveBeenCalledWith("sw");
  });
});
