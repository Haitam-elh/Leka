import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * À valider, in a real browser (LEKA-380).
 *
 * The seed runs LEKA's analyses over the demo company as the job runs them
 * (scripts/seed.py): what waits here is what they proposed, not words
 * written for the demo. Thomas and Mei maintain postgres-prod, the database
 * no one is named to own, and both are members of Platform; acme/user-service
 * is a repository nothing ties to user-service.
 *
 * What a unit test cannot answer: that the proposals reach the overview,
 * the sidebar and À valider through the API, worded; and that a decision is
 * taken — accepted, rejected, sent back. The test leaves the proposal as it
 * found it, waiting: it can run again on the same database.
 */

test.describe("À valider", () => {
  test("says what LEKA proposes, on the overview and beside the sidebar's entry", async ({
    page,
  }) => {
    await signIn(page);

    const waiting = page.getByTestId("approvals-waiting").getByRole("listitem");
    await expect(waiting.filter({ hasText: "Platform est responsable de postgres-prod" })).toHaveCount(1);
    await expect(
      waiting.filter({ hasText: "acme/user-service est le code de user-service" }),
    ).toHaveCount(1);
    await expect(page.getByTestId("nav-approvals")).toContainText("2");

    await waiting.filter({ hasText: "Platform est responsable de postgres-prod" }).getByRole("link").click();
    await expect(page).toHaveURL(/\/approvals\/[0-9a-f-]{36}$/);
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
    await expect(panel).toContainText("Appliqué au modèle à sa prochaine construction.");

    // Rejected, with why: withdrawn from the model.
    await panel.getByRole("button", { name: "Refuser" }).click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("textbox").fill("Le DBA en est responsable");
    await dialog.getByRole("button", { name: "Refuser" }).click();
    await expect(panel.getByTestId("candidate-status")).toHaveText("Refusé");
    await panel.getByRole("tab", { name: "Décisions" }).click();
    await expect(panel.getByTestId("candidate-history")).toContainText("« Le DBA en est responsable »");

    // Sent back to its analysis: waiting again.
    await panel.getByRole("button", { name: "Retraiter" }).click();
    await expect(panel.getByTestId("candidate-status")).toHaveText("À valider");
  });
});
