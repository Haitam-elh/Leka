import { expect, test } from "@playwright/test";

import { analyse, ask } from "./intention-helpers";
import { signIn } from "./sign-in";

/**
 * The LLM runtime, end to end (LEKA-429): LEKA's default model — Gemini 3.8
 * Flash, at the tests' stand-in (e2e/model-stub.mjs) — doing real work
 * through the real gateway and runtime, in a real browser.
 *
 * An Intention flow: words the rules cannot read — no goal said — read by
 * the model, so the intention is analysed instead of stopped for a
 * question; what it understood said, and by which model.
 *
 * A Capability flow: the synthesis — a capability written by a model,
 * chosen for it by what it needs — answers the analysis in words, each
 * point citing what it rests on; its sheet says which model runs it.
 *
 * Both kept: Paramètres › Modèle de langage counts them, with the version
 * that answered.
 */

test.describe("LLM runtime", () => {
  test("an intention read and answered by the model, a capability run by it", async ({
    page,
  }) => {
    await signIn(page);
    const id = await ask(page, `auth-service, c'est à qui de voir ça ? (${Date.now()})`);

    // Read by the model: its goal settled, not stopped for a question —
    // what LEKA understood is step 1's.
    await page.getByTestId("tab-overview").click();
    const understood = page.getByTestId("intention-brief");
    await expect(understood.locator('[data-testid="brief-slot"][data-slot="goal"]')).toContainText(
      "Trouver le responsable",
    );
    await expect(understood.getByTestId("brief-restated")).toContainText("Lu par Gemini 3.8 Flash");
    await expect(understood.getByTestId("brief-questions")).toHaveCount(0);

    analyse(id);

    // Answered: the synthesis ran after the rules, its answer leads.
    await page.goto(`/intentions/${id}/analysis`);
    const synthesis = page.locator('[data-testid="analysis-step"][data-name="synthesis"]');
    await expect(synthesis).toHaveAttribute("data-status", "succeeded");
    await page.goto(`/intentions/${id}/results`);
    const answer = page.getByTestId("analysis-answer");
    await expect(answer).toContainText("D'après l'analyse");
    await expect(answer.getByTestId("answer-point").first()).toContainText("élément(s) cité(s)");
    await expect(answer).toContainText("Rédigée par Gemini 3.8 Flash");

    // The capability, and the model its needs chose.
    await page.goto("/capabilities/synthesis");
    await expect(page.getByTestId("capability-availability")).toContainText("Disponible");
    await expect(page.getByTestId("capability-model")).toContainText(
      "Gemini 3.8 Flash (LEKA), choisi selon ses besoins",
    );
    await expect(page.getByTestId("capability-model")).toContainText("réponse structurée");

    // Kept: what was asked of the model, and which version answered.
    await page.goto("/settings");
    const usage = page.getByTestId("model-usage");
    await expect(usage).toContainText("Comprendre une demande");
    await expect(usage).toContainText("Rédiger une réponse");
    await expect(page.getByTestId("model-call").first()).toContainText("gemini-3.8-flash-e2e");
  });
});
