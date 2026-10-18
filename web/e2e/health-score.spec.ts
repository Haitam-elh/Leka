import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The environment's health score, explained (LEKA-489): from the home, the
 * way to it; on Mon environnement, its rule, what each state means and
 * what would raise it — on the demo company's real figures.
 */
test.describe("The health score, explained (LEKA-489)", () => {
  test("from the home to its rule, its states and what would raise it", async ({ page }) => {
    await signIn(page);
    await page.goto("/overview");
    await page.getByTestId("home-health-explained").click();
    await expect(page).toHaveURL(/\/environment$/);

    const explained = page.getByTestId("score-explained");
    await expect(explained).toBeVisible();
    await explained.getByText("Comment ce score est calculé").click();
    await expect(page.getByTestId("score-method")).toContainText(/\d+ éléments? opérationnels? sur \d+ suivis?/);
    await explained.getByText("Que veut dire chaque état ?").click();
    await expect(page.getByTestId("score-states").getByRole("term")).toHaveCount(6);
    await expect(page.getByTestId("score-improve")).toContainText("Pour améliorer la couverture");
  });
});
