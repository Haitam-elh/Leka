import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * Paramètres → Modèle de langage (LEKA-394), in a real browser, against the
 * real API — with no model key, as CI runs: LEKA's default, Gemini 3.8
 * Flash, said with its price and the key it lacks; nobody to answer, so the
 * rules do. The company's Azure OpenAI plugged in — its key sent once,
 * never shown again — answering first; then removed. No model is called:
 * saving one calls nothing.
 */

test.describe("Language model", () => {
  test("LEKA's default, the company's own plugged in and removed", async ({ page }) => {
    await signIn(page);
    await page.goto("/settings");
    const section = page.getByTestId("language-model");
    await expect(section).toBeVisible();
    await expect(page.getByTestId("model-default")).toContainText("Gemini 3.8 Flash");
    await expect(page.getByTestId("model-default")).toContainText("par million de tokens");
    await expect(page.getByTestId("model-default")).toContainText("Clé non configurée");
    await expect(page.getByTestId("model-nobody")).toBeVisible();

    await page.getByTestId("model-bring").click();
    await page.getByTestId("model-provider").selectOption("azure_openai");
    await page.getByTestId("model-name").fill("gpt-prod");
    await page.getByTestId("model-url").fill("https://acme-ai.openai.azure.com");
    await page.getByTestId("model-version").fill("2024-10-21");
    await page.getByTestId("model-key").fill("azure-e2e-secret-4321");
    await page.getByTestId("model-save").click();

    const line = page.getByTestId("model-own-line");
    await expect(line).toContainText("Azure OpenAI");
    await expect(line).toContainText("…4321");
    await expect(line).toContainText("Non testé");
    await expect(section).not.toContainText("azure-e2e-secret-4321");
    await expect(page.getByTestId("model-answering")).toContainText("Votre entreprise");

    await page.getByTestId("model-remove").click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Retirer" }).click();
    await expect(page.getByTestId("model-own")).toContainText(
      "Aucun : c'est le modèle de LEKA qui répond.",
    );
    await expect(page.getByTestId("model-nobody")).toBeVisible();
  });
});
