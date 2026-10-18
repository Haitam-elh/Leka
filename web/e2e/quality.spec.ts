import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * Knowledge quality, in a real browser (LEKA-381).
 *
 * The seed runs LEKA's analyses over the demo company as the job runs them
 * (scripts/seed.py): the scores are what the `quality` analysis measured.
 * payment-api's sources disagree on its SLA and its owner (LEKA-382): it is
 * the thing known least well. postgres-prod has no owner and no page: its
 * completeness is weak, and so it is held to « À consolider » — and the
 * workspace with it, its completeness weak across.
 *
 * What a unit test cannot answer: that the analysis's scores reach the
 * screen through the API, the sidebar leads to them, and a thing's sheet
 * says its own.
 */

test.describe("Knowledge quality", () => {
  test("says how far what LEKA knows can be trusted, the weakest first", async ({ page }) => {
    await signIn(page);
    // Mon environnement, then its view in the menu after its tabs (LEKA-459).
    await page.getByTestId("nav-environment").click();
    await page.getByTestId("env-more").click();
    await page.getByRole("option", { name: "Qualité" }).click();
    await expect(page).toHaveURL("http://localhost:3000/environment?tab=quality");
    await expect(page.getByTestId("env-more")).toContainText("Qualité");

    await expect(page.getByTestId("quality-workspace-score")).toContainText("%");
    await expect(page.getByTestId("quality-dimension-completeness")).toBeVisible();

    const first = page.getByRole("table", { name: /Éléments mesurés/ }).getByRole("row").nth(1);
    await expect(first).toContainText("payment-api");
    await expect(first).toContainText("sources en désaccord (2)");
  });

  test("has no violation a machine can see, its scores read", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment?tab=quality");
    await expect(
      page.getByTestId("quality-trend").or(page.getByTestId("quality-trend-empty")),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "payment-api" }).first()).toBeVisible();

    const { violations } = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"])
      .analyze();
    expect(violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);
  });

  test("says a thing's own on its sheet", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment?tab=quality");

    await page.getByRole("link", { name: "postgres-prod" }).first().click();
    await expect(page).toHaveURL(/\/environment\/databases\/[0-9a-f-]{36}$/);
    await expect(page.getByTestId("quality-entity-score")).toContainText("84 %");
    await expect(page.getByTestId("quality-capped")).toContainText("une dimension est sous 60 %");
    await expect(page.getByTestId("quality-lacks")).toContainText("aucun responsable");
  });
});
