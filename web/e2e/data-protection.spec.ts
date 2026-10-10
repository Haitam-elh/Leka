import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * Sécurité & gouvernance › Données, in a browser, on the demo (LEKA-405):
 * the platform's protections as the running API reads them, what was found
 * per source, and the policy — changed, then set back, so that no other
 * spec meets it changed.
 */

test.describe("data protection", () => {
  test("says the platform's protections and keeps the policy", async ({ page }) => {
    await signIn(page);
    await page.goto("/governance");
    await page.getByRole("tab", { name: "Données" }).click();

    const platform = page.getByTestId("platform-protections");
    await expect(platform.getByTestId("protection-credentials")).toContainText("Chiffrés (Fernet)");
    await expect(platform.getByTestId("protection-isolation")).toContainText(
      "Chaque requête limitée à votre espace",
    );
    await expect(page.getByRole("heading", { name: "Ce que LEKA a trouvé dans vos données" })).toBeVisible();

    const policy = page.getByTestId("protection-policy");
    const days = policy.getByRole("combobox");
    const before = await days.inputValue();
    const other = before === "8" ? "9" : "8";
    await days.selectOption(other);
    await policy.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByText("Choisie par votre espace")).toBeVisible();
    await expect(days).toHaveValue(other);

    await days.selectOption(before);
    await policy.getByRole("button", { name: "Enregistrer" }).click();
    await expect(days).toHaveValue(before);
  });
});
