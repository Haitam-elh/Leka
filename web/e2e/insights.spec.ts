import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * "Insights LEKA", in a real browser (LEKA-377).
 *
 * The seed runs LEKA's analyses over the demo company as the job runs them
 * (scripts/seed.py): what is on the card is what they found, not words
 * written for the demo. Three things rely on postgres-prod, nothing watches
 * it and no one is named as its owner — the services Nadia and Thomas own
 * are not said.
 *
 * What a unit test cannot answer: that the engine's findings reach both
 * screens through the API, worded, each leading to the sheet of what it is
 * about, and that asking for an analysis now is taken.
 */

test.describe("Insights LEKA", () => {
  test("says on the overview what the analyses found, and leads to it", async ({ page }) => {
    await signIn(page);

    const found = page.getByTestId("insights-findings");
    await expect(found).toContainText("Aucun responsable nommé pour postgres-prod");
    await expect(found).toContainText("3 éléments dépendent de postgres-prod");
    // Owned by a person: not said.
    await expect(found).not.toContainText("payment-api");

    await found.getByRole("link", { name: /Aucun responsable nommé pour postgres-prod/ }).click();
    await expect(page).toHaveURL(/\/environment\/databases\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("postgres-prod");
  });

  test("says it on Mon environnement too, and takes an analysis asked for", async ({ page }) => {
    await signIn(page);
    // The card is the landscapes' (the architecture tab draws its own board).
    await page.goto("/environment?tab=applications");

    const found = page.getByTestId("insights-findings");
    await expect(found).toContainText("3 éléments dépendent de postgres-prod");
    await expect(page.getByText(/^Dernière analyse · /)).toBeVisible();

    await page.getByTestId("insights-analyse").click();
    // Taken: the card waits for the run — or says one was already on its way.
    await expect(
      page
        .getByRole("button", { name: /Analyse en cours/ })
        .or(page.getByRole("status").filter({ hasText: "Une analyse est déjà en cours" })),
    ).toBeVisible();
  });
});
