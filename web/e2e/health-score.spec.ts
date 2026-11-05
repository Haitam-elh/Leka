import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The environment's health score, explained (LEKA-489, LEKA-532): from the
 * home, the way to it; on Mon environnement, the diagnosis — its rule as
 * the code applies it, health apart from coverage, what each state means
 * and what keeps it from 100 % — on the demo company's real figures.
 */
test.describe("The health score, explained (LEKA-489, LEKA-532)", () => {
  test("from the home to its rule, its states and what keeps it from 100 %", async ({ page }) => {
    await signIn(page);
    await page.goto("/overview");
    await page.getByTestId("home-health-explained").click();
    await expect(page).toHaveURL(/\/environment\?state=all$/);

    const diagnostic = page.getByTestId("diagnostic");
    await expect(diagnostic).toBeVisible();
    await expect(page.getByTestId("diagnostic-method")).toContainText(
      /Score = éléments en bonne santé ÷ éléments suivis\. Ici : \d+ ÷ \d+ = \d+\s%\./,
    );
    await expect(page.getByTestId("diagnostic-method")).toContainText("Ne comptent pas : les dépôts");
    await page.getByTestId("diagnostic-states").getByText("Que veut dire chaque état ?").click();
    await expect(page.getByTestId("diagnostic-states").getByRole("term")).toHaveCount(6);
    await expect(diagnostic).toContainText("Ce qui empêche 100 %");
    await expect(diagnostic).toContainText("100 % ne garantit pas que tout fonctionne");
  });
});
