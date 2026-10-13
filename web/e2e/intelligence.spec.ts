import { expect, test } from "@playwright/test";

import { openIncident, openIncidentAnalysis } from "./incident";

/**
 * LEKA's intelligence components on a real analysis (LEKA-341): the demo
 * incident of scripts/seed.py — payment-api's latency, which Jira says the
 * v2.8.4 deployment caused — read by the API from PostgreSQL and drawn on
 * its sheet.
 *
 * What a unit test cannot answer: that the company model's own account of
 * an incident — what it comes to, its cause, how sure and on what, its
 * evidence, what it reaches — comes through whole, inspectable, and on a
 * laptop's screen, folded or not.
 */

test.describe("an incident's analysis", () => {
  test("says what it comes to, then its cause, how sure, its evidence, what it reaches", async ({
    page,
  }) => {
    await openIncident(page);
    const analysis = page.getByTestId("incident-analysis");
    await expect(analysis.getByTestId("incident-summary")).toContainText(
      "Cause déclarée par sa source : payment-api v2.8.4.",
    );
    // Folded until asked: mockup 11's band.
    await expect(analysis.getByTestId("analysis")).toBeHidden();

    await analysis.getByRole("button", { name: "Voir l'analyse complète" }).click();
    const cause = analysis.getByTestId("probable-cause");
    await expect(cause).toContainText("payment-api v2.8.4");
    await expect(cause).toContainText("Cause déclarée");
    await expect(cause.getByTestId("confidence")).toContainText("Confiance moyenne");
    await expect(cause.getByTestId("confidence")).toContainText("83 % · déclaré par la source");
    await cause.getByRole("button", { name: /Voir les éléments/ }).click();
    await expect(cause.getByTestId("evidence")).toContainText("Déploiement · payment-api v2.8.4");

    await expect(analysis.getByTestId("findings")).toContainText("sev2");
    await expect(
      analysis.getByRole("region", { name: "Confiance de l'analyse" }),
    ).toContainText(/sources? lues?/);
    await expect(analysis.getByTestId("impact-level")).toHaveText("Moyen");
    await expect(analysis.getByTestId("impact")).toContainText("payment-api");
    // Nothing proposed that the model does not propose.
    await expect(analysis.getByTestId("intelligence-proposal")).toContainText(
      "LEKA ne propose pas encore de recommandation",
    );
  });

  test("holds on a laptop's screen, unfolded", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await openIncidentAnalysis(page);
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
