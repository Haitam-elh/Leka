import { expect, test } from "@playwright/test";

import { approved } from "./intention-helpers";
import { signIn } from "./sign-in";

/**
 * Approved decisions carried out, in a real browser (LEKA-391).
 *
 * What a unit test cannot answer: that an action asked, analysed and
 * approved on the demo is prepared into a plan — no system is authorized
 * there, so a person does it — run once asked, confirmed with what shows
 * it, and the intention then verifying; and that a run scheduled can be
 * called off, the intention approved again. Calls to authorized systems
 * are proven by the API's tests, against a stand-in that checks LEKA's
 * signature: there is no customer's system to call here.
 */

test.describe("Intention actions", () => {
  test("prepared, run, a person's step confirmed — then verifying", async ({ page }) => {
    await signIn(page);
    await approved(page);

    await page.getByTestId("tab-actions").click();
    await expect(page).toHaveURL(/\/actions$/);
    await page.getByTestId("plan-prepare-button").click();
    const step = page.getByTestId("plan-step");
    await expect(step).toContainText("Redémarrer · auth-service · production");
    await expect(step).toContainText("Par une personne");
    await expect(page.getByTestId("plan-status")).toHaveText("Prêt");

    await page.getByTestId("plan-start").click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Redémarrer · auth-service · production");
    await dialog.getByRole("button", { name: "Lancer maintenant" }).click();
    await expect(page.getByTestId("plan-status")).toHaveText("En cours");
    await expect(step.getByTestId("step-status")).toHaveText("À confirmer");
    await expect(page.getByTestId("intention-status")).toContainText("En exécution");
    // Checked before it ran.
    await expect(page.getByTestId("plan-checks")).toContainText("La décision est toujours validée");

    await step.getByTestId("step-report-note").fill("Redémarré depuis la console, healthcheck vert.");
    await step.getByTestId("step-done").click();
    await expect(page.getByTestId("plan-status")).toHaveText("Exécuté");
    await expect(step.getByTestId("step-evidence")).toContainText(
      "Confirmé : « Redémarré depuis la console, healthcheck vert. »",
    );
    await expect(page.getByTestId("intention-status")).toContainText("En vérification");
    await expect(page.getByTestId("plan-journal")).toContainText("Actions exécutées");
  });

  test("scheduled, then called off — approved again", async ({ page }) => {
    await signIn(page);
    await approved(page);
    await page.getByTestId("tab-actions").click();
    await page.getByTestId("plan-prepare-button").click();
    await expect(page.getByTestId("plan-status")).toHaveText("Prêt");

    // Tomorrow, whatever the hour now.
    const tomorrow = new Date(Date.now() + 24 * 3_600_000);
    const local = new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60_000)
      .toISOString()
      .slice(0, 16);
    await page.getByTestId("plan-schedule-at").fill(local);
    await page.getByTestId("plan-schedule").click();
    await expect(page.getByTestId("plan-status")).toHaveText("Planifié");
    await expect(page.getByTestId("intention-status")).toContainText("Planifiée");

    await page.getByTestId("plan-cancel").click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("textbox").fill("L'incident s'est résolu seul.");
    await dialog.getByRole("button", { name: "Annuler la planification" }).click();
    await expect(page.getByTestId("plan-status")).toHaveText("Annulé");
    await expect(page.getByTestId("intention-status")).toContainText("Approuvée");
  });
});
