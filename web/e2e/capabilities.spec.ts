import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * Capacités, in a real browser (LEKA-393).
 *
 * What a unit test cannot answer: that the API registers its catalogue when
 * it starts, and that on the demo the page shows it — LEKA's own analyses,
 * available, and the application architect registered, saying why it cannot
 * run yet: no source to read from connected, the language model to come;
 * that its sheet says what it takes and delivers, and offers to run it —
 * not without a model (LEKA-395); and that an admin turns a
 * capability off, saying why, and on again.
 */

test.describe("Capabilities", () => {
  test("the catalogue, the architect's sheet, turned off and on", async ({ page }) => {
    await signIn(page);
    await page.goto("/capabilities");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Les capacités de LEKA");
    await expect(page.getByTestId("catalogue-stat-available")).toContainText("Capacités disponibles");

    const owner = page.locator('[data-testid="capability-card"][data-key="ownership"]');
    await expect(owner).toContainText("Responsabilités");
    await expect(owner).toHaveAttribute("data-available", "true");
    const architect = page.locator('[data-testid="capability-card"][data-key="application-architecture"]');
    await expect(architect).toContainText("Architecte applicatif");
    // A model answers here (the stand-in, LEKA-429) and agents run
    // (LEKA-395): nothing is in its way.
    await expect(architect).toHaveAttribute("data-available", "true");

    // Its words find it.
    await page.getByTestId("catalogue-search").fill("architecte");
    await expect(page.getByTestId("capability-card")).toHaveCount(1);

    await architect.getByRole("link", { name: "Architecte applicatif" }).click();
    await expect(page).toHaveURL(/\/capabilities\/application-architecture$/);
    const sheet = page.getByTestId("capability");
    await expect(sheet.getByTestId("capability-inputs")).toContainText("parcours");
    await expect(sheet.getByTestId("capability-formats")).toContainText("PDF");
    await expect(sheet.getByTestId("capability-versions")).toContainText("v19.0.0");
    // Run from its sheet (LEKA-395): here it can — a model answers.
    await expect(sheet.getByTestId("agent-run-form")).not.toContainText(
      "Il ne peut pas s'exécuter ici pour l'instant.",
    );
    await expect(sheet).toContainText("Aucune exécution pour l'instant.");

    // Turned off, saying why — then on again.
    await page.goto("/capabilities?tab=configuration");
    const migration = page.locator('[data-testid="configuration-row"][data-key="migration"]');
    await migration.getByTestId("configuration-toggle").click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("textbox").fill("Pas de migration prévue.");
    await dialog.getByRole("button", { name: "Désactiver" }).click();
    await expect(migration).toContainText("Désactivée : « Pas de migration prévue. »");
    await migration.getByTestId("configuration-toggle").click();
    await expect(migration).not.toContainText("Désactivée :");
  });
});
