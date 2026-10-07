import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * "Insights LEKA", in a real browser (LEKA-377).
 *
 * The seed runs LEKA's analyses over the demo company as the job runs them
 * (scripts/seed.py): what is on the card is what they found, not words
 * written for the demo. payment-api v2.8.4 was deployed 26 hours ago and
 * an incident followed (LEKA-378); the Confluence runbooks space is in
 * error and was never read, and no repository is said to be payment-api's
 * code (LEKA-379); three things rely on postgres-prod, nothing watches it,
 * and no one is named as its owner — Thomas and Mei maintain it, which
 * makes that lighter (LEKA-380) — the services Nadia and Thomas own are not
 * said. And six days ago redis-sessions went from every source while
 * auth-service relied on it (LEKA-383).
 *
 * What a unit test cannot answer: that the engine's findings reach both
 * screens through the API, worded, in an order that holds, each leading to
 * the sheet of what it is about — a source to its page — and that asking
 * for an analysis now is taken.
 */

test.describe("Insights LEKA", () => {
  test("says on the overview what the analyses found, the most pressing first", async ({ page }) => {
    await signIn(page);

    // Two on the overview, the most pressing first: the deployment an
    // incident followed (LEKA-378), then what went while relied on
    // (LEKA-383).
    const lines = page.getByTestId("insights-findings").getByRole("listitem");
    await expect(lines).toHaveCount(2);
    await expect(lines.nth(0)).toContainText(
      "Déploiement « payment-api v2.8.4 » : 1 incident(s) ensuite",
    );
    await expect(lines.nth(1)).toContainText("redis-sessions a disparu de vos sources");
  });

  test("leads from a gap to the source it is about", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment?tab=applications");

    await page
      .getByTestId("insights-findings")
      .getByRole("link", { name: /La source Runbooks space est en erreur/ })
      .click();
    await expect(page).toHaveURL(/\/sources\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Runbooks space");
  });

  test("leads from what the model's course says to the thing it is about", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment?tab=applications");

    await page
      .getByTestId("insights-findings")
      .getByRole("link", { name: /redis-sessions a disparu de vos sources/ })
      .click();
    await expect(page).toHaveURL(/\/environment\/resources\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("redis-sessions");
  });

  test("leads from a change to the service it was made to", async ({ page }) => {
    await signIn(page);

    await page
      .getByTestId("insights-findings")
      .getByRole("link", { name: /payment-api v2\.8\.4/ })
      .click();
    await expect(page).toHaveURL(/\/environment\/services\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("payment-api");
  });

  test("says it on Mon environnement too, and takes an analysis asked for", async ({ page }) => {
    await signIn(page);
    // The card is the landscapes' (the architecture tab draws its own board).
    await page.goto("/environment?tab=applications");

    // Three here: what went while relied on, then — of two equals, the
    // surer (IntelligenceRepository.top) — the source in error.
    const lines = page.getByTestId("insights-findings").getByRole("listitem");
    await expect(lines).toHaveCount(3);
    await expect(lines.nth(1)).toContainText("redis-sessions a disparu de vos sources");
    await expect(lines.nth(1)).toContainText("auth-service en dépendai(en)t encore");
    await expect(lines.nth(2)).toContainText("La source Runbooks space est en erreur");
    await expect(lines.nth(2)).toContainText("Jamais lue");
    await expect(page.getByText(/^Dernière analyse · /)).toBeVisible();
    // Owned by a person: not said.
    await expect(page.getByTestId("insights-findings")).not.toContainText(
      "Aucun responsable nommé pour payment-api",
    );

    await page.getByTestId("insights-analyse").click();
    // Taken: the card waits for the run — and, when one was already on its
    // way, says so too.
    await expect(
      page
        .getByRole("button", { name: /Analyse en cours/ })
        .or(page.getByRole("status").filter({ hasText: "Une analyse est déjà en cours" }))
        .first(),
    ).toBeVisible();
  });
});
