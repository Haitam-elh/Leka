import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * Sécurité & gouvernance › Approbations, in a browser, on the demo
 * (LEKA-404): the policy per risk as the API says it — an owner among a
 * critical action's approvers; a migration in production simulated, said
 * critical and why; a freeze granted, listed, revoked once confirmed, both
 * kept in the journal. The freeze covers an environment no other spec uses,
 * and is revoked before the test ends: nothing else is frozen.
 */

test.describe("the governance of consequential actions", () => {
  test("says the policy per risk and simulates an action against it", async ({ page }) => {
    await signIn(page);
    await page.goto("/governance");
    await page.getByRole("tab", { name: "Approbations" }).click();

    const policy = page.getByTestId("approval-policy");
    await expect(policy.getByRole("row", { name: /Risque critique/ })).toBeVisible();
    await expect(
      policy.getByRole("combobox", { name: "Rôle requis · Risque critique" }),
    ).toHaveValue("owner");

    const simulate = page.getByTestId("policy-simulate");
    await simulate.getByRole("combobox", { name: "Action" }).selectOption("migrate");
    await simulate.getByRole("button", { name: "Évaluer" }).click();
    const verdict = page.getByTestId("policy-verdict");
    await expect(verdict).toContainText("Risque critique");
    await expect(verdict).toContainText("Irréversible en production : au moins critique");
    await expect(verdict).toContainText("dont un propriétaire");
  });

  test("grants a freeze, lists it, revokes it — the journal keeps both", async ({ page }) => {
    await signIn(page);
    await page.goto("/governance");
    await page.getByRole("tab", { name: "Approbations" }).click();

    const reason = `Gel de recette e2e ${Date.now()}`;
    const form = page.getByTestId("exception-form");
    await form.getByRole("textbox", { name: "Pourquoi" }).fill(reason);
    await form.locator("input[type=datetime-local]").nth(1).fill("2099-01-01T08:00");
    await form.getByRole("textbox", { name: /Environnements/ }).fill("recette-e2e");
    // 2099 is past the 90 days an exception may last: refused, said.
    await form.getByRole("button", { name: "Accorder" }).click();
    await expect(page.getByTestId("governance-exceptions").getByText(reason)).toHaveCount(0);

    const inAWeek = new Date(Date.now() + 7 * 24 * 3_600_000);
    const local = new Date(inAWeek.getTime() - inAWeek.getTimezoneOffset() * 60_000)
      .toISOString()
      .slice(0, 16);
    await form.locator("input[type=datetime-local]").nth(1).fill(local);
    await form.getByRole("button", { name: "Accorder" }).click();

    const granted = page.getByTestId("governance-exceptions").locator("li", { hasText: reason });
    await expect(granted).toContainText("Gel");
    await expect(granted).toContainText("En cours");
    await expect(granted).toContainText("recette-e2e");

    await granted.getByRole("button", { name: "Révoquer" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Révoquer ce gel ?");
    await dialog.getByRole("button", { name: "Révoquer" }).click();
    await expect(granted).toContainText("Révoqué");

    const journal = page.getByTestId("governance-journal");
    await expect(journal.locator("li").first()).toContainText("Exception révoquée");
    await expect(journal.locator("li", { hasText: reason })).toContainText("Exception accordée");
  });
});
