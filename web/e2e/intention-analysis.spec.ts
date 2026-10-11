import { expect, test } from "@playwright/test";

import { analyse, ask } from "./intention-helpers";
import { signIn } from "./sign-in";

/**
 * Intentions analysed, in a real browser (LEKA-388).
 *
 * What a unit test cannot answer: that an intention asked from the
 * composer is analysed from the context assembled for it — by LEKA's own
 * capabilities, on the demo's company — that its page follows the analysis
 * while it runs and shows how it went and what it found, worded, with the
 * evidence and where it came from; that a question answered completes the
 * intention, and an action asked waits for a person.
 *
 * There is no worker here: the analysis the API queues is run as the job
 * runner would, for this intention only.
 */

test.describe("Intention analysis", () => {
  test("asked, analysed, how it went and what it found, its evidence", async ({ page }) => {
    await signIn(page);
    const id = await ask(page, `Qui est responsable de auth-service ? (${Date.now()})`);

    // Not analysed yet: on its way, said so.
    await page.getByTestId("tab-analysis").click();
    await expect(page).toHaveURL(/\/analysis$/);
    const head = page.getByTestId("analysis-head");
    await expect(head).toHaveAttribute("data-live", "true");
    await expect(head).toContainText("Analyse en attente");

    analyse(id);

    // Read again while on its way: done, how it went.
    await expect(head).toHaveAttribute("data-live", "false", { timeout: 15_000 });
    await expect(head.getByTestId("analysis-status")).toHaveText("Complète");
    await expect(head.getByTestId("analysis-meta")).toContainText(
      "Analyse n° 1 · à la création",
    );
    const steps = page.getByTestId("analysis-step");
    await expect(steps).toHaveCount(3);
    await expect(steps.nth(0)).toHaveAttribute("data-name", "standing");
    await expect(steps.nth(1)).toHaveAttribute("data-name", "ownership");
    await expect(steps.nth(1)).toHaveAttribute("data-status", "succeeded");
    await expect(steps.nth(1)).toContainText("Responsabilités · pour son objectif");
    // Written by the model (the stand-in, LEKA-394/429), after the rules.
    await expect(steps.nth(2)).toHaveAttribute("data-name", "synthesis");
    await expect(steps.nth(2)).toHaveAttribute("data-status", "succeeded");
    await expect(steps.nth(2)).toContainText("Synthèse · toujours");

    // Step 3, mockup 04: what it comes to.
    await page.getByTestId("tab-results").click();
    await expect(page).toHaveURL(/\/results$/);
    await expect(page.getByTestId("analysis-answer")).toContainText("Rédigée par Gemini 3.8 Flash");
    // What it found, worded — no proposal.
    await expect(page.getByTestId("analysis-summary")).toContainText(
      "auth-service appartient à Thomas Berger.",
    );
    await expect(page.getByText("Recommandations de LEKA")).toHaveCount(0);
    // Answered: completed, by LEKA.
    await expect(page.getByTestId("intention-status")).toContainText("Terminée");

    // Its evidence: the record that says who owns it, and where from.
    await page.getByTestId("tab-evidence").click();
    const evidence = page.getByTestId("intention-evidence");
    const owner = evidence
      .getByRole("listitem")
      .filter({ hasText: "Thomas Berger possède auth-service" });
    await expect(owner).toBeVisible();
    await expect(owner).toContainText("acme/backend");

    // Its overview and history say it too.
    await page.getByTestId("tab-overview").click();
    // What it came to: the answer the model wrote from it (LEKA-394).
    await expect(page.getByTestId("intention-summary")).toContainText("D'après l'analyse");
    await page.getByTestId("tab-history").click();
    // What happened to the intention itself (its whole story: LEKA-392).
    await page.getByTestId("timeline-category-intention").click();
    await expect(page.getByTestId("intention-event").last()).toContainText("LEKA a répondu");
  });

  test("an action asked waits for a person, what it reaches said", async ({ page }) => {
    await signIn(page);
    const id = await ask(page, `Redémarre auth-service en production (${Date.now()})`);
    analyse(id);

    await page.goto(`/intentions/${id}/analysis`);
    await expect(page.getByTestId("analysis-head")).toHaveAttribute("data-live", "false");
    // By its name: the conclusion says it received « Action demandée » too.
    const action = page.locator('[data-testid="analysis-step"][data-name="action"]');
    await expect(action).toContainText("Action demandée");
    await expect(action).toHaveAttribute("data-status", "succeeded");
    await page.getByTestId("tab-results").click();
    await expect(page.getByTestId("analysis")).toContainText(
      "Demandé : Redémarrer auth-service. Une personne doit l'approuver avant toute exécution.",
    );
    await expect(page.getByTestId("analysis")).toContainText("payment-api");
    // Never LEKA's to decide.
    await expect(page.getByTestId("intention-status")).toContainText("À décider");

    // Left as found: nothing waits in À valider after this test.
    await page.getByTestId("intention-cancel").click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Annuler l'intention" }).click();
    await expect(page.getByTestId("intention-status")).toContainText("Annulée");
  });
});
