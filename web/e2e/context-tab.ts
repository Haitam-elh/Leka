import { expect, type Page } from "@playwright/test";

import { signIn } from "./sign-in";

/** payment-api's sheet, on its "Contexte" tab, ready to assemble a new
 * context — the database outlives a run, so one may be there already. */
export async function openContextTab(page: Page) {
  await signIn(page);
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByTestId("palette-input").fill("payment-api");
  await page.getByRole("option", { name: /^payment-api/ }).first().click();
  await expect(page).toHaveURL(/\/environment\/services\/[0-9a-f-]{36}$/);
  await page.getByRole("link", { name: "Contexte" }).click();
  await expect(page).toHaveURL(/\/context$/);

  const purpose = page.getByLabel("Pourquoi ?");
  await expect(purpose.or(page.getByTestId("entity-context"))).toBeVisible();
  if (!(await purpose.isVisible())) {
    await page.getByRole("button", { name: "Nouveau contexte" }).click();
  }
}
