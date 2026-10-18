/**
 * A plan LEKA's rules wrote, in the reader's language (LEKA-495): French for
 * French, English for any other; a model's own words as written.
 */

import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intentions/queries", () => ({ useIntentionAnalysis: () => ({ data: undefined }) }));

const { inReadersWords } = await import("@/components/intentions/agents-decision");

const proposal = {
  agents: [],
  steps: [
    {
      title: "Rassembler ce qui a changé",
      detail: "Déploiements récents.",
      agent: null,
      words: {
        fr: { title: "Rassembler ce qui a changé", detail: "Déploiements récents." },
        en: { title: "Gather what changed", detail: "Recent deployments." },
      },
    },
    { title: "Étape écrite par le modèle", detail: "", agent: null, words: null },
  ],
} as never;

describe("a rules plan, in the reader's words", () => {
  it("English for an English reader, French for a French one, a model's words untouched", () => {
    const en = inReadersWords(proposal, "en-GB");
    expect(en.steps.map((s) => s.title)).toEqual(["Gather what changed", "Étape écrite par le modèle"]);
    expect(inReadersWords(proposal, "de").steps[0].title).toBe("Gather what changed");
    expect(inReadersWords(proposal, "fr").steps[0].detail).toBe("Déploiements récents.");
  });
});
