import { expect, test } from "@playwright/test";

import { openIncident } from "./incident";

/**
 * LEKA's intelligence components on a real analysis (LEKA-341): the demo
 * incident of scripts/seed.py — payment-api's latency, which Jira says the
 * v2.8.4 deployment caused — read by the API from PostgreSQL and drawn on
 * its sheet.
 *
 * What a unit test cannot answer: that the company model's own account of
 * an incident — its cause, how sure, its evidence, what it reaches — comes
 * through whole, inspectable, and on a laptop's screen.
 */

test.describe("an incident's analysis", () => {
  test("says its probable cause, how sure, its evidence, and what it reaches", async ({
    page,
  }) => {
    await openIncident(page);
    const analysis = page.getByTestId("incident-analysis");

    const cause = analysis.getByTestId("probable-cause");
    await expect(cause).toContainText("payment-api v2.8.4");
    await expect(cause).toContainText("Confiance moyenne · 83 % · déclaré par la source");
    await cause.getByRole("button", { name: /preuve/ }).click();
    await expect(cause.getByTestId("evidence")).toContainText("Déploiement · payment-api v2.8.4");

    await expect(analysis.getByTestId("findings")).toContainText("sev2");
    await expect(analysis.getByTestId("impact")).toContainText("Risque moyen");
    await expect(analysis.getByTestId("impact")).toContainText("payment-api");
    // Nothing proposed that the model does not propose.
    await expect(analysis.getByTestId("intelligence-proposal")).toContainText(
      "LEKA ne propose pas encore de recommandation",
    );
  });

  test("holds on a laptop's screen", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await openIncident(page);
    const overflow = await page.evaluate(() => {
      const main = document.querySelector("main");
      return Math.max(
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
        main ? main.scrollWidth - main.clientWidth : 0,
      );
    });
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
