import { expect, test } from "@playwright/test";

import { accountLanguage } from "./account-language";
import { signIn } from "./sign-in";

/**
 * The interface in English, page after page (LEKA-495): its own words
 * translated — the agents' names too —, the company's things as their
 * sources name them, kept after a reload.
 */
test.describe("in English", () => {
  test.afterEach(() => accountLanguage("fr"));

  test("every page in English, agents named in English, the data as it is — kept after a reload", async ({ page }) => {
    accountLanguage("en");
    await signIn(page);

    await page.goto("/overview");
    await expect(page.getByRole("heading", { name: "Recommended agents" })).toBeVisible();

    await page.goto("/capabilities");
    await expect(page.getByText("Code review").first()).toBeVisible();
    await expect(page.getByText("Revue de code")).toHaveCount(0);

    await page.goto("/environment");
    // The company's own things: as their sources name them, never translated.
    await expect(page.getByText("payment-api").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "My environment", level: 1 })).toBeVisible();

    await page.goto("/settings");
    await expect(page.getByText("Default environment")).toBeVisible();

    await page.reload();
    await expect(page.getByText("Default environment")).toBeVisible();
  });
});
