import { expect, test } from "@playwright/test";

import { openNavigation, signIn } from "./sign-in";

/**
 * À valider, in a real browser (LEKA-380).
 *
 * The seed runs LEKA's analyses over the demo company as the job runs them
 * (scripts/seed.py): what waits here is what they proposed, not words
 * written for the demo. Thomas and Mei maintain postgres-prod, the database
 * no one is named to own, and both are members of Platform; acme/user-service
 * is a repository nothing ties to user-service (LEKA-380). payment-api's SLA
 * is 99.95 to GitHub and 99.9 to Datadog; GitHub and Jira name two owners
 * for it, Nadia Kowalski and Nadia K. (LEKA-382).
 *
 * What a unit test cannot answer: that the proposals reach the overview,
 * the sidebar and À valider through the API, worded; and that a decision is
 * taken — accepted, rejected, sent back; a conflict settled and reopened.
 * The tests leave each as they found it, waiting: they can run again on the
 * same database.
 */

test.describe("À valider", () => {
  test("says what waits, on the overview and beside the sidebar's entry", async ({ page }) => {
    await signIn(page);

    // The conflicts first, then what LEKA proposes: three, the rest counted.
    const waiting = page.getByTestId("approvals-waiting").getByRole("listitem");
    await expect(waiting).toHaveCount(3);
    await expect(waiting.filter({ hasText: "SLA de payment-api : 99.95 ou 99.9" })).toHaveCount(1);
    await expect(page.getByText("4 éléments en attente", { exact: true })).toBeVisible();
    await openNavigation(page);
    await expect(page.getByTestId("nav-approvals")).toContainText("4");
    await page.keyboard.press("Escape");

    await waiting.filter({ hasText: "SLA de payment-api" }).getByRole("link").click();
    await expect(page).toHaveURL(/\/approvals\/[0-9a-f-]{36}\?kind=conflict$/);
    await expect(page.getByTestId("conflict-panel").getByTestId("conflict-sides")).toContainText(
      "acme-eu",
    );

    await page.goto("/approvals");
    await page.getByRole("table").getByText("Platform est responsable de postgres-prod").click();
    await expect(page.getByTestId("candidate-panel")).toContainText(
      "2 des 2 personnes qui le maintiennent sont membres de Platform",
    );
  });

  test("takes a decision, and undoes it", async ({ page }) => {
    await signIn(page);
    await page.goto("/approvals");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("À valider");
    await expect(page.getByTestId("approvals-stats")).toContainText("En attente");

    await page.getByRole("table").getByText("Platform est responsable de postgres-prod").click();
    const panel = page.getByTestId("candidate-panel");
    await expect(panel.getByTestId("candidate-change")).toContainText(
      "postgres-prod appartient à Platform",
    );
    await expect(panel.getByTestId("candidate-evidence")).toContainText("Thomas Berger");

    // Accepted: kept, applied by the model's next build.
    await panel.getByRole("button", { name: "Valider" }).click();
    await expect(panel.getByTestId("candidate-status")).toHaveText("Validé");
    await expect(panel).toContainText("Pris en compte à la prochaine mise à jour de votre environnement.");

    // Rejected, with why: withdrawn from the model.
    await panel.getByRole("button", { name: "Refuser" }).click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("textbox").fill("Le DBA en est responsable");
    await dialog.getByRole("button", { name: "Refuser" }).click();
    await expect(panel.getByTestId("candidate-status")).toHaveText("Refusé");
    await panel.getByRole("tab", { name: "Décisions" }).click();
    await expect(panel.getByTestId("candidate-history")).toContainText("« Le DBA en est responsable »");

    // Sent back to its analysis: waiting again.
    await panel.getByRole("button", { name: "Revérifier" }).click();
    await expect(panel.getByTestId("candidate-status")).toHaveText("À valider");
  });

  test("settles a conflict between sources, and reopens it", async ({ page }) => {
    await signIn(page);
    await page.goto("/approvals");

    await page.getByRole("table").getByText("SLA de payment-api : 99.95 ou 99.9").click();
    const panel = page.getByTestId("conflict-panel");
    await expect(panel).toContainText("LEKA retient aujourd'hui 99.95");
    const sides = panel.getByTestId("conflict-sides");
    await expect(sides).toContainText("acme/backend");
    await expect(sides).toContainText("Recommandé");

    // Datadog's word kept: the model will show it.
    await panel.getByTestId("keep-1").click();
    await expect(panel.getByTestId("conflict-status")).toHaveText("Tranché");
    await expect(panel.getByRole("status")).toHaveText("Tranché.");
    await expect(sides).toContainText("Retenu");

    // Reopened: the decision withdrawn, waiting again.
    await panel.getByRole("button", { name: "Rouvrir" }).click();
    await expect(panel.getByTestId("conflict-status")).toHaveText("À arbitrer");
    await panel.getByRole("tab", { name: "Décisions" }).click();
    await expect(panel.getByTestId("conflict-history")).toContainText("Rouvert");
  });
});
