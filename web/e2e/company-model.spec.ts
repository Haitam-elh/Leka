import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * No model catalogue for customers (LEKA-530), in a real browser, against
 * the real API: Paramètres says nothing of LEKA's models — no list, no
 * price, no choice of which one answers, no tokens — on a public plan, and
 * offers no model of the company's own (an Enterprise contract does:
 * enterprise.spec.ts). A capability's page says it is ready, on the model
 * LEKA chose, never which one nor what it needs.
 */

test.describe("No model catalogue", () => {
  test("Paramètres and a capability's page say nothing of LEKA's models", async ({ page }) => {
    await signIn(page);
    await page.goto("/settings");
    const main = page.locator("#main-content");
    await expect(page.getByTestId("workspace-settings")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("company-model")).toHaveCount(0);
    for (const said of ["Gemini", "Mistral", "par million de tokens", "Modèle de langage"]) {
      await expect(main).not.toContainText(said);
    }

    await page.goto("/capabilities/synthesis");
    const model = page.getByTestId("capability-model");
    await expect(model).toContainText("prêt : le modèle choisi par LEKA");
    await expect(model).not.toContainText("Gemini");
    await expect(model).not.toContainText("réponse structurée");
  });
});
