import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * Activité and a thing's Historique, in a real browser (LEKA-383).
 *
 * The seed writes the month that led the demo company where it is, as its
 * builds would have recorded it (scripts/seed.py): payment-api shipped
 * 2.8.2, 2.8.3, then 2.8.4; user-service went from Nadia to Thomas;
 * redis-sessions went from every source six days ago while auth-service
 * relied on it. LEKA's analyses ran over it.
 *
 * What a unit test cannot answer: that the model's history, the systems'
 * events, the analyses and the decisions reach the page through the API,
 * counted and worded; that a version is shown as it was at its date; that
 * a restore asked is kept and taken back — leaving the demo as it was found
 * (every run adds its own operation, and asserts only on its own).
 */

test.describe("Activité", () => {
  test("says what happened and what LEKA did, from the workspace's own course", async ({
    page,
  }) => {
    await signIn(page);
    // Activité is one of Mon environnement's lines (2026-10-07).
    await page.getByTestId("nav-section-environment-toggle").click();
    await page.getByTestId("nav-activity").click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Activité");

    await expect(page.getByTestId("activity-stat-incidents")).toHaveText("1");
    await expect(page.getByTestId("activity-bars")).toBeVisible();
    const latest = page.getByTestId("activity-latest");
    // All of the week: what the other tests decided comes first.
    await latest.getByRole("button", { name: "Voir tout" }).click();
    await expect(latest.getByText("Analyse de LEKA exécutée").first()).toBeVisible();
    await expect(latest.getByText("Modèle mis à jour").first()).toBeVisible();
    await expect(
      page.getByTestId("activity-top").getByRole("link", { name: /payment-api/ }),
    ).toBeVisible();
    // What the model's course says, in the banner.
    await expect(page.getByTestId("activity-trends")).toContainText(
      "redis-sessions a disparu de vos sources",
    );

    // Only the incidents: the one that followed the deployment.
    await page.getByRole("combobox", { name: "Type" }).click();
    await page.getByRole("option", { name: "Incidents" }).click();
    await expect(latest.getByRole("listitem")).toHaveCount(1);
    await latest.getByRole("link", { name: /Incident détecté sur payment-api/ }).click();
    await expect(page).toHaveURL(/\/environment\/incidents\/[0-9a-f-]{36}$/);
  });

  test("shows over a month what no source shows any more", async ({ page }) => {
    await signIn(page);
    await page.goto("/activity");
    await page.getByRole("combobox", { name: "Période" }).click();
    await page.getByRole("option", { name: "30 derniers jours" }).click();
    await page.getByTestId("activity-latest").getByRole("button", { name: "Voir tout" }).click();
    await expect(
      page
        .getByTestId("activity-latest")
        .getByText("redis-sessions n'apparaît plus dans vos sources"),
    ).toBeVisible();
  });
});

test.describe("a thing's Historique", () => {
  test("shows each version, what it was then, and restores one — then takes it back", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto("/activity");
    await page.getByTestId("activity-top").getByRole("link", { name: /payment-api/ }).click();
    await page.getByRole("link", { name: "Historique" }).click();
    await expect(page).toHaveURL(/\/environment\/services\/[0-9a-f-]{36}\/history$/);

    const latest = page.getByTestId("history-version-4");
    await expect(latest).toContainText("Actuelle");
    await expect(latest).toContainText("2.8.3 → 2.8.4");
    await expect(page.getByTestId("history-version-1")).toContainText(
      "Première version connue de LEKA",
    );
    await expect(page.getByTestId("history-relationships")).toContainText(
      "payment-api dépend de user-service",
    );

    // What it was when it shipped 2.8.2: before it depended on user-service.
    await page
      .getByTestId("history-version-2")
      .getByRole("button", { name: "Voir à cette date" })
      .click();
    const at = page.getByTestId("history-at");
    await expect(at).toContainText("version2.8.2");
    await expect(at).toContainText("payment-api dépend de auth-service");
    await expect(at).not.toContainText("user-service");

    const before = await page.getByTestId("history-operation-undone").count();
    await page.getByTestId("history-version-3").getByRole("button", { name: "Restaurer" }).click();
    await page.getByLabel("Pourquoi (facultatif)").fill("e2e");
    await page.getByRole("button", { name: "Restaurer cette version" }).click();
    const applied = page.getByTestId("history-operation-applied");
    await expect(applied).toHaveCount(1);
    await expect(applied).toContainText("Restauration de la version 3");
    await expect(applied).toContainText("2.8.4 → 2.8.3");

    await applied.getByRole("button", { name: "Annuler" }).click();
    await expect(page.getByTestId("history-operation-applied")).toHaveCount(0);
    await expect(page.getByTestId("history-operation-undone")).toHaveCount(before + 1);
  });
});
