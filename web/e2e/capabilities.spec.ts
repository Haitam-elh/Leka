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
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Agents et bundles LEKA");
    // A model answers here: nothing holds the catalogue back (LEKA-438).
    await expect(page.getByTestId("catalogue-grid")).toBeVisible();
    await expect(page.getByTestId("catalogue-wide")).toHaveCount(0);

    // The agents by the marketplace's categories (LEKA-467): « Architecture &
    // Code » first here — the code review in it — never mixed with LEKA's
    // own skills, which have their own section, never priced.
    const code = page.locator('[data-testid="catalogue-domain"][data-kind="agent"][data-domain="architecture"]');
    await expect(page.getByTestId("catalogue-domain").first()).toHaveAttribute("data-domain", "architecture");
    await expect(code).toContainText("Architecture & Code");
    await expect(code.locator('[data-testid="capability-card"][data-key="code-review"]')).toContainText("Revue de code");
    await expect(code.locator('[data-testid="capability-card"]:not([data-kind="agent"])')).toHaveCount(0);
    const skills = page.getByTestId("catalogue-skills");
    await expect(skills).toContainText("Compétences LEKA, incluses dans toutes les formules");
    await expect(skills.getByTestId("agent-price")).toHaveCount(0);

    const owner = page.locator('[data-testid="capability-card"][data-key="ownership"]');
    await expect(owner).toContainText("Responsabilités");
    await expect(owner).toHaveAttribute("data-available", "true");
    const architect = page.locator('[data-testid="capability-card"][data-key="application-architecture"]');
    await expect(architect).toContainText("Architecte applicatif");
    // A model answers here (the stand-in, LEKA-429) and agents run
    // (LEKA-395): nothing is in its way.
    await expect(architect).toHaveAttribute("data-available", "true");
    // Made for this organisation (2026-10-25): first, apart, never priced.
    const dedicated = page.getByTestId("catalogue-dedicated");
    await expect(dedicated).toContainText("Conçus pour Acme Corp");
    await expect(dedicated.locator('[data-testid="capability-card"][data-key="application-architecture"]')).toHaveCount(1);
    await expect(architect.getByTestId("agent-price")).toHaveCount(0);
    await expect(architect.getByTestId("agent-state")).toHaveText("Dédié à votre organisation");
    // An agent on sale: its price — the demo's plan includes it (Karim's
    // matrix, LEKA-454), said in words —, and the bundles under the domains.
    const review = code.locator('[data-testid="capability-card"][data-key="code-review"]');
    await expect(review.getByTestId("agent-price")).toContainText("9 € / mois");
    await expect(review.getByTestId("agent-state")).toHaveText("Inclus dans votre plan");
    await expect(page.getByTestId("bundle")).toHaveCount(5);

    // Its words find it.
    await page.getByTestId("catalogue-search").fill("architecte");
    await expect(page.getByTestId("capability-card")).toHaveCount(1);

    await architect.getByRole("link", { name: "Architecte applicatif" }).click();
    await expect(page).toHaveURL(/\/capabilities\/application-architecture$/);
    const sheet = page.getByTestId("capability");
    // Its product page (LEKA-471), the registry's details folded under it.
    await expect(sheet).toHaveAttribute("data-page", "product");
    await sheet.getByTestId("agent-technical").getByText("Détails techniques").click();
    await expect(sheet.getByTestId("capability-inputs")).toContainText("parcours");
    await expect(sheet.getByTestId("capability-formats")).toContainText("PDF");
    await expect(sheet.getByTestId("capability-versions")).toContainText("v19.2.0");
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

test.describe("Demander une compétence (LEKA-501)", () => {
  test("a suggestion for LEKA's team, never a new intention", async ({ page }) => {
    await signIn(page);
    await page.goto("/capabilities");
    await page.getByTestId("catalogue-ask").click();

    const dialog = page.getByTestId("suggestion-dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByLabel("Compétence ou agent souhaité").fill(`Agent FinOps ${Date.now()}`);
    await dialog.getByLabel("Le problème à résoudre").fill("Nos factures cloud montent sans explication.");
    await dialog.getByLabel("Le cas d'usage").fill("Chaque lundi, dire quel service a coûté plus.");
    await dialog.getByTestId("suggestion-send").click();

    await expect(dialog.getByTestId("suggestion-sent")).toContainText("Demande reçue");
    await expect(page).toHaveURL("http://localhost:3000/capabilities");
  });
});
