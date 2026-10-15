import { expect, type Page, test } from "@playwright/test";

import { approved, openStep } from "./intention-helpers";
import { signIn } from "./sign-in";

/**
 * What came of approved actions, and each intention's whole story, in a
 * real browser (LEKA-392).
 *
 * What a unit test cannot answer: that on the demo, a plan expects LEKA's
 * defaults — what is restarted, healthy — that who may approve changes them
 * before it runs; that once a person did it, its outcome is verified on the
 * page — a person's word with what shows it achieving it, the intention
 * completed, the company's context rebuilt — or concluded short of it, the
 * intention failed; and that its history tells all of it, filtered. What the
 * model and the systems that acted say is proven by the API's tests: there
 * is no sync, nor a customer's system, here.
 */

/** Prepared from the tab Actions: the plan ready, what it expects said. */
async function prepared(page: Page) {
  await approved(page);
  await openStep(page, "actions");
  await page.getByTestId("plan-prepare-button").click();
  await expect(page.getByTestId("plan-status")).toHaveText("Prêt");
  const expected = page.getByTestId("expectations");
  // LEKA's default: what is restarted, healthy.
  await expect(expected).toContainText("auth-service en bonne santé");
  return expected;
}

/** Run, its one step done by a person: verifying. */
async function done(page: Page) {
  await page.getByTestId("plan-start").click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Lancer maintenant" }).click();
  const step = page.getByTestId("plan-step");
  await step.getByTestId("step-report-note").fill("Redémarré depuis la console.");
  await step.getByTestId("step-done").click();
  await expect(page.getByTestId("plan-status")).toHaveText("Exécuté · à vérifier");
  await expect(page.getByTestId("intention-status")).toContainText("Résultat à vérifier");
  await expect(page.getByTestId("verification-status")).toHaveText("En vérification");
}

test.describe("Intention outcomes", () => {
  test("expected, confirmed by a person — achieved, its story told", async ({ page }) => {
    await signIn(page);
    const expected = await prepared(page);

    // Only what a person confirms, instead.
    await page.getByTestId("expectations-edit").click();
    const removing = expected.getByTestId("expectation-remove");
    while ((await removing.count()) > 0) await removing.first().click();
    await page.getByTestId("expectation-kind").selectOption("confirmed");
    await page.getByTestId("expectation-said").fill("La connexion passe de bout en bout");
    await page.getByTestId("expectation-add-button").click();
    await page.getByTestId("expectations-save").click();
    await expect(expected.getByTestId("expectation")).toHaveCount(1);
    await expect(expected).toContainText(
      "Une personne confirme : « La connexion passe de bout en bout »",
    );

    await done(page);
    const result = page.getByTestId("verification-result");
    await expect(result.getByTestId("verification-seen")).toHaveText("À confirmer");
    await result.getByTestId("expectation-report").click();
    await result
      .getByTestId("expectation-report-note")
      .fill("Connexion testée, tableau de bord affiché.");
    await result
      .getByTestId("expectation-report-link")
      .fill("https://status.acme.example/checks/42");
    await result.getByTestId("expectation-met").click();

    await expect(page.getByTestId("verification-status")).toHaveText("Atteint");
    await expect(page.getByTestId("intention-status")).toContainText("Terminée");
    await expect(page.getByTestId("verification-reported")).toContainText(
      "Atteint selon vous : « Connexion testée, tableau de bord affiché. »",
    );
    await expect(page.getByTestId("verification-context")).toContainText(
      "Contexte de l'entreprise mis à jour",
    );
    await expect(page.getByTestId("plan-journal")).toContainText("Résultat atteint");

    // Its whole story, one click away — filtered.
    await page.getByTestId("impact-history").click();
    await expect(page).toHaveURL(/\/history$/);
    const events = page.getByTestId("intention-event");
    await expect(events.first()).toContainText("Intention créée");
    await expect(events.last()).toContainText("Résultat vérifié");
    for (const words of ["Analyse lancée", "Validée", "Plan préparé", "Résultat atteint"]) {
      await expect(page.getByTestId("intention-history")).toContainText(words);
    }
    await page.getByTestId("timeline-category-outcome").click();
    await expect(events.first()).toContainText("Résultat attendu défini");
    const others = page.locator('[data-testid="intention-event"]:not([data-category="outcome"])');
    await expect(others).toHaveCount(0);
    await page.getByTestId("timeline-actor-system").click();
    await expect(events.first()).toContainText("Vérification du résultat lancée");
    await expect(events.filter({ hasText: "par vous" })).toHaveCount(0);
  });

  test("concluded short of what was expected — failed, said why", async ({ page }) => {
    await signIn(page);
    await prepared(page);
    await done(page);

    // auth-service has not been read again since: not said healthy.
    const healthy = page.locator(
      '[data-testid="verification-result"][data-expectation^="healthy:"]',
    );
    await expect(healthy.getByTestId("verification-seen")).not.toHaveText("Atteint");
    await page.getByTestId("verification-conclude").click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("textbox").fill("Toujours des erreurs de connexion.");
    await dialog.getByRole("button", { name: "Conclure" }).click();

    await expect(page.getByTestId("verification-status")).toHaveText("Non atteint");
    // Ran, short of what was expected: the action failed, said why.
    await expect(page.getByTestId("intention-status")).toContainText("Action échouée");
    await expect(page.getByTestId("journey-why")).toContainText("le résultat attendu n'est pas constaté");
    await expect(page.getByTestId("verification-concluded")).toContainText(
      "Conclu par vous : « Toujours des erreurs de connexion. »",
    );
    await expect(page.getByTestId("verification-context")).toHaveCount(0);
    // What did not succeed may be tried again.
    await expect(page.getByTestId("plan-retry")).toBeVisible();
  });
});
